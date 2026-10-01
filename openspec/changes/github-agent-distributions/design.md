## Context

The `agentstash` CLI accepts a local directory and safely validates its `agents.yaml` before reading selected Claude Code Markdown. This change adds a GitHub transport layer while keeping local manifest validation, source adapters, Agent IR, and target rendering as-is.

The remote path is security-sensitive: repositories are untrusted input, the reference may be mutable, archive extraction can escape a cache directory, and a redirect can change the network destination.

## Goals / Non-Goals

**Goals:**
- Accept explicit public GitHub locators in existing list, inspect, and add commands.
- Resolve a branch, tag, or commit reference to a full commit SHA before archive download.
- Cache archives by canonical owner/repository/commit and report the pin used.
- Support offline operation for an already cached full commit SHA.
- Bound network and extraction resource use; extract only regular files and directories beneath a private staging directory.
- Treat all repository content as inert data and reuse the current conversion and permission gate.

**Non-Goals:**
- Private repositories, GitHub credentials, arbitrary Git hosts, Git submodules, Git LFS, package installation, or source-code execution.
- Automatically updating an installed agent or tracking a mutable branch between installs.
- Signing or asserting the trustworthiness of the upstream repository.

## Decisions

### Explicit locator and immutable resolution

Use `github:OWNER/REPO@REF`, requiring an explicit ref. Resolve non-SHA refs with `GET /repos/{owner}/{repo}/commits/{ref}` and validate the returned SHA as 40 lowercase hexadecimal characters. Download the archive by that SHA through GitHub's tarball endpoint, then report the resolved pin. This prevents a mutable ref changing between resolution and content download. A supplied full SHA needs no resolver request and can use a cache hit without network access. The API endpoint and redirect-based tarball endpoint follow GitHub's documented REST behavior ([commit endpoint](https://docs.github.com/en/rest/commits/commits), [repository tarball endpoint](https://docs.github.com/en/rest/repos/contents)).

Alternatives considered: requiring users to supply full SHAs is maximally reproducible but awkward; downloading a branch archive directly can produce unreported mutable content. Resolving once and fetching by SHA balances usability and traceability.

### Cache location and promotion

Use `AGENTSTASH_CACHE_DIR` when set, falling back to the legacy `AGENT_IR_CACHE_DIR`; otherwise use `$XDG_CACHE_HOME/agentstash/distributions` or `~/.cache/agentstash/distributions`. Cache entries live under `github/OWNER/REPO/SHA`. Download and extract into a unique temporary directory below the cache root, validate the manifest, then atomically rename the completed tree into its immutable cache location. Never overwrite an existing cache entry. A cache hit is still validated by the current strict local distribution reader.

### Bounded HTTPS and archive extraction

Use `urllib` with request timeouts, a bounded response reader, and a redirect handler that permits only `api.github.com` and `codeload.github.com`. Limit the compressed archive to 100 MiB, extracted regular file bytes to 500 MiB, and entries to 20,000. Reject absolute paths, parent traversal, backslashes, paths outside GitHub's single archive root, duplicate output paths, symlinks, hard links, devices, FIFOs, and other special entries. Create regular files with exclusive creation inside the staging tree; do not call generic `tarfile.extract`.

These limits are initial implementation constants, not a promise to support arbitrarily large repositories. No new runtime dependency is required.

### CLI integration

Change the distribution positional argument from a filesystem-only `Path` to a string locator. `github:` selects remote resolution; all other values retain current local path behavior. The resolver returns both a validated `LocalDistribution` and optional source metadata. CLI JSON includes remote owner, repository, requested ref, and resolved commit SHA. For `add`, the same Codex context and renderer remain mandatory; remote availability does not change the authority policy.

### Package and command identity

Name the Python distribution `agentstash` and expose the matching `agentstash` console script so `uvx agentstash ...` can infer both the distribution and command name. Keep `agents` as a compatibility alias for the distribution CLI and keep `agent-ir` for IR conversion/schema commands. The import package remains `agent_ir`. Add a GitHub release workflow using PyPI Trusted Publishing; the workflow builds and tests without OIDC permission, then publishes only downloaded artifacts from a separate job. This change configures but does not trigger a PyPI release.

## Risks / Trade-offs

- [GitHub anonymous API rate limits or transient service failures] → Return clear errors, use the cache when a full SHA is supplied, and avoid retries with unbounded duration.
- [A repository archive is oversized or malicious] → Enforce download, entry-count, extracted-size, path, and file-type limits before promotion.
- [A cached directory is locally modified] → Validate the manifest and every referenced source path on each operation; never execute cache contents.
- [A user mistakes a commit pin for trusted content] → Report the resolved SHA and document that pinning provides repeatability, not provenance or safety.
- [A repository depends on symlinks or submodules] → Reject those archive entries and explain the unsupported feature rather than dereferencing them.

## Migration Plan

No migration is needed. Existing local directory arguments retain their behavior. Remote locators are additive. Rollback consists of removing the remote resolver module and CLI dispatch; cache directories can be deleted manually by the user.

## Open Questions

- Cache pruning and an explicit `agents cache clean` command can be designed after observing cache size in use.
- Other Git hosting services need separate host, pin-resolution, and archive-security decisions before support is added.
