from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tarfile

import pytest

from agent_ir import github_distributions as github

SHA = "0123456789abcdef0123456789abcdef01234567"


def _archive(
    entries: list[tuple[str, bytes | None, str]],
    *,
    second_root: bool = False,
) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive_root = tarfile.TarInfo("repo-root")
        archive_root.type = tarfile.DIRTYPE
        archive.addfile(archive_root)
        if second_root:
            other_root = tarfile.TarInfo("repo-other")
            other_root.type = tarfile.DIRTYPE
            archive.addfile(other_root)
        for name, data, kind in entries:
            item = tarfile.TarInfo(f"repo-root/{name}")
            if kind == "directory":
                item.type = tarfile.DIRTYPE
                archive.addfile(item)
            elif kind == "symlink":
                item.type = tarfile.SYMTYPE
                item.linkname = data.decode() if data else "outside"
                archive.addfile(item)
            elif kind == "hardlink":
                item.type = tarfile.LNKTYPE
                item.linkname = data.decode() if data else "repo-root/profile.md"
                archive.addfile(item)
            else:
                payload = data or b""
                item.size = len(payload)
                archive.addfile(item, BytesIO(payload))
    return buffer.getvalue()


def _valid_archive() -> bytes:
    return _archive(
        [
            (
                "agents.yaml",
                b"schema_version: 1\nname: remote-kit\nversion: 1.0.0\nagents:\n"
                b"  - id: reviewer\n    source: {harness: claude-code, path: reviewer.md}\n",
                "file",
            ),
            ("reviewer.md", b"---\nname: reviewer\ntools: Read\n---\nReview safely.\n", "file"),
        ]
    )


def test_parse_github_locator_and_reject_unsafe_components() -> None:
    locator = github.parse_github_locator("github:NousResearch/hermes-agent@main")
    assert (locator.owner, locator.repository, locator.reference) == (
        "NousResearch",
        "hermes-agent",
        "main",
    )

    for invalid in (
        "github:owner/repo",
        "github:owner/repo@",
        "github:../repo@main",
        "github:owner/repo@../main",
        "github:owner/repo@main\\evil",
        "github:owner/repo/extra@main",
    ):
        with pytest.raises(ValueError):
            github.parse_github_locator(invalid)


def test_redirect_handler_allows_only_https_github_hosts() -> None:
    handler = github._GitHubRedirectHandler()
    request = github.Request("https://api.github.com/start")
    allowed = handler.redirect_request(request, None, 302, "Found", {}, "https://codeload.github.com/a/b")
    assert allowed is not None

    with pytest.raises(ValueError, match="unsupported host"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://attacker.invalid/archive")
    with pytest.raises(ValueError, match="non-HTTPS"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://api.github.com/archive")
    with pytest.raises(ValueError, match="unsupported port"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://codeload.github.com:8443/archive")
    with pytest.raises(ValueError, match="user credentials"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://user:password@api.github.com/archive")


def test_read_limited_caps_stream_bytes() -> None:
    assert github._read_limited(BytesIO(b"12345"), 5) == b"12345"
    with pytest.raises(ValueError, match="size limit"):
        github._read_limited(BytesIO(b"123456"), 5)


def test_agentstash_cache_location_prefers_new_env_and_keeps_legacy_compatibility(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("AGENT_IR_CACHE_DIR", str(tmp_path / "legacy"))
    monkeypatch.delenv("AGENTSTASH_CACHE_DIR", raising=False)
    assert github.default_cache_dir() == tmp_path / "legacy"

    monkeypatch.setenv("AGENTSTASH_CACHE_DIR", str(tmp_path / "new"))
    assert github.default_cache_dir() == tmp_path / "new"

    monkeypatch.delenv("AGENTSTASH_CACHE_DIR")
    monkeypatch.delenv("AGENT_IR_CACHE_DIR")
    assert github.default_cache_dir() == tmp_path / "xdg" / "agentstash" / "distributions"


def test_github_http_reader_enforces_body_caps_and_timeout(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, body: bytes, content_length: str | None = None) -> None:
            self.body = BytesIO(body)
            self.headers = {"Content-Length": content_length} if content_length is not None else {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self) -> str:
            return "https://api.github.com/test"

        def read(self, size: int = -1) -> bytes:
            return self.body.read(size)

    class FakeOpener:
        def __init__(self, response: FakeResponse) -> None:
            self.response = response
            self.timeout = None

        def open(self, request, timeout: int):
            self.timeout = timeout
            return self.response

    opener = FakeOpener(FakeResponse(b"123456"))
    monkeypatch.setattr(github, "build_opener", lambda handler: opener)
    with pytest.raises(ValueError, match="size limit"):
        github._request_bytes("https://api.github.com/test", max_bytes=5, accept="application/json")
    assert opener.timeout == github.REQUEST_TIMEOUT_SECONDS

    oversized_header_opener = FakeOpener(FakeResponse(b"", content_length="6"))
    monkeypatch.setattr(github, "build_opener", lambda handler: oversized_header_opener)
    with pytest.raises(ValueError, match="size limit"):
        github._request_bytes("https://api.github.com/test", max_bytes=5, accept="application/json")


def test_extracts_valid_archive_and_rejects_unsafe_entries(tmp_path: Path) -> None:
    valid = tmp_path / "valid"
    valid.mkdir()
    github._extract_archive(_valid_archive(), valid)
    assert (valid / "agents.yaml").is_file()
    assert (valid / "reviewer.md").read_text(encoding="utf-8").endswith("Review safely.\n")

    malicious_archives = [
        _archive([("../outside", b"bad", "file")]),
        _archive([("link", b"../../outside", "symlink")]),
        _archive([("hardlink", b"repo-root/reviewer.md", "hardlink")]),
        _archive([("same", b"one", "file"), ("same", b"two", "file")]),
        _archive([("nested/child", b"one", "file"), ("nested", b"not-a-dir", "file")]),
        _archive([], second_root=True),
        _archive([("CON.txt", b"device", "file")]),
    ]
    for index, contents in enumerate(malicious_archives):
        destination = tmp_path / f"invalid-{index}"
        destination.mkdir()
        with pytest.raises(ValueError):
            github._extract_archive(contents, destination)


def test_extract_rejects_size_limits(tmp_path: Path, monkeypatch) -> None:
    archive = _archive([("large", b"12345", "file")])
    monkeypatch.setattr(github, "MAX_EXTRACTED_BYTES", 4)
    destination = tmp_path / "limited"
    destination.mkdir()

    with pytest.raises(ValueError, match="extraction limit"):
        github._extract_archive(archive, destination)


def test_resolves_once_downloads_by_sha_and_reuses_cache_offline(tmp_path: Path, monkeypatch) -> None:
    archive = _valid_archive()
    requests: list[str] = []

    def fake_request(url: str, *, max_bytes: int, accept: str) -> bytes:
        requests.append(url)
        if "/commits/main" in url:
            return json.dumps({"sha": SHA}).encode()
        if url.endswith(f"/tarball/{SHA}"):
            return archive
        raise AssertionError(f"unexpected request: {url}")

    monkeypatch.setattr(github, "_request_bytes", fake_request)
    first = github.resolve_github_distribution("github:OctoCat/repo@main", cache_root=tmp_path / "cache")
    assert first.source.commit_sha == SHA
    assert first.source.cache_hit is False
    assert first.distribution.manifest.name == "remote-kit"
    assert requests == [
        "https://api.github.com/repos/OctoCat/repo/commits/main",
        f"https://api.github.com/repos/OctoCat/repo/tarball/{SHA}",
    ]

    def network_must_not_be_used(*args, **kwargs) -> bytes:
        raise AssertionError("full-SHA cache hit should not make a network request")

    monkeypatch.setattr(github, "_request_bytes", network_must_not_be_used)
    cached = github.resolve_github_distribution(
        f"github:OctoCat/repo@{SHA}",
        cache_root=tmp_path / "cache",
    )
    assert cached.source.cache_hit is True
    assert cached.source.commit_sha == SHA


def test_invalid_archive_does_not_promote_cache_entry(tmp_path: Path, monkeypatch) -> None:
    malicious = _archive([("escape", b"../../outside", "symlink")])

    def fake_request(url: str, *, max_bytes: int, accept: str) -> bytes:
        if "/commits/main" in url:
            return json.dumps({"sha": SHA}).encode()
        return malicious

    monkeypatch.setattr(github, "_request_bytes", fake_request)
    with pytest.raises(ValueError, match="unsupported link or special"):
        github.resolve_github_distribution("github:owner/repo@main", cache_root=tmp_path / "cache")
    assert not (tmp_path / "cache" / "github" / "owner" / "repo" / SHA).exists()


def test_cache_promotion_never_overwrites_an_existing_entry(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "staged.txt").write_text("new", encoding="utf-8")
    destination = tmp_path / SHA
    destination.mkdir()
    (destination / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to overwrite"):
        github._promote_cache_entry(staging, destination)
    assert (destination / "existing.txt").read_text(encoding="utf-8") == "keep"
    assert (staging / "staged.txt").read_text(encoding="utf-8") == "new"


def test_cache_promotion_refuses_a_live_population_lock(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    destination = tmp_path / SHA
    (tmp_path / f".{SHA}.lock").write_text("in progress", encoding="utf-8")

    with pytest.raises(ValueError, match="another process"):
        github._promote_cache_entry(staging, destination)
    assert staging.is_dir()
    assert not destination.exists()
