# Agent IR

An experimental, internal Python package for converting custom agent definitions through a typed intermediate representation. It is not a proposed universal agent specification.

This first slice implements a Claude Code Markdown source adapter and a Codex custom-agent TOML target adapter. The adapters preserve prompt and source metadata, and conversion diagnostics distinguish lost functionality from changes to authority.

See [plan.md](plan.md) for the accepted implementation plan and [docs/architecture.md](docs/architecture.md) for the design.

## Development

```sh
uv sync --extra dev
uv run pytest
uv run agent-ir schema
uv run agent-ir convert path/to/agent.md \
  --codex-capability filesystem.read_content \
  --codex-filesystem read-only \
  --codex-shell none \
  --codex-network none \
  --codex-delegation none \
  --output /tmp/agent.toml
```

Codex custom-agent files do not encode an arbitrary per-agent tool allowlist, but they can carry supported per-agent sandbox and feature settings. This adapter maps read-only/workspace-write filesystem boundaries to `sandbox_mode`, disables the shell tool when it is absent from an explicit Claude allowlist, and disables Codex web search when Claude search is not allowed. These controls cover only the target features they name. Conversion also accepts an operator description of the effective Codex capability boundary through `--codex-capability` and the filesystem, shell, network, and delegation options. The converter does not inspect or verify the active Codex configuration; its JSON report labels this input as an operator declaration. Only use it after checking the policy actually enforced by the runtime. Omit `--codex-capability` or pass `unknown` for any boundary dimension you cannot establish; unknown or broader target authority blocks output.

The JSON report includes an advisory profile template based on the source filesystem grants. `--codex-profile-name` selects its suggested `$CODEX_HOME/<name>.config.toml` name. A recommended Codex profile applies to the whole CLI session, including subagents; per-agent sandbox and supported feature settings are emitted in the generated agent TOML. Repository config or runtime flags may override profile settings. Treat the profile as a session-level sandbox aid, inspect the effective configuration, and use a separately constrained OS account, container, or VM when strict isolation is required. The converter never writes this recommendation into the generated subagent TOML or installs it into `$CODEX_HOME`.

## Local agent distributions

The `agents` command can list, inspect, preview, and install an agent from a local distribution. A distribution has an `agents.yaml` manifest with stable IDs and relative source paths. The first version accepts Claude Code Markdown sources and installs Codex standalone agent TOML files:

```yaml
schema_version: 1
name: my-agents
version: 1.0.0
description: Reusable local agent profiles
agents:
  - id: security-auditor
    source:
      harness: claude-code
      path: categories/security/security-auditor.md
```

```sh
agents list ./my-agents
agents inspect ./my-agents security-auditor
agents add ./my-agents security-auditor --to codex --scope project \
  --codex-context ./codex-context.json --dry-run
agents add ./my-agents security-auditor --to codex --scope project \
  --codex-context ./codex-context.json
```

The context JSON must validate as `CodexTargetContext` and describe the effective Codex capability boundary enforced outside the generated agent file. The CLI cannot verify that policy; it labels this input as operator-declared and unverified. The Codex renderer blocks output when it cannot prove that the effective target is no broader than the Claude source. Project installs go to `.codex/agents/`; user installs go to `$CODEX_HOME/agents/` or `~/.codex/agents/`. Existing files are preserved unless `--force` is supplied. Local distribution files are treated as data: commands do not execute scripts, import modules, install dependencies, or access the network.

For example, an operator who has verified these effective limits can supply:

```json
{
  "enforced_capabilities": [
    "filesystem.read_content",
    "filesystem.search_content",
    "filesystem.list_paths"
  ],
  "filesystem": "read-only",
  "shell": "none",
  "network": "none",
  "delegation": "none",
  "workspace_scope": "workspace"
}
```

This is a local installer slice, not a published `uvx agents` package. Remote GitHub resolution, source pinning, publishing, updates, and additional harnesses remain deferred.
