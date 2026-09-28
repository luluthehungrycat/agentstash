## Context

The `agent-ir` repository has a validated IR and a Claude Code → Codex converter, but users must currently point the conversion CLI at a single profile and manually handle destination paths. This change adds a local distribution manifest and a small installer command without adding remote fetching or another harness adapter.

The Codex renderer accepts a `CodexTargetContext` describing the effective runtime boundary. The installer must pass this context through unchanged and must never treat missing or broader authority as a functionality-only warning.

## Goals / Non-Goals

**Goals:**
- Make a local directory a validated, named distribution containing selectable agent profiles.
- List and inspect agents without writing files.
- Install a selected agent as Codex TOML into an explicit project or user scope, reusing the current parser, IR, renderer, and diagnostics.
- Offer a preview path, refuse unsafe conversion, and avoid overwriting an existing target by default.

**Non-Goals:**
- Fetching GitHub or other remote sources, package publishing, or version-update/lockfile management.
- Installing to harnesses other than Codex or parsing source formats other than Claude Code Markdown.
- Installing Codex profiles or changing global Codex configuration. The installer writes only the selected standalone agent file.
- Trusting the distribution's declarations as proof of target runtime enforcement.

## Decisions

### Local manifest is explicit and versioned

Use `agents.yaml` at the distribution root. A strict Pydantic v2 model validates `schema_version`, distribution name/version/description, and a list of agents. Each agent has a stable `id` and a source object containing `harness` and a relative `path`. The first implementation accepts `harness: claude-code` and Markdown files only. Reject duplicate IDs, unknown manifest fields, unsupported schema versions, missing files, absolute paths, and paths that resolve outside the distribution root (including escaping symlinks).

An explicit manifest is preferred over recursively treating every Markdown file as an agent: repositories contain READMEs and other Markdown, and installs need stable identities. Future distributions may add more harness-specific source definitions while retaining the manifest versioning boundary.

### CLI is local-first and separates read-only commands from writes

Expose an `agents` console command alongside the existing `agent-ir` command:

- `agents list <distribution>` validates the manifest and lists stable IDs/names.
- `agents inspect <distribution> <id>` parses the source and reports its identity, source harness, and semantic capability summary without writing.
- `agents add <distribution> <id> --to codex --scope project|user --codex-context <file>` converts and installs. `--dry-run` reports diagnostics and the destination without writing; `--force` is required to replace an existing profile.

The Codex context file is JSON produced from the existing `CodexTargetContext` model. It is operator-owned policy input, not part of the distribution. Reports must label it as operator-declared and unverified by the CLI. The renderer remains the authority gate; no output file is created when rendering blocks.

### Resolve Codex destinations by explicit scope

- Project scope writes `<project-root>/.codex/agents/<agent-name>.toml`; `--project-root` defaults to the current directory.
- User scope writes `$CODEX_HOME/agents/<agent-name>.toml`, falling back to `~/.codex/agents/` when `CODEX_HOME` is unset.
- `--scope` is required. Do not infer scope from the source or current path.
- Create parent directories only during a real install. Write via a temporary file in the destination directory and atomically replace it. Existing targets fail unless `--force` is supplied.

### Keep distribution reading inert

Read only the manifest and the selected source file. Do not execute distribution code, import Python modules from a distribution, load MCP servers, install dependencies, or access the network. Resolve every manifest path and verify it remains beneath the distribution root before reading.

## Risks / Trade-offs

- [Operator context may not match active Codex policy] → Label it as unverified in CLI output and docs; require it to pass the existing renderer's subset checks; refuse if absent or unknown.
- [Manifest could point outside the distribution through traversal or symlinks] → Resolve and containment-check paths before reading; test traversal and escaping symlink cases.
- [A force install could replace user-edited agent configuration] → Never overwrite by default, clearly report the exact path, and require `--force` for replacement.
- [Codex custom-agent schemas may evolve] → Keep the writer delegated to the existing Codex adapter and validate emitted TOML in tests.

## Migration Plan

No existing config or installed files are migrated. Add the console script and manifest reader, then use temporary-directory fixtures to preview and install a Codex profile. Existing `agent-ir` commands and generated files remain unchanged. Rollback consists of removing the newly installed target file and reverting this Git change.

## Open Questions

- Remote source resolution and immutable commit pinning are deferred to a later change.
- Package naming/publishing for a direct `uvx agents` invocation is deferred; this slice exposes the `agents` executable locally and keeps the existing `agent-ir` distribution name.
