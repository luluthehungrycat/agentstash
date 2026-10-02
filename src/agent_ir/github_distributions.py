"""Safe resolver and cache for public GitHub agent distributions."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from typing import BinaryIO, Protocol, cast
import zlib
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from agent_ir.distribution import LocalDistribution

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20_000
MAX_API_RESPONSE_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 20
_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,39}$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_ALLOWED_REDIRECT_HOSTS = {"api.github.com", "codeload.github.com"}


class _ReadableBytes(Protocol):
    def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True)
class GitHubLocator:
    owner: str
    repository: str
    reference: str


@dataclass(frozen=True)
class RemoteSourceInfo:
    owner: str
    repository: str
    requested_ref: str
    commit_sha: str
    cache_hit: bool

    def as_json(self) -> dict[str, str | bool]:
        return {
            "provider": "github",
            "owner": self.owner,
            "repository": self.repository,
            "requested_ref": self.requested_ref,
            "commit_sha": self.commit_sha,
            "cache_hit": self.cache_hit,
        }


@dataclass(frozen=True)
class ResolvedRemoteDistribution:
    distribution: LocalDistribution
    source: RemoteSourceInfo


class _GitHubRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_github_url(newurl, redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_github_url(url: str, *, redirect: bool = False) -> None:
    parsed = urlparse(url)
    prefix = "GitHub redirected" if redirect else "GitHub response ended"
    if parsed.scheme != "https":
        if redirect:
            raise ValueError("GitHub attempted to redirect to a non-HTTPS URL")
        raise ValueError("GitHub response ended at a non-HTTPS URL")
    if parsed.hostname not in _ALLOWED_REDIRECT_HOSTS:
        raise ValueError(f"{prefix} at an unsupported host: {parsed.hostname or '<missing>'}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{prefix} at a URL with an invalid port") from exc
    if port not in (None, 443):
        raise ValueError(f"{prefix} at an unsupported port")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{prefix} at a URL containing user credentials")


def parse_github_locator(value: str) -> GitHubLocator:
    if not value.startswith("github:"):
        raise ValueError("remote distribution must use `github:OWNER/REPO@REF`")
    location = value.removeprefix("github:")
    if "@" not in location:
        raise ValueError("GitHub distribution locator requires an explicit ref: `github:OWNER/REPO@REF`")
    repository_path, reference = location.rsplit("@", 1)
    parts = repository_path.split("/")
    if len(parts) != 2:
        raise ValueError("GitHub distribution locator must contain exactly OWNER/REPO")
    owner, repository = parts
    if not _OWNER_PATTERN.fullmatch(owner) or owner.startswith("-") or owner.endswith("-"):
        raise ValueError("invalid GitHub owner in distribution locator")
    if (
        not _REPOSITORY_PATTERN.fullmatch(repository)
        or repository in {".", ".."}
        or repository.startswith(".")
    ):
        raise ValueError("invalid GitHub repository name in distribution locator")
    if (
        not reference
        or reference.startswith("-")
        or reference.startswith("/")
        or reference.endswith("/")
        or ".." in reference
        or "\\" in reference
        or any(ord(character) < 32 for character in reference)
    ):
        raise ValueError("invalid GitHub ref in distribution locator")
    return GitHubLocator(owner, repository, reference)


def default_cache_dir() -> Path:
    configured = os.environ.get("AGENTSTASH_CACHE_DIR") or os.environ.get("AGENT_IR_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return base / "agentstash" / "distributions"


def _read_limited(stream: BinaryIO, max_bytes: int) -> bytes:
    data = bytearray()
    while len(data) <= max_bytes:
        chunk = stream.read(min(64 * 1024, max_bytes + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    if len(data) > max_bytes:
        raise ValueError(f"remote response exceeds the {max_bytes}-byte size limit")
    return bytes(data)


def _request_bytes(url: str, *, max_bytes: int, accept: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.github.com":
        raise ValueError("GitHub requests must start at https://api.github.com")
    request = Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "agentstash/0.1.0",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    opener = build_opener(_GitHubRedirectHandler())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            _validate_github_url(response.geturl())
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except ValueError as exc:
                    raise ValueError("GitHub response has an invalid Content-Length") from exc
                if declared_length > max_bytes:
                    raise ValueError(f"remote response exceeds the {max_bytes}-byte size limit")
            return _read_limited(response, max_bytes)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"GitHub request failed: {exc}") from exc


def _resolve_commit(locator: GitHubLocator) -> str:
    if _SHA_PATTERN.fullmatch(locator.reference):
        return locator.reference.lower()
    url = (
        f"https://api.github.com/repos/{locator.owner}/{locator.repository}/commits/"
        f"{quote(locator.reference, safe='/')}"
    )
    payload = _request_bytes(
        url,
        max_bytes=MAX_API_RESPONSE_BYTES,
        accept="application/vnd.github+json",
    )
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("GitHub returned an invalid commit response") from exc
    sha = data.get("sha") if isinstance(data, dict) else None
    if not isinstance(sha, str) or not _SHA_PATTERN.fullmatch(sha):
        raise ValueError("GitHub did not resolve the ref to a full commit SHA")
    return sha.lower()


def _cache_location(cache_root: Path, owner: str, repository: str, sha: str) -> Path:
    root = cache_root.expanduser().resolve(strict=False)
    destination = root / "github" / owner.lower() / repository.lower() / sha
    parent_resolved = destination.parent.resolve(strict=False)
    if not parent_resolved.is_relative_to(root):
        raise ValueError("GitHub cache path resolves outside the configured cache root")
    return destination


def _load_cached(path: Path) -> LocalDistribution:
    distribution = LocalDistribution.load(path)
    distribution.validate_sources()
    return distribution


def _archive_url(owner: str, repository: str, sha: str) -> str:
    return f"https://api.github.com/repos/{owner}/{repository}/tarball/{sha}"


def resolve_github_distribution(
    value: str,
    *,
    cache_root: Path | None = None,
) -> ResolvedRemoteDistribution:
    locator = parse_github_locator(value)
    cache_base = (cache_root or default_cache_dir()).expanduser()
    cache_path = _cache_location(cache_base, locator.owner, locator.repository, "placeholder")
    repository_cache = cache_path.parent
    sha = _resolve_commit(locator)
    destination = repository_cache / sha
    if destination.is_symlink():
        raise ValueError("refusing to use a symlink as a GitHub cache entry")
    if destination.exists():
        return ResolvedRemoteDistribution(
            distribution=_load_cached(destination),
            source=RemoteSourceInfo(locator.owner, locator.repository, locator.reference, sha, True),
        )
    root_resolved = cache_base.resolve(strict=False)
    root_resolved.mkdir(parents=True, exist_ok=True)
    current = root_resolved
    for component in ("github", locator.owner.lower(), locator.repository.lower()):
        current = current / component
        if current.is_symlink():
            raise ValueError("refusing to follow a symlink inside the GitHub cache tree")
        current.mkdir(exist_ok=True)
        if not current.resolve(strict=True).is_relative_to(root_resolved):
            raise ValueError("GitHub cache directory resolves outside the configured cache root")
    repository_cache = current
    destination = repository_cache / sha
    archive = _request_bytes(
        _archive_url(locator.owner, locator.repository, sha),
        max_bytes=MAX_ARCHIVE_BYTES,
        accept="application/vnd.github+json",
    )
    staging = Path(tempfile.mkdtemp(prefix=f".{sha}.", dir=repository_cache))
    try:
        _extract_archive(archive, staging)
        distribution = LocalDistribution.load(staging)
        distribution.validate_sources()
        _promote_cache_entry(staging, destination)
        distribution = _load_cached(destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return ResolvedRemoteDistribution(
        distribution=distribution,
        source=RemoteSourceInfo(locator.owner, locator.repository, locator.reference, sha, False),
    )


def _promote_cache_entry(staging: Path, destination: Path) -> None:
    lock_path = destination.parent / f".{destination.name}.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("another process is populating this GitHub cache entry; retry the command") from exc
    try:
        if destination.exists() or destination.is_symlink():
            raise ValueError("GitHub cache entry appeared during download; refusing to overwrite it")
        os.rename(staging, destination)
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _extract_archive(archive: bytes, destination: Path) -> None:
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError(f"GitHub archive exceeds the {MAX_ARCHIVE_BYTES}-byte download limit")
    try:
        compressed = io.BytesIO(archive)
        with gzip.GzipFile(fileobj=compressed, mode="rb") as decompressed:
            bounded = _DecompressionLimitReader(
                decompressed,
                MAX_EXTRACTED_BYTES + MAX_ARCHIVE_ENTRIES * 1024 + 1024 * 1024,
            )
            with tarfile.open(fileobj=cast(BinaryIO, bounded), mode="r|") as tar:
                root_name: str | None = None
                entries: dict[Path, str] = {}
                file_paths: set[Path] = set()
                paths_with_descendants: set[Path] = set()
                total_size = 0
                entry_count = 0
                base = destination.resolve(strict=True)
                for member in tar:
                    entry_count += 1
                    if entry_count > MAX_ARCHIVE_ENTRIES:
                        raise ValueError(f"GitHub archive exceeds the {MAX_ARCHIVE_ENTRIES}-entry limit")
                    raw_name = member.name
                    if "\\" in raw_name or "\x00" in raw_name:
                        raise ValueError("GitHub archive contains a platform-ambiguous path")
                    archive_path = PurePosixPath(raw_name)
                    parts = archive_path.parts
                    if archive_path.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
                        raise ValueError(f"GitHub archive contains an unsafe path: {raw_name!r}")
                    if any(_unsafe_windows_component(part) for part in parts):
                        raise ValueError(f"GitHub archive contains a platform-ambiguous path: {raw_name!r}")
                    if root_name is None:
                        root_name = parts[0]
                    elif root_name != parts[0]:
                        raise ValueError("GitHub archive must have exactly one top-level directory")
                    if len(parts) == 1:
                        relative = Path()
                        if not member.isdir():
                            raise ValueError("GitHub archive root entry must be a directory")
                    else:
                        relative = Path(*parts[1:])
                    if member.isdir():
                        kind = "directory"
                    elif member.isreg():
                        kind = "file"
                        if member.size < 0:
                            raise ValueError("GitHub archive contains a negative file size")
                        total_size += member.size
                        if total_size > MAX_EXTRACTED_BYTES:
                            raise ValueError(f"GitHub archive exceeds the {MAX_EXTRACTED_BYTES}-byte extraction limit")
                    else:
                        raise ValueError(f"GitHub archive contains an unsupported link or special entry: {raw_name!r}")

                    _register_archive_path(
                        relative,
                        kind,
                        raw_name,
                        entries,
                        file_paths,
                        paths_with_descendants,
                    )

                    if relative == Path():
                        continue
                    output = destination / relative
                    if not output.resolve(strict=False).is_relative_to(base):
                        raise ValueError(f"GitHub archive path escapes its cache staging directory: {raw_name!r}")
                    if kind == "directory":
                        output.mkdir(parents=True, exist_ok=True)
                        continue
                    output.parent.mkdir(parents=True, exist_ok=True)
                    source = tar.extractfile(member)
                    if source is None:
                        raise ValueError(f"cannot read archive file {raw_name!r}")
                    try:
                        with source, output.open("xb") as target:
                            remaining = member.size
                            while remaining:
                                chunk = source.read(min(64 * 1024, remaining))
                                if not chunk:
                                    raise ValueError(f"truncated archive content for {raw_name!r}")
                                target.write(chunk)
                                remaining -= len(chunk)
                    except OSError as exc:
                        raise ValueError(f"cannot extract archive file {raw_name!r}: {exc}") from exc
                if entry_count == 0 or root_name is None:
                    raise ValueError("GitHub archive is empty")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise ValueError(f"GitHub returned an invalid or truncated tar.gz archive: {exc}") from exc


def _register_archive_path(
    relative: Path,
    kind: str,
    raw_name: str,
    entries: dict[Path, str],
    file_paths: set[Path],
    paths_with_descendants: set[Path],
) -> None:
    if relative in entries:
        raise ValueError(f"GitHub archive contains a duplicate path: {raw_name!r}")
    if kind == "file" and relative in paths_with_descendants:
        raise ValueError("GitHub archive has a file used as a parent directory")
    for parent in relative.parents:
        if parent in file_paths:
            raise ValueError("GitHub archive has a file used as a parent directory")
        paths_with_descendants.add(parent)
    entries[relative] = kind
    if kind == "file":
        file_paths.add(relative)


def _unsafe_windows_component(component: str) -> bool:
    if ":" in component or component.endswith((".", " ")):
        return True
    stem = component.split(".", 1)[0].upper()
    return stem in {"CON", "PRN", "AUX", "NUL"} or bool(re.fullmatch(r"(?:COM|LPT)[1-9]", stem))


class _DecompressionLimitReader:
    """Read-only wrapper that bounds bytes expanded from compressed archives."""

    def __init__(self, stream: _ReadableBytes, limit: int) -> None:
        self.stream = stream
        self.limit = limit
        self.read_bytes = 0

    def read(self, size: int = -1) -> bytes:
        request_size = self.limit - self.read_bytes + 1 if size < 0 else min(size, self.limit - self.read_bytes + 1)
        data = self.stream.read(max(0, request_size))
        self.read_bytes += len(data)
        if self.read_bytes > self.limit:
            raise ValueError("GitHub archive exceeds the decompressed tar stream limit")
        return data
