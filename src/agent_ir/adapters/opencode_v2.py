"""OpenCode V2 Markdown source adapter with conservative authority handling."""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import Field, model_validator

from agent_ir.adapters.base import ParseResult, SourceParseContext, validate_agent_relative_path
from agent_ir.diagnostics import (
    AuthorityEffect,
    ConversionDiagnostic,
    DiagnosticCategory,
    MappingStatus,
)
from agent_ir.models import (
    AgentIR,
    Capabilities,
    CodexTargetContext,
    Delegation,
    DelegationAccess,
    FilesystemAccess,
    ModelRequirement,
    NetworkAccess,
    ShellAccess,
    SourceMetadata,
    StrictModel,
    ToolGrant,
    ToolPolicyMode,
    GrantState,
)


_ACTION_SEMANTICS: dict[str, list[str]] = {
    "read": ["filesystem.read_content"],
    "glob": ["filesystem.list_paths"],
    "grep": ["filesystem.search_content"],
    "edit": ["filesystem.create_content", "filesystem.modify_content"],
    "shell": ["shell.execute"],
    "webfetch": ["network.fetch"],
    "websearch": ["network.search"],
    "subagent": ["delegation.invoke"],
}
_KNOWN_FIELDS = {"description", "mode", "model", "permissions", "steps", "hidden", "color", "disabled", "request"}
_V1_FIELDS = {"permission", "tools", "prompt", "disable", "maxSteps", "temperature", "top_p"}
_REQUIRED_CAPABILITY_FIELDS = {
    "tools",
    "tool_policy_mode",
    "filesystem",
    "shell",
    "network",
    "delegation",
    "workspace_scope",
}
_UNKNOWN_AUTHORITY_DIAGNOSTIC = "opencode.source_authority_unknown"
_MISSING = object()


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently changing permission meaning."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing OpenCode frontmatter",
                node.start_mark,
                "frontmatter mapping keys must be scalar values",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing OpenCode frontmatter",
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


class OpenCodeSourceContext(StrictModel):
    """Operator declaration of effective OpenCode authority, never auto-discovered."""

    effective_capabilities: Capabilities

    @model_validator(mode="after")
    def complete_effective_capabilities(self) -> "OpenCodeSourceContext":
        capabilities = self.effective_capabilities
        omitted = _REQUIRED_CAPABILITY_FIELDS - capabilities.model_fields_set
        if omitted:
            raise ValueError(f"OpenCode effective_capabilities is missing explicit fields: {', '.join(sorted(omitted))}")
        if capabilities.tool_policy_mode != ToolPolicyMode.ALLOWLIST or capabilities.tools is None:
            raise ValueError("OpenCode effective_capabilities requires allowlist tool_policy_mode and an explicit tools list")
        if any(grant.state not in {GrantState.ALLOWED, GrantState.DENIED} for grant in capabilities.tools):
            raise ValueError("OpenCode effective_capabilities cannot contain ask or unknown tool grants")
        if capabilities.filesystem == FilesystemAccess.UNKNOWN:
            raise ValueError("OpenCode effective_capabilities.filesystem cannot be unknown")
        if capabilities.shell in {ShellAccess.UNKNOWN, ShellAccess.APPROVAL_REQUIRED}:
            raise ValueError("OpenCode effective_capabilities.shell must be none or allowed")
        if capabilities.network in {NetworkAccess.UNKNOWN, NetworkAccess.APPROVAL_REQUIRED}:
            raise ValueError("OpenCode effective_capabilities.network must be none or allowed")
        if capabilities.delegation == DelegationAccess.UNKNOWN:
            raise ValueError("OpenCode effective_capabilities.delegation cannot be unknown")
        if capabilities.filesystem != FilesystemAccess.NONE or capabilities.shell == ShellAccess.ALLOWED:
            if not capabilities.workspace_scope or not capabilities.workspace_scope.strip():
                raise ValueError("OpenCode effective_capabilities requires workspace_scope for path-scoped access")
        elif capabilities.workspace_scope is not None and not capabilities.workspace_scope.strip():
            raise ValueError("OpenCode effective_capabilities.workspace_scope must be non-empty or null")

        expected: set[str] = set()
        for grant in capabilities.tools:
            mapped = _ACTION_SEMANTICS.get(grant.name)
            if mapped is None or grant.semantic_capabilities != mapped:
                raise ValueError(f"OpenCode effective_capabilities contains an unsupported tool grant: {grant.name!r}")
            if grant.state == GrantState.ALLOWED:
                expected.update(mapped)
        actual = {
            capability
            for grant in capabilities.tools
            if grant.state == GrantState.ALLOWED
            for capability in grant.semantic_capabilities
        }
        if actual != expected:
            raise ValueError("OpenCode effective_capabilities contains inconsistent tool semantics")
        has_fs_read = bool(expected.intersection({"filesystem.read_content", "filesystem.list_paths", "filesystem.search_content"}))
        has_fs_write = bool(expected.intersection({"filesystem.create_content", "filesystem.modify_content"}))
        expected_filesystem = (
            FilesystemAccess.WORKSPACE_WRITE
            if has_fs_write
            else FilesystemAccess.READ_ONLY
            if has_fs_read
            else FilesystemAccess.NONE
        )
        if capabilities.filesystem != expected_filesystem:
            raise ValueError("OpenCode filesystem access must agree with the effective tool grants")
        if capabilities.shell != (ShellAccess.ALLOWED if "shell.execute" in expected else ShellAccess.NONE):
            raise ValueError("OpenCode shell access must agree with the effective tool grants")
        if capabilities.network != (
            NetworkAccess.ALLOWED if expected.intersection({"network.fetch", "network.search"}) else NetworkAccess.NONE
        ):
            raise ValueError("OpenCode network access must agree with the effective tool grants")
        if capabilities.delegation != (
            DelegationAccess.ALLOWED if "delegation.invoke" in expected else DelegationAccess.NONE
        ):
            raise ValueError("OpenCode delegation access must agree with the effective tool grants")
        return self


class OpenCodeV2Adapter:
    harness = "opencode-v2"

    def parse_with_context(self, document: str, context: SourceParseContext) -> ParseResult:
        identity = _identity_from_path(context.agent_relative_path)
        lines = document.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            raise ValueError("OpenCode V2 agent must start with YAML frontmatter")
        closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if closing is None:
            raise ValueError("OpenCode V2 agent has unterminated YAML frontmatter")
        try:
            frontmatter = yaml.load("".join(lines[1:closing]), Loader=_UniqueKeyLoader)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid OpenCode V2 YAML frontmatter: {exc}") from exc
        if not isinstance(frontmatter, dict) or any(not isinstance(key, str) for key in frontmatter):
            raise ValueError("OpenCode V2 frontmatter must be a mapping with string keys")
        body = "".join(lines[closing + 1 :])

        diagnostics: list[ConversionDiagnostic] = []
        description = frontmatter.get("description", "")
        if not isinstance(description, str):
            raise ValueError("OpenCode V2 `description` must be a string")

        mode_value = frontmatter.get("mode", "primary")
        if not isinstance(mode_value, str) or mode_value not in {"primary", "subagent", "all"}:
            raise ValueError("OpenCode V2 `mode` must be `primary`, `subagent`, or `all`")
        if mode_value != "subagent":
            diagnostics.append(_diagnostic(
                "opencode.mode_not_representable",
                "mode",
                f"OpenCode mode {mode_value!r} cannot be represented by a standalone Codex subagent.",
                category=DiagnosticCategory.FUNCTIONALITY,
                status=MappingStatus.UNSUPPORTED,
                blocks=True,
            ))

        model = _model_requirement(frontmatter.get("model"), diagnostics)
        steps = frontmatter.get("steps")
        if steps is not None:
            if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
                raise ValueError("OpenCode V2 `steps` must be a positive integer")
            diagnostics.append(_diagnostic(
                "opencode.steps_not_representable",
                "steps",
                "Codex standalone agents cannot preserve OpenCode's maximum step count.",
                category=DiagnosticCategory.FUNCTIONALITY,
                status=MappingStatus.UNSUPPORTED,
                blocks=True,
            ))

        disabled = frontmatter.get("disabled", False)
        if not isinstance(disabled, bool):
            raise ValueError("OpenCode V2 `disabled` must be a boolean")
        if disabled:
            diagnostics.append(_diagnostic(
                "opencode.agent_disabled",
                "disabled",
                "This OpenCode V2 agent is disabled and cannot be emitted as a runnable Codex agent.",
                category=DiagnosticCategory.FUNCTIONALITY,
                status=MappingStatus.UNSUPPORTED,
                blocks=True,
            ))

        permissions_value = frontmatter.get("permissions", _MISSING)
        if permissions_value is None:
            raise ValueError("OpenCode V2 `permissions` must be omitted or an ordered list, not null")
        permissions = _parse_permissions(None if permissions_value is _MISSING else permissions_value, diagnostics)
        capabilities = _derive_local_capabilities(permissions, diagnostics)
        legacy = sorted(_V1_FIELDS.intersection(frontmatter))
        for field in legacy:
            diagnostics.append(_diagnostic(
                "opencode.v1_field_unsupported",
                field,
                f"OpenCode V1 field {field!r} is not interpreted as V2 semantics.",
                category=DiagnosticCategory.FUNCTIONALITY,
                status=MappingStatus.UNSUPPORTED,
                blocks=True,
            ))
        if "hooks" in frontmatter or "lifecycle" in frontmatter:
            diagnostics.append(_diagnostic(
                "opencode.lifecycle_unsupported",
                "lifecycle",
                "OpenCode lifecycle behavior is not supported by this V2 Markdown adapter.",
                category=DiagnosticCategory.FUNCTIONALITY,
                status=MappingStatus.UNSUPPORTED,
                blocks=True,
            ))
        if "request" in frontmatter:
            diagnostics.append(_diagnostic(
                "opencode.request_options_preserved",
                "request",
                "OpenCode request overlays are preserved but are not represented in Codex agent files.",
                category=DiagnosticCategory.FUNCTIONALITY,
                status=MappingStatus.DROPPED,
                blocks=False,
            ))
        unknown = {key: value for key, value in frontmatter.items() if key not in _KNOWN_FIELDS and key not in _V1_FIELDS}
        if unknown:
            diagnostics.append(_diagnostic(
                "opencode.extension_preserved",
                "metadata.extensions",
                "Unknown OpenCode V2 frontmatter fields were preserved; their semantics are unsupported.",
                category=DiagnosticCategory.FIDELITY,
                status=MappingStatus.UNSUPPORTED,
                blocks=True,
                details={"fields": ", ".join(sorted(unknown))},
            ))
        if "hidden" in frontmatter and not isinstance(frontmatter["hidden"], bool):
            raise ValueError("OpenCode V2 `hidden` must be a boolean")
        if "color" in frontmatter and not isinstance(frontmatter["color"], str):
            raise ValueError("OpenCode V2 `color` must be a string")

        agent = AgentIR(
            name=identity,
            description=description,
            instructions=body,
            capabilities=capabilities,
            model=model,
            delegation=_delegation_from_capabilities(capabilities),
            metadata=SourceMetadata(
                harness=self.harness,
                fields={key: value for key, value in frontmatter.items() if key in _KNOWN_FIELDS},
                original_frontmatter=frontmatter,
                original_document=document,
                extensions=unknown,
            ),
        )
        return ParseResult(agent=agent, diagnostics=diagnostics)

    def validate_target_scope(
        self,
        parsed: ParseResult,
        target: CodexTargetContext,
    ) -> list[ConversionDiagnostic]:
        source = parsed.agent.capabilities
        if source.filesystem == FilesystemAccess.NONE and source.shell == ShellAccess.NONE:
            return []
        if not source.workspace_scope or not target.workspace_scope or source.workspace_scope != target.workspace_scope:
            return [_diagnostic(
                "opencode.workspace_scope_not_proven",
                "capabilities.workspace_scope",
                "OpenCode path-scoped access is emitted only when the source and Codex contexts name the same explicit workspace scope.",
                category=DiagnosticCategory.AUTHORITY,
                status=MappingStatus.UNSUPPORTED,
                effect=AuthorityEffect.UNKNOWN,
                blocks=True,
                details={
                    "source_scope": source.workspace_scope or "unknown",
                    "target_scope": target.workspace_scope or "unknown",
                },
            )]
        return []

    def apply_source_context(
        self,
        parsed: ParseResult,
        context: OpenCodeSourceContext | None,
    ) -> ParseResult:
        if parsed.agent.metadata.harness != self.harness:
            raise ValueError("OpenCode source context can only be applied to an OpenCode V2 source")
        blockers = [
            item for item in parsed.diagnostics
            if item.blocks_emission and item.code != _UNKNOWN_AUTHORITY_DIAGNOSTIC
        ]
        if blockers:
            return parsed
        local_permissions = parsed.agent.metadata.original_frontmatter.get("permissions")
        if parsed.agent.capabilities.tool_policy_mode == ToolPolicyMode.ALLOWLIST:
            # A final universal deny is self-contained and is never widened by context.
            if context is not None and _has_allowed_grant(context.effective_capabilities):
                raise ValueError("OpenCode source context cannot broaden the final agent-local catch-all deny")
            if context is None:
                return parsed
        if context is None:
            return parsed
        _validate_context_against_rules(context.effective_capabilities, local_permissions)
        diagnostics = [item for item in parsed.diagnostics if item.code != _UNKNOWN_AUTHORITY_DIAGNOSTIC]
        diagnostics.append(_diagnostic(
            "opencode.source_context_unverified",
            "effective_capabilities",
            "OpenCode source effective capabilities are operator-declared and not independently verified by this CLI.",
            category=DiagnosticCategory.AUTHORITY,
            status=MappingStatus.APPROXIMATED,
            effect=AuthorityEffect.UNKNOWN,
            blocks=False,
        ))
        agent = parsed.agent.model_copy(update={"capabilities": context.effective_capabilities})
        agent = agent.model_copy(update={"delegation": _delegation_from_capabilities(agent.capabilities)})
        return ParseResult(agent=agent, diagnostics=diagnostics)


def _identity_from_path(value: str) -> str:
    validate_agent_relative_path(value)
    parts = value.split("/")
    name_parts = [*parts[:-1], parts[-1][:-3]]
    if any(not part or part in {".", ".."} for part in name_parts):
        raise ValueError("OpenCode source identity path has an empty name")
    return "/".join(name_parts)


def _model_requirement(value: Any, diagnostics: list[ConversionDiagnostic]) -> ModelRequirement:
    if value is None:
        diagnostics.append(_diagnostic(
            "opencode.model_inherited",
            "model",
            "No model is declared; OpenCode uses its active session or parent model.",
            category=DiagnosticCategory.FIDELITY,
            status=MappingStatus.MAPPED,
            blocks=False,
        ))
        return ModelRequirement(kind="inherited")
    if not isinstance(value, str):
        raise ValueError("OpenCode V2 `model` must be a provider/model string")
    model_part, hash_sep, variant = value.partition("#")
    provider, slash, model_name = model_part.partition("/")
    if not slash or not provider or not model_name or (hash_sep and not variant):
        raise ValueError("OpenCode V2 model must use `provider/model` with an optional `#variant`")
    if hash_sep:
        diagnostics.append(_diagnostic(
            "opencode.model_variant_not_representable",
            "model",
            "Codex standalone agent files cannot preserve OpenCode model variants.",
            category=DiagnosticCategory.FUNCTIONALITY,
            status=MappingStatus.UNSUPPORTED,
            blocks=True,
        ))
    else:
        diagnostics.append(_diagnostic(
            "opencode.model_not_copied",
            "model",
            "The OpenCode provider/model value is preserved but Codex will use its configured default model.",
            category=DiagnosticCategory.FUNCTIONALITY,
            status=MappingStatus.DROPPED,
            blocks=False,
        ))
    return ModelRequirement(
        kind="explicit",
        identifier=value,
        provider=provider,
        source_identifier=value,
        reasoning_preference=variant if hash_sep else None,
    )


def _parse_permissions(value: Any, diagnostics: list[ConversionDiagnostic]) -> list[dict[str, str]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("OpenCode V2 `permissions` must be an ordered list of rules")
    rules: list[dict[str, str]] = []
    for index, rule in enumerate(value):
        if not isinstance(rule, dict) or any(not isinstance(key, str) for key in rule):
            raise ValueError(f"OpenCode permission rule {index} must be a mapping with string keys")
        if set(rule) != {"action", "resource", "effect"}:
            diagnostics.append(_diagnostic(
                "opencode.permission_rule_unrepresentable",
                f"permissions[{index}]",
                "OpenCode permission rules must contain only action, resource, and effect for safe conversion.",
                category=DiagnosticCategory.AUTHORITY,
                status=MappingStatus.UNSUPPORTED,
                effect=AuthorityEffect.UNKNOWN,
                blocks=True,
            ))
        if not all(isinstance(rule.get(key), str) and rule[key] for key in ("action", "resource", "effect")):
            raise ValueError(f"OpenCode permission rule {index} requires non-empty string action, resource, and effect")
        if rule["effect"] not in {"allow", "deny", "ask"}:
            raise ValueError(f"OpenCode permission rule {index} has an unsupported effect")
        rules.append({key: rule[key] for key in ("action", "resource", "effect")})
    return rules


def _derive_local_capabilities(
    rules: list[dict[str, str]] | None,
    diagnostics: list[ConversionDiagnostic],
) -> Capabilities:
    if rules and rules[-1] == {"action": "*", "resource": "*", "effect": "deny"}:
        diagnostics.append(_diagnostic(
            "opencode.source_authority_derived",
            "permissions",
            "A final agent-local catch-all deny establishes a zero-capability source ceiling under OpenCode V2 last-match semantics.",
            category=DiagnosticCategory.AUTHORITY,
            status=MappingStatus.MAPPED,
            effect=AuthorityEffect.NARROWED,
            blocks=False,
        ))
        return Capabilities(
            tools=[],
            tool_policy_mode=ToolPolicyMode.ALLOWLIST,
            filesystem=FilesystemAccess.NONE,
            shell=ShellAccess.NONE,
            network=NetworkAccess.NONE,
            delegation=DelegationAccess.NONE,
        )
    diagnostics.append(_diagnostic(
        _UNKNOWN_AUTHORITY_DIAGNOSTIC,
        "capabilities",
        "OpenCode V2 permissions may inherit the permissive base policy or ambient rules; effective authority is unknown.",
        category=DiagnosticCategory.AUTHORITY,
        status=MappingStatus.UNSUPPORTED,
        effect=AuthorityEffect.UNKNOWN,
        blocks=True,
    ))
    if rules is None:
        return Capabilities()
    for index, rule in enumerate(rules):
        if rule["effect"] == "ask":
            diagnostics.append(_diagnostic(
                "opencode.ask_not_representable",
                f"permissions[{index}].effect",
                "OpenCode approval prompts cannot be represented by a Codex standalone agent.",
                category=DiagnosticCategory.AUTHORITY,
                status=MappingStatus.UNSUPPORTED,
                effect=AuthorityEffect.UNKNOWN,
                blocks=True,
            ))
        if rule["action"] not in _ACTION_SEMANTICS and rule["action"] != "*":
            diagnostics.append(_diagnostic(
                "opencode.permission_action_unknown",
                f"permissions[{index}].action",
                f"OpenCode permission action {rule['action']!r} has no conservative Agent IR mapping.",
                category=DiagnosticCategory.AUTHORITY,
                status=MappingStatus.UNSUPPORTED,
                effect=AuthorityEffect.UNKNOWN,
                blocks=True,
            ))
        if rule["resource"] != "*":
            diagnostics.append(_diagnostic(
                "opencode.permission_resource_unrepresentable",
                f"permissions[{index}].resource",
                "OpenCode resource patterns cannot be reduced to the Codex renderer's whole-capability boundary.",
                category=DiagnosticCategory.AUTHORITY,
                status=MappingStatus.UNSUPPORTED,
                effect=AuthorityEffect.UNKNOWN,
                blocks=True,
            ))
    return Capabilities()


def _validate_context_against_rules(capabilities: Capabilities, rules: Any) -> None:
    if rules is None:
        return
    if not isinstance(rules, list):
        raise ValueError("OpenCode source context cannot resolve a malformed permission list")
    allowed_actions = {
        grant.name
        for grant in (capabilities.tools or [])
        if grant.state == GrantState.ALLOWED
    }
    for action in _ACTION_SEMANTICS:
        effective = next(
            (rule["effect"] for rule in reversed(rules) if rule["action"] in {"*", action}),
            None,
        )
        if effective != "deny":
            continue
        if action in allowed_actions:
            raise ValueError(f"OpenCode source context cannot override the agent-local denial for {action!r}")
        if action in {"read", "glob", "grep"} and capabilities.filesystem != FilesystemAccess.NONE:
            raise ValueError(f"OpenCode source context filesystem access conflicts with the agent-local denial for {action!r}")
        if action == "edit" and capabilities.filesystem in {FilesystemAccess.WORKSPACE_WRITE, FilesystemAccess.FULL}:
            raise ValueError("OpenCode source context filesystem writes conflict with the agent-local edit denial")
        if action == "shell" and capabilities.shell != ShellAccess.NONE:
            raise ValueError("OpenCode source context shell access conflicts with the agent-local shell denial")
        if action in {"webfetch", "websearch"} and capabilities.network != NetworkAccess.NONE:
            raise ValueError(f"OpenCode source context network access conflicts with the agent-local denial for {action!r}")
        if action == "subagent" and capabilities.delegation != DelegationAccess.NONE:
            raise ValueError("OpenCode source context delegation conflicts with the agent-local subagent denial")


def _has_allowed_grant(capabilities: Capabilities) -> bool:
    return any(grant.state == GrantState.ALLOWED for grant in (capabilities.tools or []))


def _delegation_from_capabilities(capabilities: Capabilities) -> Delegation:
    allowed = any(
        "delegation.invoke" in grant.semantic_capabilities and grant.state == GrantState.ALLOWED
        for grant in (capabilities.tools or [])
    )
    return Delegation(enabled=allowed if capabilities.tools is not None else None, semantics="OpenCode V2 subagent permission")


def _diagnostic(
    code: str,
    field: str,
    message: str,
    *,
    category: DiagnosticCategory,
    status: MappingStatus,
    effect: AuthorityEffect = AuthorityEffect.NOT_APPLICABLE,
    blocks: bool,
    details: dict[str, str] | None = None,
) -> ConversionDiagnostic:
    return ConversionDiagnostic(
        code=code,
        field_path=field,
        status=status,
        category=category,
        authority_effect=effect,
        message=message,
        blocks_emission=blocks,
        details=details or {},
    )
