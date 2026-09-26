"""Claude Code Markdown subagent source adapter."""

from __future__ import annotations

from typing import Any

import yaml

from agent_ir.adapters.base import ParseResult
from agent_ir.diagnostics import AuthorityEffect, ConversionDiagnostic, DiagnosticCategory, MappingStatus
from agent_ir.models import (
    AgentIR,
    Capabilities,
    Delegation,
    DelegationAccess,
    Execution,
    FilesystemAccess,
    Lifecycle,
    ModelRequirement,
    NetworkAccess,
    ShellAccess,
    SourceMetadata,
    ToolPolicyMode,
    ToolGrant,
    GrantState,
)


_TOOL_SEMANTICS: dict[str, list[str]] = {
    "Read": ["filesystem.read_content"],
    "Write": ["filesystem.create_content"],
    "Edit": ["filesystem.modify_content"],
    "Bash": ["shell.execute"],
    "Glob": ["filesystem.list_paths"],
    "Grep": ["filesystem.search_content"],
    "WebFetch": ["network.fetch"],
    "WebSearch": ["network.search"],
    "Task": ["delegation.invoke"],
    "Agent": ["delegation.invoke"],
}
_KNOWN_FIELDS = {
    "name", "description", "tools", "disallowedTools", "model", "effort",
    "maxTurns", "permissionMode", "hooks", "skills", "memory", "background",
    "isolation", "color", "permission", "permissions", "mcpServers",
}


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently accepting the last value."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a frontmatter mapping",
                node.start_mark,
                "frontmatter mapping keys must be scalar values",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a frontmatter mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _tool_names(value: Any, field_name: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        values = [part.strip() for part in value.split(",")]
    elif isinstance(value, list) and all(isinstance(part, str) for part in value):
        values = [part.strip() for part in value]
    else:
        raise ValueError(f"frontmatter {field_name} must be a comma-separated string or list of strings")
    if not all(values):
        raise ValueError(f"frontmatter {field_name} contains an empty tool name")
    return values


def _capability(name: str) -> list[str]:
    if name in _TOOL_SEMANTICS:
        return _TOOL_SEMANTICS[name]
    if name.startswith("mcp__"):
        return [f"mcp.invoke:{name[5:]}"]
    return [f"tool.invoke:{name}"]


class ClaudeCodeAdapter:
    harness = "claude-code"

    def parse(self, document: str) -> ParseResult:
        if not document.startswith("---\n") and not document.startswith("---\r\n"):
            raise ValueError("Claude agent definition must start with YAML frontmatter")
        lines = document.splitlines(keepends=True)
        closing = next(
            (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
            None,
        )
        if closing is None:
            raise ValueError("Claude agent definition has an unterminated YAML frontmatter block")
        raw_frontmatter = "".join(lines[1:closing])
        try:
            frontmatter = yaml.load(raw_frontmatter, Loader=_UniqueKeyLoader)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
        if not isinstance(frontmatter, dict):
            raise ValueError("Claude YAML frontmatter must be a mapping")
        if any(not isinstance(key, str) for key in frontmatter):
            raise ValueError("Claude frontmatter keys must be strings")
        body = "".join(lines[closing + 1 :])
        name = frontmatter.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Claude frontmatter requires a non-empty name")
        description = frontmatter.get("description", "")
        if not isinstance(description, str):
            raise ValueError("Claude frontmatter description must be a string")

        allowed = _tool_names(frontmatter.get("tools"), "tools")
        denied = _tool_names(frontmatter.get("disallowedTools"), "disallowedTools") or []
        grants: list[ToolGrant] | None = None
        if allowed is not None:
            grants = [
                ToolGrant(
                    name=name,
                    source_name=name,
                    state=GrantState.ALLOWED,
                    semantic_capabilities=_capability(name),
                )
                for name in allowed
            ]
        if denied:
            grants = grants or []
            present = {grant.name for grant in grants}
            if present.intersection(denied):
                raise ValueError("a tool cannot appear in both tools and disallowedTools")
            grants.extend(
                ToolGrant(
                    name=name,
                    source_name=name,
                    state=GrantState.DENIED,
                    semantic_capabilities=_capability(name),
                )
                for name in denied
            )

        policy_mode = (
            ToolPolicyMode.ALLOWLIST
            if allowed is not None
            else ToolPolicyMode.INHERIT_WITH_DENIALS
            if denied
            else ToolPolicyMode.INHERIT
        )
        caps = _derive_capabilities(grants, policy_mode, frontmatter.get("permissionMode"))
        source_model = frontmatter.get("model")
        if source_model in (None, "inherit", "default"):
            model = ModelRequirement(
                kind="inherited" if source_model == "inherit" else "target-default",
                source_identifier=source_model,
            )
        elif isinstance(source_model, str):
            model = ModelRequirement(
                kind="explicit",
                source_identifier=source_model,
            )
        else:
            raise ValueError("Claude frontmatter model must be a string")

        hooks = frontmatter.get("hooks", [])
        if hooks is None:
            hooks = []
        if not isinstance(hooks, (list, dict)):
            raise ValueError("Claude frontmatter hooks must be a list or mapping")
        lifecycle_hooks = hooks if isinstance(hooks, list) else [hooks]
        diagnostics: list[ConversionDiagnostic] = []
        unknown = {key: value for key, value in frontmatter.items() if key not in _KNOWN_FIELDS}
        if unknown:
            diagnostics.append(
                ConversionDiagnostic(
                    code="source.extension_preserved",
                    field_path="metadata.extensions",
                    status=MappingStatus.LOSSLESS,
                    category=DiagnosticCategory.FIDELITY,
                    message="Unknown Claude frontmatter fields were retained in IR extensions.",
                )
            )
        agent = AgentIR(
            name=name.strip(),
            description=description,
            instructions=body,
            capabilities=caps,
            model=model,
            delegation=Delegation(
                enabled=True if any(g.name in {"Task", "Agent"} and g.state == GrantState.ALLOWED for g in (grants or [])) else (False if grants is not None else None),
                allowed_targets=None,
                semantics="Claude Code Agent/Task tool delegation" if grants is not None else None,
            ),
            execution=Execution(
                isolation=str(frontmatter["isolation"]) if frontmatter.get("isolation") is not None else None,
                workspace_access=str(frontmatter.get("permissionMode")) if frontmatter.get("permissionMode") is not None else None,
            ),
            lifecycle=Lifecycle(hooks=lifecycle_hooks),
            metadata=SourceMetadata(
                harness=self.harness,
                fields={key: value for key, value in frontmatter.items() if key in _KNOWN_FIELDS},
                original_frontmatter=frontmatter,
                original_document=document,
                extensions=unknown,
            ),
        )
        return ParseResult(agent=agent, diagnostics=diagnostics)


def _derive_capabilities(
    grants: list[ToolGrant] | None,
    policy_mode: ToolPolicyMode,
    permission_mode: Any,
) -> Capabilities:
    if policy_mode != ToolPolicyMode.ALLOWLIST:
        return Capabilities(tools=grants, tool_policy_mode=policy_mode)
    allowed = {grant.name for grant in (grants or []) if grant.state == GrantState.ALLOWED}
    fs = FilesystemAccess.UNKNOWN
    if allowed:
        reads = bool(allowed.intersection({"Read", "Glob", "Grep"}))
        writes = bool(allowed.intersection({"Write", "Edit"}))
        fs = FilesystemAccess.WORKSPACE_WRITE if writes else (FilesystemAccess.READ_ONLY if reads else FilesystemAccess.NONE)
    elif grants:
        fs = FilesystemAccess.NONE
    shell = ShellAccess.ALLOWED if "Bash" in allowed else ShellAccess.NONE
    network = NetworkAccess.ALLOWED if allowed.intersection({"WebFetch", "WebSearch"}) else NetworkAccess.NONE
    delegation = DelegationAccess.ALLOWED if allowed.intersection({"Task", "Agent"}) else DelegationAccess.NONE
    # Claude's plan mode is a source-side behavioral boundary; without an explicit
    # tools field, the effective tool pool remains ambient and cannot be inferred.
    if permission_mode == "plan" and grants and fs == FilesystemAccess.WORKSPACE_WRITE:
        fs = FilesystemAccess.READ_ONLY
    return Capabilities(
        tools=grants,
        tool_policy_mode=policy_mode,
        filesystem=fs,
        shell=shell,
        network=network,
        delegation=delegation,
        workspace_scope="workspace" if fs != FilesystemAccess.UNKNOWN else None,
    )
