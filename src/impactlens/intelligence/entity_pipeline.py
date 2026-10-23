"""LLM entity proposals → canonical securities/factors via the deterministic resolver.

The model's ``proposed_ticker`` is a hint only: it can never override or substitute for a
name resolution. A mismatch is recorded as a note for auditing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from impactlens.entities.factors import resolve_factor
from impactlens.entities.normalize import normalize_name, normalize_ticker
from impactlens.entities.resolver import Candidate, ResolutionStatus, SecurityResolver
from impactlens.intelligence.schema import AnalysisOutput, EntityProposal
from impactlens.intelligence.taxonomy import Direction, EntityRole, EntityType


class ResolvedEntity(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    normalized_name: str
    entity_type: EntityType
    role: EntityRole
    direction: Direction
    status: ResolutionStatus
    kind: str  # security | factor | sector | industry | none
    issuer_id: str | None = None
    security_ids: tuple[str, ...] = ()
    factor_key: str | None = None
    candidates: tuple[Candidate, ...] = ()
    proposed_ticker: str | None = None
    evidence_supported: bool = False
    notes: tuple[str, ...] = ()


class ResolutionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    entities: tuple[ResolvedEntity, ...]

    @property
    def impact_entities(self) -> list[ResolvedEntity]:
        return [
            e
            for e in self.entities
            if e.evidence_supported
            and e.status is ResolutionStatus.RESOLVED
            and e.direction is not Direction.UNCERTAIN
        ]


def _match_label(values: set[str], name: str) -> str | None:
    key = normalize_name(name)
    for value in sorted(values):
        if normalize_name(value) == key:
            return value
    return None


def resolve_entity(
    proposal: EntityProposal, resolver: SecurityResolver, default_direction: Direction, supported: bool
) -> ResolvedEntity:
    direction = proposal.direction or default_direction
    base: dict[str, Any] = dict(
        name=proposal.name,
        normalized_name=normalize_name(proposal.name),
        entity_type=proposal.entity_type,
        role=proposal.role,
        direction=direction,
        proposed_ticker=proposal.proposed_ticker,
        evidence_supported=supported,
    )
    if proposal.entity_type in (EntityType.COMPANY, EntityType.INDEX):
        result = resolver.resolve_name(proposal.name)
        notes = list(result.notes)
        if proposal.proposed_ticker and result.status is ResolutionStatus.RESOLVED:
            tickers = {resolver.get(sid).ticker for sid in result.security_ids if resolver.get(sid)}  # type: ignore[union-attr]
            if normalize_ticker(proposal.proposed_ticker) not in tickers:
                notes.append(
                    f"model proposed ticker {proposal.proposed_ticker!r} ignored; resolver mapped to {sorted(tickers)}"
                )
        elif proposal.proposed_ticker and result.status is ResolutionStatus.UNRESOLVED:
            notes.append("model-proposed ticker not used: tickers alone never resolve an LLM entity")
        return ResolvedEntity(
            **base,
            status=result.status,
            kind="security",
            issuer_id=result.issuer_id,
            security_ids=result.security_ids,
            candidates=result.candidates,
            notes=tuple(notes),
        )
    if proposal.entity_type in (EntityType.SECTOR, EntityType.INDUSTRY):
        values = resolver.sectors() if proposal.entity_type is EntityType.SECTOR else resolver.industries()
        label = _match_label(values, proposal.name)
        if label is None:
            return ResolvedEntity(**base, status=ResolutionStatus.UNRESOLVED, kind="none")
        prefix = "sector" if proposal.entity_type is EntityType.SECTOR else "industry"
        return ResolvedEntity(
            **base, status=ResolutionStatus.RESOLVED, kind=prefix, factor_key=f"{prefix}:{label}"
        )
    if proposal.entity_type in (EntityType.COUNTRY, EntityType.COMMODITY, EntityType.MACRO_FACTOR):
        key = resolve_factor(proposal.name, proposal.entity_type.value)
        if key is None:
            return ResolvedEntity(**base, status=ResolutionStatus.UNRESOLVED, kind="none")
        return ResolvedEntity(**base, status=ResolutionStatus.RESOLVED, kind="factor", factor_key=key)
    # Regulators, people, products, other: retained for context, never mapped to a security.
    return ResolvedEntity(
        **base, status=ResolutionStatus.UNRESOLVED, kind="none", notes=("non-mappable entity type",)
    )


def resolve_entities(
    analysis: AnalysisOutput, resolver: SecurityResolver, supported_names: set[str]
) -> ResolutionSummary:
    resolved = [
        resolve_entity(p, resolver, analysis.direction, p.name in supported_names) for p in analysis.entities
    ]
    return ResolutionSummary(entities=tuple(resolved))
