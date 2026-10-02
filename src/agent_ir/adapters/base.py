"""Adapter interfaces and parse result."""

import re
from typing import Protocol, TypeVar

from pydantic import Field

from agent_ir.diagnostics import ConversionDiagnostic, ConversionResult
from agent_ir.models import AgentIR, StrictModel

ContextT = TypeVar("ContextT", contravariant=True)


class ParseResult(StrictModel):
    agent: AgentIR
    diagnostics: list[ConversionDiagnostic] = Field(default_factory=list)


class SourceAdapter(Protocol):
    harness: str

    def parse(self, document: str) -> ParseResult: ...


class ContextAwareSourceAdapter(Protocol):
    harness: str

    def parse_with_context(self, document: str, context: "SourceParseContext") -> ParseResult: ...


class SourceParseContext(StrictModel):
    """Caller-supplied identity context for path-named source formats."""

    agent_relative_path: str


def validate_agent_relative_path(value: str) -> None:
    """Validate an OpenCode identity path without consulting the read path."""
    parts = value.split("/")
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
        or any(part in {"", ".", ".."} for part in parts)
        or not value.endswith(".md")
    ):
        raise ValueError("OpenCode `agent_relative_path` must be a safe relative Markdown path")
    for index, part in enumerate(parts):
        stem = part[:-3] if index == len(parts) - 1 else part
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]*", stem)
            or stem.endswith((".", " "))
            or ":" in stem
        ):
            raise ValueError("OpenCode `agent_relative_path` contains an unsafe identity component")
        windows_name = stem.split(".", 1)[0].upper()
        if windows_name in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", windows_name):
            raise ValueError("OpenCode `agent_relative_path` contains a reserved identity component")


class TargetAdapter(Protocol[ContextT]):
    harness: str

    def render(
        self,
        agent: AgentIR,
        context: ContextT | None = None,
    ) -> ConversionResult: ...
