"""Source-only Python import statements and isolated job orchestration."""

import ast
import json
import platform
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, Field

from github_mcp import graph
from github_mcp.acquisition import Snapshot, _safe_path
from github_mcp.models import Evidence, Result, ToolError
from github_mcp.snapshots import _validate

MAX_IMPORTS = 20_000


class ImportLimit(Exception):
    pass


class ImportRecord(BaseModel):
    module: str | None
    imported_name: str | None
    alias: str | None
    bound_name: str | None
    level: int
    resolution: Literal["module_unverified", "relative_unresolved", "star_unresolved"]
    blob_sha: str
    evidence: Evidence


class ImportCoverage(BaseModel):
    files_acquired: int
    files_parsed: int
    unscanned_files: int
    failed_files: dict[str, str]
    omitted_files: dict[str, int]
    filtered_imports: int
    complete: Literal[False] = False


class ImportContinuation(BaseModel):
    owner: str
    repo: str
    ref: str
    focus_path: str
    module_prefix: str
    max_items: int
    start_index: int


class ImportMap(BaseModel):
    schema_version: Literal["1"] = "1"
    repository: str
    commit_sha: str
    parser: str
    focus_path: str
    module_prefix: str
    imports: list[ImportRecord] = Field(max_length=100)
    total_imports: int
    omitted_imports: int
    coverage: ImportCoverage
    limitations: list[str]
    continuation: ImportContinuation | None = None


def error(code: str, message: str) -> Result[ImportMap]:
    return Result(error=ToolError(code=code, message=message))


def scan_snapshot(
    snapshot: Snapshot, focus_path="", module_prefix="", max_items=50, start_index=0
) -> ImportMap:
    paths = [
        p
        for p in sorted(snapshot.files)
        if PurePosixPath(p).suffix.lower() == ".py"
        and (not focus_path or p == focus_path)
    ]
    records: list[ImportRecord] = []
    failed = {}
    for path in paths:
        text = (snapshot.root / path).read_bytes().decode("utf-8-sig")
        if "\r" in text.replace("\r\n", ""):
            failed[path] = "UNSUPPORTED_NEWLINES"
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            failed[path] = "SYNTAX_ERROR"
            continue
        except (ValueError, RecursionError):
            failed[path] = "PARSE_LIMIT"
            continue
        line_count = text.count("\n") + int(bool(text) and not text.endswith("\n"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            end = node.end_lineno or node.lineno
            if not 1 <= node.lineno <= end <= line_count:
                raise ValueError("Unverifiable source span")
            evidence = Evidence(
                path=path,
                start_line=node.lineno,
                end_line=end,
                source_url=f"https://github.com/{snapshot.repository}/blob/{snapshot.commit_sha}/{quote(path, safe='/')}#L{node.lineno}-L{end}",
            )
            for name in node.names:
                module: str | None
                bound: str | None
                if isinstance(node, ast.Import):
                    module, member, level = name.name, None, 0
                    bound = name.asname or name.name.split(".")[0]
                else:
                    module, member, level = node.module, name.name, node.level
                    bound = None if name.name == "*" else name.asname or name.name
                records.append(
                    ImportRecord(
                        module=module,
                        imported_name=member,
                        alias=name.asname,
                        bound_name=bound,
                        level=level,
                        resolution="star_unresolved"
                        if member == "*"
                        else "relative_unresolved"
                        if level
                        else "module_unverified",
                        blob_sha=snapshot.blob_shas[path],
                        evidence=evidence,
                    )
                )
                if len(records) > MAX_IMPORTS:
                    raise ImportLimit
    matched = [
        record
        for record in records
        if not module_prefix
        or (
            record.level == 0
            and record.module is not None
            and (
                record.module == module_prefix
                or record.module.startswith(module_prefix + ".")
            )
        )
    ]
    matched.sort(
        key=lambda record: (
            record.evidence.path,
            record.evidence.start_line,
            record.evidence.end_line,
        )
    )
    selected = matched[start_index : start_index + max_items]
    next_index = start_index + len(selected)
    continuation = None
    if next_index < len(matched):
        owner, repo = snapshot.repository.split("/")
        continuation = ImportContinuation(
            owner=owner,
            repo=repo,
            ref=snapshot.commit_sha,
            focus_path=focus_path,
            module_prefix=module_prefix,
            max_items=max_items,
            start_index=next_index,
        )
    return ImportMap(
        repository=snapshot.repository,
        commit_sha=snapshot.commit_sha,
        parser=f"python-ast/{platform.python_version()}",
        focus_path=focus_path,
        module_prefix=module_prefix,
        imports=selected,
        total_imports=len(matched),
        omitted_imports=len(matched) - len(selected),
        coverage=ImportCoverage(
            files_acquired=len(snapshot.files),
            files_parsed=len(paths) - len(failed),
            unscanned_files=len(snapshot.files) - len(paths),
            failed_files=failed,
            omitted_files=snapshot.omitted,
            filtered_imports=len(records) - len(matched),
        ),
        limitations=[
            "Observed AST import statements, not runtime execution or reference usage. Conditional/type-only/unreachable imports are included without evaluating conditions or scopes.",
            "Absolute module names do not prove installed distributions or external-vs-local ownership; relative targets and star exports remain unresolved.",
            "Dynamic imports, import hooks, re-export resolution, alias reassignment and Python stubs are outside coverage. Absence never proves safe upgrades or unused code.",
            "AST identifier normalization applies; citations retain the source spelling. Parse failures use this runtime's grammar; failed/omitted files are not a clean bill of health.",
        ],
        continuation=continuation,
    )


async def query_imports(
    owner: str,
    repo: str,
    ref="HEAD",
    focus_path="",
    module_prefix="",
    max_items=50,
    start_index=0,
) -> Result[ImportMap]:
    if invalid := _validate(owner, repo, ref):
        return Result(error=invalid.error)
    if focus_path and (
        not _safe_path(focus_path) or PurePosixPath(focus_path).suffix.lower() != ".py"
    ):
        return error(
            "INVALID_PATH",
            "focus_path must be an acquired portable Python source path.",
        )
    module_prefix = unicodedata.normalize("NFKC", module_prefix)
    if len(module_prefix) > 200 or (
        module_prefix
        and not all(part.isidentifier() for part in module_prefix.split("."))
    ):
        return error(
            "INVALID_MODULE",
            "module_prefix must be a dotted Python identifier up to 200 characters.",
        )
    if (
        type(max_items) is not int
        or not 1 <= max_items <= 100
        or type(start_index) is not int
        or not 0 <= start_index <= MAX_IMPORTS
    ):
        return error(
            "INVALID_LIMIT", "max_items must be 1..100; start_index must be 0..20000."
        )
    if not graph._SLOT.acquire(blocking=False):
        return error(
            "IMPORT_BUSY", "Another analysis is running; retry after it finishes."
        )
    try:
        with tempfile.TemporaryDirectory(prefix="github-mcp-imports-") as name:
            directory = Path(name).resolve()
            request = dict(
                owner=owner,
                repo=repo,
                ref=ref,
                focus_path=focus_path,
                module_prefix=module_prefix,
                max_items=max_items,
                start_index=start_index,
            )
            (directory / "input.json").write_text(json.dumps(request), encoding="utf-8")
            if await graph._run_job(directory, worker="github_mcp.import_worker") != 0:
                return error(
                    "IMPORT_WORKER_FAILED",
                    "Import worker failed or exceeded its memory budget.",
                )
            with (directory / "result.json").open("rb") as stream:
                payload = stream.read(graph.MAX_OUTPUT + 1)
            if len(payload) > graph.MAX_OUTPUT:
                return error(
                    "IMPORT_OUTPUT_LIMIT", "Import view exceeds its output budget."
                )
            return Result[ImportMap].model_validate_json(payload)
    except TimeoutError:
        return error(
            "IMPORT_TIMEOUT", "Import analysis exceeded its 45-second deadline."
        )
    except (OSError, ValueError):
        return error(
            "IMPORT_WORKER_FAILED", "Import analysis could not produce a valid result."
        )
    finally:
        graph._SLOT.release()
