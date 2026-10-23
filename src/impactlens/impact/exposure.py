"""Direct and provenance-backed indirect exposure mapping (rules ``exposure-rules-v1``).

Relationship families and how each is triggered:

=============  ==============================================================  =====================================
Family         Trigger (resolved, evidence-supported event entity)             Held-position link required
=============  ==============================================================  =====================================
direct         company entity resolved to issuer/securities                    position.security_id in those ids
supplier/      company entity                                                  stored ``security_relationships`` row
customer/                                                                      (provenance required, never LLM)
competitor
sector         sector entity ``sector:<name>``                                 security master sector == name
industry       industry entity ``industry:<name>``                             security master industry == name
country        country entity ``country:XX``                                   stored factor exposure for that key
commodity      commodity entity ``commodity:*``                                stored factor exposure for that key
macro          macro entity ``macro:*``                                        stored factor exposure for that key
=============  ==============================================================  =====================================

Direction propagation: direct/sector/industry/supplier/customer keep the entity direction;
competitor maps positive↔negative (a competitor's gain is a relative headwind); factor
exposures multiply the factor direction by the sign of the stored sensitivity.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from impactlens.entities.models import FactorExposure, Security, SecurityRelationship
from impactlens.intelligence.entity_pipeline import ResolvedEntity
from impactlens.intelligence.taxonomy import Direction
from impactlens.portfolio.models import PortfolioSnapshot, Position

RULES_VERSION = "exposure-rules-v1"
INDIRECT_FAMILIES = ("sector", "industry", "country", "commodity", "macro", "relationship")
_FLIP = {Direction.POSITIVE: Direction.NEGATIVE, Direction.NEGATIVE: Direction.POSITIVE}


class ExposureMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    security_id: str
    ticker: str
    display_name: str
    position_line: int
    position_weight: float
    position_market_value: float | None
    relationship_type: str  # direct | sector | industry | country | commodity | macro | supplier | ...
    family: str  # direct | sector | ... | relationship
    source_entity: str
    source_entity_role: str
    entity_direction: Direction
    direction: Direction  # direction for this position after propagation
    link_strength: float  # 1.0 direct/classification; stored strength/|sensitivity| otherwise
    provenance: dict[str, str]
    path: str


def _match(
    position: Position,
    security: Security,
    entity: ResolvedEntity,
    *,
    relationship_type: str,
    family: str,
    direction: Direction,
    link_strength: float,
    provenance: dict[str, str],
    path: str,
) -> ExposureMatch:
    return ExposureMatch(
        security_id=security.security_id,
        ticker=security.ticker,
        display_name=position.display_name,
        position_line=position.line_no,
        position_weight=position.weight,
        position_market_value=position.market_value,
        relationship_type=relationship_type,
        family=family,
        source_entity=entity.name,
        source_entity_role=entity.role.value,
        entity_direction=entity.direction,
        direction=direction,
        link_strength=link_strength,
        provenance=provenance,
        path=path,
    )


class ExposureEngine:
    def __init__(
        self,
        securities: dict[str, Security],
        relationships: Iterable[tuple[int, SecurityRelationship]] = (),
        factor_exposures: Iterable[tuple[int, FactorExposure]] = (),
        disabled_families: Iterable[str] = (),
    ) -> None:
        self.securities = securities
        self.relationships = list(relationships)
        self.factor_exposures = list(factor_exposures)
        self.disabled = set(disabled_families)
        unknown = self.disabled - set(INDIRECT_FAMILIES)
        if unknown:
            raise ValueError(f"unknown exposure families: {sorted(unknown)}")

    def match(
        self, entities: Iterable[ResolvedEntity], snapshot: PortfolioSnapshot, as_of: str | None = None
    ) -> list[ExposureMatch]:
        """Exposure matches for impact entities. ``as_of`` excludes links recorded later (point-in-time)."""
        held: dict[str, list[Position]] = {}
        for pos in snapshot.security_positions():
            held.setdefault(pos.security_id or "", []).append(pos)
        cutoff = as_of[:10] if as_of else None
        matches: list[ExposureMatch] = []
        for entity in entities:
            if entity.kind == "security":
                matches.extend(self._direct(entity, held))
                if "relationship" not in self.disabled:
                    matches.extend(self._relationships(entity, held, cutoff))
            elif entity.kind in ("sector", "industry") and entity.kind not in self.disabled:
                matches.extend(self._classification(entity, held))
            elif entity.kind == "factor" and entity.factor_key:
                family = entity.factor_key.split(":", 1)[0]
                if family not in self.disabled:
                    matches.extend(self._factor(entity, held, cutoff))
        return sorted(
            matches,
            key=lambda m: (m.position_line, m.family != "direct", m.relationship_type, m.source_entity),
        )

    def _direct(self, entity: ResolvedEntity, held: dict[str, list[Position]]) -> list[ExposureMatch]:
        out = []
        for sid in entity.security_ids:
            for pos in held.get(sid, []):
                sec = self.securities[sid]
                label = f" ({sec.share_class})" if sec.share_class else ""
                out.append(
                    _match(
                        pos,
                        sec,
                        entity,
                        relationship_type="direct",
                        family="direct",
                        direction=entity.direction,
                        link_strength=1.0,
                        provenance={
                            "rule": RULES_VERSION,
                            "source": "security_master",
                            "match": "security_id",
                        },
                        path=f"{entity.name} → held security {sec.ticker}{label}",
                    )
                )
        return out

    def _relationships(
        self, entity: ResolvedEntity, held: dict[str, list[Position]], cutoff: str | None
    ) -> list[ExposureMatch]:
        out = []
        subject_ids = set(entity.security_ids)
        for rel_id, rel in self.relationships:
            if cutoff and rel.as_of[:10] > cutoff:
                continue
            if rel.target_security_id in subject_ids and rel.source_security_id in held:
                # held security is a supplier/customer/competitor *of* the event subject
                held_id, rel_type = rel.source_security_id, rel.relationship_type.value
            elif rel.source_security_id in subject_ids and rel.target_security_id in held:
                held_id = rel.target_security_id
                rel_type = {"supplier": "customer", "customer": "supplier"}.get(
                    rel.relationship_type.value, rel.relationship_type.value
                )
            else:
                continue
            if held_id in subject_ids:
                continue
            direction = (
                _FLIP.get(entity.direction, entity.direction)
                if rel_type == "competitor"
                else entity.direction
            )
            sec = self.securities[held_id]
            for pos in held[held_id]:
                out.append(
                    _match(
                        pos,
                        sec,
                        entity,
                        relationship_type=rel_type,
                        family="relationship",
                        direction=direction,
                        link_strength=rel.strength,
                        provenance={
                            "rule": RULES_VERSION,
                            "relationship_id": str(rel_id),
                            "source": rel.provenance_source,
                            "ref": rel.provenance_ref,
                            "as_of": rel.as_of,
                        },
                        path=f"{entity.name} → {sec.ticker} is a {rel_type} of {entity.name}",
                    )
                )
        return out

    def _classification(self, entity: ResolvedEntity, held: dict[str, list[Position]]) -> list[ExposureMatch]:
        assert entity.factor_key
        family, label = entity.factor_key.split(":", 1)
        out = []
        for sid, positions in held.items():
            sec = self.securities.get(sid)
            if sec is None or getattr(sec, family) != label:
                continue
            for pos in positions:
                out.append(
                    _match(
                        pos,
                        sec,
                        entity,
                        relationship_type=family,
                        family=family,
                        direction=entity.direction,
                        link_strength=1.0,
                        provenance={
                            "rule": RULES_VERSION,
                            "source": "security_master",
                            "classification": f"{family}={label}",
                        },
                        path=f"{entity.name} ({family}) → {sec.ticker} classified in {label}",
                    )
                )
        return out

    def _factor(
        self, entity: ResolvedEntity, held: dict[str, list[Position]], cutoff: str | None
    ) -> list[ExposureMatch]:
        out = []
        for exp_id, exp in self.factor_exposures:
            if exp.factor_key != entity.factor_key or exp.security_id not in held:
                continue
            if cutoff and exp.as_of[:10] > cutoff:
                continue
            direction = entity.direction
            if exp.sensitivity < 0:
                direction = _FLIP.get(direction, direction)
            sec = self.securities[exp.security_id]
            for pos in held[exp.security_id]:
                out.append(
                    _match(
                        pos,
                        sec,
                        entity,
                        relationship_type=exp.family.value,
                        family=exp.family.value,
                        direction=direction,
                        link_strength=abs(exp.sensitivity),
                        provenance={
                            "rule": RULES_VERSION,
                            "factor_exposure_id": str(exp_id),
                            "source": exp.provenance_source,
                            "ref": exp.provenance_ref,
                            "as_of": exp.as_of,
                            "sensitivity": f"{exp.sensitivity:+.2f}",
                        },
                        path=f"{entity.name} → {sec.ticker} stored {exp.family.value} sensitivity {exp.sensitivity:+.2f}",
                    )
                )
        return out
