"""Structured conversion diagnostics, separating fidelity and authority."""

from enum import StrEnum

from pydantic import Field

from agent_ir.models import StrictModel


class MappingStatus(StrEnum):
    LOSSLESS = "LOSSLESS"
    MAPPED = "MAPPED"
    APPROXIMATED = "APPROXIMATED"
    UNSUPPORTED = "UNSUPPORTED"
    DROPPED = "DROPPED"


class DiagnosticCategory(StrEnum):
    FIDELITY = "fidelity"
    FUNCTIONALITY = "functionality"
    AUTHORITY = "authority"


class AuthorityEffect(StrEnum):
    UNCHANGED = "unchanged"
    NARROWED = "narrowed"
    INCREASED = "increased"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not-applicable"


class ConversionDiagnostic(StrictModel):
    code: str
    field_path: str
    status: MappingStatus
    category: DiagnosticCategory
    authority_effect: AuthorityEffect = AuthorityEffect.NOT_APPLICABLE
    message: str
    blocks_emission: bool = False
    details: dict[str, str] = Field(default_factory=dict)


class ConversionResult(StrictModel):
    agent: "AgentIR"
    target_text: str | None = None
    diagnostics: list[ConversionDiagnostic] = Field(default_factory=list)

    @property
    def emitted(self) -> bool:
        return self.target_text is not None


from agent_ir.models import AgentIR  # noqa: E402  (forward model reference)

ConversionResult.model_rebuild()
