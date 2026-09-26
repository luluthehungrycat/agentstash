"""Adapter interfaces and parse result."""

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


class TargetAdapter(Protocol[ContextT]):
    harness: str

    def render(
        self,
        agent: AgentIR,
        context: ContextT | None = None,
    ) -> ConversionResult: ...
