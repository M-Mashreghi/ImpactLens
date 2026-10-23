"""Versioned deterministic impact-priority scoring (``impact-v1``).

For every exposure match ``m`` on a position with weight ``w``::

    exposure_magnitude = min(w, weight_cap) / weight_cap                      ∈ [0, 1]
    relevance_weight   = role_relevance[entity_role] × link_strength           ∈ [0, 1]
    base               = exposure_magnitude × relationship_weight[type]
                         × severity_value[severity] × confidence × relevance_weight
    signed_component   = base × direction_sign[direction]                      (+1 / −1 / 0)
    absolute_component = base × direction_priority[direction]

Per position only the match with the largest ``absolute_component`` is *counted* (ties:
direct first, then relationship type, then entity name) so one holding is never double
counted through several paths; the other matches stay visible with ``counted = False``.

Portfolio aggregates (rounded to 4 dp)::

    signed_score      = 100 × clamp(Σ counted signed_component, −1, 1)       ∈ [−100, 100]
    absolute_priority = 100 × min(Σ counted absolute_component, 1)           ∈ [0, 100]
    impact_level      = Critical ≥ 50 > High ≥ 25 > Medium ≥ 10 > Low

This is an impact-PRIORITY score for triage. It is not an expected return or a forecast.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from impactlens.impact.exposure import ExposureMatch
from impactlens.intelligence.taxonomy import Direction, Severity

SCORE_SEMANTICS = (
    "Impact-priority score for triage (0–100). Not an expected return, forecast or price target."
)
LEVEL_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}


class ScoringConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "impact-v1"
    weight_cap: float = Field(default=0.20, gt=0, le=1)
    relationship_weights: dict[str, float] = {
        "direct": 1.0,
        "supplier": 0.6,
        "customer": 0.6,
        "competitor": 0.4,
        "industry": 0.5,
        "sector": 0.35,
        "country": 0.4,
        "commodity": 0.5,
        "macro": 0.4,
    }
    severity_values: dict[str, float] = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}
    role_relevance: dict[str, float] = {"primary_subject": 1.0, "affected": 0.8, "counterparty": 0.6}
    direction_signs: dict[str, float] = {"positive": 1.0, "negative": -1.0, "mixed": 0.0, "neutral": 0.0}
    direction_priority: dict[str, float] = {"positive": 1.0, "negative": 1.0, "mixed": 1.0, "neutral": 0.5}
    level_thresholds: tuple[tuple[str, float], ...] = (("Critical", 50.0), ("High", 25.0), ("Medium", 10.0))


DEFAULT_CONFIG = ScoringConfig()


def level_for(priority: float, config: ScoringConfig = DEFAULT_CONFIG) -> str:
    for level, threshold in config.level_thresholds:
        if priority >= threshold:
            return level
    return "Low"


class ScoreComponent(BaseModel):
    model_config = ConfigDict(frozen=True)

    security_id: str
    ticker: str
    display_name: str
    position_line: int
    relationship_type: str
    family: str
    source_entity: str
    source_entity_role: str
    direction: str
    position_weight: float
    exposure_magnitude: float
    relationship_weight: float
    severity: str
    severity_value: float
    confidence: float
    role_relevance: float
    link_strength: float
    relevance_weight: float
    direction_sign: float
    base: float
    signed_component: float
    absolute_component: float
    position_priority: float
    position_level: str
    counted: bool
    path: str
    provenance: dict[str, str]


class ExcludedMatch(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    relationship_type: str
    reason: str


class ImpactScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    scoring_version: str
    signed_score: float
    absolute_priority: float
    impact_level: str
    net_direction: str
    components: tuple[ScoreComponent, ...]
    excluded: tuple[ExcludedMatch, ...] = ()
    affected_positions: int
    semantics: str = SCORE_SEMANTICS
    config: dict


def _r(value: float) -> float:
    return round(value + 0.0, 6)


def score_matches(
    matches: Iterable[ExposureMatch],
    *,
    severity: Severity | str,
    confidence: float,
    config: ScoringConfig = DEFAULT_CONFIG,
) -> ImpactScore:
    if not 0.0 <= confidence <= 1.0 or math.isnan(confidence):
        raise ValueError("confidence must be in [0, 1]")
    severity = Severity(severity)
    sev_value = config.severity_values[severity.value]
    raw: list[dict] = []
    excluded: list[ExcludedMatch] = []
    for m in matches:
        if m.direction is Direction.UNCERTAIN:
            excluded.append(
                ExcludedMatch(
                    ticker=m.ticker, relationship_type=m.relationship_type, reason="direction uncertain"
                )
            )
            continue
        if m.relationship_type not in config.relationship_weights:
            excluded.append(
                ExcludedMatch(
                    ticker=m.ticker,
                    relationship_type=m.relationship_type,
                    reason="relationship type not supported by scoring config",
                )
            )
            continue
        magnitude = min(max(m.position_weight, 0.0), config.weight_cap) / config.weight_cap
        rel_weight = config.relationship_weights[m.relationship_type]
        role_rel = config.role_relevance.get(m.source_entity_role, 0.0)
        relevance = role_rel * m.link_strength
        base = magnitude * rel_weight * sev_value * confidence * relevance
        sign = config.direction_signs[m.direction.value]
        absolute = base * config.direction_priority[m.direction.value]
        raw.append(
            dict(
                security_id=m.security_id,
                ticker=m.ticker,
                display_name=m.display_name,
                position_line=m.position_line,
                relationship_type=m.relationship_type,
                family=m.family,
                source_entity=m.source_entity,
                source_entity_role=m.source_entity_role,
                direction=m.direction.value,
                position_weight=m.position_weight,
                exposure_magnitude=_r(magnitude),
                relationship_weight=rel_weight,
                severity=severity.value,
                severity_value=sev_value,
                confidence=confidence,
                role_relevance=role_rel,
                link_strength=m.link_strength,
                relevance_weight=_r(relevance),
                direction_sign=sign,
                base=_r(base),
                signed_component=_r(base * sign),
                absolute_component=_r(absolute),
                position_priority=round(100 * min(absolute, 1.0), 4),
                position_level=level_for(round(100 * min(absolute, 1.0), 4), config),
                path=m.path,
                provenance=m.provenance,
                counted=False,
            )
        )

    by_position: dict[int, list[dict]] = {}
    for comp in raw:
        by_position.setdefault(comp["position_line"], []).append(comp)
    for comps in by_position.values():
        best = sorted(
            comps,
            key=lambda c: (
                -c["absolute_component"],
                c["family"] != "direct",
                c["relationship_type"],
                c["source_entity"],
            ),
        )[0]
        best["counted"] = True

    counted = [c for c in raw if c["counted"]]
    signed_sum = math.fsum(c["signed_component"] for c in counted)
    abs_sum = math.fsum(c["absolute_component"] for c in counted)
    signed_score = round(100 * max(-1.0, min(1.0, signed_sum)), 4)
    priority = round(100 * min(abs_sum, 1.0), 4)
    has_pos = any(c["signed_component"] > 0 for c in counted)
    has_neg = any(c["signed_component"] < 0 for c in counted)
    if has_pos and has_neg:
        net = "mixed"
    elif has_pos:
        net = "positive"
    elif has_neg:
        net = "negative"
    elif counted:
        net = "mixed" if any(c["direction"] == "mixed" for c in counted) else "neutral"
    else:
        net = "none"
    components = sorted(
        (ScoreComponent(**c) for c in raw),
        key=lambda c: (-c.absolute_component, not c.counted, c.ticker, c.relationship_type, c.source_entity),
    )
    return ImpactScore(
        scoring_version=config.version,
        signed_score=signed_score + 0.0,
        absolute_priority=priority,
        impact_level=level_for(priority, config),
        net_direction=net,
        components=tuple(components),
        excluded=tuple(excluded),
        affected_positions=len(by_position),
        config=config.model_dump(mode="json"),
    )
