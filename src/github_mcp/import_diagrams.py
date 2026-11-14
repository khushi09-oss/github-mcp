"""Bounded, source-backed Python import views; no package or runtime resolution."""

from typing import Literal
from urllib.parse import quote

from pydantic import Field

from github_mcp import imports
from github_mcp.acquisition import _safe_path
from github_mcp.diagrams import DiagramLimit, _label
from github_mcp.models import Result, ToolError
from github_mcp.snapshots import SHA, _validate

LEGEND = [
    "Solid arrow: observed import syntax from a file to a named module, not runtime usage.",
    "Module nodes are unverified names, not resolved packages or local files.",
    "Statement links open pinned source; aliases are syntactic bindings only.",
]


class ImportDiagram(imports.ImportMap):
    format: Literal["mermaid"] = "mermaid"
    requested_ref: str
    mermaid: str = Field(max_length=100_000)
    text: str = Field(max_length=100_000)
    legend: list[str]


def build_diagram(view: imports.ImportMap, requested_ref: str) -> ImportDiagram:
    parts = view.repository.split("/")
    if (
        len(parts) != 2
        or _validate(parts[0], parts[1], view.commit_sha)
        or not SHA.fullmatch(view.commit_sha)
        or not view.module_prefix
    ):
        raise ValueError("Invalid repository, commit or module scope")
    if len(view.imports) > 30:
        raise DiagramLimit("Import view exceeds diagram limits")
    for record in view.imports:
        evidence = record.evidence
        expected = f"https://github.com/{view.repository}/blob/{view.commit_sha}/{quote(evidence.path, safe='/')}#L{evidence.start_line}-L{evidence.end_line}"
        if (
            not _safe_path(evidence.path)
            or evidence.start_line > evidence.end_line
            or evidence.source_url != expected
            or not SHA.fullmatch(record.blob_sha)
            or record.level != 0
            or record.module is None
            or not (
                record.module == view.module_prefix
                or record.module.startswith(view.module_prefix + ".")
            )
        ):
            raise ValueError("Invalid import provenance or scope")
    coverage = (
        f"Incomplete import view - shown {len(view.imports)} of {view.total_imports} - "
        f"outside page {view.omitted_imports} - acquired {view.coverage.files_acquired} - "
        f"parsed {view.coverage.files_parsed} - failed {len(view.coverage.failed_files)} - "
        f"unscanned {view.coverage.unscanned_files} - filtered {view.coverage.filtered_imports} - "
        f"omitted files {sum(view.coverage.omitted_files.values())}"
    )
    summary = f"{view.repository} - module {_label(view.module_prefix, 200)} - commit {view.commit_sha} - ref {_label(requested_ref)}"
    source = [
        "---",
        f'title: "{_label(view.repository)} - {_label(view.module_prefix, 200)} imports - {view.commit_sha[:12]}"',
        "---",
        "flowchart LR",
        f"  accTitle: {_label(view.repository)} Python import diagram",
        f"  accDescr: {_label(summary + ' - ' + coverage, 2000)}",
    ]
    text = [
        summary,
        f"Parser: {_label(view.parser)}; focus: {_label(view.focus_path or 'acquired Python files', 200)}",
        coverage,
        "Static import syntax, not runtime/deployment architecture or upgrade-safety evidence.",
    ]
    modules = sorted({record.module for record in view.imports if record.module})
    ids = {module: f"M{i}" for i, module in enumerate(modules)}
    for module, identity in ids.items():
        source.append(f'  {identity}["module {_label(module, 200)} (unverified)"]')
    for i, path in enumerate(sorted({r.evidence.path for r in view.imports})):
        source.append(f'  subgraph F{i}["{_label(path, 200)}"]')
        for j, record in enumerate(view.imports):
            if record.evidence.path == path:
                label = "import " + (record.imported_name or record.module or "unknown")
                if record.alias:
                    label += " as " + record.alias
                source.append(f'    I{j}["{_label(label)}"]')
        source.append("  end")
    for j, record in enumerate(view.imports):
        assert record.module is not None
        status = (
            "star exports unresolved"
            if record.imported_name == "*"
            else "observed import"
        )
        source.extend(
            [
                f'  I{j} -->|"{status}"| {ids[record.module]}',
                f'  click I{j} href "{record.evidence.source_url}" "Open pinned import" _blank',
            ]
        )
        text.append(
            f"I{j} {_label(record.evidence.path, 200)}:{record.evidence.start_line}-{record.evidence.end_line} -> "
            f"{ids[record.module]} {_label(record.module, 200)}; member {_label(record.imported_name or '(module)')}; "
            f"alias {_label(record.alias or '(none)')}; binding {_label(record.bound_name or '(none)')}; "
            f"{record.resolution}; blob {record.blob_sha}; {record.evidence.source_url}"
        )
    if not view.imports:
        source.append(
            '  EMPTY["No matching imports on this page - coverage is incomplete"]'
        )
    source.append(
        f'  LEGEND["Incomplete: shown {len(view.imports)} of {view.total_imports}; outside page {view.omitted_imports}. '
        'Module names unverified. Not runtime usage."]'
    )
    text.extend(["Legend:", *LEGEND, *view.limitations])
    mermaid, alternative = "\n".join(source), "\n".join(text)
    if len(mermaid.encode()) + len(alternative.encode()) > 100_000:
        raise DiagramLimit("Import diagram exceeds its text budget")
    return ImportDiagram(
        **view.model_dump(),
        requested_ref=requested_ref,
        mermaid=mermaid,
        text=alternative,
        legend=LEGEND,
    )


async def create_diagram(
    owner: str,
    repo: str,
    module_prefix: str,
    ref: str = "HEAD",
    focus_path: str = "",
    max_items: int = 30,
    start_index: int = 0,
) -> Result[ImportDiagram]:
    if not module_prefix:
        return Result(
            error=ToolError(
                code="INVALID_MODULE",
                message="A nonempty absolute module prefix is required.",
            )
        )
    if type(max_items) is not int or not 1 <= max_items <= 30:
        return Result(
            error=ToolError(
                code="INVALID_LIMIT", message="Import diagram max_items must be 1..30."
            )
        )
    result = await imports.query_imports(
        owner, repo, ref, focus_path, module_prefix, max_items, start_index
    )
    if result.error:
        return Result(error=result.error)
    assert result.data is not None
    try:
        return Result(data=build_diagram(result.data, ref))
    except DiagramLimit:
        return Result(
            error=ToolError(
                code="DIAGRAM_LIMIT", message="Reduce max_items or narrow focus_path."
            )
        )
    except ValueError:
        return Result(
            error=ToolError(
                code="DIAGRAM_INVALID_SOURCE",
                message="Import diagram evidence could not be verified.",
            )
        )
