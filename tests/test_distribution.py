from pathlib import Path

import pytest

from agent_ir.distribution import LocalDistribution

FIXTURE = Path(__file__).parent / "fixtures" / "distribution"


def test_loads_and_resolves_real_local_manifest() -> None:
    distribution = LocalDistribution.load(FIXTURE)

    assert distribution.manifest.name == "security-review-kit"
    entry = distribution.get_agent("security-auditor")
    assert "Read-only security review" in distribution.read_source(entry)


@pytest.mark.parametrize(
    "manifest, message",
    [
        ("schema_version: 2\nname: kit\nversion: '1'\nagents: [{id: x, source: {harness: claude-code, path: a.md}}]\n", "unsupported distribution schema_version"),
        ("schema_version: 1\nname: kit\nversion: '1'\nunknown: true\nagents: [{id: x, source: {harness: claude-code, path: a.md}}]\n", "Extra inputs are not permitted"),
        ("schema_version: 1\nname: kit\nversion: '1'\nagents: [{id: x, source: {harness: claude-code, path: a.md}}, {id: x, source: {harness: claude-code, path: a.md}}]\n", "IDs must be unique"),
        ("schema_version: 1\nschema_version: 1\nname: kit\nversion: '1'\nagents: [{id: x, source: {harness: claude-code, path: a.md}}]\n", "duplicate key"),
    ],
)
def test_rejects_malformed_manifests(tmp_path: Path, manifest: str, message: str) -> None:
    (tmp_path / "agents.yaml").write_text(manifest, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        LocalDistribution.load(tmp_path)


@pytest.mark.parametrize("source_path", ["/etc/passwd", "../outside.md", "missing.md", "profile.py"])
def test_rejects_absolute_traversal_and_missing_sources(tmp_path: Path, source_path: str) -> None:
    (tmp_path / "agents.yaml").write_text(
        "schema_version: 1\nname: kit\nversion: '1'\nagents:\n"
        f"  - id: x\n    source: {{harness: claude-code, path: {source_path}}}\n",
        encoding="utf-8",
    )
    distribution = LocalDistribution.load(tmp_path)

    with pytest.raises(ValueError):
        distribution.validate_sources()


def test_rejects_symlink_that_escapes_distribution_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("secret", encoding="utf-8")
    source_dir = tmp_path / "distribution"
    source_dir.mkdir()
    (source_dir / "escape.md").symlink_to(outside)
    (source_dir / "agents.yaml").write_text(
        "schema_version: 1\nname: kit\nversion: '1'\nagents:\n"
        "  - id: x\n    source: {harness: claude-code, path: escape.md}\n",
        encoding="utf-8",
    )
    distribution = LocalDistribution.load(source_dir)

    with pytest.raises(ValueError, match="escapes distribution root"):
        distribution.read_source(distribution.get_agent("x"))


def test_requires_open_code_relative_identity_and_forbids_explicit_null_on_claude(tmp_path: Path) -> None:
    manifest = tmp_path / "agents.yaml"
    manifest.write_text(
        "schema_version: 1\nname: kit\nversion: '1'\nagents:\n"
        "  - id: x\n    source: {harness: opencode-v2, path: agents/a.md}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="require `agent_relative_path`"):
        LocalDistribution.load(tmp_path)

    manifest.write_text(
        "schema_version: 1\nname: kit\nversion: '1'\nagents:\n"
        "  - id: x\n    source: {harness: claude-code, path: a.md, agent_relative_path: null}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="only valid for OpenCode"):
        LocalDistribution.load(tmp_path)
