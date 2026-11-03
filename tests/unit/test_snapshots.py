import asyncio
import base64
from unittest.mock import Mock

import pytest

from github_mcp import snapshots
from github_mcp.models import FileChunk, Result
from github_mcp.server import mcp

SHA = "a" * 40


def file_data(text):
    raw = text.encode() if isinstance(text, str) else text
    return dict(
        type="file",
        path="a.py",
        encoding="base64",
        size=len(raw),
        sha="b" * 40,
        content=base64.b64encode(raw).decode(),
    )


def test_branch_is_resolved_once_and_continuation_is_pinned(monkeypatch):
    api = Mock(
        side_effect=[
            {"sha": SHA},
            file_data("one\r\ntwo\nthree"),
            file_data("one\r\ntwo\nthree"),
        ]
    )
    monkeypatch.setattr(snapshots, "gh", api)
    first = snapshots.read_file_lines("a", "b", "a.py", "main", 1, 1).data
    assert first.text == "one\r\n"
    assert first.source_url.endswith(f"/{SHA}/a.py#L1-L1")
    second = snapshots.read_file_lines(**first.continuation.model_dump()).data
    assert second.text == "two\n"
    assert second.commit_sha == SHA
    assert api.call_count == 3
    assert api.call_args_list[1].kwargs["params"] == {"ref": SHA}
    assert api.call_args_list[2].kwargs["params"] == {"ref": SHA}


@pytest.mark.parametrize("path", ["../secret", "/a", "a\\b", "a//b", "a/./b", "a\x00b"])
def test_unsafe_paths_do_not_call_api(monkeypatch, path):
    api = Mock()
    monkeypatch.setattr(snapshots, "gh", api)
    assert snapshots.read_file_lines("a", "b", path).error.code == "INVALID_PATH"
    api.assert_not_called()


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"\xff", "UNSUPPORTED_FILE"),
        (b"a\x00b", "UNSUPPORTED_FILE"),
        (b"a" * 12001, "LINE_TOO_LONG"),
    ],
)
def test_unsupported_text(monkeypatch, raw, code):
    monkeypatch.setattr(snapshots, "gh", Mock(return_value=file_data(raw)))
    assert snapshots.read_file_lines("a", "b", "a.py", SHA).error.code == code


def test_line_budget_and_empty_file(monkeypatch):
    api = Mock(return_value=file_data("x" * 7000 + "\ny\n" + "z" * 6000))
    monkeypatch.setattr(snapshots, "gh", api)
    chunk = snapshots.read_file_lines("a", "b", "a.py", SHA).data
    assert chunk.end_line == 2
    assert chunk.continuation.start_line == 3
    api.return_value = file_data("")
    chunk = snapshots.read_file_lines("a", "b", "a.py", SHA).data
    assert chunk.total_lines == chunk.end_line == 0
    assert chunk.text == "" and chunk.continuation is None
    assert (
        snapshots.read_file_lines("a", "b", "a.py", SHA, 2).error.code
        == "INVALID_RANGE"
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ({"size": 1000001}, "UNSUPPORTED_FILE"),
        ({"size": 100}, "INVALID_RESPONSE"),
        ({"content": "!"}, "INVALID_RESPONSE"),
        ({"path": "elsewhere"}, "INVALID_RESPONSE"),
        ({"type": "dir"}, "UNSUPPORTED_FILE"),
    ],
)
def test_invalid_metadata(monkeypatch, change, code):
    monkeypatch.setattr(snapshots, "gh", Mock(return_value=file_data("a") | change))
    assert snapshots.read_file_lines("a", "b", "a.py", SHA).error.code == code


def test_resolution_errors_and_encoded_paths(monkeypatch):
    api = Mock(return_value={"sha": "bad"})
    monkeypatch.setattr(snapshots, "gh", api)
    assert snapshots.resolve_revision("a", "b").error.code == "INVALID_RESPONSE"
    api.return_value = {
        "error": "Rate limited",
        "error_code": "rate_limit",
        "retry_after_seconds": 60,
    }
    result = snapshots.resolve_revision("a", "b")
    assert result.error.retry_after_seconds == 60
    assert result.as_mcp().isError
    api.return_value = file_data("a") | {"path": "x ?#é.py"}
    assert snapshots.read_file_lines("a", "b", "x ?#é.py", SHA).data
    assert api.call_args.args[0].endswith("/x%20%3F%23%C3%A9.py")


def test_success_survives_mcp_output_validation(monkeypatch):
    monkeypatch.setattr(snapshots, "gh", Mock(return_value=file_data("a\u2028b\n")))
    result = asyncio.run(
        mcp.call_tool(
            "read_file_lines", {"owner": "a", "repo": "b", "path": "a.py", "ref": SHA}
        )
    )
    parsed = Result[FileChunk].model_validate(result.structuredContent)
    assert result.isError is False
    assert parsed.data.total_lines == 1
    assert parsed.data.continuation is None
    assert parsed.data.text == "a\u2028b\n"


@pytest.mark.parametrize(
    "inputs,code",
    [
        ({"owner": "../a"}, "INVALID_REPOSITORY"),
        ({"ref": ".."}, "INVALID_REF"),
        ({"ref": "x\n"}, "INVALID_REF"),
        ({"start_line": 0}, "INVALID_RANGE"),
        ({"start_line": True}, "INVALID_RANGE"),
        ({"line_count": 201}, "INVALID_RANGE"),
    ],
)
def test_invalid_inputs_do_not_call_api(monkeypatch, inputs, code):
    api = Mock()
    monkeypatch.setattr(snapshots, "gh", api)
    args = dict(owner="a", repo="b", path="a.py", ref=SHA) | inputs
    assert snapshots.read_file_lines(**args).error.code == code
    api.assert_not_called()
