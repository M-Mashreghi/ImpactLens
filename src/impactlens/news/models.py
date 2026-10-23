"""Canonical news record and lifecycle states."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class NewsStatus(StrEnum):
    DISCOVERED = "Discovered"
    FETCHED = "Fetched"
    NORMALIZED = "Normalized"
    DUPLICATE = "Duplicate"
    PENDING_ANALYSIS = "PendingAnalysis"
    ANALYZED = "Analyzed"
    UNCERTAIN = "Uncertain"
    RESOLVED = "Resolved"
    SCORED = "Scored"
    ALERTED = "Alerted"
    FAILED = "Failed"


class TimestampQuality(StrEnum):
    EXACT = "exact"  # explicit date, time and offset
    ASSUMED_UTC = "assumed_utc"  # date and time without offset; UTC assumed
    DATE_ONLY = "date_only"  # calendar date only
    MISSING = "missing"  # no publication time supplied; retrieval time retained
    INVALID = "invalid"  # unparseable; retrieval time retained
    SUSPECT_FUTURE = "suspect_future"  # later than retrieval time (clock/feed error)

    @property
    def reliable(self) -> bool:
        return self is TimestampQuality.EXACT


class NormalizedNews(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_key: str
    source_name: str
    source_kind: str
    source_item_id: str | None
    source_url: str | None
    canonical_url: str | None
    title: str
    normalized_title: str
    body_text: str
    normalized_text: str
    published_at: str | None
    published_at_quality: TimestampQuality
    retrieved_at: str
    content_hash: str
    provenance: dict[str, str] = Field(default_factory=dict)


class NewsRecord(NormalizedNews):
    news_id: int
    canonical_news_id: int | None = None
    ingestion_status: NewsStatus
    error: dict | None = None
    status_updated_at: str

    @property
    def event_time(self) -> str:
        """Best available event timestamp: publication time, else retrieval time (flagged)."""
        return self.published_at or self.retrieved_at

    @property
    def analysis_text(self) -> str:
        """Text given to the analyzer and used for evidence validation."""
        if self.normalized_text and self.normalized_text != self.normalized_title:
            return f"{self.normalized_title}\n\n{self.normalized_text}"
        return self.normalized_title
