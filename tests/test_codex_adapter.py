from pathlib import Path
import tomllib

from agent_ir.adapters.claude import ClaudeCodeAdapter
from agent_ir.adapters.codex import CodexAdapter
from agent_ir.diagnostics import AuthorityEffect, DiagnosticCategory, MappingStatus
from agent_ir.models import (
    CodexTargetContext,
    DelegationAccess,
    FilesystemAccess,
    NetworkAccess,
    ShellAccess,
)

FIXTURES = Path(__file__).parent / "fixtures"


def context(
    tools: list[str],
    *,
    filesystem: FilesystemAccess = FilesystemAccess.READ_ONLY,
    shell: ShellAccess = ShellAccess.NONE,
    network: NetworkAccess = NetworkAccess.NONE,
    delegation: DelegationAccess = DelegationAccess.NONE,
) -> CodexTargetContext:
    return CodexTargetContext(
        enforced_capabilities=tools,
        filesystem=filesystem,
        shell=shell,
        network=network,
        delegation=delegation,
        workspace_scope="workspace",
    )


def test_real_security_auditor_renders_codex_toml_against_reference_fixture() -> None:
    source = (FIXTURES / "claude-security-auditor.md").read_text(encoding="utf-8")
    reference = tomllib.loads((FIXTURES / "codex-security-auditor.toml").read_text(encoding="utf-8"))
    parsed = ClaudeCodeAdapter().parse(source)
    result = CodexAdapter().render(parsed.agent, context(["filesystem.read_content", "filesystem.search_content", "filesystem.list_paths"]))

    assert result.emitted
    actual = tomllib.loads(result.target_text or "")
    assert actual["name"] == reference["name"] == "security-auditor"
    assert actual["description"] == reference["description"]
    assert actual["sandbox_mode"] == reference["sandbox_mode"] == "read-only"
    assert actual["developer_instructions"] == parsed.agent.instructions
    assert actual["developer_instructions"] == reference["developer_instructions"]
    assert all(not item.blocks_emission for item in result.diagnostics)


def test_unknown_codex_tool_boundary_blocks_emission() -> None:
    agent = ClaudeCodeAdapter().parse("---\nname: reviewer\ntools: Read\n---\nReview.\n").agent
    result = CodexAdapter().render(agent)

    assert not result.emitted
    diagnostic = next(item for item in result.diagnostics if item.code == "codex.tool_boundary_unknown")
    assert diagnostic.category == DiagnosticCategory.AUTHORITY
    assert diagnostic.authority_effect == AuthorityEffect.UNKNOWN
    assert diagnostic.blocks_emission


def test_inherited_claude_tool_pool_cannot_be_proven_safe() -> None:
    agent = ClaudeCodeAdapter().parse("---\nname: inherited\n---\nDo work.\n").agent
    result = CodexAdapter().render(agent, context([]))

    assert not result.emitted
    assert any(item.code == "source.tool_boundary_unknown" and item.blocks_emission for item in result.diagnostics)


def test_extra_enforced_target_tool_is_authority_increase_and_blocks() -> None:
    agent = ClaudeCodeAdapter().parse("---\nname: reviewer\ntools: Read\n---\nReview.\n").agent
    result = CodexAdapter().render(agent, context(["filesystem.read_content", "shell.execute"]))

    assert not result.emitted
    diagnostic = next(item for item in result.diagnostics if item.code == "codex.tool_authority_increase")
    assert diagnostic.category == DiagnosticCategory.AUTHORITY
    assert diagnostic.authority_effect == AuthorityEffect.INCREASED
    assert diagnostic.status == MappingStatus.UNSUPPORTED
    assert "shell.execute" in diagnostic.details["extra_target_capabilities"]


def test_safe_narrowing_emits_with_functionality_diagnostic() -> None:
    agent = ClaudeCodeAdapter().parse("---\nname: researcher\ntools: Read, Bash\n---\nResearch.\n").agent
    result = CodexAdapter().render(agent, context(["filesystem.read_content"], shell=ShellAccess.NONE))

    assert result.emitted
    diagnostic = next(item for item in result.diagnostics if item.code == "codex.shell_safely_narrowed")
    assert diagnostic.category == DiagnosticCategory.FUNCTIONALITY
    assert diagnostic.authority_effect == AuthorityEffect.NARROWED
    assert diagnostic.status == MappingStatus.APPROXIMATED
    assert any(item.code == "codex.tool_capabilities_safely_narrowed" for item in result.diagnostics)
    assert tomllib.loads(result.target_text or "")["sandbox_mode"] == "read-only"


def test_explicitly_broader_network_context_blocks_emission() -> None:
    agent = ClaudeCodeAdapter().parse("---\nname: reviewer\ntools: Read\n---\nReview.\n").agent
    result = CodexAdapter().render(
        agent,
        context(["filesystem.read_content"], network=NetworkAccess.ALLOWED),
    )

    assert not result.emitted
    assert any(item.category == DiagnosticCategory.AUTHORITY and item.blocks_emission for item in result.diagnostics)


def test_unmapped_hooks_are_functionality_loss_not_authority_increase() -> None:
    agent = ClaudeCodeAdapter().parse(
        "---\nname: reviewer\ntools: Read\nhooks:\n  PreToolUse: []\n---\nReview.\n"
    ).agent
    result = CodexAdapter().render(agent, context(["filesystem.read_content"]))

    assert result.emitted
    diagnostic = next(item for item in result.diagnostics if item.code == "codex.unsupported_hooks")
    assert diagnostic.status == MappingStatus.UNSUPPORTED
    assert diagnostic.category == DiagnosticCategory.FUNCTIONALITY
    assert diagnostic.authority_effect == AuthorityEffect.NOT_APPLICABLE
    assert not diagnostic.blocks_emission


def test_foreign_model_identifier_is_not_invented_as_codex_model() -> None:
    agent = ClaudeCodeAdapter().parse(
        "---\nname: reviewer\ntools: Read\nmodel: sonnet\n---\nReview.\n"
    ).agent
    result = CodexAdapter().render(agent, context(["filesystem.read_content"]))

    assert result.emitted
    target = tomllib.loads(result.target_text or "")
    assert "model" not in target
    diagnostic = next(item for item in result.diagnostics if item.code == "codex.foreign_model_not_copied")
    assert diagnostic.category == DiagnosticCategory.FUNCTIONALITY
    assert diagnostic.authority_effect == AuthorityEffect.NOT_APPLICABLE


def test_toml_renderer_preserves_multiline_prompt_delimiters() -> None:
    prompt = "Line one\ncontains ''' and \"\"\" delimiters\nlast line\n"
    agent = ClaudeCodeAdapter().parse(
        "---\nname: exact\ntools: Read\n---\n" + prompt
    ).agent
    result = CodexAdapter().render(agent, context(["filesystem.read_content"]))

    assert result.emitted
    assert tomllib.loads(result.target_text or "")["developer_instructions"] == prompt
