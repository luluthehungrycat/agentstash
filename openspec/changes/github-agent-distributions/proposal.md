## Why

The local distribution CLI works with checked-out folders, but users still need to clone and update each repository themselves. Adding a narrow GitHub source locator with immutable commit resolution and a local cache makes distributions shareable while keeping the existing manifest and conversion path intact.

## What Changes

- Accept explicit public GitHub distribution locators in `agents list`, `agents inspect`, and `agents add`.
- Resolve mutable refs to full commit SHAs and identify every remote operation by the resulting immutable pin.
- Cache downloaded source archives by owner, repository, and commit SHA; allow full-SHA cache hits without network access.
- Bound archive size and extracted content, reject unsafe paths and non-regular archive entries, and treat repository files as inert data.
- Report the resolved owner/repository/commit and keep conversion behind the existing Agent IR and Codex authority checks.

## Capabilities

### New Capabilities

- `remote-agent-distributions`: Resolve, cache, and safely read public GitHub agent distributions by immutable commit.

### Modified Capabilities

None.

## Impact

- Extends the `agents` CLI distribution argument and adds a GitHub distribution resolver/cache module.
- Uses the Python standard library for HTTPS and tar archive handling; no new runtime dependency is expected.
- Updates CLI tests and user documentation. Private repositories, arbitrary hosts, automatic update behavior, and other source hosts remain out of scope.
