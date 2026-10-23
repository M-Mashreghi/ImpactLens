"""Request/response DTOs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class PortfolioImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    csv_text: str = Field(min_length=1, max_length=1_000_000)
    as_of: str | None = None
    base_currency: str = Field(default="USD", min_length=3, max_length=3)


class PositionOut(BaseModel):
    line_no: int
    security_id: str | None
    ticker: str
    exchange: str | None
    display_name: str
    asset_type: str
    quantity: float | None
    market_value: float | None
    weight: float
    currency: str


class SnapshotOut(BaseModel):
    snapshot_id: str
    portfolio_id: str
    as_of: str
    created_at: str
    source: str
    weight_basis: str
    total_market_value: float | None
    content_hash: str
    positions: list[PositionOut]


class PortfolioOut(BaseModel):
    portfolio_id: str
    name: str
    base_currency: str
    created_at: str
    latest_snapshot_id: str | None = None


class ImportResult(BaseModel):
    snapshot: SnapshotOut
    warnings: list[str]


class ManualNewsRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=100_000)
    url: str | None = Field(default=None, max_length=2000)
    published_at: str | None = None
    fetch_url: bool = False
    analyze: bool = True


class NewsOut(BaseModel):
    news_id: int
    source_name: str
    source_kind: str
    source_url: str | None
    canonical_url: str | None
    title: str
    published_at: str | None
    published_at_quality: str
    retrieved_at: str
    content_hash: str
    canonical_news_id: int | None
    ingestion_status: str


class NewsDetail(NewsOut):
    normalized_text: str
    provenance: dict
    history: list[dict]
    duplicates: list[int]
    analysis: dict | None


class IngestResponse(BaseModel):
    news_id: int
    status: str
    duplicate: bool
    canonical_news_id: int | None
    analysis: dict | None = None


class ScoreRequest(BaseModel):
    analysis_id: int
    snapshot_id: str
    force: bool = False


class EventStudyRequest(BaseModel):
    news_id: int
    as_of: str | None = None
