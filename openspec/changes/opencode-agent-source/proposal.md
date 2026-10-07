## Why

AgentStash currently reads Claude Code Markdown distributions and converts them to Codex. OpenCode V2 also defines reusable agents as Markdown files, but its identity comes from the file path and its ordered permission rules depend on the rest of the active OpenCode configuration. Supporting that source format requires preserving its document and rule semantics while refusing conversions whose effective authority cannot be established.

## What Changes

- Add OpenCode V2 Markdown as a source harness for standalone conversion and manifest-backed local or public GitHub distributions.
- Parse Markdown frontmatter and body into Agent IR while retaining the original document, all frontmatter, ordered permission rules, and unsupported fields.
- Derive the OpenCode agent ID from an explicit `source.agent_relative_path` relative to an OpenCode agents directory, separate from the contained distribution `source.path`. Preserve nested IDs and fail when identity context is absent or invalid.
- Support inspection without claiming that source-local permissions describe the effective OpenCode policy.
- Convert through the existing Codex renderer only when the source permission boundary and Codex target context prove a safe subset. Require `--opencode-context` when agent-local rules do not prove the source ceiling; report supplied declarations as unverified and block unknown, broader, or unrepresentable authority. Require explicit equal source and target workspace scopes for path-scoped access, and provide `--codex-no-capabilities` to state an empty standalone target boundary.
- Keep OpenCode V1, JSONC agent definitions, OpenCode as a target, migration, and lifecycle hooks outside this change.

## Capabilities

### New Capabilities
- `opencode-v2-agent-sources`: Parse, inspect, and safely convert OpenCode V2 Markdown agent sources.

### Modified Capabilities
- `agent-distribution-cli`: Accept OpenCode V2 Markdown source entries in list, inspect, and add workflows.
- `remote-agent-distributions`: Preserve existing pinned fetch and safety behavior for OpenCode V2 source entries.

## Impact

- Adds a source adapter and a context-aware adapter dispatch path while preserving the existing `parse(document)` contract for Claude Code callers.
- Extends the distribution source harness allowlist and standalone conversion CLI with the OpenCode V2 source identity context.
- Reuses the current Codex renderer, target context, safe destination naming, and no-overwrite behavior.
- Adds independently authored OpenCode V2 fixtures and parser, CLI, permission, and regression tests.
