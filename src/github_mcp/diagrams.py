"""Portable source views; no renderer, remote service, HTML or executable callbacks."""

from typing import Literal
from urllib.parse import quote

from github_mcp import graph
from github_mcp.acquisition import _safe_path
from github_mcp.models import (
    ArchitectureDiagram,
    Evidence,
    GraphView,
    Result,
    ToolError,
)
from github_mcp.snapshots import SHA, _validate

LEGEND = [
    "Solid arrow: observed source relationship (EXTRACTED), not runtime proof.",
    "Dotted arrow: inferred relationship (INFERRED).",
    "Dotted arrow labeled unknown: uncertain relationship (AMBIGUOUS).",
]
STATUS = {"EXTRACTED": "observed", "INFERRED": "inferred", "AMBIGUOUS": "unknown"}


class DiagramLimit(ValueError):
    pass


def _label(value: str, limit: int = 160) -> str:
    # A plain-text alphabet avoids both Mermaid grammar and HTML/entity injection.
    value = " ".join(
        "".join(c if c.isalnum() or c in " _./:()-" else " " for c in value).split()
    )
    return (value[: limit - 3] + "...") if len(value) > limit else value or "unnamed"


def _source(view: GraphView, evidence: Evidence) -> str:
    if not _safe_path(evidence.path) or evidence.start_line > evidence.end_line:
        raise ValueError("Invalid source location")
    expected = f"https://github.com/{view.repository}/blob/{view.commit_sha}/{quote(evidence.path, safe='/')}#L{evidence.start_line}-L{evidence.end_line}"
    if evidence.source_url != expected:
        raise ValueError("Source link is not pinned to this repository/commit")
    return expected


def build_diagram(view: GraphView, requested_ref: str) -> ArchitectureDiagram:
    parts = view.repository.split("/")
    if (
        len(parts) != 2
        or _validate(parts[0], parts[1], view.commit_sha)
        or not SHA.fullmatch(view.commit_sha)
    ):
        raise ValueError("Invalid repository/commit")
    if len(view.nodes) > 30 or len(view.edges) > 60:
        raise DiagramLimit("Source view exceeds diagram limits")
    nodes = sorted(
        view.nodes,
        key=lambda n: (n.evidence.path, n.evidence.start_line, n.label, n.id),
    )
    ids = {node.id: f"N{i}" for i, node in enumerate(nodes)}
    if len(ids) != len(nodes):
        raise ValueError("Duplicate graph identities")
    for node in nodes:
        _source(view, node.evidence)
    edges = sorted(
        view.edges,
        key=lambda e: (
            e.source,
            e.target,
            e.relation,
            e.confidence,
            e.evidence.path,
            e.evidence.start_line,
            e.evidence.end_line,
        ),
    )
    for edge in edges:
        if edge.source not in ids or edge.target not in ids:
            raise ValueError("Dangling graph edge")
        _source(view, edge.evidence)
    scope = view.focus_path or "acquired source overview"
    kind: Literal["overview", "focus"] = "focus" if view.focus_path else "overview"
    summary = f"{view.repository} - {kind} - ref {_label(requested_ref)} - commit {view.commit_sha} - scope {_label(scope)}"
    coverage = (
        f"Incomplete static view - files {view.coverage.files_acquired} - failed {view.coverage.files_failed} - "
        f"omitted nodes {view.coverage.omitted_nodes} - omitted edges {view.coverage.omitted_edges} - "
        f"omitted files {sum(view.coverage.omitted_files.values())}"
    )
    mermaid = [
        "---",
        f'title: "{_label(view.repository)} - source {kind} - {view.commit_sha[:12]}"',
        "---",
        "flowchart TB",
        f"  accTitle: {_label(view.repository)} source {kind}",
        f"  accDescr: {_label(summary + ' - ' + coverage, 2000)}",
    ]
    text = [
        summary,
        coverage,
        "Static source evidence, not runtime/deployment architecture.",
        "Nodes / reading order:",
    ]
    paths = sorted({n.evidence.path for n in nodes})
    for index, path in enumerate(paths):
        mermaid.append(f'  subgraph F{index}["{_label(path, 200)}"]')
        for node in nodes:
            if node.evidence.path == path:
                mermaid.append(f'    {ids[node.id]}["{_label(node.label)}"]')
        mermaid.append("  end")
    if not nodes:
        mermaid.append(
            '  EMPTY["No supported source relationships in this bounded view"]'
        )
        text.append("No supported source nodes in this bounded view.")
    for node in nodes:
        url = _source(view, node.evidence)
        mermaid.append(
            f'  click {ids[node.id]} href "{url}" "Open pinned source" _blank'
        )
        text.append(
            f"{ids[node.id]} {_label(node.label)} ({_label(node.evidence.path, 200)}:{node.evidence.start_line}-{node.evidence.end_line}) {url}"
        )
    text.append("Directed edges:")
    for edge in edges:
        arrow = "-->" if edge.confidence == "EXTRACTED" else "-.->"
        label = f"{_label(edge.relation, 80)} - {STATUS[edge.confidence]}"
        mermaid.append(f'  {ids[edge.source]} {arrow}|"{label}"| {ids[edge.target]}')
        text.append(
            f"{ids[edge.source]} -> {ids[edge.target]}: {_label(edge.relation, 80)} [{edge.confidence}] {_source(view, edge.evidence)}"
        )
    if not edges:
        text.append("No supported edges in this bounded view.")
    key = (
        "Solid: observed EXTRACTED. Dotted: inferred INFERRED or unknown AMBIGUOUS. "
        "Not runtime proof. " + coverage
    )
    mermaid.append(f'  LEGEND["{_label(key, 1000)}"]')
    text.extend(
        [
            "Legend:",
            *LEGEND,
            "Dynamic/external/config-dependent relationships may be absent. Missing edges cannot prove unused code.",
        ]
    )
    source, alternative = "\n".join(mermaid), "\n".join(text)
    if len(source.encode()) + len(alternative.encode()) > 100_000:
        raise DiagramLimit("Diagram text exceeds its byte budget")
    safe_nodes = [n.model_copy(update={"label": _label(n.label)}) for n in nodes]
    return ArchitectureDiagram(
        **(view.model_dump() | {"nodes": safe_nodes, "edges": edges}),
        requested_ref=requested_ref,
        view=kind,
        mermaid=source,
        text=alternative,
        reading_order=[n.id for n in nodes],
        legend=LEGEND,
    )


async def create_diagram(
    owner: str,
    repo: str,
    ref: str = "HEAD",
    focus_path: str = "",
    max_nodes: int = 30,
    max_edges: int = 60,
) -> Result[ArchitectureDiagram]:
    if (
        type(max_nodes) is not int
        or not 1 <= max_nodes <= 30
        or type(max_edges) is not int
        or not 1 <= max_edges <= 60
    ):
        return Result(
            error=ToolError(
                code="INVALID_LIMIT",
                message="Diagram limits: max_nodes 1..30, max_edges 1..60.",
            )
        )
    result = await graph.query_graph(owner, repo, ref, focus_path, max_nodes, max_edges)
    if result.error:
        return Result(error=result.error)
    assert result.data is not None
    try:
        return Result(data=build_diagram(result.data, ref))
    except DiagramLimit:
        return Result(
            error=ToolError(
                code="DIAGRAM_LIMIT",
                message="Diagram exceeds its budget; reduce node/edge limits.",
            )
        )
    except ValueError:
        return Result(
            error=ToolError(
                code="DIAGRAM_INVALID_SOURCE",
                message="Diagram evidence could not be verified.",
            )
        )
