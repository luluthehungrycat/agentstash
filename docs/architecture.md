# Agent IR architecture

## Why an IR

Harness-specific formats encode overlapping intent with different syntax and different security guarantees. A typed internal representation allows one parser per source and one renderer per target rather than maintaining a converter for every pair. It is an implementation detail of this project, not a universal standard.

```text
Harness definition → Source adapter → Agent IR → Target adapter → Harness definition
       Claude Code ────────────────────────────────→ Codex (first slice)
```

## What belongs where

- **IR models:** versioned identity and instructions; semantic tool, filesystem, shell, network, delegation, model, execution, and lifecycle intent; provenance and explicit extensions.
- **Source adapters:** frontmatter/document parsing and interpretation of source-specific permission semantics. Preserve unrecognized source fields rather than silently discarding them. Tool names are mapped to granular capability intents (for example, content reads, path listing, content search, file creation, and file modification), not copied as if names were portable.
- **Target adapters:** target syntax, fields the target can enforce, capability checks, and diagnostics for missing or narrower behavior.
- **Registry:** adapter lookup and orchestration; target/source conditionals do not belong in the IR model.

Pydantic v2 models provide runtime validation, serialization, and JSON Schema generation. The explicit IR version supports future schema evolution. Original source frontmatter and source text are retained as provenance to support a future same-harness round trip.

## Diagnostics and authority

Diagnostics are machine-readable and include a status (`LOSSLESS`, `MAPPED`, `APPROXIMATED`, `UNSUPPORTED`, or `DROPPED`), a category, field path, authority effect, message, and emission-blocking flag. Functionality loss is separate from authority change. Safe narrowing can be emitted with a diagnostic; unknown or increased authority blocks runnable output. An authority increase is never downgraded to an ordinary fidelity warning.

## Permission mapping

Permissions are semantic capabilities, not tool-name substitutions. The renderer compares the source's effective capability grants with the target runtime's enforced boundary. Codex standalone agent TOML has no arbitrary per-agent tool allowlist, so caller-supplied `--codex-capability` values must describe controls actually enforced by the Codex runtime. They are operator-supplied claims the converter cannot independently verify, and they are not controls added by the generated TOML. The CLI labels this boundary input as operator-declared; callers should omit it or use `unknown` when they cannot establish the active policy. Unknown or broader target authority blocks emission.

Codex custom agent TOML accepts supported `ConfigToml` fields, including per-agent `sandbox_mode` and selected feature restrictions. The adapter maps a clear filesystem boundary to `sandbox_mode`, disables the shell feature when absent from an explicit source allowlist, and disables web search when not granted. Codex still has no arbitrary tool allowlist, so MCP tools, plugins, delegation, and other unhandled categories must be assessed against the effective runtime boundary. The CLI may recommend a named `$CODEX_HOME/<name>.config.toml` profile as an additional session-wide setting, but it does not attach to one agent. Operators must inspect effective configuration because repository settings and runtime flags can override profile values; strict isolation needs a separately constrained execution environment.

The first Claude mapping uses granular intents: `Read` → `filesystem.read_content`; `Write` → `filesystem.create_content`; `Edit` → `filesystem.modify_content`; `Glob` → `filesystem.list_paths`; `Grep` → `filesystem.search_content`; `Bash` → `shell.execute`; `WebFetch`/`WebSearch` → `network.fetch`/`network.search`; and `Task`/`Agent` → `delegation.invoke`. Unknown and MCP tool names remain explicit `tool.invoke:*` or `mcp.invoke:*` capabilities. A Claude `tools` list is an allowlist; deny-only `disallowedTools` and absent tool lists inherit ambient capabilities and therefore remain unknown until resolved. Codex filesystem sandbox settings can safely narrow write access, but they do not replace the runtime tool-boundary check.

Claude model `inherit` maps to the Codex caller/default model with a diagnostic. Claude model aliases such as `sonnet` are not treated as Codex model identifiers and are omitted with a functionality diagnostic. Hooks, max turns, skills, memory, and other unsupported runtime fields remain in source metadata and receive explicit diagnostics when they cannot be rendered.

## Adding another harness

Add a source parser or target renderer implementing the adapter protocol, register it, and provide independent source/target fixtures and tests. Verify the harness's current permission, model, delegation, isolation, filesystem, shell/network, and lifecycle semantics first. Preserve harness-specific fields in extensions where the core has no useful semantic concept.

## Future adapters

Claude Code and Codex are the initial adapters. OpenCode, OMP, Mistral Vibe, and Hermes need separate semantic research before implementation. In particular, Hermes delegation may target built-in delegation, profile-aware delegation plugins, or Kanban/task workflows; it must not be reduced to a generic subagent boolean without preserving those distinctions.
