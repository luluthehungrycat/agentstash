## Why

Agent IR currently provides a Claude Code Markdown → Agent IR → Codex TOML conversion path, but it has no distribution format or installer flow for discovering and selecting reusable agents. AgentStash adds that workflow while retaining conversion diagnostics and safe permission checks. Its distribution sources can be local or public GitHub repositories.

## What Changes

- Define and validate a versioned `agents.yaml` manifest for a local or public GitHub agent distribution and its relative source profile paths.
- Add `agentstash list`, `agentstash inspect`, and `agentstash add` commands for manifest-backed local and public GitHub distributions, retaining `agents` as a compatibility command.
- Implement Claude Code Markdown as the source and Codex as the first target, with project and user scopes, conversion diagnostics, safe capability checks, no-overwrite behavior by default, and an explicit preview mode.
- Add a GitHub release workflow that builds and checks distributions before a Trusted Publishing (OIDC) job; publishing an actual release remains a separate operation.
- Keep additional harness adapters, same-harness round trips, and automatic discovery from arbitrary directories outside this implementation slice.

## Longer-Term Conversion Direction

AgentStash is intended to convert supported custom agents and subagents between harnesses through Agent IR, in either direction where source and target adapters exist. The current Claude Code → IR → Codex path is the first vertical slice, not a limit on the product's harness scope.

Planned adapter research and development includes OpenCode, OMP / oh-my-pi, Pi (including an extension when required), Mistral Vibe CLI, and Hermes Agent. Claude Code target rendering and same-harness round trips should also be considered as adapters mature. OpenClaw is a possible later harness. Antigravity and Copilot CLI need capability discovery first; support depends on whether they provide usable custom-agent or subagent primitives.

When a target lacks a source primitive, its adapter may use an alternate target control when it faithfully preserves the relevant behavior and does not broaden authority. If it cannot preserve the behavior, it should omit it with a structured functionality-loss diagnostic. If it cannot establish a safe authority subset, it must block runnable output. Adapter claims should be verified against each harness's actual behavior before support is treated as mature.

## Capabilities

### New Capabilities
- `agent-distribution-cli`: Discover, inspect, preview, and install agents from a local, versioned distribution manifest.

### Modified Capabilities

## Impact

- Adds a manifest model, local distribution reader, install-target path resolver, and `agents` console command to the `agent-ir` Python package.
- Adds Codex project/user installation behavior that uses the existing Claude Code parser, Agent IR, Codex renderer, and structured diagnostics.
- Adds local fixtures and CLI/install tests. No runtime dependencies beyond the existing Python package dependencies are expected.
