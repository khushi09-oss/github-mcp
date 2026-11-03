"""Exercise optional native SVG in the same isolated worker used by the tool."""

import asyncio
import importlib.util
import json

from github_mcp.diagrams import build_diagram
from github_mcp.models import GraphView, Result
from github_mcp.svg import render_svg, validate_svg


def test_svg_worker_preserves_metadata_and_links(monkeypatch):
    sha = "a" * 40
    link = f"https://github.com/a/b/blob/{sha}/a.py#L1-L1"
    evidence = dict(path="a.py", start_line=1, end_line=1, source_url=link)
    view = GraphView(
        repository="a/b",
        commit_sha=sha,
        focus_path="a.py",
        nodes=[
            dict(id="first", label="start()", evidence=evidence),
            dict(id="second", label="finish()", evidence=evidence),
        ],
        edges=[
            dict(
                source="first",
                target="second",
                relation="calls",
                confidence="INFERRED",
                evidence=evidence,
            )
        ],
        coverage=dict(
            files_acquired=1,
            files_failed=0,
            omitted_files={},
            omitted_nodes=0,
            omitted_edges=0,
            limitations=["Incomplete"],
        ),
    )
    diagram = build_diagram(view, "main")
    from github_mcp import diagrams
    from github_mcp.server import mcp

    async def query(*args):
        return Result(data=view)

    monkeypatch.setattr(diagrams.graph, "query_graph", query)
    rpc = asyncio.run(
        mcp.call_tool(
            "create_architecture_diagram",
            {"owner": "a", "repo": "b", "include_svg": True},
        )
    )
    assert not rpc.isError
    expected = "unavailable" if importlib.util.find_spec("mmdr") is None else "ready"
    assert rpc.structuredContent["data"]["svg_status"] == expected
    assert rpc.structuredContent["data"]["mermaid"]
    result = asyncio.run(render_svg(diagram))
    if importlib.util.find_spec("mmdr") is None:
        assert result.error.code == "SVG_UNAVAILABLE"
        return
    assert result.error is None
    root = validate_svg(result.data, {link})
    text = " ".join(root.itertext())
    assert sha in text and "start()" in text and "inferred" in text
    assert "<script" not in result.data and "foreignObject" not in result.data
    metadata = json.loads(root.find("{http://www.w3.org/2000/svg}metadata").text)
    assert metadata["source"]["commit_sha"] == sha
    assert metadata["source"]["mermaid"] == diagram.mermaid
    assert metadata["source"]["coverage"]["complete"] is False
