"""Portfolio impact orchestrator: resolved analysis + snapshot → exposures → score → persist."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from impactlens.impact.explanation import build_explanation
from impactlens.impact.exposure import RULES_VERSION, ExposureEngine
from impactlens.impact.scoring import DEFAULT_CONFIG, ScoringConfig, score_matches
from impactlens.intelligence.entity_pipeline import ResolutionSummary
from impactlens.logging_setup import get_logger, log_context, log_event
from impactlens.news.models import NewsStatus
from impactlens.portfolio.models import PortfolioSnapshot
from impactlens.storage.repositories import (
    AnalysisRepository,
    ImpactRepository,
    NewsRepository,
    NotFoundError,
)
from impactlens.timeutil import utc_now_iso

logger = get_logger("impact.service")


class ImpactOutcome(BaseModel):
    impact_id: int
    analysis_id: int
    snapshot_id: str
    impact_level: str
    absolute_priority: float
    signed_score: float
    reused: bool = False


class ImpactService:
    def __init__(
        self,
        engine: ExposureEngine,
        news: NewsRepository,
        analyses: AnalysisRepository,
        impacts: ImpactRepository,
        config: ScoringConfig = DEFAULT_CONFIG,
    ) -> None:
        self.engine = engine
        self.news = news
        self.analyses = analyses
        self.impacts = impacts
        self.config = config

    def score(self, analysis_id: int, snapshot: PortfolioSnapshot, *, force: bool = False) -> ImpactOutcome:
        analysis = self.analyses.get(analysis_id)
        if analysis is None:
            raise NotFoundError(f"analysis {analysis_id} not found")
        if analysis["status"] != "Valid":
            raise ValueError(
                f"analysis {analysis_id} is {analysis['status']}; only Valid analyses are scored"
            )
        with log_context(
            stage="impact",
            news_id=analysis["news_id"],
            snapshot_id=snapshot.snapshot_id,
            analysis_id=analysis_id,
        ):
            existing = self.impacts.find(analysis_id, snapshot.snapshot_id, self.config.version)
            if existing and not force:
                return ImpactOutcome(
                    impact_id=existing["impact_id"],
                    analysis_id=analysis_id,
                    snapshot_id=snapshot.snapshot_id,
                    impact_level=existing["impact_level"],
                    absolute_priority=existing["absolute_priority"],
                    signed_score=existing["signed_score"],
                    reused=True,
                )
            news = self.news.get(analysis["news_id"])
            assert news is not None
            resolution = ResolutionSummary.model_validate(analysis["resolution"])
            matches = self.engine.match(resolution.impact_entities, snapshot)
            score = score_matches(
                matches, severity=analysis["severity"], confidence=analysis["confidence"], config=self.config
            )
            explanation = build_explanation(score=score, analysis=analysis, news=news.model_dump(mode="json"))
            result = {
                **score.model_dump(mode="json"),
                "rules_version": RULES_VERSION,
                "portfolio_id": snapshot.portfolio_id,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_as_of": snapshot.as_of,
                "analysis_versions": {
                    k: analysis[k]
                    for k in ("schema_version", "prompt_version", "model_provider", "model_name")
                },
            }
            impact_id = self.impacts.upsert(
                {
                    "analysis_id": analysis_id,
                    "news_id": analysis["news_id"],
                    "snapshot_id": snapshot.snapshot_id,
                    "scoring_version": self.config.version,
                    "rules_version": RULES_VERSION,
                    "signed_score": score.signed_score,
                    "absolute_priority": score.absolute_priority,
                    "impact_level": score.impact_level,
                    "result": result,
                    "explanation": explanation.model_dump(mode="json"),
                    "computed_at": utc_now_iso(),
                },
                [c.model_dump(mode="json") for c in score.components],
            )
            if news.ingestion_status in (NewsStatus.RESOLVED,):
                self.news.set_status(news.news_id, NewsStatus.SCORED, detail={"impact_id": impact_id})
            log_event(
                logger,
                logging.INFO,
                "impact scored",
                impact_id=impact_id,
                level=score.impact_level,
                positions=score.affected_positions,
            )
            return ImpactOutcome(
                impact_id=impact_id,
                analysis_id=analysis_id,
                snapshot_id=snapshot.snapshot_id,
                impact_level=score.impact_level,
                absolute_priority=score.absolute_priority,
                signed_score=score.signed_score,
            )

    def feed(
        self,
        snapshot_id: str | None = None,
        *,
        min_level: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        return self.impacts.feed(snapshot_id=snapshot_id, min_level=min_level, limit=limit, offset=offset)
