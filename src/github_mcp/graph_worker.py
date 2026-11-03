"""Internal one-shot worker; never imports modules from the acquired repository."""

import contextlib
import importlib.metadata
import json
import os
import sys
from importlib import import_module
from pathlib import Path

from github_mcp.acquisition import Snapshot, SnapshotError, acquire_snapshot
from github_mcp.graph import MAX_OUTPUT, error, normalize
from github_mcp.models import GraphView, Result
from github_mcp.worker_limits import limit_memory


def offline(event, args):
    if event.startswith("socket.") or event in {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.fork",
        "os.forkpty",
    }:
        raise PermissionError("External operations are disabled during extraction")


def extract_snapshot(
    snapshot: Snapshot, cache: Path, focus: str, max_nodes: int, max_edges: int
) -> Result[GraphView]:
    extract = import_module("graphify.extract").extract

    raw = extract(
        [snapshot.root / p for p in snapshot.files],
        root=snapshot.root,
        cache_root=cache,
        parallel=False,
    )
    return Result(data=normalize(raw, snapshot, focus, max_nodes, max_edges))


def execute(directory: Path) -> Result[GraphView]:
    try:
        limit_memory()
        if importlib.metadata.version("graphifyy") != "0.9.100":
            return error(
                "GRAPH_VERSION",
                "Analysis requires graphifyy==0.9.100; synchronize the locked analysis extra.",
            )
        request = json.loads((directory / "input.json").read_text(encoding="utf-8"))
        with acquire_snapshot(
            request["owner"], request["repo"], request["ref"], temp_parent=directory
        ) as snapshot:
            if request["focus_path"] and request["focus_path"] not in snapshot.files:
                return error(
                    "FOCUS_NOT_FOUND",
                    "focus_path was not acquired; choose an included source file.",
                )
            # The transport is finished. Extraction cannot call models, launch tools or use the network.
            os.environ.pop("GITHUB_TOKEN", None)
            sys.addaudithook(offline)
            os.environ["GRAPHIFY_OUT"] = "graphify-out"
            return extract_snapshot(
                snapshot,
                directory,
                request["focus_path"],
                request["max_nodes"],
                request["max_edges"],
            )
    except importlib.metadata.PackageNotFoundError:
        return error(
            "GRAPH_UNAVAILABLE",
            "Install the optional analysis extra: uv sync --locked --extra analysis.",
        )
    except SnapshotError as exc:
        return Result(error=exc.error)
    except (MemoryError, OSError):
        return error(
            "GRAPH_RESOURCE_LIMIT",
            "Analysis could not stay within its process or storage limits.",
        )
    except Exception:
        return error(
            "GRAPH_EXTRACTION_FAILED",
            "Analysis failed; source relationships could not be verified.",
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
                error(
                    "GRAPH_OUTPUT_LIMIT",
                    "Graph view exceeds its output budget; lower node/edge limits.",
                )
                .model_dump_json()
                .encode()
            )
        with (directory / "result.json").open("xb") as stream:
            stream.write(payload)


if __name__ == "__main__":
    main()
