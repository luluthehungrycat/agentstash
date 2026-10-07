"""Local distribution discovery and safe Codex agent installation CLI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from pydantic import ValidationError

from agent_ir.adapters.codex import CodexAdapter
from agent_ir.adapters.opencode_v2 import OpenCodeSourceContext
from agent_ir.distribution import LocalDistribution
from agent_ir.github_distributions import RemoteSourceInfo, resolve_github_distribution
from agent_ir.models import CodexTargetContext
from agent_ir.registry import apply_source_context, parse_source, validate_source_target_scope


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="profileferry")
    commands = parser.add_subparsers(dest="command", required=True)

    list_command = commands.add_parser("list", help="list agents in a local distribution")
    list_command.add_argument("distribution")
    list_command.set_defaults(handler=_list)

    inspect = commands.add_parser("inspect", help="inspect an agent without installing it")
    inspect.add_argument("distribution")
    inspect.add_argument("agent_id")
    inspect.set_defaults(handler=_inspect)

    add = commands.add_parser("add", help="convert and install an agent locally")
    add.add_argument("distribution")
    add.add_argument("agent_id")
    add.add_argument("--to", choices=["codex"], required=True)
    add.add_argument("--scope", choices=["project", "user"], required=True)
    add.add_argument("--project-root", type=Path, default=Path.cwd())
    add.add_argument("--codex-context", type=Path, required=True)
    add.add_argument(
        "--opencode-context",
        type=Path,
        help="operator-declared OpenCode effective_capabilities JSON when agent rules do not prove a ceiling",
    )
    add.add_argument("--dry-run", action="store_true")
    add.add_argument("--force", action="store_true")
    add.set_defaults(handler=_add)
    return parser


def _load_profile(distribution_path: str, agent_id: str):
    distribution, remote_source = _resolve_distribution(distribution_path)
    item = distribution.get_agent(agent_id)
    parsed = parse_source(
        item.source.harness,
        distribution.read_source(item),
        agent_relative_path=item.source.agent_relative_path,
    )
    return distribution, item, parsed, remote_source


def _resolve_distribution(locator: str) -> tuple[LocalDistribution, RemoteSourceInfo | None]:
    if locator.startswith("github:"):
        resolved = resolve_github_distribution(locator)
        return resolved.distribution, resolved.source
    if "://" in locator or locator.startswith("git@"):
        raise ValueError("only public GitHub distribution locators are supported for remote sources")
    return LocalDistribution.load(Path(locator).expanduser()), None


def _list(args: argparse.Namespace) -> int:
    try:
        distribution, remote_source = _resolve_distribution(args.distribution)
        distribution.validate_sources()
        entries = [
            {
                "id": item.id,
                "harness": item.source.harness,
                "path": item.source.path,
                **({"agent_relative_path": item.source.agent_relative_path} if item.source.agent_relative_path else {}),
            }
            for item in distribution.manifest.agents
        ]
    except (OSError, ValueError, ValidationError) as exc:
        return _error(exc)
    report: dict[str, object] = {
        "distribution": distribution.manifest.name,
        "version": distribution.manifest.version,
        "agents": entries,
    }
    if remote_source is not None:
        report["remote_source"] = remote_source.as_json()
    _print(report)
    return 0


def _inspect(args: argparse.Namespace) -> int:
    try:
        distribution, item, parsed, remote_source = _load_profile(args.distribution, args.agent_id)
    except (OSError, ValueError, ValidationError) as exc:
        return _error(exc)
    agent = parsed.agent
    capabilities = agent.capabilities
    report = {
        "distribution": distribution.manifest.name,
        "id": item.id,
        "source": {
            "harness": item.source.harness,
            "path": item.source.path,
            **({"agent_relative_path": item.source.agent_relative_path} if item.source.agent_relative_path else {}),
        },
        "agent": {"name": agent.name, "description": agent.description},
        "capabilities": {
            "tool_policy_mode": capabilities.tool_policy_mode.value,
            "tools": [
                {
                    "name": grant.name,
                    "state": grant.state.value,
                    "semantic_capabilities": grant.semantic_capabilities,
                }
                for grant in capabilities.tools or []
            ],
            "filesystem": capabilities.filesystem.value,
            "shell": capabilities.shell.value,
            "network": capabilities.network.value,
            "delegation": capabilities.delegation.value,
        },
        "diagnostics": [diagnostic.model_dump(mode="json") for diagnostic in parsed.diagnostics],
    }
    if agent.metadata.harness == "opencode-v2":
        report["opencode"] = {
            "mode": agent.metadata.original_frontmatter.get("mode", "primary"),
            "model": agent.model.model_dump(mode="json"),
            "permissions": agent.metadata.original_frontmatter.get("permissions"),
            "effective_authority": (
                "derived from agent rules"
                if any(item.code == "opencode.source_authority_derived" for item in parsed.diagnostics)
                else "unknown or inherited"
            ),
        }
    if remote_source is not None:
        report["remote_source"] = remote_source.as_json()
    _print(report)
    return 0


def _add(args: argparse.Namespace) -> int:
    try:
        distribution, item, parsed, remote_source = _load_profile(args.distribution, args.agent_id)
        opencode_context = None
        if args.opencode_context is not None:
            opencode_context = OpenCodeSourceContext.model_validate_json(
                args.opencode_context.read_text(encoding="utf-8")
            )
        parsed = apply_source_context(parsed, opencode_context)
        context_text = args.codex_context.read_text(encoding="utf-8")
        context = CodexTargetContext.model_validate_json(context_text)
        result = CodexAdapter().render(parsed.agent, context)
        scope_diagnostics = validate_source_target_scope(parsed, context)
        destination = _destination(args.scope, args.project_root, parsed.agent.name)
        _validate_destination(args.scope, args.project_root, destination)
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        return _error(exc)

    diagnostics = [
        diagnostic.model_dump(mode="json")
        for diagnostic in [*parsed.diagnostics, *scope_diagnostics, *result.diagnostics]
    ]
    parse_blocks = any(item.blocks_emission for item in [*parsed.diagnostics, *scope_diagnostics])
    emitted = result.emitted and not parse_blocks
    report = {
        "distribution": distribution.manifest.name,
        "agent_id": item.id,
        "source": {
            "harness": item.source.harness,
            "path": item.source.path,
            **({"agent_relative_path": item.source.agent_relative_path} if item.source.agent_relative_path else {}),
        },
        "target": args.to,
        "scope": args.scope,
        "destination": destination.as_posix(),
        "codex_boundary_input": "operator-declared; not independently verified by this CLI",
        "emitted": emitted,
        "dry_run": args.dry_run,
        "diagnostics": diagnostics,
    }
    if item.source.harness == "opencode-v2":
        report["opencode_source_boundary_input"] = (
            "operator-declared; not independently verified by this CLI"
            if any(d.code == "opencode.source_context_unverified" for d in parsed.diagnostics)
            else "derived from agent rules"
            if any(d.code == "opencode.source_authority_derived" for d in parsed.diagnostics)
            else "unknown"
        )
    if remote_source is not None:
        report["remote_source"] = remote_source.as_json()
    if not emitted:
        _print(report)
        return 2
    if (destination.exists() or destination.is_symlink()) and not args.force:
        report["error"] = "destination already exists; pass --force to replace it"
        _print(report)
        return 2
    if args.dry_run:
        _print(report)
        return 0
    try:
        _atomic_write(destination, result.target_text or "", force=args.force, create_parents=True)
    except OSError as exc:
        return _error(exc)
    report["installed"] = True
    _print(report)
    return 0


def _destination(scope: str, project_root: Path, agent_name: str) -> Path:
    filename = _safe_filename(agent_name)
    if scope == "project":
        root = project_root.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"project root is not a directory: {root}")
        return root / ".codex" / "agents" / f"{filename}.toml"
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return base / "agents" / f"{filename}.toml"


def _safe_filename(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or name in {".", ".."}:
        raise ValueError(f"agent name is not safe for a destination filename: {name!r}")
    return name


def _validate_destination(scope: str, project_root: Path, destination: Path) -> None:
    if scope != "project":
        return
    root = project_root.expanduser().resolve(strict=True)
    resolved_parent = destination.parent.resolve(strict=False)
    if not resolved_parent.is_relative_to(root):
        raise ValueError("project destination resolves outside the selected project root")


def _atomic_write(destination: Path, contents: str, *, force: bool, create_parents: bool) -> None:
    if create_parents:
        destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
        if force:
            os.replace(temporary_path, destination)
        else:
            # A hard link gives us atomic create-if-absent semantics; a check
            # followed by replace would still race with another installer.
            os.link(temporary_path, destination)
            os.unlink(temporary_path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _error(exc: Exception) -> int:
    _print({"error": str(exc)}, file=sys.stderr)
    return 2


def _print(value: object, *, file=None) -> None:
    print(json.dumps(value, indent=2), file=file or sys.stdout)


def main() -> int:
    args = _parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
