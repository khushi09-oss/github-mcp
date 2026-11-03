import asyncio
import json
import sys
import threading
from unittest.mock import Mock

import pytest

from github_mcp import graph
from github_mcp.acquisition import Snapshot

SHA = "a" * 40


@pytest.fixture
def snapshot(tmp_path):
    (tmp_path / "a.py").write_text("def start():\n    pass\n")
    (tmp_path / "b.py").write_text("def end():\n    pass\n")
    return Snapshot(tmp_path, "a/b", SHA, ("a.py", "b.py"), {}, 48, {"symlink": 1})


def raw_graph():
    return {
        "nodes": [
            dict(id="one", label="start()", source_file="a.py", source_location="L1"),
            dict(id="two", label="end()", source_file="b.py", source_location="L1"),
        ],
        "edges": [
            dict(
                source="one",
                target="two",
                relation="calls",
                confidence="INFERRED",
                source_file="a.py",
                source_location="L2",
            )
        ],
        "failed_sources": [],
        "skipped_sources": [],
    }


def test_evidence_is_pinned_and_direction_confidence_survive(snapshot):
    view = graph.normalize(raw_graph(), snapshot, "a.py", 30, 60)
    assert view.nodes[0].evidence.source_url.endswith(f"/{SHA}/a.py#L1-L1")
    assert view.edges[0].source == view.nodes[0].id
    assert view.edges[0].target == view.nodes[1].id
    assert view.edges[0].confidence == "INFERRED"
    assert view.edges[0].evidence.start_line == 2
    assert view.coverage.complete is False
    assert view.coverage.omitted_files == {"symlink": 1}


def test_unverifiable_nodes_and_edges_are_omitted(snapshot):
    raw = raw_graph()
    raw["nodes"][1]["source_file"] = "/private/location/key.py"
    view = graph.normalize(raw, snapshot, "", 30, 60)
    assert len(view.nodes) == 1 and view.edges == []
    assert view.coverage.omitted_nodes == view.coverage.omitted_edges == 1
    assert "private" not in view.model_dump_json()


def test_stable_order_limits_and_parallel_evidence(snapshot):
    raw = raw_graph()
    raw["edges"].append(raw["edges"][0] | {"confidence": "AMBIGUOUS"})
    first = graph.normalize(raw, snapshot, "", 30, 60)
    raw["nodes"].reverse()
    raw["edges"].reverse()
    assert first == graph.normalize(raw, snapshot, "", 30, 60)
    assert len(first.edges) == 2
    bounded = graph.normalize(raw, snapshot, "", 1, 1)
    assert len(bounded.nodes) == 1 and bounded.edges == []
    assert bounded.coverage.omitted_nodes == 1
    assert bounded.coverage.omitted_edges == 2


@pytest.mark.parametrize("location", ["L0", "L3", "L2-L1", "not a line"])
def test_invalid_evidence_location_cannot_create_citation(snapshot, location):
    raw = raw_graph()
    raw["edges"][0]["source_location"] = location
    assert graph.normalize(raw, snapshot, "", 30, 60).edges == []


def test_duplicate_raw_ids_cannot_misattribute_edges(snapshot):
    raw = raw_graph()
    raw["nodes"].append(raw["nodes"][0] | {"source_file": "b.py"})
    view = graph.normalize(raw, snapshot, "", 30, 60)
    assert view.edges == []


def test_invalid_query_never_starts_worker(monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(graph.asyncio, "create_subprocess_exec", spawn)
    result = asyncio.run(graph.query_graph("../a", "b"))
    assert result.error.code == "INVALID_REPOSITORY"
    spawn.assert_not_called()


def test_bare_cr_does_not_invent_source_lines(snapshot):
    (snapshot.root / "a.py").write_bytes(b"first\rsecond")
    assert graph.normalize(raw_graph(), snapshot, "", 30, 60).edges == []


def test_query_busy_does_not_create_artifacts(monkeypatch):
    slot = threading.BoundedSemaphore(1)
    slot.acquire()
    monkeypatch.setattr(graph, "_SLOT", slot)
    result = asyncio.run(graph.query_graph("a", "b"))
    assert result.error.code == "GRAPH_BUSY"


@pytest.mark.parametrize(
    "payload,code",
    [
        (b"not json", "GRAPH_WORKER_FAILED"),
        (b"x" * (graph.MAX_OUTPUT + 1), "GRAPH_OUTPUT_LIMIT"),
    ],
)
def test_worker_output_is_bounded_and_sanitized(monkeypatch, tmp_path, payload, code):
    monkeypatch.setattr(graph.tempfile, "tempdir", str(tmp_path))

    async def job(directory):
        (directory / "result.json").write_bytes(payload)
        return 0

    monkeypatch.setattr(graph, "_run_job", job)
    result = asyncio.run(graph.query_graph("a", "b"))
    assert result.error.code == code
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "cancel,delayed_spawn", [(False, False), (True, False), (True, True)]
)
def test_timeout_and_cancellation_reap_real_child_before_cleanup(
    monkeypatch, tmp_path, cancel, delayed_spawn
):
    monkeypatch.setattr(graph.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(graph, "TIMEOUT", 0.05 if not cancel else 10)
    create = asyncio.create_subprocess_exec
    children = []

    async def spawn(*args, **kwargs):
        child = await create(
            sys.executable, "-I", "-c", "import time; time.sleep(30)", **kwargs
        )
        children.append(child)
        if delayed_spawn:
            await asyncio.sleep(0.05)
        return child

    monkeypatch.setattr(graph.asyncio, "create_subprocess_exec", spawn)

    async def exercise():
        task = asyncio.create_task(graph.query_graph("a", "b"))
        if cancel:
            while not children:
                await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).error.code == "GRAPH_TIMEOUT"
        assert children[0].returncode is not None

    asyncio.run(exercise())
    assert list(tmp_path.iterdir()) == []


def test_result_schema_survives_mcp_conversion(snapshot, monkeypatch):
    from github_mcp.models import GraphView, Result
    from github_mcp.server import mcp

    async def query(*args, **kwargs):
        return Result(data=graph.normalize(raw_graph(), snapshot, "", 30, 60))

    monkeypatch.setattr(graph, "query_graph", query)
    result = asyncio.run(
        mcp.call_tool("query_repository_graph", {"owner": "a", "repo": "b"})
    )
    assert not result.isError
    parsed = Result[GraphView].model_validate(result.structuredContent)
    assert parsed.data.commit_sha == SHA


def test_wrong_engine_version_fails_before_github(monkeypatch, tmp_path):
    from github_mcp import graph_worker

    monkeypatch.setattr(graph_worker, "limit_memory", lambda: None)
    monkeypatch.setattr(graph_worker.importlib.metadata, "version", lambda _: "0.9.101")
    acquire = Mock()
    monkeypatch.setattr(graph_worker, "acquire_snapshot", acquire)
    assert graph_worker.execute(tmp_path).error.code == "GRAPH_VERSION"
    acquire.assert_not_called()


@pytest.mark.parametrize(
    "inputs", [{"max_nodes": 0}, {"max_edges": 101}, {"focus_path": "../secret"}]
)
def test_invalid_focus_or_limits_never_spawn(monkeypatch, inputs):
    spawn = Mock()
    monkeypatch.setattr(graph.asyncio, "create_subprocess_exec", spawn)
    assert asyncio.run(graph.query_graph("a", "b", **inputs)).error
    spawn.assert_not_called()


def test_worker_uses_owned_workspace_and_clears_credentials(
    snapshot, monkeypatch, tmp_path
):
    from contextlib import contextmanager

    from github_mcp import graph_worker
    from github_mcp.models import Result

    (tmp_path / "input.json").write_text(
        json.dumps(
            dict(
                owner="a", repo="b", ref=SHA, focus_path="", max_nodes=30, max_edges=60
            )
        )
    )
    monkeypatch.setattr(graph_worker, "limit_memory", lambda: None)
    monkeypatch.setattr(graph_worker.importlib.metadata, "version", lambda _: "0.9.100")
    monkeypatch.setenv("GITHUB_TOKEN", "private-test-token")
    audit = Mock()
    monkeypatch.setattr(graph_worker.sys, "addaudithook", audit)

    @contextmanager
    def acquire(*args, **kwargs):
        assert kwargs["temp_parent"] == tmp_path
        yield snapshot

    monkeypatch.setattr(graph_worker, "acquire_snapshot", acquire)

    def extract(snapshot, *args):
        assert "GITHUB_TOKEN" not in graph_worker.os.environ
        return Result(data=graph.normalize(raw_graph(), snapshot, "", 30, 60))

    monkeypatch.setattr(graph_worker, "extract_snapshot", extract)
    assert graph_worker.execute(tmp_path).data.commit_sha == SHA
    audit.assert_called_once_with(graph_worker.offline)
