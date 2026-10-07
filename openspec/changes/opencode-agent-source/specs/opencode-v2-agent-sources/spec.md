# OpenCode V2 Agent Sources Specification

## Purpose
Define how Profile Ferry reads and safely converts OpenCode V2 Markdown agent files through Agent IR.

## ADDED Requirements
### Requirement: Parse V2 Markdown with path-derived identity
The system SHALL accept only OpenCode V2 Markdown agent sources for this harness. It SHALL derive an OpenCode agent identity from an explicit safe path relative to an OpenCode agents directory, preserving nested path components. It SHALL NOT infer identity from document content or a basename when the path context is absent. The system SHALL map the Markdown body to instructions and supported V2 metadata to Agent IR while preserving the original document, frontmatter, ordered permission rules, and unsupported fields.

#### Scenario: Parse a nested V2 Markdown agent
- **WHEN** a valid V2 Markdown source is supplied with agent-relative path `team/reviewer.md`
- **THEN** the parser reports identity `team/reviewer`, maps its description, model, mode, and body, and retains the original document and permission rule order

#### Scenario: Reject missing or malformed source context
- **WHEN** a V2 Markdown source has no agent-relative path, an unsafe path, malformed frontmatter, or duplicate frontmatter keys
- **THEN** parsing reports a blocking diagnostic and does not invent an identity or emit a runnable target

#### Scenario: Preserve unsupported V2 fields
- **WHEN** a V2 source contains fields that Agent IR does not model
- **THEN** the parser preserves them in source metadata and emits structured fidelity or functionality diagnostics without interpreting V1-only fields as V2 semantics

#### Scenario: Report hidden-agent visibility loss
- **WHEN** a V2 source sets `hidden: true`
- **THEN** the parser emits a non-blocking functionality diagnostic explaining that Codex agent files cannot preserve OpenCode's hidden-listing and subagent-catalog behavior

### Requirement: Preserve ordered OpenCode permission semantics
The system SHALL retain each V2 permission rule's order, action, resource, and `allow`, `ask`, or `deny` effect. It SHALL evaluate or summarize rules using OpenCode's last-matching-rule behavior and SHALL distinguish agent-local rules from unknown global, default, plugin, and runtime policy.

#### Scenario: Respect last matching rule
- **WHEN** a source has a broad permission followed by a narrower matching rule
- **THEN** inspection and conversion retain both in order and treat the later matching rule as effective for that request

#### Scenario: Do not treat missing permissions as denial
- **WHEN** a source omits agent-specific permissions or inherits ambient policy
- **THEN** inspection reports effective authority as unknown or inherited and conversion does not infer a restrictive boundary from omission

#### Scenario: Report ask and unrepresentable rules
- **WHEN** a rule has an `ask` effect, unknown action, or resource pattern the safe subset cannot resolve
- **THEN** the system reports the unresolved behavior and blocks runnable output until the rule itself is interpreted by supported semantics; a source-context declaration cannot erase it

### Requirement: Require evidence for safe Codex conversion
The system SHALL require the existing operator-declared Codex target context and SHALL require `--opencode-context <file>` unless agent-local ordered rules independently prove a restrictive ceiling. The source context SHALL contain an `effective_capabilities` object using the strict existing `Capabilities` fields: explicit `tool_policy_mode`, `tools`, `filesystem`, `shell`, `network`, `delegation`, and `workspace_scope`. `tool_policy_mode` SHALL be `allowlist`; `tools` SHALL be an explicit list with no `unknown` grants; access enums SHALL not be `unknown`; and `workspace_scope` SHALL be an explicit string or null, with null treated as unknown whenever path-scoped access is granted. A supplied context may narrow known agent-local rules but SHALL NOT override an explicit local denial or known restriction, and SHALL NOT erase an unresolved local `ask`, unknown action, or unrepresentable resource. The CLI SHALL label supplied declarations as unverified; when no source context is needed, it SHALL report the ceiling as derived from agent rules. It SHALL block output when any authority dimension is unknown, the source boundary is ambiguous, source behavior cannot be represented without broadening, or the Codex target is broader than the established source ceiling. The standalone CLI SHALL allow an explicit empty target capability set through `--codex-no-capabilities`, and SHALL treat omitted target capabilities as unknown. Path-scoped filesystem or shell access SHALL be emitted only when the source declaration and target `workspace_scope` are both explicit and equal; standalone conversion SHALL accept the target scope through `--codex-workspace-scope`.

#### Scenario: Convert a provably restricted source
- **WHEN** the selected agent's final agent-local rules prove a restrictive authority ceiling without unresolved rules and the Codex target context is no broader
- **THEN** the existing Codex renderer may emit a target with structured diagnostics, reporting the source ceiling as derived from agent rules and the target context as operator-declared and unverified

#### Scenario: Use a source context to narrow known rules
- **WHEN** an operator supplies a complete strict source context that is no broader than known agent-local restrictions and contains no unresolved `ask`, unknown action, or unrepresentable resource
- **THEN** conversion may use that narrower source ceiling and reports it as operator-declared and unverified

#### Scenario: Block conversion when source context is absent
- **WHEN** global/default/runtime policy may affect the source boundary and no complete OpenCode source context is supplied
- **THEN** conversion is blocked and no target file is written

#### Scenario: Block a broader target
- **WHEN** the Codex context grants a capability beyond the established OpenCode source ceiling
- **THEN** conversion is blocked and no target file is written

#### Scenario: Require matching explicit workspace scopes
- **WHEN** a source context grants path-scoped filesystem or shell access and the target scope is missing or differs from the source scope
- **THEN** standalone conversion and distribution add block output and write no target file

#### Scenario: Declare an empty target boundary
- **WHEN** a source's final catch-all deny proves zero authority and the operator explicitly declares an empty Codex target capability set
- **THEN** standalone conversion may emit while an omitted target capability set remains unknown and blocks output

### Requirement: Preserve identity and install safeguards
The system SHALL pass an explicit OpenCode identity path through standalone conversion and local or public GitHub distribution workflows. In a distribution manifest, `source.path` SHALL remain the contained path used to read the Markdown file, while the OpenCode-only required `source.agent_relative_path` SHALL carry the path relative to an OpenCode agents directory. The system SHALL NOT guess an identity by stripping a directory prefix from `source.path`. It SHALL retain existing distribution containment checks and Codex destination filename validation. It SHALL NOT flatten nested OpenCode identities to create a Codex filename.

#### Scenario: Refuse nested identity at Codex install
- **WHEN** a nested OpenCode identity such as `team/reviewer` is selected for Codex installation
- **THEN** the existing safe filename validation refuses the install without flattening the ID or writing a destination

#### Scenario: Keep read path distinct from identity path
- **WHEN** a manifest entry reads `agents/reviewer.md` and declares `agent_relative_path: reviewer.md`
- **THEN** the CLI reads the contained `source.path` and derives identity `reviewer` only from `agent_relative_path`
