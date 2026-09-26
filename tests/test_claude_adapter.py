from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_ir.adapters.claude import ClaudeCodeAdapter
from agent_ir.models import AgentIR, FilesystemAccess, GrantState, ToolPolicyMode

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_real_claude_profile_and_preserves_round_trip_source() -> None:
    text = (FIXTURES / "claude-security-auditor.md").read_text(encoding="utf-8")
    result = ClaudeCodeAdapter().parse(text)

    assert result.agent.name == "security-auditor"
    assert result.agent.model.source_identifier == "inherit"
    assert result.agent.capabilities.filesystem == FilesystemAccess.READ_ONLY
    assert {tool.name for tool in result.agent.capabilities.tools or []} == {"Read", "Grep", "Glob"}
    assert result.agent.metadata.original_document == text
    assert result.agent.metadata.original_frontmatter["tools"] == "Read, Grep, Glob"
    assert result.agent.instructions.startswith("\nYou are a senior security auditor")


def test_unknown_frontmatter_is_retained_in_extension_and_diagnosed() -> None:
    text = "---\nname: custom\ndescription: test\ncustomPolicy:\n  x: 3\ntools: Read\n---\nPrompt\n"
    result = ClaudeCodeAdapter().parse(text)

    assert result.agent.metadata.extensions == {"customPolicy": {"x": 3}}
    assert result.agent.metadata.original_frontmatter["customPolicy"] == {"x": 3}
    assert result.diagnostics[0].status == "LOSSLESS"
    assert result.diagnostics[0].field_path == "metadata.extensions"


def test_ir_json_round_trip_retains_source_document_and_extensions() -> None:
    text = "---\nname: future\ntools: Read\ncustom: value\n---\nPrompt\n"
    agent = ClaudeCodeAdapter().parse(text).agent

    restored = AgentIR.model_validate_json(agent.model_dump_json())
    assert restored == agent
    assert restored.metadata.original_document == text
    assert restored.metadata.extensions == {"custom": "value"}


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter\n",
        "---\nname: foo\n",
        "---\nname: [broken\n---\nbody\n",
        "---\ndescription: no name\n---\nbody\n",
        "---\nname: foo\ntools: Read, Read\n---\nbody\n",
        "---\nname: foo\nname: bar\n---\nbody\n",
        "---\n? [not, scalar]\n: value\n---\nbody\n",
        "---\n1: non-string-key\nname: foo\n---\nbody\n",
        "---\nname: foo\ntools: Read\ndisallowedTools: Read\n---\nbody\n",
    ],
)
def test_malformed_definitions_fail_closed(text: str) -> None:
    with pytest.raises((ValueError, ValidationError)):
        ClaudeCodeAdapter().parse(text)


def test_agent_ir_rejects_unknown_version_and_duplicate_tools() -> None:
    with pytest.raises(ValidationError):
        AgentIR.model_validate({
            "version": "999",
            "name": "agent",
            "instructions": "prompt",
            "metadata": {"harness": "test"},
        })

    text = "---\nname: foo\ntools: Read, Read\n---\nbody\n"
    with pytest.raises(ValueError, match="unique"):
        ClaudeCodeAdapter().parse(text)


def test_allowlist_tools_have_semantic_capability_labels() -> None:
    result = ClaudeCodeAdapter().parse("---\nname: x\ntools: Read, Bash, WebSearch\n---\np\n")
    grants = {grant.name: grant for grant in result.agent.capabilities.tools or []}

    assert grants["Read"].state == GrantState.ALLOWED
    assert grants["Read"].semantic_capabilities == ["filesystem.read_content"]
    assert grants["Bash"].semantic_capabilities == ["shell.execute"]
    assert grants["WebSearch"].semantic_capabilities == ["network.search"]


def test_deny_only_definition_retains_inherited_unknown_authority() -> None:
    result = ClaudeCodeAdapter().parse("---\nname: restricted\ndisallowedTools: Write, Edit\n---\nPrompt\n")

    assert result.agent.capabilities.tool_policy_mode == ToolPolicyMode.INHERIT_WITH_DENIALS
    assert result.agent.capabilities.filesystem == FilesystemAccess.UNKNOWN
