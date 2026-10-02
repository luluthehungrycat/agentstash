"""Codex standalone custom-agent TOML target adapter."""

from __future__ import annotations

from collections.abc import Iterable

import tomlkit

from agent_ir.diagnostics import (
    AuthorityEffect,
    ConversionDiagnostic,
    ConversionResult,
    DiagnosticCategory,
    MappingStatus,
)
from agent_ir.models import (
    AgentIR,
    CodexTargetContext,
    DelegationAccess,
    FilesystemAccess,
    GrantState,
    NetworkAccess,
    ShellAccess,
    ToolPolicyMode,
)


class CodexAdapter:
    harness = "codex"

    def render(self, agent: AgentIR, context: CodexTargetContext | None = None) -> ConversionResult:
        diagnostics: list[ConversionDiagnostic] = []
        source_tools = agent.capabilities.tools
        source_allowed = (
            {
                capability
                for grant in source_tools
                if grant.state == GrantState.ALLOWED
                for capability in grant.semantic_capabilities
            }
            if source_tools is not None
            else None
        )
        source_denied = (
            {
                capability
                for grant in source_tools
                if grant.state == GrantState.DENIED
                for capability in grant.semantic_capabilities
            }
            if source_tools is not None
            else set()
        )
        if context is None or context.enforced_capabilities is None:
            diagnostics.append(_authority_block(
                "codex.tool_boundary_unknown",
                "capabilities.tools",
                "Codex custom-agent TOML has no per-agent tool allowlist; an enforced target capability boundary was not supplied.",
            ))
            return ConversionResult(agent=agent, diagnostics=diagnostics)

        target_tools = set(context.enforced_capabilities)
        if source_allowed is None or agent.capabilities.tool_policy_mode != ToolPolicyMode.ALLOWLIST:
            diagnostics.append(_authority_block(
                "source.tool_boundary_unknown",
                "capabilities.tools",
                "The Claude source inherits an ambient tool set, so the source authority ceiling is unknown.",
            ))
        else:
            broader = target_tools - source_allowed
            narrowed = source_allowed - target_tools
            if broader:
                diagnostics.append(_authority_block(
                    "codex.tool_authority_increase",
                    "capabilities.tools",
                    "The enforced Codex capability boundary includes capabilities not granted by Claude.",
                    details={"extra_target_capabilities": ", ".join(sorted(broader))},
                    effect=AuthorityEffect.INCREASED,
                ))
            elif narrowed:
                diagnostics.append(ConversionDiagnostic(
                    code="codex.tool_capabilities_safely_narrowed",
                    field_path="capabilities.tools",
                    status=MappingStatus.APPROXIMATED,
                    category=DiagnosticCategory.FUNCTIONALITY,
                    authority_effect=AuthorityEffect.NARROWED,
                    message="The enforced Codex boundary omits some Claude tool capabilities; the result is safely narrower.",
                    details={"omitted_capabilities": ", ".join(sorted(narrowed))},
                ))
            if source_denied.intersection(target_tools) and not broader:
                diagnostics.append(_authority_block(
                    "codex.denied_tool_available",
                    "capabilities.tools",
                    "The Codex runtime boundary includes a capability explicitly denied by Claude.",
                    details={"denied_capabilities_available": ", ".join(sorted(source_denied.intersection(target_tools)))},
                    effect=AuthorityEffect.INCREASED,
                ))

        authority_checks = [
            ("filesystem", agent.capabilities.filesystem, context.filesystem, _fs_subset(context.filesystem, agent.capabilities.filesystem)),
            ("shell", agent.capabilities.shell, context.shell, _shell_subset(context.shell, agent.capabilities.shell)),
            ("network", agent.capabilities.network, context.network, _network_subset(context.network, agent.capabilities.network)),
            ("delegation", agent.capabilities.delegation, context.delegation, _delegation_subset(context.delegation, agent.capabilities.delegation)),
        ]
        for field, source, target, effect in authority_checks:
            if effect in {AuthorityEffect.INCREASED, AuthorityEffect.UNKNOWN}:
                diagnostics.append(_authority_block(
                    f"codex.{field}_boundary_not_proven",
                    f"capabilities.{field}",
                    f"The effective Codex {field} boundary is unknown or broader than the Claude source.",
                    details={"source": str(source), "target": str(target)},
                    effect=effect,
                ))
            elif effect == AuthorityEffect.NARROWED:
                diagnostics.append(ConversionDiagnostic(
                    code=f"codex.{field}_safely_narrowed",
                    field_path=f"capabilities.{field}",
                    status=MappingStatus.APPROXIMATED,
                    category=DiagnosticCategory.FUNCTIONALITY,
                    authority_effect=AuthorityEffect.NARROWED,
                    message=f"Codex {field} access is narrower than the source and was retained safely.",
                    details={"source": str(source), "target": str(target)},
                ))

        if any(d.blocks_emission for d in diagnostics):
            return ConversionResult(agent=agent, diagnostics=diagnostics)

        for field in ("hooks", "maxTurns", "effort", "skills", "memory", "background", "isolation", "color", "permission", "permissions", "mcpServers"):
            value = agent.metadata.fields.get(field)
            if value not in (None, [], {}):
                diagnostics.append(ConversionDiagnostic(
                    code=f"codex.unsupported_{field}",
                    field_path=f"metadata.fields.{field}",
                    status=MappingStatus.UNSUPPORTED,
                    category=DiagnosticCategory.FUNCTIONALITY,
                    authority_effect=AuthorityEffect.NOT_APPLICABLE,
                    message=f"Claude field `{field}` is retained in source metadata but has no mapping in the Codex agent definition.",
                ))
        permission_mode = agent.metadata.fields.get("permissionMode")
        if permission_mode is not None:
            if permission_mode == "plan" and context.filesystem == FilesystemAccess.READ_ONLY:
                diagnostics.append(ConversionDiagnostic(
                    code="codex.plan_mode_approximated",
                    field_path="execution.workspace_access",
                    status=MappingStatus.APPROXIMATED,
                    category=DiagnosticCategory.AUTHORITY,
                    authority_effect=AuthorityEffect.NARROWED,
                    message="Codex read-only sandbox preserves the no-write boundary, but Claude plan-mode approval behavior is not reproduced.",
                ))
            else:
                diagnostics.append(ConversionDiagnostic(
                    code="codex.permission_mode_not_preserved",
                    field_path="execution.workspace_access",
                    status=MappingStatus.UNSUPPORTED,
                    category=DiagnosticCategory.FUNCTIONALITY,
                    authority_effect=AuthorityEffect.UNCHANGED,
                    message="Claude permission-mode interaction behavior is not represented in the Codex agent file.",
                ))

        doc = tomlkit.document()
        doc.add("name", tomlkit.string(agent.name))
        doc.add("description", tomlkit.string(agent.description))
        if source_allowed is not None and agent.capabilities.tool_policy_mode == ToolPolicyMode.ALLOWLIST:
            disabled_features = tomlkit.table()
            if "shell.execute" not in source_allowed:
                disabled_features.add("shell_tool", False)
                diagnostics.append(ConversionDiagnostic(
                    code="codex.shell_tool_disabled_per_agent",
                    field_path="capabilities.tools",
                    status=MappingStatus.MAPPED,
                    category=DiagnosticCategory.AUTHORITY,
                    authority_effect=AuthorityEffect.NARROWED,
                    message="Codex per-agent feature settings disable the shell tool because the Claude allowlist does not grant shell execution.",
                ))
            if disabled_features:
                doc.add("features", disabled_features)
            if "network.search" not in source_allowed:
                doc.add("web_search", tomlkit.string("disabled"))
                diagnostics.append(ConversionDiagnostic(
                    code="codex.web_search_disabled_per_agent",
                    field_path="capabilities.tools",
                    status=MappingStatus.MAPPED,
                    category=DiagnosticCategory.AUTHORITY,
                    authority_effect=AuthorityEffect.NARROWED,
                    message="Codex per-agent configuration disables web search because the Claude allowlist does not grant search.",
                ))
        if agent.model.kind == "explicit":
            diagnostics.append(ConversionDiagnostic(
                code="codex.foreign_model_not_copied",
                field_path="model.identifier",
                status=MappingStatus.DROPPED,
                category=DiagnosticCategory.FUNCTIONALITY,
                authority_effect=AuthorityEffect.NOT_APPLICABLE,
                message="The Claude model identifier is not assumed to be a Codex model; Codex will use its configured default.",
                details={"source_model": agent.model.source_identifier or ""},
            ))
        elif agent.model.kind == "inherited":
            diagnostics.append(ConversionDiagnostic(
                code="codex.inherited_model_uses_target_default",
                field_path="model.kind",
                status=MappingStatus.MAPPED,
                category=DiagnosticCategory.FIDELITY,
                authority_effect=AuthorityEffect.NOT_APPLICABLE,
                message="The source inherits its caller's model; the Codex agent omits a model override and uses the Codex caller/default model.",
            ))
        if context.filesystem == FilesystemAccess.READ_ONLY:
            doc.add("sandbox_mode", tomlkit.string("read-only"))
        elif context.filesystem == FilesystemAccess.WORKSPACE_WRITE:
            doc.add("sandbox_mode", tomlkit.string("workspace-write"))
        elif context.filesystem == FilesystemAccess.FULL:
            diagnostics.append(_authority_block(
                "codex.full_filesystem_not_renderable",
                "capabilities.filesystem",
                "Codex standalone agent configuration cannot prove or scope full host filesystem access.",
            ))
            return ConversionResult(agent=agent, diagnostics=diagnostics)

        doc.add("developer_instructions", tomlkit.string(agent.instructions))
        text = tomlkit.dumps(doc)
        # Parse our own output to ensure TOML serialization is valid before emission.
        tomlkit.parse(text)
        return ConversionResult(agent=agent, target_text=text, diagnostics=diagnostics)


def _authority_block(
    code: str,
    field: str,
    message: str,
    *,
    details: dict[str, str] | None = None,
    effect: AuthorityEffect = AuthorityEffect.UNKNOWN,
) -> ConversionDiagnostic:
    return ConversionDiagnostic(
        code=code,
        field_path=field,
        status=MappingStatus.UNSUPPORTED,
        category=DiagnosticCategory.AUTHORITY,
        authority_effect=effect,
        message=message,
        blocks_emission=True,
        details=details or {},
    )


def _fs_subset(target: FilesystemAccess, source: FilesystemAccess) -> AuthorityEffect:
    order = {
        FilesystemAccess.NONE: 0,
        FilesystemAccess.READ_ONLY: 1,
        FilesystemAccess.WORKSPACE_WRITE: 2,
        FilesystemAccess.FULL: 3,
    }
    if target not in order or source not in order:
        return AuthorityEffect.UNKNOWN
    if order[target] > order[source]:
        return AuthorityEffect.INCREASED
    return AuthorityEffect.UNCHANGED if target == source else AuthorityEffect.NARROWED


def _shell_subset(target: ShellAccess, source: ShellAccess) -> AuthorityEffect:
    return _ordered_effect(target, source, [ShellAccess.NONE, ShellAccess.APPROVAL_REQUIRED, ShellAccess.ALLOWED])


def _network_subset(target: NetworkAccess, source: NetworkAccess) -> AuthorityEffect:
    return _ordered_effect(target, source, [NetworkAccess.NONE, NetworkAccess.APPROVAL_REQUIRED, NetworkAccess.ALLOWED])


def _delegation_subset(target: DelegationAccess, source: DelegationAccess) -> AuthorityEffect:
    if target == DelegationAccess.UNKNOWN or source == DelegationAccess.UNKNOWN:
        return AuthorityEffect.UNKNOWN
    if target == DelegationAccess.ALLOWED and source == DelegationAccess.NONE:
        return AuthorityEffect.INCREASED
    if target == source:
        return AuthorityEffect.UNCHANGED
    return AuthorityEffect.NARROWED


def _ordered_effect(target: object, source: object, order: Iterable[object]) -> AuthorityEffect:
    values = list(order)
    if target not in values or source not in values:
        return AuthorityEffect.UNKNOWN
    if values.index(target) > values.index(source):
        return AuthorityEffect.INCREASED
    return AuthorityEffect.UNCHANGED if target == source else AuthorityEffect.NARROWED
