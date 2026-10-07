## 1. GitHub Locator and Safe Fetching

- [x] 1.1 Implement strict `github:OWNER/REPO@REF` parsing and commit SHA resolution through the GitHub API.
- [x] 1.2 Implement bounded HTTPS reads with timeouts, response caps, and an allowlisted redirect handler.
- [x] 1.3 Implement commit-keyed cache paths, cache reuse, staging, manifest validation, and atomic promotion.
- [x] 1.4 Implement bounded tarball extraction that rejects traversal, links, special files, duplicate paths, and limit violations.

## 2. CLI Integration and Documentation

- [x] 2.1 Route existing `agents list`, `inspect`, and `add` operations through local or GitHub distribution resolution.
- [x] 2.2 Report the remote locator, requested ref, resolved SHA, and cache state while preserving existing safety diagnostics.
- [x] 2.3 Document remote syntax, public-only access, cache configuration, pin semantics, and unsupported repository features.
- [x] 2.4 Adopt the `profileferry` distribution and primary command name, preserving `agents` and `agent-ir` entry points.
- [x] 2.5 Add a GitHub release workflow for PyPI Trusted Publishing with an isolated OIDC publish job.

## 3. Verification

- [x] 3.1 Add mocked HTTP and archive tests for ref resolution, cache hits, redirect policy, download bounds, extraction safety, and atomic promotion.
- [x] 3.2 Add CLI regression tests proving local paths remain compatible and remote unsafe conversions never write targets.
- [x] 3.3 Run the full test suite, type checks, compilation, and OpenSpec validation; fix regressions.
