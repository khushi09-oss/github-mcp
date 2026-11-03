import asyncio

import pytest

from github_mcp import diagrams
from github_mcp.models import (
    Evidence,
    GraphCoverage,
    GraphEdge,
    GraphNode,
    GraphView,
    Result,
)

SHA = "a" * 40


def fixture_graph(label="start()", confidence="EXTRACTED"):
    def evidence(path):
        return Evidence(
            path=path,
            start_line=1,
            end_line=1,
            source_url=f"https://github.com/a/b/blob/{SHA}/{path}#L1-L1",
        )

    return GraphView(
        repository="a/b",
        commit_sha=SHA,
        focus_path="",
        nodes=[
            GraphNode(id="one", label=label, evidence=evidence("src/a.py")),
            GraphNode(id="two", label="finish()", evidence=evidence("src/b.py")),
        ],
        edges=[
            GraphEdge(
                source="one",
                target="two",
                relation="calls",
                confidence=confidence,
                evidence=evidence("src/a.py"),
            )
        ],
        coverage=GraphCoverage(
            files_acquired=2,
            files_failed=0,
            omitted_files={"symlink": 1},
            omitted_nodes=3,
            omitted_edges=2,
            limitations=["Incomplete static graph"],
        ),
    )


def test_groups_links_legend_coverage_and_reading_order():
    diagram = diagrams.build_diagram(fixture_graph(), "main")
    assert 'subgraph F0["src/a.py"]' in diagram.mermaid
    assert f"https://github.com/a/b/blob/{SHA}/src/a.py#L1-L1" in diagram.mermaid
    assert "calls - observed" in diagram.mermaid
    assert "omitted nodes 3" in diagram.text
    assert "omitted files 1" in diagram.text
    assert diagram.reading_order == ["one", "two"]
    assert SHA in diagram.text and "main" in diagram.text
    assert diagram.view == "overview" and len(diagram.legend) == 3


@pytest.mark.parametrize(
    "confidence,word", [("INFERRED", "inferred"), ("AMBIGUOUS", "unknown")]
)
def test_confidence_is_visible_without_color(confidence, word):
    diagram = diagrams.build_diagram(fixture_graph(confidence=confidence), SHA)
    assert f"calls - {word}" in diagram.mermaid
    assert "-.->" in diagram.mermaid
    assert confidence in diagram.text


def test_order_is_deterministic_and_focus_is_explicit():
    graph = fixture_graph()
    graph.focus_path = "src/a.py"
    expected = diagrams.build_diagram(graph, SHA)
    graph.nodes.reverse()
    graph.edges.reverse()
    assert diagrams.build_diagram(graph, SHA) == expected
    assert expected.view == "focus" and "src/a.py" in expected.text


@pytest.mark.parametrize(
    "label",
    [
        'x"]\nclick N0 "javascript:alert(1)"',
        "<script>alert(1)</script>",
        '%%{init: {"securityLevel":"loose"}}%%',
        "`[link](https://evil.test)`",
    ],
)
def test_labels_cannot_inject_directives_html_links_or_statements(label):
    diagram = diagrams.build_diagram(fixture_graph(label), SHA)
    assert "<script" not in diagram.mermaid
    assert "%%{" not in diagram.mermaid
    assert "`" not in diagram.mermaid
    assert diagram.mermaid.count("\n  click ") == 2
    assert diagram.mermaid.count('href "https://github.com/') == 2


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://evil.test/a.py",
        f"https://github.com/evil/b/blob/{SHA}/src/a.py#L1-L1",
        "https://github.com/a/b/blob/HEAD/src/a.py#L1-L1",
    ],
)
def test_unpinned_or_external_source_url_is_rejected(url):
    graph = fixture_graph()
    graph.nodes[0].evidence.source_url = url
    with pytest.raises(ValueError):
        diagrams.build_diagram(graph, SHA)


def test_empty_view_and_dangling_edges():
    graph = fixture_graph()
    graph.nodes = []
    graph.edges = []
    diagram = diagrams.build_diagram(graph, SHA)
    assert "No supported source" in diagram.mermaid
    assert diagram.reading_order == []
    graph.edges = fixture_graph().edges
    with pytest.raises(ValueError):
        diagrams.build_diagram(graph, SHA)


def test_error_propagation_and_diagram_budget(monkeypatch):
    calls = []

    async def query(*args):
        calls.append(args)
        return Result(
            error={"code": "GRAPH_UNAVAILABLE", "message": "Install analysis extra"}
        )

    monkeypatch.setattr(diagrams.graph, "query_graph", query)
    assert (
        asyncio.run(diagrams.create_diagram("a", "b", max_nodes=31)).error.code
        == "INVALID_LIMIT"
    )
    assert calls == []
    assert (
        asyncio.run(diagrams.create_diagram("a", "b")).error.code == "GRAPH_UNAVAILABLE"
    )


def test_success_and_invalid_evidence_use_mcp_schema(monkeypatch):
    from github_mcp.models import ArchitectureDiagram
    from github_mcp.server import mcp

    view = fixture_graph()

    async def query(*args):
        return Result(data=view)

    monkeypatch.setattr(diagrams.graph, "query_graph", query)
    result = asyncio.run(
        mcp.call_tool("create_architecture_diagram", {"owner": "a", "repo": "b"})
    )
    assert result.isError is False
    parsed = Result[ArchitectureDiagram].model_validate(result.structuredContent)
    assert parsed.data.commit_sha == SHA
    view.edges[0].evidence.source_url = "https://evil.test/"
    assert (
        asyncio.run(diagrams.create_diagram("a", "b")).error.code
        == "DIAGRAM_INVALID_SOURCE"
    )


def test_source_node_budget_is_explicit():
    view = fixture_graph()
    view.nodes = [view.nodes[0].model_copy(update={"id": str(i)}) for i in range(31)]
    with pytest.raises(diagrams.DiagramLimit):
        diagrams.build_diagram(view, SHA)


def test_unicode_source_links_cannot_bypass_utf8_budget():
    from urllib.parse import quote

    view = fixture_graph()
    path = "层" * 80 + "/" + "次" * 80 + ".py"
    proof = Evidence(
        path=path,
        start_line=1,
        end_line=1,
        source_url=f"https://github.com/a/b/blob/{SHA}/{quote(path, safe='/')}#L1-L1",
    )
    view.nodes = [
        view.nodes[0].model_copy(
            update={"id": str(i), "label": str(i), "evidence": proof}
        )
        for i in range(30)
    ]
    view.edges = [
        view.edges[0].model_copy(
            update={"source": "0", "target": "1", "evidence": proof}
        )
        for _ in range(60)
    ]
    with pytest.raises(diagrams.DiagramLimit):
        diagrams.build_diagram(view, SHA)
