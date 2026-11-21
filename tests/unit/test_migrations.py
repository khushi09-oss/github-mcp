import asyncio
from unittest.mock import AsyncMock

import pytest

from github_mcp import imports, migrations, server
from github_mcp.acquisition import Snapshot
from github_mcp.models import Result, ToolError

SHA = "a" * 40


@pytest.fixture
def view(tmp_path):
    raw = b"""from pydantic import (
    BaseSettings as Settings,
    validator as validate,
    BaseModel, field_validator,
)
import pydantic as pd
from pydantic import *
from pydantic.v1 import BaseSettings
from pydantic.v1.validators import validator
from pydantic.settings import BaseSettings
from unrelated import validator
raise RuntimeError('must never execute')
"""
    (tmp_path / "app.py").write_bytes(raw)
    (tmp_path / "bad.py").write_text("def broken(:", encoding="utf-8")
    snapshot = Snapshot(
        tmp_path,
        "a/b",
        SHA,
        ("app.py", "bad.py"),
        {"app.py": "b" * 40, "bad.py": "c" * 40},
        len(raw),
        {"symlink": 1},
    )
    return imports.scan_snapshot(snapshot, module_prefix="pydantic")


def test_labelled_imports_keep_evidence_and_distinguish_unknown(view, monkeypatch):
    query = AsyncMock(return_value=Result(data=view))
    monkeypatch.setattr(imports, "query_imports", query)
    result = asyncio.run(migrations.check_migration("a", "b"))
    report = result.data
    assert report.source == view
    assert [a.status for a in report.assessments] == [
        "matched_import",
        "matched_import",
        "no_rule_match",
        "no_rule_match",
        "unknown",
        "unknown",
        "no_rule_match",
        "no_rule_match",
        "unknown",
    ]
    assert [a.rule.change_kind for a in report.assessments[:2]] == [
        "moved",
        "deprecated",
    ]
    assert report.assessments[0].rule.replacement == "pydantic_settings.BaseSettings"
    assert report.assessments[1].rule.replacement == "pydantic.field_validator"
    assert "migration/" in report.assessments[0].rule.documentation_url
    assert [a.import_index for a in report.assessments] == list(range(9))
    assert report.source.imports[0].alias == "Settings"
    assert report.source.imports[0].evidence.source_url.endswith("/app.py#L1-L5")
    assert report.source.coverage.failed_files == {"bad.py": "SYNTAX_ERROR"}
    assert report.source.coverage.complete is False
    assert report.continuation is None
    assert "safety" in " ".join(report.limitations)
    query.assert_awaited_once_with("a", "b", "HEAD", "", "pydantic", 30, 0)


def test_continuation_routes_to_migration_tool_at_same_commit(view, monkeypatch):
    view.imports = view.imports[:1]
    view.omitted_imports = 8
    view.continuation = imports.ImportContinuation(
        owner="a",
        repo="b",
        ref=SHA,
        focus_path="app.py",
        module_prefix="pydantic",
        max_items=1,
        start_index=1,
    )
    query = AsyncMock(return_value=Result(data=view))
    monkeypatch.setattr(imports, "query_imports", query)
    first = asyncio.run(migrations.check_migration("a", "b", max_items=1))
    args = first.data.continuation.model_dump()
    assert args["migration_id"] == "pydantic-v1-to-v2" and args["ref"] == SHA
    assert "module_prefix" not in args
    asyncio.run(migrations.check_migration(**args))
    query.assert_awaited_with("a", "b", SHA, "app.py", "pydantic", 1, 1)


@pytest.mark.parametrize(
    "arguments,code",
    [
        ({"migration_id": "unknown"}, "UNSUPPORTED_MIGRATION"),
        ({"max_items": True}, "INVALID_LIMIT"),
        ({"max_items": 31}, "INVALID_LIMIT"),
        ({"start_index": -1}, "INVALID_LIMIT"),
        ({"start_index": 20001}, "INVALID_LIMIT"),
        ({"start_index": False}, "INVALID_LIMIT"),
    ],
)
def test_invalid_inputs_fail_before_reads(arguments, code, monkeypatch):
    query = AsyncMock()
    monkeypatch.setattr(imports, "query_imports", query)
    result = asyncio.run(migrations.check_migration("a", "b", **arguments))
    assert result.error.code == code
    query.assert_not_awaited()


def test_empty_page_and_acquisition_errors_remain_explicit(view, monkeypatch):
    view.imports = []
    view.total_imports = 0
    query = AsyncMock(return_value=Result(data=view))
    monkeypatch.setattr(imports, "query_imports", query)
    report = asyncio.run(migrations.check_migration("a", "b")).data
    assert report.assessments == [] and report.source.coverage.complete is False
    error = ToolError(code="IMPORT_BUSY", message="Busy")
    query.return_value = Result(error=error)
    result = asyncio.run(migrations.check_migration("a", "b"))
    assert result.error == error and result.data is None


def test_tool_serializes_success_with_source_and_rules(view, monkeypatch):
    monkeypatch.setattr(
        imports, "query_imports", AsyncMock(return_value=Result(data=view))
    )
    response = asyncio.run(server.check_python_migration("a", "b"))
    assert response.isError is False
    report = response.structuredContent["data"]
    assert report["source"]["commit_sha"] == SHA
    assert report["source"]["imports"][0]["evidence"]["start_line"] == 1
    assert report["assessments"][0]["rule"]["change_kind"] == "moved"
    assert response.structuredContent["error"] is None
