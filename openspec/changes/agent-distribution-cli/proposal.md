## Why

Agent IR currently converts a profile supplied as a local file, but it has no distribution format or installer flow for discovering and selecting reusable agents. A small local-first `agents` CLI makes the IR useful for installing named agents into a harness while retaining conversion diagnostics and safe permission checks.

## What Changes

- Define and validate a versioned `agents.yaml` manifest for a local agent distribution and its relative source profile paths.
- Add `agents list`, `agents inspect`, and `agents add` commands for manifest-backed local distributions.
- Implement Codex as the first install target, with project and user scopes, conversion diagnostics, safe capability checks, no-overwrite behavior by default, and an explicit preview mode.
- Keep remote GitHub sources, other target harnesses, automatic discovery from arbitrary directories, and package publishing out of this change.

## Capabilities

### New Capabilities
- `agent-distribution-cli`: Discover, inspect, preview, and install agents from a local, versioned distribution manifest.

### Modified Capabilities

## Impact

- Adds a manifest model, local distribution reader, install-target path resolver, and `agents` console command to the `agent-ir` Python package.
- Adds Codex project/user installation behavior that uses the existing Claude Code parser, Agent IR, Codex renderer, and structured diagnostics.
- Adds local fixtures and CLI/install tests. No runtime dependencies beyond the existing Python package dependencies are expected.
