# Agent IR and Profile Ferry

An experimental, internal Python package for converting custom agent definitions through a typed intermediate representation. It is not a proposed universal agent specification.

This slice implements Claude Code and OpenCode V2 Markdown source adapters and a Codex custom-agent TOML target adapter. The adapters preserve prompt and source metadata, and conversion diagnostics distinguish lost functionality from changes to authority.

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

The `profileferry` command can list, inspect, preview, and install an agent from a local or public GitHub distribution. The `agents` command remains as a compatibility alias. A distribution has an `agents.yaml` manifest with stable IDs and relative source paths. It accepts Claude Code or OpenCode V2 Markdown sources and installs Codex standalone agent TOML files:

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
profileferry list ./my-agents
profileferry inspect ./my-agents security-auditor
profileferry add ./my-agents security-auditor --to codex --scope project \
  --codex-context ./codex-context.json --dry-run
profileferry add ./my-agents security-auditor --to codex --scope project \
  --codex-context ./codex-context.json
profileferry list github:OWNER/REPO@main
profileferry add github:OWNER/REPO@main security-auditor --to codex --scope user \
  --codex-context ./codex-context.json --dry-run
```

OpenCode V2 agent identity comes from the path relative to an OpenCode agents directory, while `source.path` remains the contained file path within the distribution. Manifests therefore require a separate `source.agent_relative_path` for OpenCode entries:

```yaml
agents:
  - id: code-reviewer
    source:
      harness: opencode-v2
      path: agents/team/reviewer.md
      agent_relative_path: team/reviewer.md
```

Standalone conversion uses `--from opencode-v2 --source-agent-path team/reviewer.md`. The adapter reads V2 Markdown frontmatter and body as data, preserves the original document and ordered permission rules, and retains unknown fields with blocking diagnostics. It supports the documented description, model, mode, and permissions fields, but blocks features Codex cannot preserve, including primary/all modes, disabled agents, step limits, lifecycle behavior, model variants, and resource-specific permission patterns. `hidden: true` emits a non-blocking diagnostic because Codex agent files cannot preserve OpenCode's hidden-listing and subagent-catalog behavior. A nested OpenCode identity is preserved; installation refuses it when it cannot be represented by Codex's safe single-file agent name.

OpenCode's effective permissions can depend on global rules and runtime context. Inspection does not claim that agent-local rules are the complete policy. Conversion therefore requires either a final agent-local `action: "*"`, `resource: "*"`, `effect: deny` rule that establishes zero authority, or an explicit source context supplied with `--opencode-context`. That JSON must contain a complete, strict `effective_capabilities` object using supported OpenCode action names and consistent Agent IR dimensions; it is an operator declaration, not independently verified evidence. Known local denials cannot be overridden by the context. Ask rules, unknown actions, and scoped resource rules remain blockers because a broad declaration cannot prove their narrower semantics.

For example, an operator who has verified that the active OpenCode policy permits only read, glob, and grep within `/workspace` can supply:

```json
{
  "effective_capabilities": {
    "tools": [
      {"name": "read", "state": "allowed", "semantic_capabilities": ["filesystem.read_content"]},
      {"name": "glob", "state": "allowed", "semantic_capabilities": ["filesystem.list_paths"]},
      {"name": "grep", "state": "allowed", "semantic_capabilities": ["filesystem.search_content"]}
    ],
    "tool_policy_mode": "allowlist",
    "filesystem": "read-only",
    "shell": "none",
    "network": "none",
    "delegation": "none",
    "workspace_scope": "/workspace"
  }
}
```

OpenCode path-scoped filesystem or shell access is emitted only when source and target contexts provide the same explicit `workspace_scope`. For standalone conversions, `--codex-workspace-scope` supplies the target scope. Use `--codex-no-capabilities` to declare an explicitly empty target tool boundary; omitting both it and `--codex-capability` leaves that boundary unknown. OpenCode-derived zero authority can only convert when the Codex context is explicitly no broader. For example, a final catch-all deny can be converted with `--codex-no-capabilities` and all four Codex access dimensions set to `none`.

```sh
agent-ir convert path/to/zero-authority.md --from opencode-v2 \
  --source-agent-path reviewer.md \
  --codex-no-capabilities \
  --codex-filesystem none --codex-shell none \
  --codex-network none --codex-delegation none \
  --output /tmp/reviewer.toml
```

The package is named `profileferry` and provides the matching command, so once it is published the CLI can run ephemerally as `uvx profileferry <command>`. It is not published to PyPI yet. For development, use `uv run profileferry <command>`.

The context JSON must validate as `CodexTargetContext` and describe the effective Codex capability boundary enforced outside the generated agent file. The CLI cannot verify that policy; it labels this input as operator-declared and unverified. The Codex renderer blocks output when it cannot prove that the effective target is no broader than the source. Project installs go to `.codex/agents/`; user installs go to `$CODEX_HOME/agents/` or `~/.codex/agents/`. Existing files are preserved unless `--force` is supplied. Local distribution files are treated as data: commands do not execute scripts, import modules, install dependencies, or access the network.

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

GitHub distribution locators use `github:OWNER/REPO@REF`. Mutable refs are resolved to a full commit SHA before downloading; CLI output shows the requested ref, resolved SHA, and whether the immutable cache was used. You can pin a full SHA directly. Full-SHA cache hits work offline. Set `PROFILEFERRY_CACHE_DIR` to change the cache location; the legacy `AGENT_IR_CACHE_DIR` setting remains supported. By default the cache uses `$XDG_CACHE_HOME/profileferry/distributions` or `~/.cache/profileferry/distributions`.

Remote support currently accepts public GitHub repositories only and does not use credentials. Archives are size-limited and extracted as data; traversal, symlinks, hard links, special files, and ambiguous paths are rejected. This protects extraction and repeatability, but a commit pin does not establish that an upstream agent is trustworthy. Private repositories, other Git hosts, submodules, automatic updates, and cache cleanup commands are not supported yet.

## Publishing

The package is configured for PyPI Trusted Publishing from GitHub Actions. The release workflow builds and checks the package in one job, then publishes only the built artifacts in a separate OIDC-enabled job using the GitHub `pypi` environment. No PyPI token is stored in repository secrets. To publish a release, first merge the workflow to the default branch, configure a PyPI Trusted Publisher for `luluthehungrycat/profileferry` with workflow `.github/workflows/publish.yml` and environment `pypi`, then publish a GitHub Release. The first PyPI upload has not been made yet.
