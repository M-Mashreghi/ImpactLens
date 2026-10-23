"""Template-first, evidence-backed impact explanations.

The deterministic template path only restates validated inputs: event fields, grounded
evidence quotes, exposure paths and score components exactly as computed. Any optional
LLM prose layer must receive this object and may not change numbers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from impactlens.impact.scoring import SCORE_SEMANTICS, ImpactScore, ScoreComponent
from impactlens.intelligence.taxonomy import EVENT_TYPE_LABELS, EventType

RELATIONSHIP_LABELS = {
    "direct": "Direct holding",
    "supplier": "Supplier relationship",
    "customer": "Customer relationship",
    "competitor": "Competitor relationship",
    "sector": "Sector peer",
    "industry": "Industry peer",
    "country": "Country / geographic exposure",
    "commodity": "Commodity exposure",
    "macro": "Macro factor exposure",
}


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_id: int
    quote: str
    source_name: str
    source_url: str | None
    published_at: str | None
    published_at_quality: str
    content_hash: str


class PositionExplanation(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    relationship: str
    path: str
    direction: str
    counted: bool
    text: str
    numbers: dict[str, float]
    citations: tuple[Citation, ...]


class ImpactExplanation(BaseModel):
    model_config = ConfigDict(frozen=True)
    headline: str
    event_line: str
    positions: tuple[PositionExplanation, ...]
    citations: tuple[Citation, ...]
    disclaimer: str = SCORE_SEMANTICS
    method: str = "template-v1"


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _position_text(c: ScoreComponent) -> str:
    rel = RELATIONSHIP_LABELS.get(c.relationship_type, c.relationship_type)
    counted = "" if c.counted else " (shown for transparency; a stronger path is counted for this position)"
    return (
        f"{c.ticker} ({c.display_name}) — {rel}: {c.path}. Direction for this position: {c.direction}. "
        f"Weight {_pct(c.position_weight)} → exposure magnitude {c.exposure_magnitude:.4f}; "
        f"relationship weight {c.relationship_weight:.2f}; severity {c.severity} ({c.severity_value:.2f}); "
        f"confidence {c.confidence:.2f}; relevance {c.relevance_weight:.4f}. "
        f"Component {c.signed_component:+.6f} (priority {c.position_priority:.2f}, {c.position_level}){counted}."
    )


def build_explanation(
    *,
    score: ImpactScore,
    analysis: dict,
    news: dict,
) -> ImpactExplanation:
    """``analysis`` is the stored validated analysis JSON; ``news`` the news record dict."""
    report = analysis.get("evidence_report") or {}
    grounded = {s["id"] for s in report.get("spans", []) if s.get("grounded")}
    spans = {e["id"]: e for e in analysis["analysis"]["evidence"] if e["id"] in grounded}
    entity_evidence = {e["name"]: tuple(e.get("evidence_ids", ())) for e in analysis["analysis"]["entities"]}

    def cite(ids: tuple[int, ...] | list[int]) -> tuple[Citation, ...]:
        return tuple(
            Citation(
                evidence_id=i,
                quote=spans[i]["quote"],
                source_name=news["source_name"],
                source_url=news.get("source_url"),
                published_at=news.get("published_at"),
                published_at_quality=news["published_at_quality"],
                content_hash=news["content_hash"],
            )
            for i in sorted(set(ids))
            if i in spans
        )

    positions = tuple(
        PositionExplanation(
            ticker=c.ticker,
            relationship=RELATIONSHIP_LABELS.get(c.relationship_type, c.relationship_type),
            path=c.path,
            direction=c.direction,
            counted=c.counted,
            text=_position_text(c),
            numbers={
                "position_weight": c.position_weight,
                "exposure_magnitude": c.exposure_magnitude,
                "relationship_weight": c.relationship_weight,
                "severity_value": c.severity_value,
                "confidence": c.confidence,
                "relevance_weight": c.relevance_weight,
                "signed_component": c.signed_component,
                "absolute_component": c.absolute_component,
                "position_priority": c.position_priority,
            },
            citations=cite(entity_evidence.get(c.source_entity, ())),
        )
        for c in score.components
    )
    event_type = analysis["event_type"]
    label = EVENT_TYPE_LABELS.get(EventType(event_type), event_type)
    headline = (
        f"Portfolio impact priority {score.impact_level.upper()} ({score.absolute_priority:.2f}/100, "
        f"signed {score.signed_score:+.2f}) across {score.affected_positions} position(s)"
    )
    event_line = (
        f"{label}: {analysis['event_summary']} — direction {analysis['direction']}, severity "
        f"{analysis['severity']}, model confidence {analysis['confidence']:.2f}, horizon {analysis['time_horizon']}."
    )
    return ImpactExplanation(
        headline=headline,
        event_line=event_line,
        positions=positions,
        citations=cite(list(spans)),
    )
