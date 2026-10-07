## ADDED Requirements

### Requirement: Apply existing pinned remote safety to OpenCode V2 sources
The system SHALL process a remote OpenCode V2 Markdown source only from the already validated, immutable, bounded GitHub distribution cache. It SHALL read from the containment-checked `source.path`, derive identity only from the required safe `source.agent_relative_path`, and SHALL apply the same OpenCode authority gate and Codex target checks as for local sources.

#### Scenario: Inspect a remote OpenCode V2 entry
- **WHEN** a user inspects a valid OpenCode V2 entry from a public GitHub distribution
- **THEN** the CLI reports the requested ref, resolved commit SHA, source path, and source-local permission data without claiming ambient policy is known

#### Scenario: Block an unsafe remote OpenCode conversion
- **WHEN** source identity, effective authority, or target capability safety cannot be established
- **THEN** conversion is blocked and no Codex installation target is written
