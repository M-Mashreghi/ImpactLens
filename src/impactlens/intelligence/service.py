"""News analysis orchestrator: pending news → LLM → schema → evidence → resolver → persist.

Outcomes per news item (persisted with model/prompt/schema versions):

* ``Valid`` analysis + news ``Resolved`` — grounded, at least one resolved impact entity.
* ``Uncertain`` — model said uncertain, evidence failed, or no impact entity resolved.
* ``Failed`` — provider/schema failure after the bounded retry policy.

No portfolio scoring happens here (Phase 4 owns scoring).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from impactlens.entities.resolver import SecurityResolver
from impactlens.intelligence.entity_pipeline import resolve_entities
from impactlens.intelligence.evidence import validate_evidence
from impactlens.intelligence.llm import (
    AnalysisRequest,
    LLMPermanentError,
    LLMTransientError,
    MalformedOutputError,
    StructuredLLMClient,
)
from impactlens.intelligence.prompt import PROMPT_VERSION, system_prompt, user_prompt
from impactlens.intelligence.taxonomy import SCHEMA_VERSION
from impactlens.logging_setup import get_logger, log_context, log_event
from impactlens.news.models import NewsRecord, NewsStatus
from impactlens.storage.repositories import AnalysisRepository, NewsRepository
from impactlens.timeutil import utc_now_iso

logger = get_logger("intelligence.service")
MAX_RAW_CHARS = 20_000


class AnalysisOutcome(BaseModel):
    news_id: int
    analysis_id: int | None
    status: str
    news_status: NewsStatus
    reasons: list[str] = []
    reused: bool = False


class AnalysisService:
    def __init__(
        self,
        client: StructuredLLMClient,
        resolver: SecurityResolver,
        news: NewsRepository,
        analyses: AnalysisRepository,
    ) -> None:
        self.client = client
        self.resolver = resolver
        self.news = news
        self.analyses = analyses

    @property
    def versions(self) -> dict[str, str]:
        return {
            "schema_version": SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "model_provider": self.client.provider.provider_name,
            "model_name": self.client.provider.model_name,
        }

    def analyze_pending(self, limit: int = 50) -> list[AnalysisOutcome]:
        outcomes = []
        for record in self.news.pending_analysis(limit):
            try:
                outcomes.append(self.analyze(record))
            except Exception as exc:  # never let one item stop the batch
                self.news.set_status(
                    record.news_id,
                    NewsStatus.FAILED,
                    error={"stage": "analysis", "error_type": type(exc).__name__, "message": str(exc)[:500]},
                )
                outcomes.append(
                    AnalysisOutcome(
                        news_id=record.news_id,
                        analysis_id=None,
                        status="Failed",
                        news_status=NewsStatus.FAILED,
                        reasons=[str(exc)[:200]],
                    )
                )
        return outcomes

    def analyze(self, record: NewsRecord) -> AnalysisOutcome:
        versions = self.versions
        with log_context(stage="analysis", news_id=record.news_id):
            existing = self.analyses.find(record.news_id, **versions)
            if existing:
                return AnalysisOutcome(
                    news_id=record.news_id,
                    analysis_id=existing["analysis_id"],
                    status=existing["status"],
                    news_status=record.ingestion_status,
                    reused=True,
                )
            text = record.analysis_text
            request = AnalysisRequest(
                news_id=record.news_id,
                content_hash=record.content_hash,
                title=record.normalized_title,
                text=text,
                system_prompt=system_prompt(),
                user_prompt=user_prompt(
                    record.normalized_title, record.normalized_text, record.published_at, record.source_name
                ),
            )
            base = {"news_id": record.news_id, **versions, "created_at": utc_now_iso()}
            try:
                attempt = self.client.analyze(request)
            except (LLMTransientError, LLMPermanentError, MalformedOutputError) as exc:
                raw = getattr(exc, "raw", None)
                analysis_id = self.analyses.insert(
                    {
                        **base,
                        "status": "Failed",
                        "attempts": self.client.max_retries + 1,
                        "raw_response": raw[:MAX_RAW_CHARS] if raw else None,
                        "failure_json": {"error_type": type(exc).__name__, "message": str(exc)[:1000]},
                    }
                )
                self.news.set_status(
                    record.news_id,
                    NewsStatus.FAILED,
                    detail={"analysis_id": analysis_id},
                    error={"stage": "analysis", "error_type": type(exc).__name__, "message": str(exc)[:500]},
                )
                log_event(
                    logger,
                    logging.WARNING,
                    "analysis failed",
                    analysis_id=analysis_id,
                    error_type=type(exc).__name__,
                )
                return AnalysisOutcome(
                    news_id=record.news_id,
                    analysis_id=analysis_id,
                    status="Failed",
                    news_status=NewsStatus.FAILED,
                    reasons=[str(exc)[:300]],
                )

            output = attempt.output
            report = validate_evidence(output, text)
            resolution = resolve_entities(output, self.resolver, set(report.supported_entities))
            reasons = list(report.reasons)
            if output.is_uncertain:
                reasons.insert(0, "model marked analysis as uncertain")
            if output.direction.value == "uncertain" and not output.is_uncertain:
                reasons.append("overall direction is uncertain")
            if report.passed and not resolution.impact_entities:
                reasons.append("no impact-relevant entity resolved to a canonical security or factor")
            status = "Valid" if not reasons else "Uncertain"
            analysis_id = self.analyses.insert(
                {
                    **base,
                    "status": status,
                    "attempts": attempt.attempts,
                    "event_type": output.event_type.value,
                    "event_summary": output.event_summary,
                    "direction": output.direction.value,
                    "severity": output.severity.value,
                    "confidence": output.confidence,
                    "time_horizon": output.time_horizon.value,
                    "analysis_json": output.model_dump(mode="json"),
                    "evidence_report_json": report.model_dump(mode="json"),
                    "resolution_json": resolution.model_dump(mode="json"),
                    "raw_response": attempt.raw[:MAX_RAW_CHARS],
                    "failure_json": {"uncertain_reasons": reasons} if reasons else None,
                }
            )
            if status == "Valid":
                self.news.set_status(record.news_id, NewsStatus.ANALYZED, detail={"analysis_id": analysis_id})
                self.news.set_status(
                    record.news_id,
                    NewsStatus.RESOLVED,
                    detail={
                        "analysis_id": analysis_id,
                        "resolved_entities": len(resolution.impact_entities),
                    },
                )
                news_status = NewsStatus.RESOLVED
            else:
                self.news.set_status(
                    record.news_id,
                    NewsStatus.UNCERTAIN,
                    detail={"analysis_id": analysis_id, "reasons": reasons[:5]},
                )
                news_status = NewsStatus.UNCERTAIN
            log_event(logger, logging.INFO, "analysis stored", analysis_id=analysis_id, status=status)
            return AnalysisOutcome(
                news_id=record.news_id,
                analysis_id=analysis_id,
                status=status,
                news_status=news_status,
                reasons=reasons,
            )
