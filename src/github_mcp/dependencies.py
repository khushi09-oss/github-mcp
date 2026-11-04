"""Bounded, commit-pinned declaration inventory; no dependency resolution or execution."""

import tomllib
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field

from github_mcp import snapshots
from github_mcp.acquisition import _safe_path
from github_mcp.models import Evidence, Result, ToolError


class DeclaredDependency(BaseModel):
    requirement: str
    group: str | None = None


class InventoryContinuation(BaseModel):
    owner: str
    repo: str
    ref: str
    manifest_path: str
    max_items: int
    start_index: int


class DependencyInventory(BaseModel):
    schema_version: Literal["1"] = "1"
    repository: str
    commit_sha: str
    blob_sha: str
    manifest: Evidence
    dependencies: list[DeclaredDependency] = Field(max_length=100)
    total_declared: int
    omitted_items: int
    dynamic_dependencies: list[str]
    limitations: list[str]
    continuation: InventoryContinuation | None = None


def _error(code: str, message: str) -> Result[DependencyInventory]:
    return Result(error=ToolError(code=code, message=message))


def inspect_dependencies(
    owner: str,
    repo: str,
    ref: str = "HEAD",
    manifest_path: str = "pyproject.toml",
    max_items: int = 50,
    start_index: int = 0,
) -> Result[DependencyInventory]:
    if invalid := snapshots._validate(owner, repo, ref):
        return Result(error=invalid.error)
    if (
        not _safe_path(manifest_path)
        or PurePosixPath(manifest_path).name != "pyproject.toml"
    ):
        return _error("INVALID_PATH", "Choose a portable relative pyproject.toml path.")
    if (
        type(max_items) is not int
        or not 1 <= max_items <= 100
        or type(start_index) is not int
        or not 0 <= start_index <= 10_000
    ):
        return _error(
            "INVALID_LIMIT", "max_items must be 1..100; start_index must be 0..10000."
        )
    result = snapshots.read_file_lines(owner, repo, manifest_path, ref, line_count=200)
    if result.error:
        return Result(error=result.error)
    assert result.data is not None
    source = result.data
    if source.continuation is not None:
        return _error(
            "MANIFEST_LIMIT",
            "Manifest exceeds 200 lines or 12000 characters; partial TOML is not parsed.",
        )
    try:
        project = tomllib.loads(source.text).get("project")
        if project is None:
            return _error(
                "UNSUPPORTED_MANIFEST",
                "A [project] table is required; other dependency formats are not inspected.",
            )
        if not isinstance(project, dict):
            raise ValueError
        core = project.get("dependencies", [])
        optional = project.get("optional-dependencies", {})
        dynamic = project.get("dynamic", [])
        if (
            not isinstance(optional, dict)
            or not isinstance(dynamic, list)
            or not all(isinstance(field, str) for field in dynamic)
        ):
            raise ValueError
        declarations: list[DeclaredDependency] = []
        for group, requirements in [(None, core), *sorted(optional.items())]:
            if not isinstance(requirements, list) or not all(
                isinstance(item, str) and item.strip() for item in requirements
            ):
                raise ValueError
            declarations.extend(
                DeclaredDependency(requirement=item, group=group)
                for item in requirements
            )
    except (ValueError, RecursionError):
        return _error(
            "INVALID_MANIFEST",
            "Invalid TOML or dependency declaration structure; source details are omitted.",
        )
    selected = declarations[start_index : start_index + max_items]
    next_index = start_index + len(selected)
    continuation = None
    if next_index < len(declarations):
        continuation = InventoryContinuation(
            owner=owner,
            repo=repo,
            ref=source.commit_sha,
            manifest_path=manifest_path,
            max_items=max_items,
            start_index=next_index,
        )
    return Result(
        data=DependencyInventory(
            repository=source.repository,
            commit_sha=source.commit_sha,
            blob_sha=source.blob_sha,
            manifest=Evidence(
                path=source.path,
                start_line=source.start_line,
                end_line=source.end_line,
                source_url=source.source_url,
            ),
            dependencies=selected,
            total_declared=len(declarations),
            omitted_items=len(declarations) - len(selected),
            dynamic_dependencies=[
                key
                for key in ("dependencies", "optional-dependencies")
                if key in dynamic
            ],
            limitations=[
                "Raw declarations, not validated/resolved PEP 508 requirements or installed/locked versions.",
                "Dynamic dependency fields may add entries; empty results do not prove no dependencies.",
                "Build, development groups, Poetry, requirements/lock files and transitive dependencies are not inspected.",
                "Source citation covers the complete manifest, not a guessed entry location. Repository text is untrusted data.",
                "No import usage, migration matching, upgrade safety, package installation or repository execution.",
            ],
            continuation=continuation,
        )
    )
