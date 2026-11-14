import asyncio

import pytest

from github_mcp import import_diagrams, imports
from github_mcp.models import Result

SHA = "a" * 40


def fixture_map():
    return imports.ImportMap(
        repository="a/b",
        commit_sha=SHA,
        parser="python-ast/3.12.13",
        focus_path="",
        module_prefix="pydantic",
        imports=[
            dict(
                module="pydantic",
                imported_name="BaseModel",
                alias="Model",
                bound_name="Model",
                level=0,
                resolution="module_unverified",
                blob_sha="b" * 40,
                evidence=dict(
                    path="src/models.py",
                    start_line=2,
                    end_line=4,
                    source_url=f"https://github.com/a/b/blob/{SHA}/src/models.py#L2-L4",
                ),
            )
        ],
        total_imports=3,
        omitted_imports=2,
        coverage=dict(
            files_acquired=5,
            files_parsed=3,
            unscanned_files=1,
            failed_files={"bad.py": "SYNTAX_ERROR"},
            omitted_files={"symlink": 1},
            filtered_imports=4,
        ),
        limitations=["No runtime or distribution resolution."],
        continuation=dict(
            owner="a",
            repo="b",
            ref=SHA,
            focus_path="",
            module_prefix="pydantic",
            max_items=1,
            start_index=1,
        ),
    )


def test_diagram_preserves_import_evidence_and_incomplete_coverage():
    view = fixture_map()
    diagram = import_diagrams.build_diagram(view, "main")
    assert 'subgraph F0["src/models.py"]' in diagram.mermaid
    assert 'M0["module pydantic (unverified)"]' in diagram.mermaid
    assert "BaseModel as Model" in diagram.mermaid
    assert "I0 -->" in diagram.mermaid
    assert view.imports[0].evidence.source_url in diagram.mermaid
    assert "shown 1 of 3" in diagram.text and "outside page 2" in diagram.text
    assert "failed 1" in diagram.text and "unscanned 1" in diagram.text
    assert "omitted files 1" in diagram.text
    assert SHA in diagram.text and "python-ast/3.12.13" in diagram.text
    assert "runtime" in diagram.text and "unverified" in diagram.text
    assert diagram.imports == view.imports and diagram.continuation == view.continuation
    assert diagram.coverage.complete is False
    assert "extractor" not in diagram.model_dump()


def test_multiple_imports_share_module_but_keep_individual_source_links():
    view = fixture_map()
    view.imports.append(
        view.imports[0].model_copy(update={"alias": "Other"}, deep=True)
    )
    view.omitted_imports = 1
    diagram = import_diagrams.build_diagram(view, SHA)
    assert diagram.mermaid.count('M0["') == 1
    assert diagram.mermaid.count("\n  click ") == 2
    assert "I1 -->" in diagram.mermaid
    second = view.imports[1].evidence
    second.path = "other.py"
    second.source_url = f"https://github.com/a/b/blob/{SHA}/other.py#L2-L4"
    assert 'subgraph F0["other.py"]' in import_diagrams.build_diagram(view, SHA).mermaid
    assert (
        'subgraph F1["src/models.py"]'
        in import_diagrams.build_diagram(view, SHA).mermaid
    )


@pytest.mark.parametrize("field", ["commit", "url", "span", "blob", "scope"])
def test_invalid_provenance_is_rejected(field):
    view = fixture_map()
    if field == "commit":
        view.commit_sha = "HEAD"
    elif field == "url":
        view.imports[0].evidence.source_url = "https://evil.test/"
    elif field == "span":
        view.imports[0].evidence.end_line = 1
    elif field == "blob":
        view.imports[0].blob_sha = "invalid"
    else:
        view.imports[0].module = "pydantic_fake"
    with pytest.raises(ValueError):
        import_diagrams.build_diagram(view, SHA)


def test_untrusted_labels_empty_page_and_render_budget():
    view = fixture_map()
    view.imports[0].alias = '"]\nclick I0 "javascript:alert(1)" <script> %%{init: x}'
    diagram = import_diagrams.build_diagram(view, '"\n%%{init: x}')
    assert "<script>" not in diagram.mermaid and "%%{" not in diagram.mermaid
    assert diagram.mermaid.count("\n  click ") == 1
    view.imports = []
    assert (
        "No matching imports on this page"
        in import_diagrams.build_diagram(view, SHA).mermaid
    )
    view.imports = fixture_map().imports * 31
    with pytest.raises(import_diagrams.DiagramLimit):
        import_diagrams.build_diagram(view, SHA)
    view.imports = []
    view.limitations = ["large" * 20_000]
    with pytest.raises(import_diagrams.DiagramLimit):
        import_diagrams.build_diagram(view, SHA)


@pytest.mark.parametrize(
    "failure,code", [("url", "DIAGRAM_INVALID_SOURCE"), ("budget", "DIAGRAM_LIMIT")]
)
def test_build_errors_are_sanitized(monkeypatch, failure, code):
    view = fixture_map()
    if failure == "url":
        view.imports[0].evidence.source_url = "private/local/path"
    else:
        view.limitations = ["large" * 20_000]

    async def query(*args):
        return Result(data=view)

    monkeypatch.setattr(imports, "query_imports", query)
    result = asyncio.run(import_diagrams.create_diagram("a", "b", "pydantic"))
    assert (
        result.error.code == code
        and "private/local/path" not in result.model_dump_json()
    )


def test_tool_validation_errors_pagination_and_mcp_schema(monkeypatch):
    from github_mcp.server import mcp

    calls = []

    async def query(*args):
        calls.append(args)
        return Result(data=fixture_map())

    monkeypatch.setattr(imports, "query_imports", query)
    for kwargs in [dict(module_prefix=""), dict(max_items=31), dict(max_items=True)]:
        args = dict(owner="a", repo="b", module_prefix="pydantic") | kwargs
        assert asyncio.run(import_diagrams.create_diagram(**args)).error
    assert not calls
    rpc = asyncio.run(
        mcp.call_tool(
            "create_python_import_diagram",
            dict(
                owner="a",
                repo="b",
                module_prefix="pydantic",
                max_items=1,
            ),
        )
    )
    assert not rpc.isError and rpc.structuredContent["data"]["mermaid"]
    follow = rpc.structuredContent["data"]["continuation"]
    assert not asyncio.run(import_diagrams.create_diagram(**follow)).error
    assert calls[-1] == ("a", "b", SHA, "", "pydantic", 1, 1)

    async def error(*args):
        return Result(error=dict(code="IMPORT_BUSY", message="Busy"))

    monkeypatch.setattr(imports, "query_imports", error)
    assert (
        asyncio.run(import_diagrams.create_diagram("a", "b", "pydantic")).error.code
        == "IMPORT_BUSY"
    )
