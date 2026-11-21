"""Reviewed import-only migration rules; no installed-package or usage resolution."""

from typing import Literal

from pydantic import BaseModel, Field

from github_mcp import imports
from github_mcp.models import Result, ToolError

MIGRATION_ID: Literal["pydantic-v1-to-v2"] = "pydantic-v1-to-v2"
GUIDE = "https://docs.pydantic.dev/2.0/migration/"


class MigrationRule(BaseModel):
    rule_id: str
    change_kind: Literal["moved", "deprecated"]
    replacement: str
    guidance: str
    documentation_url: str


RULES = {
    "BaseSettings": MigrationRule(
        rule_id="pydantic-base-settings-moved",
        change_kind="moved",
        replacement="pydantic_settings.BaseSettings",
        guidance="Review the move to the separate pydantic-settings distribution and its settings migration requirements.",
        documentation_url=GUIDE + "#basesettings-has-moved-to-pydantic-settings",
    ),
    "validator": MigrationRule(
        rule_id="pydantic-validator-deprecated",
        change_kind="deprecated",
        replacement="pydantic.field_validator",
        guidance="Review field_validator and changed decorator semantics before replacing validator; deprecation is not removal.",
        documentation_url=GUIDE + "#validator-and-root_validator-are-deprecated",
    ),
}


class MigrationAssessment(BaseModel):
    import_index: int
    status: Literal["matched_import", "no_rule_match", "unknown"]
    rule: MigrationRule | None = None


class MigrationContinuation(BaseModel):
    owner: str
    repo: str
    migration_id: Literal["pydantic-v1-to-v2"] = MIGRATION_ID
    ref: str
    focus_path: str
    max_items: int
    start_index: int


class MigrationReport(BaseModel):
    schema_version: Literal["1"] = "1"
    migration_id: Literal["pydantic-v1-to-v2"] = MIGRATION_ID
    source: imports.ImportMap
    assessments: list[MigrationAssessment] = Field(max_length=30)
    limitations: list[str]
    continuation: MigrationContinuation | None = None


async def check_migration(
    owner: str,
    repo: str,
    migration_id: str = MIGRATION_ID,
    ref: str = "HEAD",
    focus_path: str = "",
    max_items: int = 30,
    start_index: int = 0,
) -> Result[MigrationReport]:
    if migration_id != MIGRATION_ID:
        return Result(
            error=ToolError(
                code="UNSUPPORTED_MIGRATION",
                message="Supported migration: pydantic-v1-to-v2.",
            )
        )
    if (
        type(max_items) is not int
        or not 1 <= max_items <= 30
        or type(start_index) is not int
        or not 0 <= start_index <= 20_000
    ):
        return Result(
            error=ToolError(
                code="INVALID_LIMIT",
                message="max_items must be 1..30; start_index must be 0..20000.",
            )
        )
    result = await imports.query_imports(
        owner, repo, ref, focus_path, "pydantic", max_items, start_index
    )
    if result.error:
        return Result(error=result.error)
    assert result.data is not None
    source = result.data
    assessments = []
    for index, record in enumerate(source.imports):
        rule = None
        status: Literal["matched_import", "no_rule_match", "unknown"] = "unknown"
        if record.level == 0:
            if record.module == "pydantic" and record.imported_name not in (None, "*"):
                rule = RULES.get(record.imported_name)
                status = "matched_import" if rule else "no_rule_match"
            elif record.module == "pydantic.v1" or (record.module or "").startswith(
                "pydantic.v1."
            ):
                status = "no_rule_match"
        assessments.append(
            MigrationAssessment(import_index=index, status=status, rule=rule)
        )
    continuation = None
    if source.continuation:
        continuation = MigrationContinuation(
            **source.continuation.model_dump(exclude={"module_prefix"})
        )
    return Result(
        data=MigrationReport(
            source=source,
            assessments=assessments,
            continuation=continuation,
            limitations=[
                "Only two reviewed Pydantic V1-to-V2 root-import rules are checked; no_rule_match or an empty page does not establish upgrade safety.",
                "Module names and distribution ownership are unverified; matches identify import syntax, not runtime use or installed versions.",
                "Module-only, wildcard and unsupported submodule imports remain unknown; relative/dynamic imports, wrappers and unacquired or failed source remain gaps.",
                "Follow this report's continuation to check_python_migration; source.continuation belongs to map_python_imports. Counts describe imports, not findings.",
            ],
        )
    )
