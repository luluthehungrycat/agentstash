## Context

The `agent-ir` repository has a validated IR and a Claude Code → Codex converter, but users must currently point the conversion CLI at a single profile and manually handle destination paths. This change adds a versioned distribution manifest and an installer command for local and public GitHub sources. Its implemented conversion path remains Claude Code Markdown → Agent IR → Codex TOML.

The project direction is broader than this slice: Profile Ferry is intended to support conversions between harnesses through source and target adapters, not to stop at Claude Code and Codex. Future adapters should cover OpenCode, OMP / oh-my-pi, Pi (using an extension if necessary), Mistral Vibe CLI, Hermes Agent, and Claude Code target/round-trip behavior. OpenClaw is a possible later addition. Antigravity and Copilot CLI require capability discovery before deciding whether they can be supported.

Adapters own semantic mappings and diagnostics. If a target lacks a source primitive, an adapter may select another target control only when it safely preserves or narrows effective authority. It should report omitted functionality; if the adapter cannot establish a safe capability subset, it must block runnable output. Additional harnesses require verification against real harness behavior before they are treated as supported.

The Codex renderer accepts a `CodexTargetContext` describing the effective runtime boundary. The installer must pass this context through unchanged and must never treat missing or broader authority as a functionality-only warning.

## Goals / Non-Goals

**Goals:**
- Make a local directory or public GitHub repository a validated, named distribution containing selectable agent profiles.
- List and inspect agents without writing files.
- Install a selected agent as Codex TOML into an explicit project or user scope, reusing the current parser, IR, renderer, and diagnostics.
- Offer a preview path, refuse unsafe conversion, and avoid overwriting an existing target by default.

**Implementation-slice boundaries (not product non-goals):**
- This slice implements Claude Code Markdown as a source and Codex TOML as a target; it does not implement the additional adapters or same-harness round trips listed above.
- Other Git hosts, private GitHub repositories, and version-update/lockfile management are not included in this slice.
- The release workflow is prepared, but creating a release and publishing a package are separate operations.

**Other Non-Goals:**
- Installing Codex profiles or changing global Codex configuration. The installer writes only the selected standalone agent file.
- Trusting the distribution's declarations as proof of target runtime enforcement.

## Decisions

### Local manifest is explicit and versioned

Use `agents.yaml` at the distribution root. A strict Pydantic v2 model validates `schema_version`, distribution name/version/description, and a list of agents. Each agent has a stable `id` and a source object containing `harness` and a relative `path`. The first implementation accepts `harness: claude-code` and Markdown files only. Reject duplicate IDs, unknown manifest fields, unsupported schema versions, missing files, absolute paths, and paths that resolve outside the distribution root (including escaping symlinks).

An explicit manifest is preferred over recursively treating every Markdown file as an agent: repositories contain READMEs and other Markdown, and installs need stable identities. Future distributions may add more harness-specific source definitions while retaining the manifest versioning boundary.

### CLI separates read-only commands from writes

Expose the primary `profileferry` console command alongside the existing `agent-ir` command; retain `agents` as a compatibility alias:

- `agents list <distribution>` validates the manifest and lists stable IDs/names.
- `agents inspect <distribution> <id>` parses the source and reports its identity, source harness, and semantic capability summary without writing.
- `agents add <distribution> <id> --to codex --scope project|user --codex-context <file>` converts and installs. `--dry-run` reports diagnostics and the destination without writing; `--force` is required to replace an existing profile.

The Codex context file is JSON produced from the existing `CodexTargetContext` model. It is operator-owned policy input, not part of the distribution. Reports must label it as operator-declared and unverified by the CLI. The renderer remains the authority gate; no output file is created when rendering blocks.

### Resolve Codex destinations by explicit scope

- Project scope writes `<project-root>/.codex/agents/<agent-name>.toml`; `--project-root` defaults to the current directory.
- User scope writes `$CODEX_HOME/agents/<agent-name>.toml`, falling back to `~/.codex/agents/` when `CODEX_HOME` is unset.
- `--scope` is required. Do not infer scope from the source or current path.
- Create parent directories only during a real install. Write via a temporary file in the destination directory and atomically replace it. Existing targets fail unless `--force` is supplied.

### Treat distribution content as data

Read only the manifest and selected source file. Do not execute distribution code, import Python modules from a distribution, load MCP servers, or install dependencies. Resolve every manifest path and verify it remains beneath the distribution root before reading. Local distribution operations do not access the network. Public GitHub sources use bounded HTTPS requests to resolve refs and download archives; validate archive paths and entry types before exposing cached files to the manifest reader.

## Risks / Trade-offs

- [Operator context may not match active Codex policy] → Label it as unverified in CLI output and docs; require it to pass the existing renderer's subset checks; refuse if absent or unknown.
- [Manifest could point outside the distribution through traversal or symlinks] → Resolve and containment-check paths before reading; test traversal and escaping symlink cases.
- [A force install could replace user-edited agent configuration] → Never overwrite by default, clearly report the exact path, and require `--force` for replacement.
- [Codex custom-agent schemas may evolve] → Keep the writer delegated to the existing Codex adapter and validate emitted TOML in tests.

## Migration Plan

No existing config or installed files are migrated. Add the console script and manifest reader, then use temporary-directory fixtures to preview and install a Codex profile. Existing `agent-ir` commands and generated files remain unchanged. Rollback consists of removing the newly installed target file and reverting this Git change.

## Open Questions

- Future harness adapters need verified mappings for each harness's tools, permissions, model controls, delegation, isolation, and lifecycle semantics.
- Antigravity and Copilot CLI first need research into whether they expose custom-agent or subagent definitions.
- The package and primary CLI are named `profileferry`; `agents` and `agent-ir` remain available for compatibility. The release workflow uses PyPI Trusted Publishing, but the first package release has not been published.
