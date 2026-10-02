## ADDED Requirements

### Requirement: Validate local agent distribution manifests
The system SHALL read a versioned `agents.yaml` manifest from a local distribution root and SHALL validate its distribution metadata and agent source entries before listing, inspecting, or installing agents. The system SHALL reject duplicate agent IDs, unsupported manifest versions, unknown manifest fields, missing source files, absolute source paths, and source paths that resolve outside the distribution root.

#### Scenario: List a valid local distribution
- **WHEN** a user runs `agents list` against a valid local distribution
- **THEN** the CLI lists each manifest agent by stable ID and source identity without writing files

#### Scenario: Reject an invalid or escaping source path
- **WHEN** a manifest contains a missing, absolute, traversal, or escaping symlink source path
- **THEN** the CLI reports a validation error and does not read a file outside the distribution root

### Requirement: Inspect an agent without side effects
The system SHALL provide an inspection command that parses the selected source profile through its registered source adapter and reports its identity, source harness, and semantic capability summary without writing files or executing distribution content.

#### Scenario: Inspect a manifest agent
- **WHEN** a user runs `agents inspect <distribution> <agent-id>` for a valid Claude Code entry
- **THEN** the CLI reports the source metadata and semantic capability summary without creating or modifying files

#### Scenario: Reject an unknown agent ID
- **WHEN** the requested agent ID is not present in the manifest
- **THEN** the CLI reports that the ID is unavailable and performs no conversion or filesystem writes

### Requirement: Install a converted Codex agent safely
The system SHALL provide `agents add` to convert a selected local source profile through Agent IR and install a Codex standalone-agent TOML file in an explicitly selected `project` or `user` scope. The command SHALL reuse the Codex renderer and its structured diagnostics. It SHALL block installation when rendering cannot establish a safe capability subset, SHALL require an operator-supplied Codex target context, and SHALL report that this context is not independently verified by the CLI.

#### Scenario: Install to project scope
- **WHEN** a valid conversion succeeds and the user selects project scope
- **THEN** the CLI writes `<project-root>/.codex/agents/<name>.toml` and reports the installed path and conversion diagnostics

#### Scenario: Install to user scope
- **WHEN** a valid conversion succeeds and the user selects user scope
- **THEN** the CLI writes `$CODEX_HOME/agents/<name>.toml` or `~/.codex/agents/<name>.toml` when `CODEX_HOME` is unset

#### Scenario: Block an unsafe conversion
- **WHEN** the Codex renderer reports unknown or increased authority
- **THEN** the CLI exits unsuccessfully and creates no target file or destination directories

### Requirement: Preview and protect existing target files
The system SHALL support a dry-run mode that reports the selected source, target scope, destination, and diagnostics without writing. The system SHALL refuse to replace an existing target unless the user supplies an explicit force option.

#### Scenario: Preview an install
- **WHEN** a user runs `agents add` with dry-run enabled
- **THEN** the CLI reports the conversion result and destination without creating directories or files

#### Scenario: Refuse an existing destination by default
- **WHEN** a target file already exists and force replacement was not requested
- **THEN** the CLI preserves the existing file, reports the conflict, and exits unsuccessfully

#### Scenario: Replace an existing destination explicitly
- **WHEN** a target file exists and the user explicitly enables force replacement
- **THEN** the CLI atomically replaces that target with the successfully rendered profile

### Requirement: Keep local distribution operations inert
The system SHALL treat distribution contents as data. It SHALL NOT execute source files, import modules from the distribution, load MCP servers, install package dependencies, or access the network during list, inspect, preview, or local install operations.

#### Scenario: Process a distribution with unrelated executable files
- **WHEN** the distribution contains scripts or modules beside its manifest and profile
- **THEN** list, inspect, preview, and install read only the manifest and selected profile and do not execute or import those files
