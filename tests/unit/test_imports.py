import asyncio
import hashlib
import json
from unittest.mock import Mock

import pytest

from github_mcp import graph, imports
from github_mcp.acquisition import Snapshot

SHA = "a" * 40


@pytest.fixture
def snapshot(tmp_path):
    sources = {
        "a.py": b"import requests.sessions, os as operating\r\nfrom pydantic import (\r\n    BaseModel as Model,\r\n)\r\nfrom .local import thing as local\r\nfrom x import *\r\nif False:\r\n    import hidden\r\n__import__('dynamic')\r\nraise RuntimeError('never execute')\r\n",
        "bad.py": b"def broken(:\n",
        "cr.py": b"import a\rimport b\r",
        "script.js": b"throw Error('never execute');",
    }
    blobs = {}
    for path, raw in sources.items():
        (tmp_path / path).write_bytes(raw)
        blobs[path] = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest()
    return Snapshot(
        tmp_path,
        "a/b",
        SHA,
        tuple(sources),
        blobs,
        sum(map(len, sources.values())),
        {"symlink": 1},
    )


def test_aliases_spans_failures_and_unresolved_targets(snapshot):
    view = imports.scan_snapshot(snapshot)
    assert len(view.imports) == 6
    assert (
        view.imports[0].module == "requests.sessions"
        and view.imports[0].bound_name == "requests"
    )
    assert view.imports[1].alias == "operating"
    model = view.imports[2]
    assert (model.module, model.imported_name, model.alias, model.bound_name) == (
        "pydantic",
        "BaseModel",
        "Model",
        "Model",
    )
    assert model.evidence.source_url.endswith(f"/{SHA}/a.py#L2-L4")
    assert view.imports[3].resolution == "relative_unresolved"
    assert (
        view.imports[4].resolution == "star_unresolved"
        and view.imports[4].bound_name is None
    )
    assert view.imports[5].module == "hidden"
    assert view.coverage.failed_files == {
        "bad.py": "SYNTAX_ERROR",
        "cr.py": "UNSUPPORTED_NEWLINES",
    }
    assert view.coverage.unscanned_files == 1 and view.coverage.complete is False
    assert str(snapshot.root) not in view.model_dump_json()


def test_filter_scope_and_pagination_are_explicit(snapshot):
    first = imports.scan_snapshot(snapshot, max_items=2)
    assert first.total_imports == 6 and first.omitted_imports == 4
    assert first.continuation.ref == SHA and first.continuation.start_index == 2
    focused = imports.scan_snapshot(
        snapshot, focus_path="a.py", module_prefix="pydantic"
    )
    assert len(focused.imports) == 1 and focused.coverage.filtered_imports == 5
    assert focused.coverage.unscanned_files == 3
    assert focused.continuation is None
    assert (
        imports.scan_snapshot(snapshot, module_prefix="pydantic.BaseModel").imports
        == []
    )


def test_record_limit_does_not_silently_claim_complete(snapshot, monkeypatch):
    monkeypatch.setattr(imports, "MAX_IMPORTS", 1)
    with pytest.raises(imports.ImportLimit):
        imports.scan_snapshot(snapshot)


def test_bom_and_ast_identifier_normalization(tmp_path):
    raw = "import \u212aelvin as alias\n".encode("utf-8-sig")
    (tmp_path / "a.py").write_bytes(raw)
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    snap = Snapshot(tmp_path, "a/b", SHA, ("a.py",), {"a.py": blob}, len(raw), {})
    record = imports.scan_snapshot(snap, module_prefix="Kelvin").imports[0]
    assert record.module == "Kelvin" and record.alias == "alias"
    assert record.evidence.start_line == record.evidence.end_line == 1


def test_worker_removes_credentials_before_parsing(snapshot, monkeypatch, tmp_path):
    from contextlib import contextmanager

    from github_mcp import import_worker

    request = dict(
        owner="a",
        repo="b",
        ref=SHA,
        focus_path="",
        module_prefix="",
        max_items=50,
        start_index=0,
    )
    (tmp_path / "input.json").write_text(json.dumps(request))
    monkeypatch.setattr(import_worker, "limit_memory", lambda: None)
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    audit = Mock()
    monkeypatch.setattr(import_worker.sys, "addaudithook", audit)

    @contextmanager
    def acquire(*args, **kwargs):
        assert kwargs["temp_parent"] == tmp_path
        yield snapshot

    monkeypatch.setattr(import_worker, "acquire_snapshot", acquire)
    original = import_worker.scan_snapshot

    def scan(*args):
        assert "GITHUB_TOKEN" not in import_worker.os.environ
        return original(*args)

    monkeypatch.setattr(import_worker, "scan_snapshot", scan)
    assert import_worker.execute(tmp_path).data.commit_sha == SHA
    audit.assert_called_once_with(import_worker.offline)


@pytest.mark.parametrize(
    "args",
    [
        dict(focus_path="../x.py"),
        dict(focus_path="x.js"),
        dict(module_prefix="x..y"),
        dict(max_items=0),
        dict(start_index=20001),
    ],
)
def test_invalid_arguments_never_spawn(monkeypatch, args):
    spawn = Mock()
    monkeypatch.setattr(graph, "_run_job", spawn)
    assert asyncio.run(imports.query_imports("a", "b", **args)).error
    spawn.assert_not_called()


@pytest.mark.parametrize("failure", ["timeout", "exit", "json", "size", "cancel"])
def test_parent_cleanup_and_gate_release(monkeypatch, failure):
    jobs = []

    async def run(directory, **kwargs):
        jobs.append(directory)
        assert kwargs["worker"] == "github_mcp.import_worker"
        if failure == "timeout":
            raise TimeoutError
        if failure == "cancel":
            raise asyncio.CancelledError
        (directory / "result.json").write_bytes(
            b"x" * (graph.MAX_OUTPUT + 1) if failure == "size" else b"invalid"
        )
        return 1 if failure == "exit" else 0

    monkeypatch.setattr(graph, "_run_job", run)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(imports.query_imports("a", "b"))
    else:
        assert asyncio.run(imports.query_imports("a", "b")).error
    assert all(not directory.exists() for directory in jobs)
    assert graph._SLOT.acquire(blocking=False)
    graph._SLOT.release()


def test_shared_busy_gate():
    assert graph._SLOT.acquire(blocking=False)
    try:
        assert asyncio.run(imports.query_imports("a", "b")).error.code == "IMPORT_BUSY"
    finally:
        graph._SLOT.release()


def test_worker_fails_closed_without_memory_limits(monkeypatch, tmp_path):
    from github_mcp import import_worker

    monkeypatch.setattr(
        import_worker, "limit_memory", Mock(side_effect=OSError("private/local/path"))
    )
    acquire = Mock()
    monkeypatch.setattr(import_worker, "acquire_snapshot", acquire)
    result = import_worker.execute(tmp_path)
    assert result.error.code == "IMPORT_RESOURCE_LIMIT"
    assert "private/local/path" not in result.model_dump_json()
    acquire.assert_not_called()


def test_mcp_result_and_pinned_job_request(snapshot, monkeypatch):
    from github_mcp.models import Result
    from github_mcp.server import mcp

    async def run(directory, **kwargs):
        request = json.loads((directory / "input.json").read_text())
        assert request["ref"] == SHA
        (directory / "result.json").write_text(
            Result(data=imports.scan_snapshot(snapshot)).model_dump_json()
        )
        return 0

    monkeypatch.setattr(graph, "_run_job", run)
    result = asyncio.run(
        mcp.call_tool("map_python_imports", dict(owner="a", repo="b", ref=SHA))
    )
    assert not result.isError and result.structuredContent["data"]["commit_sha"] == SHA
