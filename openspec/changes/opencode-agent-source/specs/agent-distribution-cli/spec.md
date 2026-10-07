## ADDED Requirements

### Requirement: Support OpenCode V2 Markdown distribution sources
The system SHALL accept `harness: opencode-v2` entries that reference V2 Markdown files in the existing versioned manifest. Each such entry SHALL include a safe OpenCode-only `source.agent_relative_path` distinct from `source.path`: the latter is the contained path read from the distribution, while the former supplies OpenCode identity relative to an agents directory. The system SHALL retain the manifest's stable ID as the selection key and continue validating source paths beneath the distribution root before reading them.

#### Scenario: List and inspect an OpenCode V2 entry
- **WHEN** a user lists or inspects a valid local distribution containing an OpenCode V2 Markdown entry
- **THEN** the CLI identifies the manifest entry and reports OpenCode V2 source metadata and path-derived identity without writing files or claiming effective permissions are known

#### Scenario: Reject an invalid OpenCode source or identity path
- **WHEN** the manifest source path is missing, non-Markdown, or resolves outside the distribution root, or the required `agent_relative_path` is absent or unsafe
- **THEN** the CLI reports a validation error and does not parse or read a file outside that root

#### Scenario: Require source context for Codex add
- **WHEN** a selected OpenCode source has ambiguous effective authority and the user has not supplied the required OpenCode source context
- **THEN** `profileferry add` blocks conversion and writes no destination
