import json
from pathlib import Path
import tomllib

from agent_ir.agents_cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "distribution"
CONTEXT = {
    "enforced_capabilities": [
        "filesystem.read_content",
        "filesystem.search_content",
        "filesystem.list_paths",
    ],
    "filesystem": "read-only",
    "shell": "none",
    "network": "none",
    "delegation": "none",
    "workspace_scope": "workspace",
}


def _context(tmp_path: Path, value: dict[str, object] | None = None) -> Path:
    context_file = tmp_path / "codex-context.json"
    context_file.write_text(json.dumps(value or CONTEXT), encoding="utf-8")
    return context_file


def test_list_and_inspect_are_read_only(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("sys.argv", ["agents", "list", str(FIXTURE)])
    assert main() == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["agents"][0]["id"] == "security-auditor"

    monkeypatch.setattr("sys.argv", ["agents", "inspect", str(FIXTURE), "security-auditor"])
    assert main() == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["agent"]["name"] == "security-auditor"
    assert detail["capabilities"]["tool_policy_mode"] == "allowlist"
    assert list(tmp_path.iterdir()) == []


def test_inspect_unknown_agent_fails_without_writing(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("sys.argv", ["agents", "inspect", str(FIXTURE), "unknown"])
    assert main() == 2
    assert "not present" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_add_dry_run_reports_destination_without_creating_dirs(monkeypatch, capsys, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        ["agents", "add", str(FIXTURE), "security-auditor", "--to", "codex", "--scope", "project",
         "--project-root", str(project), "--codex-context", str(_context(tmp_path)), "--dry-run"],
    )

    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["emitted"] and report["dry_run"]
    assert "not independently verified" in report["codex_boundary_input"]
    assert report["destination"].endswith(".codex/agents/security-auditor.toml")
    assert not (project / ".codex").exists()


def test_add_installs_codex_toml_and_refuses_overwrite_by_default(monkeypatch, capsys, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    context_file = _context(tmp_path)
    argv = ["agents", "add", str(FIXTURE), "security-auditor", "--to", "codex", "--scope", "project",
            "--project-root", str(project), "--codex-context", str(context_file)]
    monkeypatch.setattr("sys.argv", argv)

    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    target = Path(report["destination"])
    installed = tomllib.loads(target.read_text(encoding="utf-8"))
    assert installed["name"] == "security-auditor"
    assert installed["sandbox_mode"] == "read-only"
    before = target.read_text(encoding="utf-8")

    assert main() == 2
    conflict = json.loads(capsys.readouterr().out)
    assert "already exists" in conflict["error"]
    assert target.read_text(encoding="utf-8") == before

    monkeypatch.setattr("sys.argv", [*argv, "--force"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["installed"]


def test_add_blocks_broader_authority_without_creating_destination(monkeypatch, capsys, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    unsafe = dict(CONTEXT, enforced_capabilities=[*CONTEXT["enforced_capabilities"], "shell.execute"])
    monkeypatch.setattr(
        "sys.argv",
        ["agents", "add", str(FIXTURE), "security-auditor", "--to", "codex", "--scope", "project",
         "--project-root", str(project), "--codex-context", str(_context(tmp_path, unsafe))],
    )

    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["emitted"]
    assert not (project / ".codex").exists()


def test_add_user_scope_uses_codex_home(monkeypatch, capsys, tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(
        "sys.argv",
        ["agents", "add", str(FIXTURE), "security-auditor", "--to", "codex", "--scope", "user",
         "--codex-context", str(_context(tmp_path))],
    )

    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert Path(report["destination"]).is_relative_to(codex_home)
    assert Path(report["destination"]).exists()


def test_distribution_neighbor_code_is_never_executed(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        ["agents", "add", str(FIXTURE), "security-auditor", "--to", "codex", "--scope", "project",
         "--project-root", str(project), "--codex-context", str(_context(tmp_path))],
    )

    assert main() == 0
    assert not (tmp_path / "marker").exists()
