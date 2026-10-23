"""Ingestion orchestrator: adapters → normalize → dedup → persist, idempotently."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from impactlens.ingestion.contracts import (
    AdapterRegistry,
    NewsSourceAdapter,
    RawNewsItem,
    SourceCursor,
    SourceFetchError,
)
from impactlens.logging_setup import get_logger, log_context, log_event
from impactlens.news.models import NewsRecord, NewsStatus
from impactlens.news.normalize import normalize_item
from impactlens.storage.repositories import CheckpointRepository, NewsRepository

logger = get_logger("ingestion.service")


class IngestOutcome(BaseModel):
    news_id: int
    status: NewsStatus
    canonical_news_id: int | None = None
    duplicate: bool = False


class SourcePollSummary(BaseModel):
    source_key: str
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    item_errors: int = 0
    failed: bool = False
    error: str | None = None
    not_modified: bool = False
    new_news_ids: list[int] = Field(default_factory=list)


class IngestionService:
    def __init__(self, news: NewsRepository, checkpoints: CheckpointRepository) -> None:
        self.news = news
        self.checkpoints = checkpoints

    def ingest_item(self, item: RawNewsItem) -> IngestOutcome:
        normalized = normalize_item(item)
        existing = self.news.find_duplicate(normalized)
        if existing is not None:
            # A repeated poll of an item we already hold creates nothing new.
            if (
                existing.source_name == normalized.source_name
                and normalized.source_item_id
                and existing.source_item_id == normalized.source_item_id
            ):
                return IngestOutcome(
                    news_id=existing.news_id,
                    status=existing.ingestion_status,
                    canonical_news_id=None,
                    duplicate=True,
                )
            if (
                existing.content_hash == normalized.content_hash
                and existing.source_name == normalized.source_name
                and existing.canonical_url == normalized.canonical_url
            ):
                return IngestOutcome(
                    news_id=existing.news_id, status=existing.ingestion_status, duplicate=True
                )
            record = self.news.insert(normalized, NewsStatus.DUPLICATE, canonical_news_id=existing.news_id)
            log_event(
                logger,
                logging.INFO,
                "duplicate news linked",
                news_id=record.news_id,
                canonical_news_id=existing.news_id,
            )
            return IngestOutcome(
                news_id=record.news_id,
                status=NewsStatus.DUPLICATE,
                canonical_news_id=existing.news_id,
                duplicate=True,
            )
        record = self.news.insert(normalized, NewsStatus.PENDING_ANALYSIS)
        log_event(
            logger,
            logging.INFO,
            "news ingested",
            news_id=record.news_id,
            ts_quality=record.published_at_quality.value,
        )
        return IngestOutcome(news_id=record.news_id, status=record.ingestion_status)

    def poll_source(self, adapter: NewsSourceAdapter) -> SourcePollSummary:
        summary = SourcePollSummary(source_key=adapter.key)
        with log_context(stage="ingestion", source=adapter.key):
            cursor = self.checkpoints.get(adapter.key) or SourceCursor(source_key=adapter.key)
            try:
                result = adapter.fetch(cursor)
            except SourceFetchError as exc:
                self.checkpoints.record_failure(adapter.key, None, "fetch", exc.error_type, str(exc))
                log_event(logger, logging.WARNING, "source fetch failed", error_type=exc.error_type)
                summary.failed, summary.error = True, str(exc)
                return summary
            except Exception as exc:  # adapter bug: isolate to this source
                self.checkpoints.record_failure(adapter.key, None, "fetch", type(exc).__name__, str(exc))
                log_event(logger, logging.ERROR, "source adapter crashed", error_type=type(exc).__name__)
                summary.failed, summary.error = True, f"{type(exc).__name__}: {exc}"
                return summary
            summary.not_modified = result.not_modified
            for err in result.errors:
                self.checkpoints.record_failure(
                    adapter.key, err.item_ref, "parse", err.error_type, err.message
                )
                summary.item_errors += 1
            for item in result.items:
                summary.fetched += 1
                try:
                    outcome = self.ingest_item(item)
                except Exception as exc:  # one bad item never loses the others
                    self.checkpoints.record_failure(
                        adapter.key, item.source_item_id, "normalize", type(exc).__name__, str(exc)
                    )
                    summary.item_errors += 1
                    continue
                if outcome.duplicate:
                    summary.duplicates += 1
                else:
                    summary.new += 1
                    summary.new_news_ids.append(outcome.news_id)
            if result.cursor is not None:
                self.checkpoints.save(result.cursor)
            log_event(
                logger,
                logging.INFO,
                "source polled",
                fetched=summary.fetched,
                new=summary.new,
                duplicates=summary.duplicates,
                item_errors=summary.item_errors,
            )
        return summary

    def poll_all(self, registry: AdapterRegistry) -> list[SourcePollSummary]:
        return [self.poll_source(adapter) for adapter in registry.enabled_adapters()]

    def get(self, news_id: int) -> NewsRecord | None:
        return self.news.get(news_id)
