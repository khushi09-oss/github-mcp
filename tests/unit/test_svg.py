import asyncio
import importlib.util

import pytest

from github_mcp import svg
from github_mcp.diagrams import build_diagram
from github_mcp.models import GraphCoverage, GraphView

NS = 'xmlns="http://www.w3.org/2000/svg"'


def artifact():
    return build_diagram(
        GraphView(
            repository="a/b",
            commit_sha="a" * 40,
            focus_path="",
            nodes=[],
            edges=[],
            coverage=GraphCoverage(
                files_acquired=0,
                files_failed=0,
                omitted_files={},
                omitted_nodes=0,
                omitted_edges=0,
                limitations=["Incomplete"],
            ),
        ),
        "main",
    )


@pytest.mark.parametrize(
    "payload",
    [
        f'<svg {NS} viewBox="0 0 100 100"><script>alert(1)</script></svg>',
        f'<svg {NS} viewBox="0 0 100 100" onload="alert(1)"/>',
        f'<svg {NS} viewBox="0 0 100 100"><foreignObject/></svg>',
        f'<svg {NS} viewBox="0 0 100 100"><image href="https://evil.test/x"/></svg>',
        f'<svg {NS} viewBox="0 0 100 100"><use href="#a"/></svg>',
        f'<svg {NS} viewBox="0 0 100 100"><style>@import url(https://evil.test);</style></svg>',
        f'<svg {NS} viewBox="0 0 100 100"><path style="fill:url(https://evil.test)"/></svg>',
        f'<svg {NS} viewBox="0 0 100 100"><a href="javascript:alert(1)"/></svg>',
        f'<svg {NS} viewBox="0 0 100 100" xml:base="https://evil.test"/>',
        f'<svg {NS} viewBox="0 0 100000 100000"/>',
        f'<!DOCTYPE svg [<!ENTITY x "danger">]><svg {NS} viewBox="0 0 100 100">&x;</svg>',
        f'<svg {NS} viewBox="0 0 100 100"><text font-size="99999">huge</text></svg>',
        f'<svg {NS} viewBox="0 0 100 100"><g transform="scale(10000)"><text>huge</text></g></svg>',
        f'<svg {NS} viewBox="0 0 100 100" width="99999" height="99999"/>',
        f'<svg {NS} viewBox="0 0 100 100"><path marker-end="url(#missing)"/></svg>',
        f'<svg {NS} viewBox="0 0 100 100"><metadata><g/></metadata></svg>',
    ],
)
def test_active_or_unbounded_svg_is_rejected(payload):
    if importlib.util.find_spec("defusedxml") is None:
        with pytest.raises(ImportError):
            svg.validate_svg(payload, set())
        return
    with pytest.raises(ValueError):
        svg.validate_svg(payload, set())


def test_static_geometry_and_exact_links_are_supported():
    if importlib.util.find_spec("defusedxml") is None:
        return  # Missing-extra behavior is exercised by the worker integration test.
    link = "https://github.com/a/b/blob/" + "a" * 40 + "/a.py#L1-L1"
    source = f'<svg {NS} viewBox="0 0 100 100"><a href="{link}"><rect width="10" height="10" fill="#fff"/></a></svg>'
    root = svg.validate_svg(source, {link})
    assert list(root)[0].attrib["rel"] == "noopener noreferrer"
    with pytest.raises(ValueError):
        svg.validate_svg(source, set())


def test_limits_and_fallback_preserve_original_artifact(monkeypatch):
    # This only tests orchestration; SVG libraries remain optional.
    async def run(*args, **kwargs):
        assert kwargs["github_token"] is False
        assert kwargs["timeout"] == svg.SVG_TIMEOUT
        raise TimeoutError

    monkeypatch.setattr(svg.graph, "_run_job", run)
    result = asyncio.run(svg.render_svg(artifact()))
    assert result.error.code == "SVG_TIMEOUT"


def test_svg_failure_returns_source_artifact_not_false_svg_success(monkeypatch):
    from github_mcp import diagrams
    from github_mcp.models import Result

    view = GraphView.model_validate(artifact().model_dump())

    async def query(*args):
        return Result(data=view)

    async def render(*args):
        return Result(error={"code": "SVG_UNAVAILABLE", "message": "Install SVG extra"})

    monkeypatch.setattr(diagrams.graph, "query_graph", query)
    monkeypatch.setattr(svg, "render_svg", render)
    response = asyncio.run(diagrams.create_diagram("a", "b", include_svg=True))
    assert response.error is None
    assert response.data.svg is None and response.data.svg_status == "unavailable"
    assert response.data.svg_error.code == "SVG_UNAVAILABLE"
    assert response.data.mermaid and response.data.text
    from github_mcp.server import mcp

    rpc = asyncio.run(
        mcp.call_tool(
            "create_architecture_diagram",
            {"owner": "a", "repo": "b", "include_svg": True},
        )
    )
    assert not rpc.isError
    assert rpc.structuredContent["data"]["svg_status"] == "unavailable"


def test_inconsistent_svg_status_is_rejected():
    from github_mcp.models import ArchitectureDiagram

    with pytest.raises(ValueError):
        ArchitectureDiagram.model_validate(
            artifact().model_dump() | {"svg_status": "ready"}
        )


def test_output_budget_is_checked_before_xml_parsing():
    if importlib.util.find_spec("defusedxml") is not None:
        with pytest.raises(ValueError):
            svg.validate_svg("x" * (svg.MAX_SVG + 1), set())


def test_worker_rebuilds_source_instead_of_trusting_mermaid(monkeypatch):
    from types import SimpleNamespace

    from github_mcp import svg_worker

    if importlib.util.find_spec("defusedxml") is None:
        return
    requested = []

    def render(source, **kwargs):
        requested.append(source)
        return SimpleNamespace(svg=lambda: f'<svg {NS} viewBox="0 0 100 100"/>')

    monkeypatch.setattr(
        svg_worker, "import_module", lambda _: SimpleNamespace(render=render)
    )
    diagram = artifact().model_copy(update={"mermaid": "inject_native_script"})
    result = svg_worker.render_artifact(diagram)
    assert "inject_native_script" not in requested[0]
    assert "a" * 40 in result


def test_expected_link_set_cannot_authorize_active_protocols():
    if importlib.util.find_spec("defusedxml") is not None:
        with pytest.raises(ValueError):
            svg.validate_svg(
                f'<svg {NS} viewBox="0 0 100 100"><a href="javascript:alert(1)"/></svg>',
                {"javascript:alert(1)"},
            )


def test_parent_rejects_unsafe_worker_output_and_removes_workspace(
    monkeypatch, tmp_path
):
    from github_mcp.models import Result

    monkeypatch.setattr(svg.tempfile, "tempdir", str(tmp_path))

    async def run(directory, **kwargs):
        (directory / "result.json").write_text(
            Result(
                data=f'<svg {NS} viewBox="0 0 100 100"><script/></svg>'
            ).model_dump_json()
        )
        return 0

    monkeypatch.setattr(svg.graph, "_run_job", run)
    assert asyncio.run(svg.render_svg(artifact())).error.code == "SVG_UNSAFE"
    assert list(tmp_path.iterdir()) == []


def test_parent_never_returns_parser_ignored_stylesheet_instructions(monkeypatch):
    from github_mcp.models import Result

    async def run(directory, **kwargs):
        source = f'<?xml-stylesheet href="https://evil.test/style.css"?><svg {NS} viewBox="0 0 100 100"/>'
        (directory / "result.json").write_text(Result(data=source).model_dump_json())
        return 0

    monkeypatch.setattr(svg.graph, "_run_job", run)
    result = asyncio.run(svg.render_svg(artifact()))
    assert result.error is None
    assert "xml-stylesheet" not in result.data and "evil.test" not in result.data


def test_canonical_serialization_cannot_expand_past_byte_budget(monkeypatch):
    from github_mcp.models import Result

    async def run(directory, **kwargs):
        start = f'<svg {NS} viewBox="0 0 100 100">'
        source = start + "<g/>" * 1000
        source += "x" * (svg.MAX_SVG - len(source) - len("</svg>")) + "</svg>"
        (directory / "result.json").write_text(Result(data=source).model_dump_json())
        return 0

    monkeypatch.setattr(svg.graph, "_run_job", run)
    assert asyncio.run(svg.render_svg(artifact())).error.code == "SVG_UNSAFE"
