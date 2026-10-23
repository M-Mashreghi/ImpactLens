"""Pydantic schema for structured LLM analysis output (``analysis-v1``).

Model output is untrusted: it must parse into :class:`AnalysisOutput` and then pass
evidence validation and entity resolution before anything downstream uses it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from impactlens.intelligence.taxonomy import (
    Direction,
    EntityRole,
    EntityType,
    EventType,
    Severity,
    TimeHorizon,
)

CLAIM_FIELDS = ("event_type", "direction", "severity")


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int = Field(ge=1, le=100)
    quote: str = Field(min_length=1, max_length=600, description="Verbatim excerpt from the article")
    supports: tuple[str, ...] = Field(
        default=(), description="Claims supported: event_type, direction, severity, entity:<name>"
    )


class EntityProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    entity_type: EntityType
    role: EntityRole
    proposed_ticker: str | None = Field(default=None, max_length=12, description="Hint only; never trusted")
    direction: Direction | None = Field(default=None, description="Per-entity direction when it differs")
    evidence_ids: tuple[int, ...] = ()


class AnalysisOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: EventType
    event_summary: str = Field(min_length=1, max_length=600)
    direction: Direction
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    time_horizon: TimeHorizon
    entities: tuple[EntityProposal, ...] = Field(default=(), max_length=30)
    evidence: tuple[EvidenceSpan, ...] = Field(default=(), max_length=30)
    uncertainties: tuple[str, ...] = Field(default=(), max_length=20)
    rationale: str = Field(default="", max_length=1500)
    is_uncertain: bool = False

    @field_validator("confidence", mode="before")
    @classmethod
    def _no_bool_confidence(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("confidence must be a number in [0, 1]")
        return value

    @model_validator(mode="after")
    def _consistency(self) -> AnalysisOutput:
        ids = [e.id for e in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence ids must be unique")
        known = set(ids)
        for entity in self.entities:
            missing = set(entity.evidence_ids) - known
            if missing:
                raise ValueError(f"entity {entity.name!r} references unknown evidence ids {sorted(missing)}")
        return self

    def claims_supported(self) -> dict[str, set[int]]:
        support: dict[str, set[int]] = {c: set() for c in CLAIM_FIELDS}
        for span in self.evidence:
            for claim in span.supports:
                if claim in support:
                    support[claim].add(span.id)
        return support


def json_schema() -> dict:
    return AnalysisOutput.model_json_schema()
