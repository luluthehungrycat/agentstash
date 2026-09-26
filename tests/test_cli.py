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
