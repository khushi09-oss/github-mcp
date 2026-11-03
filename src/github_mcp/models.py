"""Structured contracts for revision-aware retrieval."""

from typing import Generic, Literal, TypeVar

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")


class ToolError(BaseModel):
    code: str
    message: str
    retry_after_seconds: int | None = None


class Result(BaseModel, Generic[T]):
    data: T | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> "Result[T]":
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one of data or error is required")
        return self

    def as_mcp(self) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text=self.model_dump_json())],
            structuredContent=self.model_dump(mode="json"),
            isError=self.error is not None,
        )


class Revision(BaseModel):
    repository: str
    requested_ref: str
    commit_sha: str
    source_url: str


class Continuation(BaseModel):
    owner: str
    repo: str
    path: str
    ref: str
    start_line: int
    line_count: int


class FileChunk(BaseModel):
    repository: str
    commit_sha: str
    blob_sha: str
    path: str
    start_line: int
    end_line: int
    total_lines: int
    text: str
    source_url: str
    continuation: Continuation | None = None


class Evidence(BaseModel):
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    source_url: str


class GraphNode(BaseModel):
    id: str
    label: str = Field(max_length=200)
    evidence: Evidence


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str = Field(max_length=80)
    confidence: Literal["EXTRACTED", "INFERRED", "AMBIGUOUS"]
    evidence: Evidence


class GraphCoverage(BaseModel):
    files_acquired: int
    files_failed: int
    omitted_files: dict[str, int]
    omitted_nodes: int
    omitted_edges: int
    complete: Literal[False] = False
    limitations: list[str]


class GraphView(BaseModel):
    repository: str
    commit_sha: str
    schema_version: Literal["1"] = "1"
    extractor: Literal["graphifyy==0.9.100"] = "graphifyy==0.9.100"
    focus_path: str
    nodes: list[GraphNode] = Field(max_length=50)
    edges: list[GraphEdge] = Field(max_length=100)
    coverage: GraphCoverage


class ArchitectureDiagram(GraphView):
    format: Literal["mermaid"] = "mermaid"
    view: Literal["overview", "focus"]
    requested_ref: str
    mermaid: str = Field(max_length=100_000)
    text: str = Field(max_length=100_000)
    reading_order: list[str]
    legend: list[str]
