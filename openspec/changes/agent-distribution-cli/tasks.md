## 1. Distribution Manifest and Safe Reader

- [x] 1.1 Add strict Pydantic v2 models and duplicate-key-safe YAML loading for `agents.yaml`.
- [x] 1.2 Resolve selected source files with traversal, absolute-path, symlink-escape, and regular-file checks.
- [x] 1.3 Add realistic local distribution fixtures and validation tests for valid, malformed, unknown-field, duplicate-ID, missing, and escaping paths.

## 2. Local `agents` CLI

- [x] 2.1 Implement `agents list` and `agents inspect` using the existing Claude source adapter without filesystem writes.
- [x] 2.2 Implement `agents add` for Codex project and user scopes using an operator-supplied `CodexTargetContext` JSON file and existing renderer diagnostics.
- [x] 2.3 Add safe destination resolution, filename validation, dry-run, no-overwrite-by-default, explicit force, and atomic writes.
- [x] 2.4 Register the `agents` console script while preserving the existing `agent-ir` command.

## 3. Verification and Documentation

- [x] 3.1 Add CLI tests for list, inspect, safe install, blocked conversion, dry-run, conflicts, force replacement, and inert distribution handling.
- [x] 3.2 Run the full test suite, type checks, compilation checks, and OpenSpec validation; fix regressions.
- [x] 3.3 Document the manifest and local install workflow, operator context limits, and deferred remote/publishing work.
