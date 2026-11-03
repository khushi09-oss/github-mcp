"""Optional client guidance, loaded only from the installed package."""

import json
from importlib.resources import files

from github_mcp.acquisition import _safe_path
from github_mcp.snapshots import _validate


def prepare_change(
    owner: str,
    repo: str,
    change_request: str,
    ref: str = "HEAD",
    focus_path: str = "",
) -> str:
    invalid = _validate(owner, repo, ref)
    if invalid:
        assert invalid.error is not None
        raise ValueError(invalid.error.message)
    if (
        not change_request.strip()
        or len(change_request) > 500
        or any(ord(c) < 32 or ord(c) == 127 for c in change_request)
    ):
        raise ValueError(
            "Supply a change request of 1..500 characters without controls."
        )
    if (focus_path and not _safe_path(focus_path)) or len(focus_path) > 180:
        raise ValueError("focus_path must be a portable relative source path.")
    try:
        guide = (
            files("github_mcp")
            .joinpath("skills/repository-guide/SKILL.md")
            .read_text(encoding="utf-8")
        )
    except OSError:
        raise ValueError(
            "Packaged repository guide unavailable; reinstall the package."
        ) from None
    body = guide.partition("\n---\n")[2].strip()
    if not body:
        raise ValueError("Packaged repository guide is invalid; reinstall the package.")
    request = dict(
        owner=owner,
        repo=repo,
        change_request=change_request,
        ref=ref,
        focus_path=focus_path,
    )
    return (
        body
        + "\n\nRequest parameters (JSON data):\n"
        + json.dumps(request, ensure_ascii=True)
    )
