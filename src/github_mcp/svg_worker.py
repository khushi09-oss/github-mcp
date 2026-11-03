"""One-shot native renderer; no browser, network, caller paths or source execution."""

import contextlib
import importlib.metadata
import os
import re
import sys
from importlib import import_module
from pathlib import Path

from github_mcp.diagrams import build_diagram
from github_mcp.graph import MAX_OUTPUT
from github_mcp.graph_worker import offline
from github_mcp.models import ArchitectureDiagram, GraphView, Result, ToolError
from github_mcp.svg import decorate, validate_svg
from github_mcp.worker_limits import limit_memory


def render_artifact(diagram: ArchitectureDiagram) -> str:
    # Rebuild trusted grammar instead of accepting arbitrary Mermaid from input.
    diagram = build_diagram(
        GraphView.model_validate(diagram.model_dump()), diagram.requested_ref
    )
    engine = import_module("mmdr")
    source = re.sub(r'\|"([^"\n]*)"\|', r"|\1|", diagram.mermaid)
    raw = engine.render(
        source,
        backend="mermaid-rs-renderer",
        theme="modern",
        node_spacing=56,
        rank_spacing=72,
    ).svg()
    links = {n.evidence.source_url for n in diagram.nodes}
    root = validate_svg(raw, links)
    output = decorate(root, diagram)
    validate_svg(output, links)
    return output


def execute(directory: Path) -> Result[str]:
    try:
        limit_memory()
        for name, version in [
            ("mmdr", "0.4.0"),
            ("defusedxml", "0.7.1"),
            ("novasvg", "0.11.4"),
        ]:
            if importlib.metadata.version(name) != version:
                return Result(
                    error=ToolError(
                        code="SVG_VERSION", message="Synchronize the locked svg extra."
                    )
                )
        with (directory / "input.json").open("rb") as stream:
            payload = stream.read(MAX_OUTPUT + 1)
        if len(payload) > MAX_OUTPUT:
            raise ValueError("SVG input too large")
        diagram = ArchitectureDiagram.model_validate_json(payload)
        sys.addaudithook(offline)
        return Result(data=render_artifact(diagram))
    except importlib.metadata.PackageNotFoundError:
        return Result(
            error=ToolError(
                code="SVG_UNAVAILABLE",
                message="Install SVG support: uv sync --locked --extra svg.",
            )
        )
    except MemoryError:
        return Result(
            error=ToolError(
                code="SVG_RESOURCE_LIMIT",
                message="SVG rendering exceeded its memory budget.",
            )
        )
    except Exception:
        return Result(
            error=ToolError(
                code="SVG_UNSAFE",
                message="SVG rendering or validation failed; source alternatives remain available.",
            )
        )


def main():
    directory = Path(sys.argv[1]).resolve()
    with (
        open(os.devnull, "w") as silent,
        contextlib.redirect_stdout(silent),
        contextlib.redirect_stderr(silent),
    ):
        result = execute(directory)
        payload = result.model_dump_json().encode()
        if len(payload) > MAX_OUTPUT:
            payload = (
                Result(
                    error=ToolError(
                        code="SVG_OUTPUT_LIMIT",
                        message="SVG result exceeds its output budget.",
                    )
                )
                .model_dump_json()
                .encode()
            )
        with (directory / "result.json").open("xb") as stream:
            stream.write(payload)


if __name__ == "__main__":
    main()
