"""Fail-closed static SVG validation and optional isolated rendering."""

import json
import math
import re
import tempfile
import textwrap
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

from github_mcp import graph
from github_mcp.models import ArchitectureDiagram, Result, ToolError

NS = "http://www.w3.org/2000/svg"
XLINK = "{http://www.w3.org/1999/xlink}href"
MAX_SVG = 500_000
SVG_TIMEOUT = 20
RENDERER = "mmdr==0.4.0/mermaid-rs-renderer"
TAGS = {
    "svg",
    "g",
    "defs",
    "marker",
    "path",
    "rect",
    "polygon",
    "text",
    "tspan",
    "a",
    "title",
    "desc",
    "metadata",
}
NUMERIC = {
    "x",
    "y",
    "dx",
    "dy",
    "width",
    "height",
    "rx",
    "ry",
    "refX",
    "refY",
    "markerWidth",
    "markerHeight",
    "font-size",
    "stroke-width",
    "stroke-opacity",
    "fill-opacity",
    "opacity",
}
GEOMETRY = {"d", "points", "viewBox", "stroke-dasharray", "transform"}
WORDS = {
    "markerUnits": {"userSpaceOnUse", "strokeWidth"},
    "orient": {"auto", "auto-start-reverse"},
    "text-anchor": {"start", "middle", "end"},
    "stroke-linecap": {"round", "butt", "square"},
    "stroke-linejoin": {"round", "bevel", "miter"},
    "font-weight": {"normal", "bold", "400", "500", "600", "700"},
    "role": {"img"},
}
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,127}")
SOURCE_URL = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/blob/[a-f0-9]{40}/[^?#\s]+#L[1-9][0-9]*-L[1-9][0-9]*"
)


def _numbers(value: str) -> list[float]:
    values = [float(v) for v in re.findall(NUMBER, value)]
    if not values or any(not math.isfinite(n) or abs(n) > 100_000 for n in values):
        raise ValueError("Invalid SVG geometry")
    return values


def validate_svg(source: str, links: set[str]) -> ET.Element:
    parse = import_module("defusedxml.ElementTree").fromstring
    if len(source.encode()) > MAX_SVG:
        raise ValueError("SVG output budget exceeded")
    try:
        root = parse(
            source, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except Exception:
        raise ValueError("Unsafe XML") from None
    if root.tag != f"{{{NS}}}svg":
        raise ValueError("Not SVG")
    ids, refs, found = set(), set(), set()
    count = 0
    stack = [(root, 0, False)]
    while stack:
        element, depth, in_defs = stack.pop()
        count += 1
        if (
            count > 10_000
            or depth > 32
            or not isinstance(element.tag, str)
            or not element.tag.startswith(f"{{{NS}}}")
        ):
            raise ValueError("SVG structure budget or namespace violation")
        tag = element.tag.split("}", 1)[1]
        if tag not in TAGS or (tag == "svg" and element is not root):
            raise ValueError("Unsupported SVG element")
        if tag == "metadata" and len(element):
            raise ValueError("SVG metadata must be text only")
        if (
            element.get("href")
            and element.get(XLINK)
            and element.get("href") != element.get(XLINK)
        ):
            raise ValueError("Conflicting SVG links")
        for key, value in list(element.attrib.items()):
            if key.startswith("data-") or key == "class":
                del element.attrib[key]
                continue
            if len(value) > 50_000:
                raise ValueError("SVG attribute budget exceeded")
            if key in {"href", XLINK}:
                if tag != "a" or value not in links or not SOURCE_URL.fullmatch(value):
                    raise ValueError("Unverified SVG link")
                found.add(value)
                del element.attrib[key]
                element.set("href", value)
                element.set("target", "_blank")
                element.set("rel", "noopener noreferrer")
            elif key == "id":
                if not TOKEN.fullmatch(value) or value in ids:
                    raise ValueError("Invalid SVG identity")
                ids.add(value)
            elif key in {"target", "rel"}:
                if tag != "a" or value not in {"_blank", "noopener noreferrer"}:
                    raise ValueError("Unsafe link behavior")
            elif key in NUMERIC:
                if not re.fullmatch(NUMBER, value):
                    raise ValueError("Invalid numeric attribute")
                number = _numbers(value)[0]
                if (
                    (key == "font-size" and not 0 < number <= 200)
                    or (key.endswith("opacity") and not 0 <= number <= 1)
                    or (
                        key in {"stroke-width", "markerWidth", "markerHeight"}
                        and not 0 <= number <= 100
                    )
                ):
                    raise ValueError("SVG drawing budget exceeded")
            elif key in GEOMETRY:
                alphabet = (
                    r"[MmZzLlHhVvCcSsQqTtAa0-9eE.,+\-\s]+"
                    if key == "d"
                    else r"[0-9eE.,+\-\s]+"
                )
                if key == "transform":
                    alphabet = r"(?:(?:translate|rotate)\([0-9eE.,+\-\s]+\)\s*)+"
                if not re.fullmatch(alphabet, value):
                    raise ValueError("Unsupported geometry")
                _numbers(value)
            elif key in {"fill", "stroke"}:
                if value not in {
                    "none",
                    "transparent",
                    "currentColor",
                } and not re.fullmatch(r"#[0-9A-Fa-f]{3,8}", value):
                    raise ValueError("Unsupported paint")
            elif key in {"marker-start", "marker-end"}:
                match = re.fullmatch(r"url\(#([A-Za-z_][A-Za-z0-9_.:-]*)\)", value)
                if not match or in_defs:
                    raise ValueError("Unsafe marker reference")
                refs.add(match[1])
            elif key == "font-family":
                if not re.fullmatch(r"[A-Za-z0-9 ,_-]+", value):
                    raise ValueError("Unsupported font family")
            elif key == "aria-labelledby":
                tokens = value.split()
                if not tokens or not all(TOKEN.fullmatch(v) for v in tokens):
                    raise ValueError("Invalid accessibility reference")
                refs.update(tokens)
            elif key not in WORDS or value not in WORDS[key]:
                raise ValueError("Unsupported SVG attribute")
        stack.extend(
            (child, depth + 1, in_defs or tag in {"defs", "marker"})
            for child in element
        )
    box = _numbers(root.get("viewBox", ""))
    if (
        len(box) != 4
        or not 0 < box[2] <= 20_000
        or not 0 < box[3] <= 20_000
        or box[2] * box[3] > 100_000_000
    ):
        raise ValueError("SVG viewport budget exceeded")
    dimensions = [
        _numbers(root.get(k, str(box[i + 2])))[0]
        for i, k in enumerate(("width", "height"))
    ]
    if (
        any(not 0 < n <= 20_000 for n in dimensions)
        or dimensions[0] * dimensions[1] > 100_000_000
    ):
        raise ValueError("SVG intrinsic size budget exceeded")
    if not refs <= ids or found != links:
        raise ValueError("Missing SVG links or references")
    return root


def decorate(root: ET.Element, diagram: ArchitectureDiagram) -> str:
    width, height = _numbers(root.attrib["viewBox"])[2:]
    lines = []
    for line in [
        f"{diagram.repository} - source {diagram.view} - {diagram.focus_path or 'overview'}",
        f"Commit: {diagram.commit_sha}",
        f"Ref: {diagram.requested_ref}",
        f"Incomplete static view. Omitted nodes {diagram.coverage.omitted_nodes}, edges {diagram.coverage.omitted_edges}.",
    ]:
        lines.extend(textwrap.wrap(" ".join(line.split()), width=64))
    top = 24 + 18 * len(lines)
    width = max(width, 900)
    height += top
    root.set("viewBox", f"0 0 {width:g} {height:g}")
    root.set("width", f"{width:g}")
    root.set("height", f"{height:g}")
    content = ET.Element(f"{{{NS}}}g", {"transform": f"translate(0 {top})"})
    for child in list(root):
        root.remove(child)
        content.append(child)
    root.append(content)
    header = ET.SubElement(root, f"{{{NS}}}g")
    ET.SubElement(
        header,
        f"{{{NS}}}rect",
        {"width": f"{width:g}", "height": str(top), "fill": "#F8FAFC"},
    )
    for i, line in enumerate(lines):
        ET.SubElement(
            header,
            f"{{{NS}}}text",
            {
                "x": "16",
                "y": str(22 + i * 18),
                "font-size": "12",
                "font-family": "system-ui, sans-serif",
                "fill": "#0F172A",
            },
        ).text = line
    ET.SubElement(
        root, f"{{{NS}}}title"
    ).text = f"{diagram.repository} source {diagram.view} at {diagram.commit_sha}"
    ET.SubElement(root, f"{{{NS}}}desc").text = (
        f"Schema {diagram.schema_version}; extractor {diagram.extractor}; renderer {RENDERER}.\n"
        + diagram.text
    )
    source = diagram.model_dump(
        exclude={"svg", "svg_status", "svg_error", "svg_renderer"}
    )
    ET.SubElement(root, f"{{{NS}}}metadata").text = json.dumps(
        {"source": source, "rendering": {"format": "svg", "renderer": RENDERER}},
        ensure_ascii=False,
    )
    root.set("role", "img")
    ET.register_namespace("", NS)
    return ET.tostring(root, encoding="unicode")


async def render_svg(diagram: ArchitectureDiagram) -> Result[str]:
    if not graph._SLOT.acquire(blocking=False):
        return Result(
            error=ToolError(
                code="SVG_BUSY", message="Another analysis/render job is running."
            )
        )
    try:
        with tempfile.TemporaryDirectory(prefix="github-mcp-svg-") as name:
            directory = Path(name).resolve()
            (directory / "input.json").write_text(
                diagram.model_dump_json(), encoding="utf-8"
            )
            if (
                await graph._run_job(
                    directory,
                    worker="github_mcp.svg_worker",
                    timeout=SVG_TIMEOUT,
                    github_token=False,
                )
                != 0
            ):
                raise ValueError("SVG worker failed")
            with (directory / "result.json").open("rb") as stream:
                payload = stream.read(graph.MAX_OUTPUT + 1)
            if len(payload) > graph.MAX_OUTPUT:
                raise ValueError("SVG result too large")
            result = Result[str].model_validate_json(payload)
            if result.data is not None:
                root = validate_svg(
                    result.data, {n.evidence.source_url for n in diagram.nodes}
                )
                # Return validated XML, never parser-ignored original bytes.
                ET.register_namespace("", NS)
                canonical = ET.tostring(root, encoding="utf-8")
                if len(canonical) > MAX_SVG:
                    raise ValueError("Canonical SVG exceeds its output budget")
                return Result(data=canonical.decode("utf-8"))
            return result
    except TimeoutError:
        return Result(
            error=ToolError(
                code="SVG_TIMEOUT",
                message=f"SVG rendering exceeded its {SVG_TIMEOUT}-second deadline.",
            )
        )
    except ImportError:
        return Result(
            error=ToolError(
                code="SVG_UNAVAILABLE", message="Install the locked svg extra."
            )
        )
    except Exception:
        return Result(
            error=ToolError(
                code="SVG_UNSAFE",
                message="SVG rendering or validation failed; use the source alternatives.",
            )
        )
    finally:
        graph._SLOT.release()
