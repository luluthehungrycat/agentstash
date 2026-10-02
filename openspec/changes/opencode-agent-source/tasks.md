## 1. V2 Semantics and Independent Fixtures

- [x] 1.1 Record the supported OpenCode V2 Markdown fields, permission precedence, default/inherited behavior, and documented source paths from the official V2 documentation.
- [x] 1.2 Author independent valid and malformed V2 Markdown fixtures, including nested source paths, ordered allow/ask/deny rules, missing permissions, inherited model, unsupported fields, and duplicate frontmatter keys.
- [x] 1.3 Define the context-aware source parsing contract and diagnostic codes without changing Claude Code's `parse(document)` behavior.

## 2. Parser and Agent IR Mapping

- [x] 2.1 Implement strict V2 YAML frontmatter and Markdown body parsing with filename/path-derived identity; block absent, absolute, escaping, malformed, or non-Markdown identity context.
- [x] 2.2 Map supported identity, description, instructions, model, and mode fields into Agent IR and preserve the exact original document, frontmatter, ordered permission rules, and unsupported fields.
- [x] 2.3 Emit structured diagnostics for inherited/unknown models, disabled agents, unsupported lifecycle/delegation/execution fields, and unsupported V1 semantics; block runnable output when omitted behavior can broaden authority.
- [x] 2.4 Add parser tests for valid/malformed frontmatter, path-derived and nested IDs, all mapped fields, unknown-field preservation, rule-order preservation, and Claude parser regression.

## 3. Registry, CLI, and Distribution Integration

- [x] 3.1 Register `opencode-v2` through the context-aware dispatch path while leaving Claude's existing adapter call contract intact.
- [x] 3.2 Add `--source-agent-path` to standalone conversion; add required OpenCode-only `source.agent_relative_path` distinct from contained `source.path`; pass it through local and GitHub distribution list/inspect/add flows.
- [x] 3.3 Extend strict distribution harness validation for OpenCode V2 Markdown while requiring and validating `agent_relative_path` only for OpenCode; retain manifest IDs, source containment, inert reads, and existing GitHub pin/cache behavior.
- [x] 3.4 Test standalone conversion and local/remote list, inspect, and add; verify missing identity context and nested Codex filename identity fail without writes or path flattening.

## 4. Authority and Codex Conversion

- [x] 4.1 Define `--opencode-context` for add and standalone conversion as an operator declaration whose `effective_capabilities` uses existing `Capabilities` fields, requires all authority keys, allowlist tool mode and non-unknown grant/dimension values; it may narrow known source rules but cannot override explicit local denials or resolve ambiguous local rules.
- [x] 4.2 Preserve ordered last-match rules and derive capabilities only for a conservative subset; allow a final local catch-all deny to prove a ceiling without source context, otherwise block missing/inherited/unknown policy, unresolved `ask`, unknown actions, unrepresentable resources, and broader target authority.
- [x] 4.3 Test safe conversion with a provable restrictive source ceiling and no-broader Codex context; test missing context, default allow, inherited/global ambiguity, `ask`, later overrides, wildcard rules, target broadening, and no-write blocking.
- [x] 4.4 Verify disabled agents and unsupported model, lifecycle, delegation, or step limits produce the specified diagnostics or block output when behavior cannot be preserved.

## 5. Documentation and Verification

- [x] 5.1 Document the V2-only source scope, agent-relative identity, source and target context requirements, unverified declarations, permission limitations, diagnostics, and nested-ID install refusal.
- [x] 5.2 Run the full tests, mypy, compilation, and OpenSpec validation; fix regressions and verify all blocked paths leave destinations untouched.
