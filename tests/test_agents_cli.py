import json
from pathlib import Path
import tomllib

from agent_ir.agents_cli import main
from agent_ir.distribution import LocalDistribution
from agent_ir.github_distributions import RemoteSourceInfo, ResolvedRemoteDistribution

FIXTURE = Path(__file__).parent / "fixtures" / "distribution"
OPENCODE_FIXTURE = Path(__file__).parent / "fixtures" / "opencode-v2-distribution"
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


def test_pyproject_exposes_profileferry_and_compatibility_commands() -> None:
    project_file = Path(__file__).parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))

    assert project["project"]["name"] == "profileferry"
    assert project["project"]["scripts"] == {
        "agent-ir": "agent_ir.cli:main",
        "profileferry": "agent_ir.agents_cli:main",
        "agents": "agent_ir.agents_cli:main",
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


def test_remote_cli_reports_resolved_pin_and_uses_existing_codex_gate(monkeypatch, capsys, tmp_path: Path) -> None:
    resolved = ResolvedRemoteDistribution(
        distribution=LocalDistribution.load(FIXTURE),
        source=RemoteSourceInfo(
            owner="example",
            repository="agents",
            requested_ref="main",
            commit_sha="0123456789abcdef0123456789abcdef01234567",
            cache_hit=True,
        ),
    )
    monkeypatch.setattr("agent_ir.agents_cli.resolve_github_distribution", lambda locator: resolved)
    locator = "github:example/agents@main"
    monkeypatch.setattr("sys.argv", ["agents", "list", locator])

    assert main() == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["remote_source"]["commit_sha"] == resolved.source.commit_sha
    assert listing["remote_source"]["cache_hit"]

    monkeypatch.setattr("sys.argv", ["agents", "inspect", locator, "security-auditor"])
    assert main() == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["remote_source"]["commit_sha"] == resolved.source.commit_sha

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        ["agents", "add", locator, "security-auditor", "--to", "codex", "--scope", "project",
         "--project-root", str(project), "--codex-context", str(_context(tmp_path)), "--dry-run"],
    )
    assert main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["remote_source"]["requested_ref"] == "main"
    assert preview["emitted"]
    assert not (project / ".codex").exists()


def test_remote_cli_rejects_non_github_url(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["agents", "list", "https://example.invalid/agents"])

    assert main() == 2
    assert "only public GitHub" in capsys.readouterr().err


def test_remote_add_cannot_bypass_codex_authority_gate(monkeypatch, capsys, tmp_path: Path) -> None:
    resolved = ResolvedRemoteDistribution(
        distribution=LocalDistribution.load(FIXTURE),
        source=RemoteSourceInfo(
            owner="example",
            repository="agents",
            requested_ref="main",
            commit_sha="0123456789abcdef0123456789abcdef01234567",
            cache_hit=True,
        ),
    )
    monkeypatch.setattr("agent_ir.agents_cli.resolve_github_distribution", lambda locator: resolved)
    project = tmp_path / "project"
    project.mkdir()
    unsafe_context = dict(CONTEXT, enforced_capabilities=[*CONTEXT["enforced_capabilities"], "shell.execute"])
    monkeypatch.setattr(
        "sys.argv",
        ["agents", "add", "github:example/agents@main", "security-auditor", "--to", "codex", "--scope", "project",
         "--project-root", str(project), "--codex-context", str(_context(tmp_path, unsafe_context))],
    )

    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["emitted"]
    assert report["remote_source"]["commit_sha"] == resolved.source.commit_sha
    assert not (project / ".codex").exists()


def test_opencode_list_inspect_and_add_keep_path_identity_separate(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("sys.argv", ["profileferry", "list", str(OPENCODE_FIXTURE)])
    assert main() == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["agents"][0]["path"] == "agents/reviewer.md"
    assert listing["agents"][0]["agent_relative_path"] == "reviewer.md"

    monkeypatch.setattr("sys.argv", ["profileferry", "inspect", str(OPENCODE_FIXTURE), "read-only-reviewer"])
    assert main() == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["agent"]["name"] == "reviewer"
    assert inspected["opencode"]["effective_authority"] == "unknown or inherited"

    project = tmp_path / "project"
    project.mkdir()
    codex_context = _context(tmp_path)
    opencode_context = tmp_path / "opencode-context.json"
    opencode_context.write_text(json.dumps({"effective_capabilities": {
        "tools": [
            {"name": "read", "state": "allowed", "semantic_capabilities": ["filesystem.read_content"]},
            {"name": "glob", "state": "allowed", "semantic_capabilities": ["filesystem.list_paths"]},
            {"name": "grep", "state": "allowed", "semantic_capabilities": ["filesystem.search_content"]},
        ],
        "tool_policy_mode": "allowlist", "filesystem": "read-only", "shell": "none",
        "network": "none", "delegation": "none", "workspace_scope": "workspace",
    }}), encoding="utf-8")
    argv = [
        "profileferry", "add", str(OPENCODE_FIXTURE), "read-only-reviewer", "--to", "codex", "--scope", "project",
        "--project-root", str(project), "--codex-context", str(codex_context),
        "--opencode-context", str(opencode_context), "--dry-run",
    ]
    monkeypatch.setattr("sys.argv", argv)
    assert main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["emitted"]
    assert preview["source"]["agent_relative_path"] == "reviewer.md"
    assert not (project / ".codex").exists()

    monkeypatch.setattr("sys.argv", argv[:-1])
    assert main() == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["installed"]
    assert Path(installed["destination"]).exists()


def test_nested_opencode_identity_refuses_install_without_flattening(tmp_path: Path, monkeypatch, capsys) -> None:
    import shutil

    distribution_path = tmp_path / "nested-distribution"
    shutil.copytree(OPENCODE_FIXTURE, distribution_path)
    manifest_path = distribution_path / "agents.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace("agent_relative_path: reviewer.md", "agent_relative_path: team/reviewer.md"),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        ["profileferry", "add", str(distribution_path), "read-only-reviewer", "--to", "codex", "--scope", "project",
         "--project-root", str(project), "--codex-context", str(_context(tmp_path, {
             "enforced_capabilities": [], "filesystem": "none", "shell": "none",
             "network": "none", "delegation": "none", "workspace_scope": None,
         }))],
    )

    assert main() == 2
    assert "destination filename" in capsys.readouterr().err
    assert not (project / ".codex").exists()


def test_opencode_missing_context_blocks_add_without_destination(tmp_path: Path, monkeypatch, capsys) -> None:
    import shutil

    distribution_path = tmp_path / "missing-context-distribution"
    shutil.copytree(OPENCODE_FIXTURE, distribution_path)
    (distribution_path / "agents" / "reviewer.md").write_text(
        "---\nmode: subagent\ndescription: inherits ambient policy\n---\nDo work.\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    codex_context = _context(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["profileferry", "add", str(distribution_path), "read-only-reviewer", "--to", "codex", "--scope", "project",
         "--project-root", str(project), "--codex-context", str(codex_context)],
    )

    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["emitted"]
    assert report["opencode_source_boundary_input"] == "unknown"
    assert not (project / ".codex").exists()


def test_remote_opencode_inspect_and_add_keep_path_identity(monkeypatch, capsys, tmp_path: Path) -> None:
    resolved = ResolvedRemoteDistribution(
        distribution=LocalDistribution.load(OPENCODE_FIXTURE),
        source=RemoteSourceInfo(
            owner="example", repository="opencode-agents", requested_ref="main",
            commit_sha="0123456789abcdef0123456789abcdef01234567", cache_hit=True,
        ),
    )
    monkeypatch.setattr("agent_ir.agents_cli.resolve_github_distribution", lambda locator: resolved)
    locator = "github:example/opencode-agents@main"
    monkeypatch.setattr("sys.argv", ["profileferry", "list", locator])
    assert main() == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["agents"][0]["agent_relative_path"] == "reviewer.md"
    assert listing["remote_source"]["commit_sha"] == resolved.source.commit_sha

    monkeypatch.setattr("sys.argv", ["profileferry", "inspect", locator, "read-only-reviewer"])
    assert main() == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["source"]["agent_relative_path"] == "reviewer.md"
    assert inspected["remote_source"]["commit_sha"] == resolved.source.commit_sha

    project = tmp_path / "project"
    project.mkdir()
    codex_context = _context(tmp_path)
    opencode_context = tmp_path / "remote-opencode-context.json"
    opencode_context.write_text(json.dumps({"effective_capabilities": {
        "tools": [
            {"name": "read", "state": "allowed", "semantic_capabilities": ["filesystem.read_content"]},
            {"name": "glob", "state": "allowed", "semantic_capabilities": ["filesystem.list_paths"]},
            {"name": "grep", "state": "allowed", "semantic_capabilities": ["filesystem.search_content"]},
        ],
        "tool_policy_mode": "allowlist", "filesystem": "read-only", "shell": "none",
        "network": "none", "delegation": "none", "workspace_scope": "workspace",
    }}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["profileferry", "add", locator, "read-only-reviewer", "--to", "codex", "--scope", "project",
         "--project-root", str(project), "--codex-context", str(codex_context),
         "--opencode-context", str(opencode_context), "--dry-run"],
    )
    assert main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["emitted"]
    assert preview["source"]["agent_relative_path"] == "reviewer.md"
    assert preview["remote_source"]["commit_sha"] == resolved.source.commit_sha
    assert not (project / ".codex").exists()

    monkeypatch.setattr(
        "sys.argv",
        ["profileferry", "add", locator, "read-only-reviewer", "--to", "codex", "--scope", "project",
         "--project-root", str(project), "--codex-context", str(codex_context)],
    )
    assert main() == 2
    blocked = json.loads(capsys.readouterr().out)
    assert not blocked["emitted"]
    assert blocked["remote_source"]["commit_sha"] == resolved.source.commit_sha
    assert not (project / ".codex").exists()
