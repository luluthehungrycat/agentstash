"""Validated, inert local agent distribution manifests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from pydantic import Field, ValidationError, field_validator, model_validator

from agent_ir.adapters.base import validate_agent_relative_path
from agent_ir.models import StrictModel


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a distribution manifest",
                node.start_mark,
                "manifest mapping keys must be scalar values",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a distribution manifest",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class AgentSource(StrictModel):
    harness: str
    path: str = Field(min_length=1)
    agent_relative_path: str | None = None

    @field_validator("harness")
    @classmethod
    def supported_harness(cls, value: str) -> str:
        if value not in {"claude-code", "opencode-v2"}:
            raise ValueError("this distribution version supports only `claude-code` and `opencode-v2` sources")
        return value

    @model_validator(mode="after")
    def validate_agent_relative_path(self) -> "AgentSource":
        if self.harness == "opencode-v2":
            if self.agent_relative_path is None:
                raise ValueError("OpenCode V2 sources require `agent_relative_path`")
            validate_agent_relative_path(self.agent_relative_path)
        elif "agent_relative_path" in self.model_fields_set:
            raise ValueError("`agent_relative_path` is only valid for OpenCode V2 sources")
        return self


class DistributionAgent(StrictModel):
    id: str = Field(min_length=1)
    source: AgentSource

    @field_validator("id")
    @classmethod
    def stable_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError("agent IDs must start with a letter or digit and contain only letters, digits, '.', '_' or '-'")
        return value


class AgentDistribution(StrictModel):
    schema_version: int = Field(strict=True)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    agents: list[DistributionAgent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_distribution(self) -> "AgentDistribution":
        if self.schema_version != 1:
            raise ValueError(f"unsupported distribution schema_version: {self.schema_version}")
        ids = [agent.id for agent in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("distribution agent IDs must be unique")
        return self


class LocalDistribution:
    """Manifest and root path, with containment checked before source reads."""

    def __init__(self, root: Path, manifest: AgentDistribution) -> None:
        self.root = root
        self.manifest = manifest

    @classmethod
    def load(cls, root: Path) -> "LocalDistribution":
        try:
            resolved_root = root.expanduser().resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"distribution root does not exist: {root}") from exc
        if not resolved_root.is_dir():
            raise ValueError(f"distribution root is not a directory: {resolved_root}")
        manifest_path = resolved_root / "agents.yaml"
        try:
            raw = yaml.load(manifest_path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
            manifest = AgentDistribution.model_validate(raw)
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as exc:
            raise ValueError(f"invalid distribution manifest {manifest_path}: {exc}") from exc
        return cls(resolved_root, manifest)

    def get_agent(self, agent_id: str) -> DistributionAgent:
        for agent in self.manifest.agents:
            if agent.id == agent_id:
                return agent
        raise ValueError(f"agent ID is not present in distribution: {agent_id}")

    def validate_sources(self) -> None:
        """Check all manifest references without reading any profile contents."""
        for agent in self.manifest.agents:
            self._resolve_source(agent)

    def read_source(self, agent: DistributionAgent) -> str:
        source_path = self._resolve_source(agent)
        try:
            return source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"cannot read source file {agent.source.path}: {exc}") from exc

    def _resolve_source(self, agent: DistributionAgent) -> Path:
        relative = Path(agent.source.path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"source path must be relative and cannot traverse parents: {agent.source.path}")
        if relative.suffix.lower() != ".md":
            raise ValueError(f"agent source must be a Markdown file: {agent.source.path}")
        try:
            source_path = (self.root / relative).resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"source file does not exist: {agent.source.path}") from exc
        if not source_path.is_relative_to(self.root):
            raise ValueError(f"source path escapes distribution root: {agent.source.path}")
        if not source_path.is_file():
            raise ValueError(f"source path is not a regular file: {agent.source.path}")
        return source_path
