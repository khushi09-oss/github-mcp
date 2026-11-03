"""Structured contracts for revision-aware retrieval."""

from typing import Generic, TypeVar

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, model_validator

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
