"""Request-scoped source acquisition. Repository content is never executed."""

import base64
import binascii
import hashlib
import os
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Never

from github_mcp.github import gh
from github_mcp.models import ToolError
from github_mcp.snapshots import MAX_BYTES, SHA, resolve_revision

MAX_FILES = 100
MAX_TOTAL_BYTES = 5_000_000
MAX_ENTRIES = 10_000
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "__pycache__",
    ".ssh",
    ".aws",
    ".local",
}
RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    f"{p}{n}" for p in ("com", "lpt") for n in "123456789¹²³"
}


class SnapshotError(Exception):
    def __init__(self, error: ToolError):
        self.error = error
        super().__init__(error.code)


def _fail(code: str, message: str) -> Never:
    raise SnapshotError(ToolError(code=code, message=message)) from None


@dataclass(frozen=True)
class Snapshot:
    root: Path  # Internal only: never expose local paths through MCP.
    repository: str
    commit_sha: str
    files: tuple[str, ...]
    blob_shas: dict[str, str]
    total_bytes: int
    omitted: dict[str, int]


def _get(path: str, max_bytes: int, params: dict | None = None) -> dict:
    data = gh(path, params=params, max_bytes=max_bytes)
    if not isinstance(data, dict):
        _fail("INVALID_RESPONSE", "Expected a GitHub object.")
    if "error" in data:
        raise SnapshotError(
            ToolError(
                code=data.get("error_code", "GITHUB_ERROR"),
                message=data["error"],
                retry_after_seconds=data.get("retry_after_seconds"),
            )
        )
    return data


def _safe_path(path) -> bool:
    if (
        not isinstance(path, str)
        or not path
        or len(path) > 180
        or path != unicodedata.normalize("NFC", path)
        or any(ord(c) < 32 or ord(c) == 127 or c in '\\:<>"|?*' for c in path)
    ):
        return False
    parts = path.split("/")
    return len(parts) <= 20 and all(
        part not in {"", ".", ".."}
        and len(part) <= 100
        and not part.endswith((".", " "))
        and part.split(".")[0].rstrip(" ").casefold() not in RESERVED
        for part in parts
    )


def _entries(prefix: str, sha: str) -> list[dict]:
    commit = _get(f"{prefix}/git/commits/{sha}", 100_000)
    tree_sha = (
        commit.get("tree", {}).get("sha")
        if isinstance(commit.get("tree"), dict)
        else None
    )
    if (
        commit.get("sha") != sha
        or not isinstance(tree_sha, str)
        or not SHA.fullmatch(tree_sha)
    ):
        _fail("INVALID_RESPONSE", "Commit/tree identity is invalid.")
    tree = _get(f"{prefix}/git/trees/{tree_sha}", 4_000_000, {"recursive": "1"})
    entries = tree.get("tree")
    if (
        tree.get("sha") != tree_sha
        or type(tree.get("truncated")) is not bool
        or not isinstance(entries, list)
    ):
        _fail("INVALID_RESPONSE", "Invalid Git tree response.")
    if tree["truncated"] or len(entries) > MAX_ENTRIES:
        _fail("SNAPSHOT_LIMIT", "Git tree is truncated or exceeds 10,000 entries.")
    names = {}
    spellings: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not _safe_path(entry.get("path")):
            _fail("UNSAFE_PATH", "Git tree contains an unsafe or nonportable path.")
        path = entry["path"]
        key = path.casefold()
        if key in names:
            _fail("UNSAFE_PATH", "Git tree contains colliding paths.")
        names[key] = entry
        for component in (PurePosixPath(path), *PurePosixPath(path).parents):
            spelling = str(component)
            old = spellings.setdefault(spelling.casefold(), spelling)
            if old != spelling:
                _fail("UNSAFE_PATH", "Git tree contains colliding directory names.")
        if (
            (entry.get("type"), entry.get("mode"))
            not in {
                ("blob", "100644"),
                ("blob", "100755"),
                ("blob", "120000"),
                ("tree", "040000"),
                ("commit", "160000"),
            }
            or not isinstance(entry.get("sha"), str)
            or not SHA.fullmatch(entry["sha"])
        ):
            _fail("INVALID_RESPONSE", "Invalid Git tree entry.")
    for key in names:
        for parent in PurePosixPath(key).parents:
            if str(parent) in names and names[str(parent)]["type"] != "tree":
                _fail("UNSAFE_PATH", "Git tree contains a file/directory collision.")
    return sorted(entries, key=lambda e: e["path"])


def _omission(entry: dict) -> str | None:
    if entry["mode"] == "120000":
        return "symlink"
    if entry["type"] == "commit":
        return "submodule"
    path = PurePosixPath(entry["path"])
    if any(p.casefold() in IGNORED_DIRS for p in path.parts[:-1]):
        return "ignored_directory"
    if any(
        part.casefold() in {"secrets", "credentials"}
        or part.casefold().startswith(
            (".env", "secrets.", "credentials.", "id_rsa", "id_ed25519")
        )
        for part in path.parts
    ):
        return "sensitive_name"
    if path.suffix.casefold() not in SOURCE_SUFFIXES:
        return "unsupported_extension"
    return None


def _read_blob(prefix: str, entry: dict) -> bytes:
    data = _get(f"{prefix}/git/blobs/{entry['sha']}", MAX_BYTES * 2)
    content = data.get("content")
    if (
        data.get("sha") != entry["sha"]
        or data.get("size") != entry["size"]
        or data.get("encoding") != "base64"
        or not isinstance(content, str)
    ):
        _fail("INVALID_RESPONSE", "Blob metadata does not match the Git tree.")
    try:
        raw = base64.b64decode("".join(content.split()), validate=True)
    except (ValueError, binascii.Error):
        _fail("INVALID_RESPONSE", "Invalid blob encoding.")
    if (
        len(raw) != entry["size"]
        or hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        != entry["sha"]
    ):
        _fail("INVALID_RESPONSE", "Blob content does not match its identity.")
    return raw


@contextmanager
def acquire_snapshot(
    owner: str, repo: str, ref: str = "HEAD", *, temp_parent: Path | None = None
) -> Iterator[Snapshot]:
    """Yield private source files until context exit; no cross-request cache exists."""
    revision = resolve_revision(owner, repo, ref)
    if revision.error:
        raise SnapshotError(revision.error)
    assert revision.data is not None
    sha = revision.data.commit_sha
    prefix = f"/repos/{owner}/{repo}"
    entries = _entries(prefix, sha)
    omitted: Counter[str] = Counter()
    files: dict[str, str] = {}
    total = 0
    downloaded = 0
    download_count = 0
    try:
        with tempfile.TemporaryDirectory(
            prefix="github-mcp-", dir=temp_parent
        ) as directory:
            root = Path(directory).resolve()
            for entry in entries:
                if entry["type"] == "tree":
                    continue
                reason = _omission(entry)
                if reason:
                    omitted[reason] += 1
                    continue
                size = entry.get("size")
                if type(size) is not int or size < 0:
                    _fail("INVALID_RESPONSE", "Invalid Git blob size.")
                reason = (
                    "file_size_limit"
                    if size > MAX_BYTES
                    else "file_count_limit"
                    if download_count >= MAX_FILES
                    else "total_size_limit"
                    if downloaded + size > MAX_TOTAL_BYTES
                    else None
                )
                if reason:
                    omitted[reason] += 1
                    continue
                raw = _read_blob(prefix, entry)
                downloaded += len(raw)
                download_count += 1
                try:
                    raw.decode("utf-8")
                except UnicodeDecodeError:
                    omitted["non_text"] += 1
                    continue
                if b"\0" in raw:
                    omitted["non_text"] += 1
                    continue
                target = root / entry["path"]
                if not target.resolve().is_relative_to(root):
                    _fail("UNSAFE_PATH", "File destination escaped the snapshot.")
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with os.fdopen(
                    os.open(
                        target,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_BINARY", 0),
                        0o600,
                    ),
                    "wb",
                ) as stream:
                    stream.write(raw)
                files[entry["path"]] = entry["sha"]
                total += len(raw)
            yield Snapshot(
                root, f"{owner}/{repo}", sha, tuple(files), files, total, dict(omitted)
            )
    except OSError:
        _fail("SNAPSHOT_IO", "Snapshot storage or cleanup failed.")
