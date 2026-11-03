"""Read bounded text at an immutable commit, without executing repository code."""

import base64
import binascii
import re
from urllib.parse import quote

from github_mcp.github import gh
from github_mcp.models import Continuation, FileChunk, Result, Revision, ToolError

SHA = re.compile(r"[0-9a-fA-F]{40}")
NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}")
MAX_BYTES = 1_000_000
MAX_CHARS = 12_000


def _error(code: str, message: str) -> Result:
    return Result(error=ToolError(code=code, message=message))


def _validate(owner: str, repo: str, ref: str) -> Result | None:
    if any(not NAME.fullmatch(n) or n in {".", ".."} for n in (owner, repo)):
        return _error("INVALID_REPOSITORY", "Use a GitHub owner and repository name.")
    if (
        not ref.strip()
        or len(ref) > 1024
        or any(ord(c) < 32 or ord(c) == 127 for c in ref)
    ):
        return _error("INVALID_REF", "Provide a branch, tag, or full commit SHA.")
    if ref in {".", ".."}:
        return _error("INVALID_REF", "Dot path segments are not revisions.")
    return None


def _api_error(data: dict | list) -> Result | None:
    if not isinstance(data, dict):
        return _error("INVALID_RESPONSE", "Unexpected GitHub response.")
    if "error" in data:
        return Result(
            error=ToolError(
                code=data.get("error_code", "github_error"),
                message=data["error"],
                retry_after_seconds=data.get("retry_after_seconds"),
            )
        )
    return None


def resolve_revision(owner: str, repo: str, ref: str = "HEAD") -> Result[Revision]:
    """Resolve a branch/tag once; reuse commit_sha for subsequent reads."""
    if error := _validate(owner, repo, ref):
        return error
    data = gh(
        f"/repos/{owner}/{repo}/commits/{quote(ref, safe='')}",
        params={"per_page": 1},
        max_bytes=2_000_000,
    )
    if error := _api_error(data):
        return error
    assert isinstance(data, dict)
    sha = data.get("sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        return _error("INVALID_RESPONSE", "GitHub did not return a full commit SHA.")
    sha = sha.lower()
    if SHA.fullmatch(ref) and ref.lower() != sha:
        return _error("INVALID_RESPONSE", "GitHub returned a different commit.")
    return Result(
        data=Revision(
            repository=f"{owner}/{repo}",
            requested_ref=ref,
            commit_sha=sha,
            source_url=f"https://github.com/{owner}/{repo}/commit/{sha}",
        )
    )


def read_file_lines(
    owner: str,
    repo: str,
    path: str,
    ref: str = "HEAD",
    start_line: int = 1,
    line_count: int = 100,
) -> Result[FileChunk]:
    """Return whole UTF-8 lines with a pinned source link and continuation."""
    if error := _validate(owner, repo, ref):
        return error
    if (
        not path
        or "\\" in path
        or any(ord(c) < 32 or ord(c) == 127 for c in path)
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        return _error(
            "INVALID_PATH", "Use a relative POSIX file path without dot segments."
        )
    if (
        type(start_line) is not int
        or start_line < 1
        or type(line_count) is not int
        or not 1 <= line_count <= 200
    ):
        return _error(
            "INVALID_RANGE", "start_line must be positive; line_count must be 1..200."
        )
    sha = ref.lower()
    if not SHA.fullmatch(ref):
        revision = resolve_revision(owner, repo, ref)
        if revision.error:
            return Result(error=revision.error)
        assert revision.data is not None
        sha = revision.data.commit_sha
    data = gh(
        f"/repos/{owner}/{repo}/contents/{quote(path, safe='/')}",
        params={"ref": sha},
        max_bytes=2_000_000,
    )
    if error := _api_error(data):
        return error
    assert isinstance(data, dict)
    size = data.get("size")
    if (
        data.get("type") != "file"
        or data.get("encoding") != "base64"
        or (type(size) is int and size > MAX_BYTES)
    ):
        return _error(
            "UNSUPPORTED_FILE",
            "Only base64-encoded UTF-8 files up to 1,000,000 bytes are supported.",
        )
    encoded, blob = data.get("content"), data.get("sha")
    if (
        data.get("path") != path
        or type(size) is not int
        or size < 0
        or not isinstance(encoded, str)
        or len(encoded) > MAX_BYTES * 2
        or not isinstance(blob, str)
        or not SHA.fullmatch(blob)
    ):
        return _error("INVALID_RESPONSE", "Invalid file metadata from GitHub.")
    try:
        raw = base64.b64decode("".join(encoded.split()), validate=True)
    except (ValueError, binascii.Error):
        return _error("INVALID_RESPONSE", "Invalid base64 file content.")
    if len(raw) != size:
        return _error("INVALID_RESPONSE", "File size does not match its content.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _error("UNSUPPORTED_FILE", "File is not UTF-8 text.")
    if "\x00" in text:
        return _error("UNSUPPORTED_FILE", "Binary files are not supported.")
    # GitHub line anchors count LF separators, not Unicode paragraph separators.
    lines = text.split("\n")
    lines = [line + "\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
    total = len(lines)
    if start_line > max(1, total):
        return _error("INVALID_RANGE", "start_line is beyond the end of the file.")
    selected, used = [], 0
    for line in lines[start_line - 1 : start_line - 1 + line_count]:
        if used + len(line) > MAX_CHARS:
            break
        selected.append(line)
        used += len(line)
    if total and not selected:
        return _error(
            "LINE_TOO_LONG",
            "The requested line exceeds the 12,000-character output budget.",
        )
    end = start_line + len(selected) - 1
    continuation = (
        Continuation(
            owner=owner,
            repo=repo,
            path=path,
            ref=sha,
            start_line=end + 1,
            line_count=line_count,
        )
        if end < total
        else None
    )
    url = f"https://github.com/{owner}/{repo}/blob/{sha}/{quote(path, safe='/')}"
    return Result(
        data=FileChunk(
            repository=f"{owner}/{repo}",
            commit_sha=sha,
            blob_sha=blob.lower(),
            path=path,
            start_line=start_line,
            end_line=end,
            total_lines=total,
            text="".join(selected),
            source_url=f"{url}#L{start_line}-L{end}" if total else url,
            continuation=continuation,
        )
    )
