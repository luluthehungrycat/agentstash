## Context

The existing source protocol is `SourceAdapter.parse(document: str) -> ParseResult`. The Claude adapter obtains its name from required YAML frontmatter, so that contract remains unchanged for Claude. OpenCode V2 Markdown does not declare its identity in the document: the ID is derived from the Markdown path under an agents directory, and nested path components are part of the ID. Its body is the system instruction; `description`, `model`, `mode`, and ordered `permissions` are source metadata. Permission rules use `allow`, `ask`, or `deny`, with the last matching rule winning. Agent rules are applied after global rules. The documented V2 base policy allows all actions except its stated approval refinements, so a source file alone cannot generally establish effective authority.

The official V2 references used for this proposal are [Agents](https://opencode.ai/v2/docs/agents) and [Permissions](https://opencode.ai/v2/docs/permissions/). The V2 Markdown format is in scope; JSONC, V1 fields and semantics are not.

## Goals / Non-Goals

**Goals:**
- Parse and inspect OpenCode V2 Markdown without executing or normalizing away source data.
- Keep OpenCode path identity distinct from the distribution manifest's stable ID.
- Preserve permission rule order and make effective-authority uncertainty visible.
- Reuse the existing Codex target renderer and its structured diagnostics for safe conversions.

**Non-Goals:**
- Parse OpenCode V1 agent definitions or JSONC configuration.
- Render Codex or any other harness format back to OpenCode.
- Discover or load OpenCode global/project configuration, runtime approvals, plugins, or model/provider settings.
- Map arbitrary OpenCode permission patterns, lifecycle behavior, or unsupported fields into new Codex features.
- Flatten nested OpenCode IDs into Codex filenames or change the existing safe filename policy.

## Decisions

### Keep the Claude parser contract; add explicit context dispatch for OpenCode

Keep `SourceAdapter.parse(document)` intact. Add a `SourceParseContext` carrying `agent_relative_path`, and a separate context-aware source adapter method, `parse_with_context(document, context)`. Registry dispatch calls the existing method for Claude and the contextual method for OpenCode V2. The standalone `agent-ir convert --from opencode-v2` command requires a new `--source-agent-path` value relative to the OpenCode agents directory (for example, `team/reviewer.md`). An OpenCode distribution entry keeps `source.path` as the contained path to read and requires a separate `source.agent_relative_path` with the identity path; for example, `path: agents/reviewer.md` and `agent_relative_path: reviewer.md`. No directory prefix is inferred. OpenCode V2 parsing requires a non-empty, safe relative Markdown path; it removes only the `.md` suffix and joins nested components with `/` to form the Agent IR name. Missing, absolute, traversing, or non-Markdown paths produce a blocking diagnostic. The parser never invents identity from frontmatter, body text, or a basename. The manifest's stable `id` remains the distribution selection key. `agent_relative_path` is required for `opencode-v2` and forbidden for other harnesses.

### Parse only the V2 Markdown contract and preserve the whole source

Parse one YAML frontmatter mapping delimited by `---` and the remaining body. Reject malformed or duplicate frontmatter keys. Map the body to `AgentIR.instructions`, V2 `description` to `AgentIR.description`, the path-derived ID to `AgentIR.name`, supported `model` values to `ModelRequirement`, and `mode` to explicit source metadata. Preserve the original document and frontmatter, including every ordered `permissions` entry and unknown or unsupported fields, in `SourceMetadata`. Permission rules retain their original order, action, resource, and effect; do not sort, deduplicate, or reduce them to a tool allowlist during parsing.

Preserve unsupported V2 fields with a fidelity diagnostic. Treat fields that can constrain execution, including `steps`, `disabled`, `mode`, model selection, and delegation-related permission rules, as behavior that cannot be silently dropped. Emit structured diagnostics for unknown models, unsupported lifecycle/delegation behavior, disabled agents, and unrepresentable execution controls. Any unsupported field that affects authority or availability blocks runnable output; presentation-only loss may be reported without claiming an authority change. V1-only names such as `permission`, `tools`, `prompt`, `disable`, and `maxSteps` are not interpreted as V2 semantics.

### Require evidence for effective OpenCode authority

`inspect` reports source-local rules and explicitly labels effective permissions as unknown because global configuration, the V2 base policy, plugins, and runtime approvals are not loaded. `agentstash add` and standalone `agent-ir convert --from opencode-v2` require `--opencode-context <file>` unless agent-local rules independently prove a restrictive ceiling. The JSON file contains `effective_capabilities` using the existing `Capabilities` fields: explicit `tool_policy_mode: allowlist`, `tools` (an explicit list, which may be empty), `filesystem`, `shell`, `network`, `delegation`, and `workspace_scope`. The fields and access enums already exist in `models.py`; the context validator must require every key, reject `unknown` access values or `ToolGrant` states, and reject inherited tool policy. `workspace_scope` must be explicit; null is treated as unknown whenever a path-scoped capability is granted. The declaration describes the operator's effective source boundary after relevant policies and the selected agent's ordered rules are resolved; it is labelled operator-declared and unverified. It can narrow a boundary implied by known local rules but can never override an explicit local denial or known restriction. An unresolved local `ask` rule, unknown action, or unrepresentable resource pattern blocks output; a broad context declaration cannot erase that ambiguity. The supported action map intentionally compares coarse capability dimensions: if a source denies `read` but permits `glob`, the adapter may refuse a `glob`-only context because Agent IR and the Codex renderer cannot prove that their filesystem boundary omits read access.

The adapter may derive a source ceiling directly from the Markdown only when the agent-local ordered rules prove it independently of ambient policy (for example, a final catch-all deny with no later allow or ask rule); in this case reports say the source ceiling is `derived from agent rules` and do not claim a source-context declaration was supplied. Otherwise the context is mandatory. The implementation must never treat absent OpenCode permissions as deny: V2 defaults are permissive. Compare the validated source ceiling and the operator-supplied `CodexTargetContext` with the existing renderer. Block when the target can exceed the source, when either boundary is unknown, or when source approval semantics cannot be safely represented. For path-scoped filesystem or shell access, require the source and target `workspace_scope` values to be explicit and equal because the existing Codex renderer does not encode a narrower per-agent path. Standalone conversion exposes `--codex-workspace-scope`; `--codex-no-capabilities` distinguishes an explicitly empty target capability set from an omitted, unknown set. This is a conservative gate, not proof that the operator's declarations match the active OpenCode or Codex runtime.

### Reuse distribution containment and Codex install safeguards

Add `opencode-v2` to the supported manifest `source.harness` values and add its required `source.agent_relative_path` field to the strict schema. Local and remote distribution readers continue resolving `source.path` beneath the distribution root before reading; they separately validate and pass `agent_relative_path` as OpenCode identity context. `agentstash list` lists the manifest ID and source path; `inspect` shows the OpenCode path-derived ID, description, model/mode, ordered rules, preservation diagnostics, and authority unknowns. `add` uses the same Codex renderer, target context, dry-run, and no-overwrite rules as Claude sources, plus `--opencode-context` when the rules do not prove the source ceiling.

Preserve nested IDs such as `team/reviewer` in Agent IR. The existing Codex installer only accepts a flat safe filename, so `agentstash add` refuses nested IDs with the existing safe-name error; it does not flatten them or risk collisions. Standalone conversion may render a safe result to an explicitly selected output path, subject to the same authority gate.

## Risks / Trade-offs

- [OpenCode configuration layers change the effective policy] → Do not infer it from the Markdown alone; require complete source context or prove an agent-local deny ceiling, and label operator context unverified.
- [A rule summary loses order or resource matching behavior] → Preserve every ordered rule and block when its semantics cannot be represented safely.
- [Nested IDs are valid OpenCode identities but unsafe Codex filenames] → Keep the identity and refuse installation rather than flattening it.
- [V2 documentation evolves] → Base parser fixtures on independently authored V2 examples, preserve unknown fields, and require explicit semantic tests before extending the recognized subset.

## Verification Plan

- Validate strict V2 frontmatter, duplicate keys, required path context, nested identity, body/description/model/mode mapping, and preservation of raw document, ordered rules, and unknown fields.
- Exercise absent, inherited, `ask`, wildcard, and last-match permission cases; verify inspection reports unknown effective authority and conversion blocks uncertainty or broadening.
- Prove a safe conversion case with a fully restrictive source boundary and a no-broader operator-declared Codex boundary.
- Exercise list/inspect/add on local and mocked GitHub distributions and verify traversal containment and existing Claude behavior remain unchanged.
- Verify nested IDs are not flattened at the Codex install boundary and that blocked/dry-run conversions do not write.
