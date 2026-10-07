## ADDED Requirements

### Requirement: Resolve public GitHub distribution locators to immutable commits
The system SHALL accept `github:OWNER/REPO@REF` as a distribution source for list, inspect, and add. The system SHALL resolve a mutable ref to a full commit SHA before downloading the archive and SHALL fetch archive content by that SHA. The system SHALL report the requested ref and resolved commit SHA. A full commit SHA locator SHALL be usable from cache without network access.

#### Scenario: Resolve a mutable ref
- **WHEN** a user operates on a GitHub locator with a branch or tag ref
- **THEN** the CLI resolves the ref to a full commit SHA, retrieves content by that SHA, and reports both values

#### Scenario: Use a cached full commit offline
- **WHEN** a user supplies a full commit SHA already present in the local cache and network access is unavailable
- **THEN** the CLI validates and uses the cached distribution without making a network request

#### Scenario: Reject an invalid locator or unresolved ref
- **WHEN** a locator is malformed or GitHub cannot resolve its ref to a valid full SHA
- **THEN** the CLI reports an error and does not create or modify a cache entry or install target

### Requirement: Restrict remote access to public GitHub endpoints
The system SHALL use HTTPS for GitHub API and archive requests, SHALL permit redirects only to the documented GitHub API/archive hosts, SHALL bound request duration and response size, and SHALL NOT request or use credentials. Private repositories and arbitrary hosts are unsupported.

#### Scenario: Reject an untrusted redirect
- **WHEN** a GitHub request redirects to a host outside the allowed GitHub API and archive hosts
- **THEN** the request fails before content is downloaded

#### Scenario: Reject a remote locator for another host
- **WHEN** a user supplies a non-GitHub remote locator
- **THEN** the CLI reports that only public GitHub distributions are supported

### Requirement: Extract remote archives as inert, bounded data
The system SHALL extract a GitHub archive into a unique staging directory and SHALL promote it into the commit-keyed cache only after successful validation. The system SHALL reject over-limit archives, path traversal, absolute or platform-ambiguous paths, duplicate output paths, links, special files, and paths outside the archive's single root directory. The system SHALL NOT execute or import repository content.

#### Scenario: Extract a valid distribution archive
- **WHEN** an archive is within configured limits and contains regular files beneath one root directory
- **THEN** the CLI extracts it beneath staging, validates `agents.yaml`, atomically promotes the cache entry, and continues the requested operation

#### Scenario: Reject a malicious archive entry
- **WHEN** an archive contains a traversal path, link, special file, duplicate path, or path outside its root
- **THEN** extraction fails, the staging directory is discarded, no cache entry is promoted, and no install target is written

#### Scenario: Reject an oversized archive
- **WHEN** downloaded or extracted content exceeds a configured limit
- **THEN** processing stops with a clear error and no cache entry is promoted

### Requirement: Cache by immutable GitHub identity
The system SHALL cache remote distributions by owner, repository, and resolved commit SHA beneath the configured cache root. The system SHALL prefer `PROFILEFERRY_CACHE_DIR`, accept `AGENT_IR_CACHE_DIR` as a compatibility setting, and otherwise use the `profileferry/distributions` directory under the XDG cache root or the user's cache directory. Cache hits SHALL be revalidated with the local manifest and source-path checks, and existing cache entries SHALL NOT be overwritten.

#### Scenario: Reuse an existing cache entry
- **WHEN** a valid cache entry exists for the resolved commit
- **THEN** the CLI reuses it without downloading the archive again

#### Scenario: Do not promote invalid content
- **WHEN** archive extraction or manifest validation fails
- **THEN** the final commit-keyed cache path remains absent and temporary content is cleaned up

### Requirement: Preserve local conversion and authority checks for remote agents
The system SHALL pass selected remote Markdown profiles through the same registered source parser, Agent IR, target adapter, and structured diagnostics as local distributions. A remote source SHALL NOT bypass target capability-subset checks or overwrite protections.

#### Scenario: Add a remote profile with a safely narrowed target
- **WHEN** the selected source parses and the Codex renderer proves the target authority is no broader than the source
- **THEN** the existing install flow writes the Codex agent and reports the pinned remote source and conversion diagnostics

#### Scenario: Block a remote profile with unknown or increased authority
- **WHEN** the Codex renderer cannot prove a safe capability subset or detects increased authority
- **THEN** the CLI blocks installation and writes no target profile
