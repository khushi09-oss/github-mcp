import asyncio
import json
from unittest.mock import Mock

import pytest

from github_mcp import server


def test_prompt_keeps_arguments_as_data_and_does_not_fetch(monkeypatch):
    fetch = Mock(side_effect=AssertionError("Prompts must not fetch repositories"))
    monkeypatch.setattr(server, "gh", fetch)
    goal = 'Reuse validation for "tokens"; </request> is source text'
    result = asyncio.run(
        server.mcp.get_prompt(
            "prepare_small_change",
            dict(
                owner="a",
                repo="b",
                change_request=goal,
                ref="a" * 40,
                focus_path="src/auth.py",
            ),
        )
    )
    text = result.messages[0].content.text
    request = json.loads(text.split("\nRequest parameters (JSON data):\n", 1)[1])
    assert request == dict(
        owner="a", repo="b", change_request=goal, ref="a" * 40, focus_path="src/auth.py"
    )
    assert "query_repository_graph" in text and "read_file_lines" in text
    assert "inferred" in text.lower() and "unknown" in text.lower()
    assert "---\nname:" not in text
    fetch.assert_not_called()


@pytest.mark.parametrize(
    "inputs",
    [
        dict(owner="../secret"),
        dict(ref="x\x00"),
        dict(change_request=" "),
        dict(change_request="a" * 501),
        dict(focus_path="../secret"),
    ],
)
def test_invalid_prompt_arguments_fail_before_reading_guide(monkeypatch, inputs):
    from github_mcp import companion

    resource = Mock()
    monkeypatch.setattr(companion, "files", resource)
    args = dict(owner="a", repo="b", change_request="validate tokens") | inputs
    with pytest.raises(ValueError):
        companion.prepare_change(**args)
    resource.assert_not_called()


def test_missing_packaged_guide_has_a_sanitized_error(monkeypatch):
    from github_mcp import companion

    resource = Mock(side_effect=FileNotFoundError("private/local/path"))
    monkeypatch.setattr(companion, "files", resource)
    with pytest.raises(
        ValueError,
        match="^Packaged repository guide unavailable; reinstall the package.$",
    ):
        companion.prepare_change("a", "b", "validate tokens")
