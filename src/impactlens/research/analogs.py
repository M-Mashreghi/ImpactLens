"""Historical analog retrieval with transparent similarity components (``analog-v1``).

Similarity = Σ weight × component, components in [0, 1]:

* event_type   1 if same event type
* issuer       Jaccard overlap of resolved issuers
* sector       Jaccard overlap of sectors of resolved securities/sector entities
* direction    1 if same overall direction
* severity     1 − |ordinal difference| / 3
* horizon      1 if same time horizon

Eligibility (no look-ahead): a candidate's news must be published strictly before the
query event's time (``cutoff``) and must not be the query itself.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from impactlens.intelligence.taxonomy import SEVERITY_ORDINAL, Severity
from impactlens.timeutil import parse_iso

ANALOG_VERSION = "analog-v1"
WEIGHTS = {
    "event_type": 0.40,
    "issuer": 0.25,
    "sector": 0.15,
    "direction": 0.10,
    "severity": 0.05,
    "horizon": 0.05,
}


class AnalogFeatures(BaseModel):
    model_config = ConfigDict(frozen=True)
    analysis_id: int
    news_id: int
    event_time: str
    event_type: str
    direction: str
    severity: str
    time_horizon: str
    issuers: frozenset[str]
    sectors: frozenset[str]
    title: str = ""


class Analog(BaseModel):
    model_config = ConfigDict(frozen=True)
    analysis_id: int
    news_id: int
    event_time: str
    title: str
    similarity: float
    components: dict[str, float]
    weights: dict[str, float]


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(query: AnalogFeatures, cand: AnalogFeatures) -> tuple[float, dict[str, float]]:
    comps = {
        "event_type": float(query.event_type == cand.event_type),
        "issuer": _jaccard(query.issuers, cand.issuers),
        "sector": _jaccard(query.sectors, cand.sectors),
        "direction": float(query.direction == cand.direction),
        "severity": 1
        - abs(SEVERITY_ORDINAL[Severity(query.severity)] - SEVERITY_ORDINAL[Severity(cand.severity)]) / 3,
        "horizon": float(query.time_horizon == cand.time_horizon),
    }
    comps = {k: round(v, 6) for k, v in comps.items()}
    return round(sum(WEIGHTS[k] * v for k, v in comps.items()), 6), comps


def find_analogs(
    query: AnalogFeatures, candidates: list[AnalogFeatures], *, limit: int = 5, min_similarity: float = 0.0
) -> list[Analog]:
    cutoff = parse_iso(query.event_time)
    out = []
    for cand in candidates:
        if cand.news_id == query.news_id or parse_iso(cand.event_time) >= cutoff:
            continue  # current and future events are never eligible
        score, comps = similarity(query, cand)
        if score >= min_similarity:
            out.append(
                Analog(
                    analysis_id=cand.analysis_id,
                    news_id=cand.news_id,
                    event_time=cand.event_time,
                    title=cand.title,
                    similarity=score,
                    components=comps,
                    weights=WEIGHTS,
                )
            )
    out.sort(key=lambda a: (-a.similarity, a.event_time, a.analysis_id))
    return out[:limit]
