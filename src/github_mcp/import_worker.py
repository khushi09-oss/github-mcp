"""Internal one-shot AST worker. Downloaded source is parsed, never imported."""

import contextlib
import json
import os
import sys
from pathlib import Path

from github_mcp.acquisition import SnapshotError, acquire_snapshot
from github_mcp.graph import MAX_OUTPUT
from github_mcp.graph_worker import offline
from github_mcp.imports import ImportLimit, ImportMap, error, scan_snapshot
from github_mcp.models import Result
from github_mcp.worker_limits import limit_memory


def execute(directory: Path) -> Result[ImportMap]:
    try:
        limit_memory()
        request = json.loads((directory / "input.json").read_text(encoding="utf-8"))
        with acquire_snapshot(
            request["owner"], request["repo"], request["ref"], temp_parent=directory
        ) as snapshot:
            if request["focus_path"] and request["focus_path"] not in snapshot.files:
                return error(
                    "FOCUS_NOT_FOUND",
                    "focus_path was not acquired; choose an included Python source file.",
                )
            os.environ.pop("GITHUB_TOKEN", None)
            sys.addaudithook(offline)
            return Result(
                data=scan_snapshot(
                    snapshot,
                    request["focus_path"],
                    request["module_prefix"],
                    request["max_items"],
                    request["start_index"],
                )
            )
    except SnapshotError as exc:
        return Result(error=exc.error)
    except ImportLimit:
        return error(
            "IMPORT_RECORD_LIMIT",
            "Source exceeds 20000 import records; narrow focus_path.",
        )
    except (MemoryError, OSError):
        return error(
            "IMPORT_RESOURCE_LIMIT",
            "Import analysis exceeded its process/storage limits.",
        )
    except Exception:
        return error(
            "IMPORT_SCAN_FAILED", "Import analysis could not verify source statements."
        )


def main():
    directory = Path(sys.argv[1]).resolve()
    with (
        open(os.devnull, "w") as silent,
        contextlib.redirect_stdout(silent),
        contextlib.redirect_stderr(silent),
    ):
        result = execute(directory)
        payload = result.model_dump_json().encode("utf-8")
        if len(payload) > MAX_OUTPUT:
            payload = (
                error("IMPORT_OUTPUT_LIMIT", "Import view exceeds its output budget.")
                .model_dump_json()
                .encode()
            )
        with (directory / "result.json").open("xb") as stream:
            stream.write(payload)


if __name__ == "__main__":
    main()
