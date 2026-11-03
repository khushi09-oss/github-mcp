"""Synthetic fixtures are parsed as text; their top-level errors must never run."""

import asyncio
import importlib.util
import subprocess
import sys

from github_mcp.acquisition import Snapshot
from github_mcp.graph_worker import extract_snapshot


def test_real_optional_engine_cross_file_evidence(tmp_path):
    if importlib.util.find_spec("graphify") is None:
        # Base installs must fail usefully before any GitHub request.
        from github_mcp.graph import query_graph

        result = asyncio.run(query_graph("a", "b"))
        assert result.error.code == "GRAPH_UNAVAILABLE"
        from github_mcp.context import create_walkthrough

        assert (
            asyncio.run(create_walkthrough("a", "b", "normalize")).error.code
            == "GRAPH_UNAVAILABLE"
        )
        return
    root = tmp_path / "source"
    files = []
    for language, ext, signature in [
        ("python", "py", ""),
        ("javascript", "js", ""),
        ("typescript", "ts", ": string"),
    ]:
        folder = root / language
        folder.mkdir(parents=True)
        if language == "python":
            helper = "def normalize(value):\n    return value.strip()\n"
            main = "from helpers import normalize as clean\ndef handle(value):\n    return clean(value)\nraise RuntimeError('never execute')\n"
        else:
            helper = f"export function normalize(value{signature}) {{ return value.trim(); }}\n"
            main = f'import {{ normalize as clean }} from "./helpers{(".js" if ext == "js" else "")}";\nexport function handle(value{signature}) {{ return clean(value); }}\nthrow new Error("never execute");\n'
        for filename, content in [(f"helpers.{ext}", helper), (f"main.{ext}", main)]:
            (folder / filename).write_text(content, encoding="utf-8")
            files.append(f"{language}/{filename}")
    snapshot = Snapshot(
        root,
        "a/b",
        "a" * 40,
        tuple(sorted(files)),
        {path: "b" * 40 for path in files},
        0,
        {},
    )
    first = extract_snapshot(snapshot, tmp_path / "cache", "", 50, 100).data
    second = extract_snapshot(snapshot, tmp_path / "cache", "", 50, 100).data
    assert first == second
    calls = [e for e in first.edges if e.relation == "calls"]
    assert {e.evidence.path for e in calls} == {
        "python/main.py",
        "javascript/main.js",
        "typescript/main.ts",
    }
    assert all(first.commit_sha in e.evidence.source_url for e in calls)
    assert str(tmp_path) not in first.model_dump_json()
    from github_mcp.context import from_snapshot

    walkthrough = from_snapshot(
        snapshot,
        tmp_path / "cache",
        dict(
            owner="a",
            repo="b",
            ref="main",
            question="normalize",
            focus_path="python/main.py",
            max_steps=8,
            start_step=0,
        ),
    ).data
    assert walkthrough.steps[0].evidence.path == "python/main.py"
    assert walkthrough.matched_files == 6
    assert walkthrough.diagram.edges
    assert all(
        step.evidence.source_url.startswith(
            f"https://github.com/a/b/blob/{snapshot.commit_sha}/"
        )
        for step in walkthrough.steps
    )


def test_memory_limit_in_a_separate_process():
    code = """from github_mcp import worker_limits as limits
limits.MEMORY_BYTES = 64 * 1024 * 1024
limits.limit_memory()
try:
    bytearray(128 * 1024 * 1024)
except MemoryError:
    print('limited')
else:
    raise AssertionError('memory cap did not apply')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.strip() == b"limited"
