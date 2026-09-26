"""Canonical, versioned Pydantic models for the internal Agent IR."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

IR_VERSION = "1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class GrantState(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    ASK = "ask"
    UNKNOWN = "unknown"


class ToolGrant(StrictModel):
    """Semantic tool grant, retaining the source identifier for round trips."""

    name: str = Field(min_length=1)
    state: GrantState
    semantic_capabilities: list[str] = Field(default_factory=list)
    source_name: str | None = None


class FilesystemAccess(StrEnum):
    NONE = "none"
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    FULL = "full"
    UNKNOWN = "unknown"


class ShellAccess(StrEnum):
    NONE = "none"
    APPROVAL_REQUIRED = "approval-required"
    ALLOWED = "allowed"
    UNKNOWN = "unknown"


class NetworkAccess(StrEnum):
    NONE = "none"
    APPROVAL_REQUIRED = "approval-required"
    ALLOWED = "allowed"
    UNKNOWN = "unknown"


class DelegationAccess(StrEnum):
    NONE = "none"
    ALLOWED = "allowed"
    UNKNOWN = "unknown"


class ToolPolicyMode(StrEnum):
    ALLOWLIST = "allowlist"
    INHERIT = "inherit"
    INHERIT_WITH_DENIALS = "inherit-with-denials"
    UNKNOWN = "unknown"


class Capabilities(StrictModel):
    """Capabilities explicitly granted or denied by the source definition."""

    tools: list[ToolGrant] | None = None
    tool_policy_mode: ToolPolicyMode = ToolPolicyMode.UNKNOWN
    filesystem: FilesystemAccess = FilesystemAccess.UNKNOWN
    shell: ShellAccess = ShellAccess.UNKNOWN
    network: NetworkAccess = NetworkAccess.UNKNOWN
    delegation: DelegationAccess = DelegationAccess.UNKNOWN
    workspace_scope: str | None = None

    @model_validator(mode="after")
    def unique_tools(self) -> "Capabilities":
        if self.tools is not None:
            names = [tool.name for tool in self.tools]
            if len(names) != len(set(names)):
                raise ValueError("tool grants must have unique names")
        return self


class ModelRequirement(StrictModel):
    kind: str = Field(description="explicit, inherited, or target-default")
    identifier: str | None = None
    provider: str | None = None
    source_identifier: str | None = None
    reasoning_preference: str | None = None
    constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def explicit_requires_identifier(self) -> "ModelRequirement":
        if self.kind == "explicit" and not self.identifier and not self.source_identifier:
            raise ValueError("an explicit model requires an identifier")
        return self


class Delegation(StrictModel):
    enabled: bool | None = None
    allowed_targets: list[str] | None = None
    semantics: str | None = None
    source_value: Any = None


class Execution(StrictModel):
    isolation: str | None = None
    workspace_access: str | None = None
    working_directory: str | None = None


class Lifecycle(StrictModel):
    hooks: list[dict[str, Any]] = Field(default_factory=list)


class SourceMetadata(StrictModel):
    harness: str
    fields: dict[str, Any] = Field(default_factory=dict)
    original_frontmatter: dict[str, Any] = Field(default_factory=dict)
    original_document: str | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)


class AgentIR(StrictModel):
    version: str = IR_VERSION
    name: str = Field(min_length=1)
    description: str = ""
    instructions: str
    capabilities: Capabilities = Field(default_factory=Capabilities)
    model: ModelRequirement = Field(
        default_factory=lambda: ModelRequirement(kind="target-default")
    )
    delegation: Delegation = Field(default_factory=Delegation)
    execution: Execution = Field(default_factory=Execution)
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)
    metadata: SourceMetadata

    @model_validator(mode="after")
    def supported_version(self) -> "AgentIR":
        if self.version != IR_VERSION:
            raise ValueError(f"unsupported Agent IR version: {self.version}")
        return self


class CodexTargetContext(StrictModel):
    """Evidence about Codex's *enforced ambient* policy for this conversion.

    Codex agent TOML cannot encode a per-agent tool allowlist. These values
    must describe separately enforced runtime policy, not desired intent.
    """

    enforced_capabilities: list[str] | None = None
    filesystem: FilesystemAccess = FilesystemAccess.UNKNOWN
    shell: ShellAccess = ShellAccess.UNKNOWN
    network: NetworkAccess = NetworkAccess.UNKNOWN
    delegation: DelegationAccess = DelegationAccess.UNKNOWN
    workspace_scope: str | None = None
