"""Evidence normalization and a bounded, isolated analysis job."""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from github_mcp.acquisition import Snapshot, _safe_path
from github_mcp.models import (
    Evidence,
    GraphCoverage,
    GraphEdge,
    GraphNode,
    GraphView,
    Result,
    ToolError,
)
from github_mcp.snapshots import _validate

MAX_OUTPUT = 1_000_000
TIMEOUT = 45
_SLOT = threading.BoundedSemaphore(1)
LOCATION = re.compile(r"L([1-9][0-9]*)(?:-L?([1-9][0-9]*))?")
LIMITATIONS = [
    "Static source relationships, not proven runtime or deployment architecture.",
    "Dynamic calls, external dependencies, unsupported syntax and config-dependent resolution may be absent.",
    "A missing edge does not prove code is unused. Narrow focus_path for omitted nodes/edges.",
]


def error(code: str, message: str) -> Result[GraphView]:
    return Result(error=ToolError(code=code, message=message))


def normalize(
    raw: dict, snapshot: Snapshot, focus: str, max_nodes: int, max_edges: int
) -> GraphView:
    if (
        not isinstance(raw.get("nodes"), list)
        or not isinstance(raw.get("edges"), list)
        or len(raw["nodes"]) > 20_000
        or len(raw["edges"]) > 40_000
    ):
        raise ValueError("Graph record budget exceeded or invalid records")
    lines = {}
    for path in snapshot.files:
        text = (snapshot.root / path).read_bytes().decode("utf-8")
        lines[path] = text.count("\n") + int(bool(text) and not text.endswith("\n"))

    def evidence(record):
        path, location = record.get("source_file"), record.get("source_location")
        if (
            not isinstance(path, str)
            or path not in lines
            or not isinstance(location, str)
        ):
            return None
        match = LOCATION.fullmatch(location)
        if not match:
            return None
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end <= lines[path]:
            return None
        url = f"https://github.com/{snapshot.repository}/blob/{snapshot.commit_sha}/{quote(path, safe='/')}#L{start}-L{end}"
        return Evidence(path=path, start_line=start, end_line=end, source_url=url)

    ids = Counter(
        n.get("id")
        for n in raw["nodes"]
        if isinstance(n, dict) and isinstance(n.get("id"), str)
    )
    mapping = {}
    for record in raw["nodes"]:
        if not isinstance(record, dict):
            continue
        original, label = record.get("id"), record.get("label")
        if (
            not isinstance(original, str)
            or ids[original] != 1
            or not isinstance(label, str)
            or not label
        ):
            continue
        source = evidence(record)
        if source is None:
            continue
        # Identity uses validated source facts; upstream ids may contain local paths.
        identity = json.dumps(
            [source.path, source.start_line, source.end_line, label], ensure_ascii=True
        )
        mapping[original] = GraphNode(
            id=hashlib.sha256(identity.encode()).hexdigest()[:24],
            label=label[:200],
            evidence=source,
        )
    edges = []
    for record in raw["edges"]:
        if not isinstance(record, dict):
            continue
        source, target = record.get("source"), record.get("target")
        relation, confidence = record.get("relation"), record.get("confidence")
        if (
            not isinstance(source, str)
            or not isinstance(target, str)
            or source not in mapping
            or target not in mapping
            or not isinstance(relation, str)
            or not relation
            or len(relation) > 80
            or confidence not in ("EXTRACTED", "INFERRED", "AMBIGUOUS")
        ):
            continue
        proof = evidence(record)
        if proof is not None:
            edges.append(
                GraphEdge(
                    source=mapping[source].id,
                    target=mapping[target].id,
                    relation=relation,
                    confidence=confidence,
                    evidence=proof,
                )
            )
    nodes = {n.id: n for n in mapping.values()}
    candidates = set(nodes)
    if focus:
        candidates = {n.id for n in nodes.values() if n.evidence.path == focus}
        neighbors = {
            endpoint
            for e in edges
            if e.source in candidates or e.target in candidates
            for endpoint in (e.source, e.target)
        }
        candidates |= neighbors
    selected = sorted(
        (nodes[k] for k in candidates),
        key=lambda n: (
            bool(focus) and n.evidence.path != focus,
            not focus and n.label != PurePosixPath(n.evidence.path).name,
            n.evidence.path,
            n.evidence.start_line,
            n.label,
            n.id,
        ),
    )[:max_nodes]
    selected_ids = {n.id for n in selected}
    selected_edges = sorted(
        (e for e in edges if e.source in selected_ids and e.target in selected_ids),
        key=lambda e: (
            e.source,
            e.target,
            e.relation,
            e.confidence,
            e.evidence.path,
            e.evidence.start_line,
            e.evidence.end_line,
        ),
    )[:max_edges]
    failed = sum(
        len(raw.get(k, []))
        for k in ("failed_sources", "skipped_sources")
        if isinstance(raw.get(k, []), list)
    )
    return GraphView(
        repository=snapshot.repository,
        commit_sha=snapshot.commit_sha,
        focus_path=focus,
        nodes=selected,
        edges=selected_edges,
        coverage=GraphCoverage(
            files_acquired=len(snapshot.files),
            files_failed=failed,
            omitted_files=snapshot.omitted,
            omitted_nodes=len(raw["nodes"]) - len(selected),
            omitted_edges=len(raw["edges"]) - len(selected_edges),
            limitations=LIMITATIONS,
        ),
    )


async def _run_job(directory: Path) -> int:
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "LOCALAPPDATA",
            "GITHUB_TOKEN",
            "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
        }
    }
    env.update(
        OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", GRAPHIFY_OUT="graphify-out"
    )
    launch = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "github_mcp.graph_worker",
            str(directory),
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    )
    process = None
    try:
        process = await asyncio.shield(launch)
        return await asyncio.wait_for(process.wait(), timeout=TIMEOUT)
    finally:
        # Await spawning even on cancellation so no orphan survives cleanup.
        if process is None:
            process = await launch
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


async def query_graph(
    owner: str,
    repo: str,
    ref: str = "HEAD",
    focus_path: str = "",
    max_nodes: int = 30,
    max_edges: int = 60,
) -> Result[GraphView]:
    invalid = _validate(owner, repo, ref)
    if invalid:
        return Result(error=invalid.error)
    if (focus_path and not _safe_path(focus_path)) or len(focus_path) > 180:
        return error(
            "INVALID_PATH", "focus_path must be a portable relative source path."
        )
    if (
        type(max_nodes) is not int
        or not 1 <= max_nodes <= 50
        or type(max_edges) is not int
        or not 1 <= max_edges <= 100
    ):
        return error(
            "INVALID_LIMIT", "max_nodes must be 1..50; max_edges must be 1..100."
        )
    if not _SLOT.acquire(blocking=False):
        return error(
            "GRAPH_BUSY", "Another analysis is running; retry after it finishes."
        )
    try:
        with tempfile.TemporaryDirectory(prefix="github-mcp-job-") as name:
            directory = Path(name).resolve()
            (directory / "input.json").write_text(
                json.dumps(
                    dict(
                        owner=owner,
                        repo=repo,
                        ref=ref,
                        focus_path=focus_path,
                        max_nodes=max_nodes,
                        max_edges=max_edges,
                    )
                ),
                encoding="utf-8",
            )
            if await _run_job(directory) != 0:
                return error(
                    "GRAPH_WORKER_FAILED",
                    "Analysis worker failed or exceeded its memory budget.",
                )
            with (directory / "result.json").open("rb") as stream:
                payload = stream.read(MAX_OUTPUT + 1)
            if len(payload) > MAX_OUTPUT:
                return error(
                    "GRAPH_OUTPUT_LIMIT", "Analysis result exceeds its output budget."
                )
            return Result[GraphView].model_validate_json(payload)
    except TimeoutError:
        return error("GRAPH_TIMEOUT", "Analysis exceeded its 45-second deadline.")
    except (OSError, ValueError):
        return error(
            "GRAPH_WORKER_FAILED", "Analysis could not produce a valid result."
        )
    finally:
        _SLOT.release()
