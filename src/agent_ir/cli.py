"""Command-line interface for Agent IR conversion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from pydantic import ValidationError

from agent_ir.adapters.codex import CodexAdapter
from agent_ir.models import (
    AgentIR,
    CodexTargetContext,
    DelegationAccess,
    FilesystemAccess,
    NetworkAccess,
    ShellAccess,
)
from agent_ir.registry import SOURCES


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-ir")
    commands = parser.add_subparsers(dest="command", required=True)
    schema = commands.add_parser("schema", help="print the Agent IR JSON Schema")
    schema.set_defaults(handler=_schema)
    convert = commands.add_parser("convert", help="convert Claude Code Markdown to Codex TOML")
    convert.add_argument("source", type=Path)
    convert.add_argument("--from", dest="source_harness", choices=sorted(SOURCES), default="claude-code")
    convert.add_argument("--to", dest="target_harness", choices=["codex"], default="codex")
    convert.add_argument(
        "--codex-capability",
        nargs="*",
        default=None,
        help="operator-declared effective capabilities; the converter does not inspect runtime policy",
    )
    convert.add_argument("--codex-filesystem", choices=[item.value for item in FilesystemAccess], required=True)
    convert.add_argument("--codex-shell", choices=[item.value for item in ShellAccess], required=True)
    convert.add_argument("--codex-network", choices=[item.value for item in NetworkAccess], required=True)
    convert.add_argument("--codex-delegation", choices=[item.value for item in DelegationAccess], required=True)
    convert.add_argument(
        "--codex-profile-name",
        type=_validate_profile_name,
        help="name to recommend for an operator-managed CODEX_HOME/<name>.config.toml profile (advisory only)",
    )
    convert.add_argument("--output", type=Path)
    convert.set_defaults(handler=_convert)
    return parser


def _schema(_: argparse.Namespace) -> int:
    from agent_ir.models import AgentIR

    print(json.dumps(AgentIR.model_json_schema(), indent=2))
    return 0


def _convert(args: argparse.Namespace) -> int:
    try:
        document = args.source.read_text(encoding="utf-8")
        parsed = SOURCES[args.source_harness].parse(document)
        context = CodexTargetContext(
            enforced_capabilities=args.codex_capability,
            filesystem=FilesystemAccess(args.codex_filesystem),
            shell=ShellAccess(args.codex_shell),
            network=NetworkAccess(args.codex_network),
            delegation=DelegationAccess(args.codex_delegation),
            workspace_scope="workspace",
        )
        result = CodexAdapter().render(parsed.agent, context)
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    report = {
        "source": args.source.as_posix(),
        "target": args.target_harness,
        "emitted": result.emitted,
        "codex_boundary_input": (
            "operator-declared; not independently verified by the converter"
            if args.codex_capability is not None
            else "not supplied"
        ),
        "diagnostics": [diagnostic.model_dump(mode="json") for diagnostic in [*parsed.diagnostics, *result.diagnostics]],
        "codex_profile_recommendation": _profile_recommendation(
            parsed.agent,
            args.codex_profile_name,
        ),
    }
    if result.target_text is not None and args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.target_text, encoding="utf-8")
        report["output"] = args.output.as_posix()
    elif result.target_text is not None:
        report["target_text"] = result.target_text
    print(json.dumps(report, indent=2))
    return 0 if result.emitted else 2


def _validate_profile_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise argparse.ArgumentTypeError(
            "profile name must contain only letters, digits, underscores, or hyphens"
        )
    return value


def _profile_recommendation(agent: AgentIR, requested_name: str | None) -> dict[str, object]:
    """Describe session-level sandbox guidance without claiming tool isolation."""
    capabilities = {
        capability
        for grant in (agent.capabilities.tools or [])
        if grant.state.value == "allowed"
        for capability in grant.semantic_capabilities
    }
    has_read = any(
        capability in capabilities
        for capability in (
            "filesystem.read_content",
            "filesystem.list_paths",
            "filesystem.search_content",
        )
    )
    has_write = any(
        capability in capabilities
        for capability in (
            "filesystem.create_content",
            "filesystem.modify_content",
        )
    )
    if has_write:
        sandbox_mode = "workspace-write"
        profile_config = (
            'approval_policy = "on-request"\n'
            'sandbox_mode = "workspace-write"\n\n'
            "[sandbox_workspace_write]\n"
            "network_access = false\n"
        )
    elif has_read:
        sandbox_mode = "read-only"
        profile_config = 'approval_policy = "on-request"\nsandbox_mode = "read-only"\n'
    else:
        sandbox_mode = None
        profile_config = None

    profile_name = requested_name or f"{_profile_slug(agent.name)}-restricted"
    limitations = [
        "The recommended Codex profile applies to the entire CLI session, including subagents. Generated agent TOML can carry per-agent sandbox settings and selected category restrictions, but the profile itself is session-wide.",
        "Codex supports selected per-agent feature restrictions such as disabling the shell tool and web search, but it has no arbitrary per-agent tool allowlist. Other configured tools may remain available.",
        "The profile template is a recommendation, not proof of the effective policy. Repository configuration and runtime flags can override profile settings; inspect the effective configuration before relying on it.",
        "This profile does not isolate credentials or replace a separately constrained operating-system user, container, or VM when strict isolation is required.",
    ]
    if sandbox_mode is None:
        limitations.insert(
            0,
            "No filesystem sandbox template was generated because the source grants do not establish a clear read or workspace-write boundary.",
        )
    return {
        "name": profile_name,
        "config_path": f"$CODEX_HOME/{profile_name}.config.toml",
        "sandbox_mode": sandbox_mode,
        "config_toml": profile_config,
        "invocation": f"codex --profile {profile_name}",
        "scope": "whole Codex CLI session",
        "limitations": limitations,
    }


def _profile_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_")
    return (slug or "agent")[:48]


def main() -> int:
    args = _parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
