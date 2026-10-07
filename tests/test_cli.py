import json
from pathlib import Path

from agent_ir.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "claude-security-auditor.md"


def test_cli_emits_with_a_matching_enforced_codex_capability_boundary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-ir", "convert", str(FIXTURE),
            "--codex-capability", "filesystem.read_content", "filesystem.search_content", "filesystem.list_paths",
            "--codex-filesystem", "read-only",
            "--codex-shell", "none",
            "--codex-network", "none",
            "--codex-delegation", "none",
        ],
    )

    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["emitted"]
    assert any(item["code"] == "codex.inherited_model_uses_target_default" for item in report["diagnostics"])


def test_cli_never_writes_output_for_authority_increase(monkeypatch, capsys, tmp_path) -> None:
    target = tmp_path / "unsafe.toml"
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-ir", "convert", str(FIXTURE),
            "--codex-capability", "filesystem.read_content", "filesystem.search_content", "filesystem.list_paths", "shell.execute",
            "--codex-filesystem", "read-only",
            "--codex-shell", "none",
            "--codex-network", "none",
            "--codex-delegation", "none",
            "--output", str(target),
        ],
    )

    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["emitted"]
    assert not target.exists()


def test_cli_schema_command_outputs_versioned_schema(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["agent-ir", "schema"])

    assert main() == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "AgentIR"
    assert "version" in schema["properties"]


def test_opencode_cli_can_explicitly_declare_empty_target_boundary(monkeypatch, capsys, tmp_path) -> None:
    source = Path(__file__).parent / "fixtures" / "opencode-v2" / "agents" / "reviewer.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-ir", "convert", str(source), "--from", "opencode-v2",
            "--source-agent-path", "reviewer.md",
            "--codex-no-capabilities",
            "--codex-filesystem", "none", "--codex-shell", "none",
            "--codex-network", "none", "--codex-delegation", "none",
            "--output", str(tmp_path / "reviewer.toml"),
        ],
    )

    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["emitted"]
    assert report["opencode_source_boundary_input"] == "derived from agent rules"
    assert (tmp_path / "reviewer.toml").exists()


def test_opencode_cli_scope_mismatch_never_writes_output(monkeypatch, capsys, tmp_path) -> None:
    source = Path(__file__).parent / "fixtures" / "opencode-v2" / "read-only.md"
    target = tmp_path / "reader.toml"
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-ir", "convert", str(source), "--from", "opencode-v2",
            "--source-agent-path", "reader.md",
            "--opencode-context", str(tmp_path / "source-context.json"),
            "--codex-capability", "filesystem.read_content", "filesystem.list_paths", "filesystem.search_content",
            "--codex-filesystem", "read-only", "--codex-shell", "none",
            "--codex-network", "none", "--codex-delegation", "none",
            "--codex-workspace-scope", "/other", "--output", str(target),
        ],
    )
    (tmp_path / "source-context.json").write_text(
        json.dumps({"effective_capabilities": {
            "tools": [
                {"name": "read", "state": "allowed", "semantic_capabilities": ["filesystem.read_content"]},
                {"name": "glob", "state": "allowed", "semantic_capabilities": ["filesystem.list_paths"]},
                {"name": "grep", "state": "allowed", "semantic_capabilities": ["filesystem.search_content"]},
            ],
            "tool_policy_mode": "allowlist", "filesystem": "read-only", "shell": "none",
            "network": "none", "delegation": "none", "workspace_scope": "/source",
        }}),
        encoding="utf-8",
    )

    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["emitted"]
    assert any(item["code"] == "opencode.workspace_scope_not_proven" for item in report["diagnostics"])
    assert not target.exists()


def test_opencode_hard_source_blocker_gates_renderer_output_and_preserves_existing_file(monkeypatch, capsys, tmp_path) -> None:
    from agent_ir.adapters.codex import CodexAdapter
    from agent_ir.models import CodexTargetContext, DelegationAccess, FilesystemAccess, NetworkAccess, ShellAccess
    from agent_ir.registry import parse_source

    source = Path(__file__).parent / "fixtures" / "opencode-v2" / "disabled.md"
    parsed = parse_source("opencode-v2", source.read_text(encoding="utf-8"), agent_relative_path="disabled.md")
    target_context = CodexTargetContext(
        enforced_capabilities=[], filesystem=FilesystemAccess.NONE, shell=ShellAccess.NONE,
        network=NetworkAccess.NONE, delegation=DelegationAccess.NONE, workspace_scope=None,
    )
    assert CodexAdapter().render(parsed.agent, target_context).emitted
    target = tmp_path / "ask.toml"
    target.write_text("preserve this existing file", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["agent-ir", "convert", str(source), "--from", "opencode-v2", "--source-agent-path", "disabled.md",
         "--codex-no-capabilities",
         "--codex-filesystem", "none", "--codex-shell", "none", "--codex-network", "none",
         "--codex-delegation", "none", "--output", str(target)],
    )

    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["emitted"]
    assert any(item["code"] == "opencode.agent_disabled" for item in report["diagnostics"])
    assert target.read_text(encoding="utf-8") == "preserve this existing file"


def test_opencode_broader_codex_target_never_writes_output(monkeypatch, capsys, tmp_path) -> None:
    source = Path(__file__).parent / "fixtures" / "opencode-v2" / "read-only.md"
    source_context = tmp_path / "opencode-context.json"
    source_context.write_text(json.dumps({"effective_capabilities": {
        "tools": [
            {"name": "read", "state": "allowed", "semantic_capabilities": ["filesystem.read_content"]},
            {"name": "glob", "state": "allowed", "semantic_capabilities": ["filesystem.list_paths"]},
            {"name": "grep", "state": "allowed", "semantic_capabilities": ["filesystem.search_content"]},
        ],
        "tool_policy_mode": "allowlist", "filesystem": "read-only", "shell": "none",
        "network": "none", "delegation": "none", "workspace_scope": "workspace",
    }}), encoding="utf-8")
    target = tmp_path / "unsafe.toml"
    monkeypatch.setattr(
        "sys.argv",
        ["agent-ir", "convert", str(source), "--from", "opencode-v2", "--source-agent-path", "reader.md",
         "--opencode-context", str(source_context),
         "--codex-capability", "filesystem.read_content", "filesystem.list_paths", "filesystem.search_content", "shell.execute",
         "--codex-filesystem", "read-only", "--codex-shell", "allowed", "--codex-network", "none",
         "--codex-delegation", "none", "--codex-workspace-scope", "workspace", "--output", str(target)],
    )

    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["emitted"]
    assert any(item["code"] == "codex.tool_authority_increase" for item in report["diagnostics"])
    assert not target.exists()
