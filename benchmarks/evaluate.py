"""Offline artifact evaluation on fixed, synthetic source; no fixture execution."""

import argparse
import base64
import contextlib
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote

FIXTURE = Path(__file__).resolve().parent / "fixtures/small.json"
SHA = "0" * 40  # Synthetic identity, not a GitHub commit or working source link.


def score(view, expected):
    nodes = {node["id"]: node for node in view["nodes"]}
    return [
        any(
            edge["relation"] == "calls"
            and nodes[edge["source"]]["evidence"]["path"] == label["source"]
            and nodes[edge["target"]]["evidence"]["path"] == label["target"]
            and nodes[edge["source"]]["label"] == label["caller"]
            and nodes[edge["target"]]["label"] == label["callee"]
            and edge["evidence"]["path"] == label["source"]
            and edge["evidence"]["start_line"]
            <= label["line"]
            <= edge["evidence"]["end_line"]
            for edge in view["edges"]
        )
        for label in expected
    ]


def passed(run):
    return (
        "error" not in run
        and all(run.get("labelled_relations_found", [True]))
        and all(run.get("labelled_callsite_lines_available", [True]))
    )


def summarize(runs):
    summary = {}
    for arm in sorted({run["arm"] for run in runs}):
        selected = [run for run in runs if run["arm"] == arm]
        success = [run for run in selected if passed(run)]
        summary[arm] = dict(
            trials=len(selected),
            failures=len(selected) - len(success),
            median_success_seconds=statistics.median(
                run["elapsed_seconds"] for run in success
            )
            if success
            else None,
        )
    return summary


def worker(arm):
    from github_mcp import snapshots
    from github_mcp.acquisition import Snapshot, _safe_path
    from github_mcp.graph_worker import extract_snapshot, offline
    from github_mcp.worker_limits import limit_memory

    limit_memory()
    sys.addaudithook(offline)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = {path: text.encode("utf-8") for path, text in fixture["files"].items()}
    if not all(_safe_path(path) for path in source):
        raise ValueError("Unsafe fixture path")
    blobs = {
        path: hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        for path, raw in source.items()
    }

    def contents(path, params=None, **kwargs):
        if params != {"ref": SHA}:
            raise ValueError("Unpinned fixture read")
        path = unquote(path.split("/contents/", 1)[1])
        raw = source[path]
        return dict(
            type="file",
            encoding="base64",
            content=base64.b64encode(raw).decode(),
            size=len(raw),
            sha=blobs[path],
            path=path,
        )

    if arm == "retrieval":
        snapshots.gh = contents
        results = [
            snapshots.read_file_lines("fixture", "example", path, SHA, line_count=200)
            for path in sorted(source)
        ]
        if any(result.error for result in results):
            raise ValueError("Fixture retrieval failed")
        payload = [result.model_dump(mode="json") for result in results]
        present = {result.data.path: result.data.text for result in results}
        checks = [
            bool(present[label["source"]].splitlines()[label["line"] - 1])
            for label in fixture["expected"]
        ]
        metrics = dict(labelled_callsite_lines_available=checks)
    else:
        if importlib.metadata.version("graphifyy") != "0.9.100":
            raise ValueError("Wrong extractor version")
        with tempfile.TemporaryDirectory(prefix="github-mcp-eval-") as name:
            root = Path(name)
            for path, raw in source.items():
                target = root / "source" / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            snapshot = Snapshot(
                root / "source",
                "fixture/example",
                SHA,
                tuple(sorted(source)),
                blobs,
                sum(map(len, source.values())),
                {},
            )
            result = extract_snapshot(snapshot, root / "cache", "", 50, 100)
            if result.error:
                raise ValueError("Fixture extraction failed")
            payload = result.model_dump(mode="json")
            metrics = dict(
                labelled_relations_found=score(payload["data"], fixture["expected"]),
                coverage=payload["data"]["coverage"],
            )
    return dict(bytes=len(json.dumps(payload, ensure_ascii=True).encode()), **metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 11))
    parser.add_argument(
        "--worker", choices=["retrieval", "graph"], help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    if args.worker:
        with (
            open(os.devnull, "w") as silent,
            contextlib.redirect_stdout(silent),
            contextlib.redirect_stderr(silent),
        ):
            result = worker(args.worker)
        print(json.dumps(result))
        return
    # Worker credentials/provider keys/PYTHONPATH are deliberately absent.
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "LOCALAPPDATA",
        }
    }
    runs = []
    for _ in range(args.repeats):
        for arm in ("retrieval", "graph"):
            started = time.perf_counter()
            try:
                process = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        str(Path(__file__).resolve()),
                        "--worker",
                        arm,
                    ],
                    capture_output=True,
                    env=env,
                    timeout=45,
                )
                result = (
                    json.loads(process.stdout)
                    if process.returncode == 0
                    else dict(error="worker_failed")
                )
            except subprocess.TimeoutExpired:
                result = dict(error="timeout")
            except (OSError, ValueError):
                result = dict(error="invalid_worker_result")
            runs.append(
                dict(
                    arm=arm,
                    elapsed_seconds=round(time.perf_counter() - started, 4),
                    **result,
                )
            )
    report = dict(
        schema_version=1,
        fixture_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        python=platform.python_version(),
        platform=platform.system(),
        package=importlib.metadata.version("github-mcp"),
        model=None,
        model_tokens=None,
        provider_cost_usd=None,
        network_calls=0,
        runs=runs,
        summary=summarize(runs),
    )
    print(json.dumps(report, indent=2))
    if not all(passed(run) for run in runs):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
