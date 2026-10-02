from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_ir.adapters.codex import CodexAdapter
from agent_ir.adapters.opencode_v2 import OpenCodeSourceContext
from agent_ir.adapters.base import SourceParseContext
from agent_ir.models import (
    Capabilities,
    CodexTargetContext,
    DelegationAccess,
    FilesystemAccess,
    NetworkAccess,
    ShellAccess,
    ToolGrant,
    ToolPolicyMode,
)
from agent_ir.registry import apply_source_context, parse_source, validate_source_target_scope


FIXTURES = Path(__file__).parent / "fixtures" / "opencode-v2"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def source_context(*allowed: str, workspace_scope: str | None = "workspace") -> OpenCodeSourceContext:
    semantics = {
        "read": ["filesystem.read_content"],
        "glob": ["filesystem.list_paths"],
        "grep": ["filesystem.search_content"],
        "edit": ["filesystem.create_content", "filesystem.modify_content"],
        "shell": ["shell.execute"],
        "webfetch": ["network.fetch"],
        "websearch": ["network.search"],
        "subagent": ["delegation.invoke"],
    }
    names = sorted(set(allowed))
    grants = [ToolGrant(name=name, state="allowed", semantic_capabilities=semantics[name]) for name in names]
    caps = Capabilities(
        tools=grants,
        tool_policy_mode=ToolPolicyMode.ALLOWLIST,
        filesystem=(
            FilesystemAccess.WORKSPACE_WRITE if "edit" in names else
            FilesystemAccess.READ_ONLY if set(names).intersection({"read", "glob", "grep"}) else
            FilesystemAccess.NONE
        ),
        shell=ShellAccess.ALLOWED if "shell" in names else ShellAccess.NONE,
        network=NetworkAccess.ALLOWED if set(names).intersection({"webfetch", "websearch"}) else NetworkAccess.NONE,
        delegation=DelegationAccess.ALLOWED if "subagent" in names else DelegationAccess.NONE,
        workspace_scope=workspace_scope,
    )
    return OpenCodeSourceContext(effective_capabilities=caps)


def target_context(*capabilities: str, workspace_scope: str | None = "workspace") -> CodexTargetContext:
    return CodexTargetContext(
        enforced_capabilities=list(capabilities),
        filesystem=FilesystemAccess.READ_ONLY if any(item.startswith("filesystem.") for item in capabilities) else FilesystemAccess.NONE,
        shell=ShellAccess.ALLOWED if "shell.execute" in capabilities else ShellAccess.NONE,
        network=NetworkAccess.ALLOWED if any(item.startswith("network.") for item in capabilities) else NetworkAccess.NONE,
        delegation=DelegationAccess.ALLOWED if "delegation.invoke" in capabilities else DelegationAccess.NONE,
        workspace_scope=workspace_scope,
    )


def test_path_identity_and_raw_permission_order_are_preserved() -> None:
    parsed = parse_source("opencode-v2", read_fixture("agents/reviewer.md"), agent_relative_path="team/reviewer.md")

    assert parsed.agent.name == "team/reviewer"
    assert parsed.agent.description == "Reviews code without modifying files"
    assert parsed.agent.instructions.strip() == "Review the requested changes. Report only findings supported by the repository."
    assert parsed.agent.model.source_identifier == "openai/gpt-5"
    assert parsed.agent.metadata.original_frontmatter["mode"] == "subagent"
    assert parsed.agent.metadata.original_document == read_fixture("agents/reviewer.md")
    assert parsed.agent.metadata.original_frontmatter["permissions"] == [
        {"action": "shell", "resource": "*", "effect": "ask"},
        {"action": "*", "resource": "*", "effect": "deny"},
    ]
    assert any(item.code == "opencode.source_authority_derived" for item in parsed.diagnostics)


@pytest.mark.parametrize("path", ["C:/reviewer.md", "../reviewer.md", "/reviewer.md", "team\\reviewer.md", "team/\x01.md"])
def test_rejects_unsafe_or_nonportable_identity_paths(path: str) -> None:
    with pytest.raises(ValueError):
        parse_source("opencode-v2", read_fixture("agents/reviewer.md"), agent_relative_path=path)


def test_requires_identity_context_and_leaves_claude_parse_contract_unchanged() -> None:
    with pytest.raises(ValueError, match="explicit agent-relative path"):
        parse_source("opencode-v2", read_fixture("agents/reviewer.md"))

    from agent_ir.adapters.claude import ClaudeCodeAdapter

    claude = ClaudeCodeAdapter().parse((Path(__file__).parent / "fixtures" / "claude-security-auditor.md").read_text())
    assert claude.agent.name == "security-auditor"


def test_duplicate_frontmatter_key_is_rejected_and_unknown_metadata_is_retained() -> None:
    with pytest.raises(ValueError, match="duplicate key"):
        parse_source("opencode-v2", read_fixture("duplicate-key.md"), agent_relative_path="agent.md")

    parsed = parse_source("opencode-v2", read_fixture("unknown-field.md"), agent_relative_path="agent.md")
    assert parsed.agent.metadata.extensions["future_v2_option"] == {"retained": True}
    assert parsed.agent.metadata.original_frontmatter["future_v2_option"] == {"retained": True}
    assert any(item.code == "opencode.extension_preserved" and item.blocks_emission for item in parsed.diagnostics)


def test_missing_permissions_requires_operator_context_and_context_is_labelled_unverified() -> None:
    parsed = parse_source("opencode-v2", read_fixture("no-permissions.md"), agent_relative_path="reader.md")
    assert any(item.blocks_emission for item in parsed.diagnostics)
    assert not CodexAdapter().render(parsed.agent, target_context()).emitted

    resolved = apply_source_context(parsed, source_context())
    assert not any(item.blocks_emission for item in resolved.diagnostics)
    assert any(item.code == "opencode.source_context_unverified" for item in resolved.diagnostics)


def test_ordered_read_rules_can_convert_under_matching_narrow_context() -> None:
    parsed = parse_source("opencode-v2", read_fixture("read-only.md"), agent_relative_path="reader.md")
    resolved = apply_source_context(parsed, source_context("read", "glob", "grep"))
    target = target_context(
        "filesystem.read_content", "filesystem.list_paths", "filesystem.search_content"
    )

    assert not [item for item in resolved.diagnostics if item.blocks_emission]
    assert not validate_source_target_scope(resolved, target)
    assert CodexAdapter().render(resolved.agent, target).emitted


@pytest.mark.parametrize("name", ["ask.md", "unknown-action.md", "scoped-rule.md", "unknown-field.md", "disabled.md", "primary-default.md", "variant.md"])
def test_hard_source_semantics_cannot_be_overridden_by_context(name: str) -> None:
    parsed = parse_source("opencode-v2", read_fixture(name), agent_relative_path="reviewer.md")
    resolved = apply_source_context(parsed, source_context("read", "glob", "grep", "shell"))
    assert any(item.blocks_emission for item in resolved.diagnostics)


def test_context_cannot_override_local_denial_or_conflicting_scalar_boundary() -> None:
    source = "---\nmode: subagent\npermissions:\n  - {action: read, resource: '*', effect: deny}\n---\nRead nothing.\n"
    parsed = parse_source("opencode-v2", source, agent_relative_path="reviewer.md")
    with pytest.raises(ValueError, match="agent-local denial"):
        apply_source_context(parsed, source_context("read", "glob", "grep"))

    scoped = parse_source("opencode-v2", read_fixture("scoped-rule.md"), agent_relative_path="reviewer.md")
    scoped = apply_source_context(scoped, source_context("read", "glob", "grep"))
    assert any(item.blocks_emission for item in scoped.diagnostics)


def test_source_and_target_workspace_scope_must_match_explicitly() -> None:
    parsed = parse_source("opencode-v2", read_fixture("no-permissions.md"), agent_relative_path="reader.md")
    resolved = apply_source_context(parsed, source_context("read", workspace_scope="/source"))

    assert validate_source_target_scope(resolved, target_context("filesystem.read_content", workspace_scope="/source")) == []
    diagnostics = validate_source_target_scope(
        resolved,
        target_context("filesystem.read_content", workspace_scope="/other"),
    )
    assert diagnostics and diagnostics[0].blocks_emission
    assert validate_source_target_scope(
        resolved,
        target_context("filesystem.read_content", workspace_scope=None),
    )


def test_source_context_is_strict_and_rejects_duplicate_tool_grants() -> None:
    value = source_context("read").effective_capabilities.model_dump(mode="json")
    value["tools"].append(value["tools"][0])
    with pytest.raises(ValidationError, match="unique names"):
        OpenCodeSourceContext.model_validate({"effective_capabilities": value})

    with pytest.raises(ValidationError):
        OpenCodeSourceContext.model_validate({"effective_capabilities": {"filesystem": "none", "extra": True}})


@pytest.mark.parametrize(
    "value",
    [
        {"effective_capabilities": {"tools": [], "tool_policy_mode": "allowlist", "filesystem": "none", "shell": "none", "network": "none", "delegation": "none"}},
        {"effective_capabilities": {
            "tools": [{"name": "read", "state": "allowed", "semantic_capabilities": ["filesystem.read_content"]}],
            "tool_policy_mode": "allowlist", "filesystem": "none", "shell": "none", "network": "none", "delegation": "none", "workspace_scope": None,
        }},
        {"effective_capabilities": {"tools": [], "tool_policy_mode": "allowlist", "filesystem": "none", "shell": "unknown", "network": "none", "delegation": "none", "workspace_scope": None}},
        {"effective_capabilities": {
            "tools": [{"name": "read", "state": "unknown", "semantic_capabilities": ["filesystem.read_content"]}],
            "tool_policy_mode": "allowlist", "filesystem": "none", "shell": "none", "network": "none", "delegation": "none", "workspace_scope": None,
        }},
    ],
)
def test_source_context_requires_explicit_dimensions_and_consistent_grants(value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OpenCodeSourceContext.model_validate(value)


@pytest.mark.parametrize(
    "document, code",
    [
        ("---\nmode: [subagent]\npermissions: []\n---\nPrompt\n", None),
        ("---\nmode: subagent\nsteps: 3\npermissions: []\n---\nPrompt\n", "opencode.steps_not_representable"),
        ("---\nmode: subagent\nhooks: {before: []}\npermissions: []\n---\nPrompt\n", "opencode.lifecycle_unsupported"),
    ],
)
def test_malformed_mode_and_unrepresentable_lifecycle_or_steps(document: str, code: str | None) -> None:
    if code is None:
        with pytest.raises(ValueError, match="`mode` must be"):
            parse_source("opencode-v2", document, agent_relative_path="agent.md")
    else:
        parsed = parse_source("opencode-v2", document, agent_relative_path="agent.md")
        assert any(item.code == code and item.blocks_emission for item in parsed.diagnostics)
