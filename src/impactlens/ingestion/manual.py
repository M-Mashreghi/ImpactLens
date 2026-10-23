"""Manual text / explicit-URL ingestion for analysts and fixtures."""

from __future__ import annotations

from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict

from impactlens.ingestion.contracts import RawNewsItem
from impactlens.ingestion.html_text import html_to_text
from impactlens.ingestion.http import HttpFetchError, bounded_get
from impactlens.timeutil import utc_now_iso

MAX_TEXT_CHARS = 100_000
MAX_TITLE_CHARS = 500
MIN_TEXT_CHARS = 20
MANUAL_SOURCE_KEY = "manual"


class ManualInputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FetchedArticle(BaseModel):
    model_config = ConfigDict(frozen=True)
    url: str
    final_url: str
    title: str
    text: str


class ArticleFetchError(RuntimeError):
    """Structured URL fetch failure."""

    def __init__(self, url: str, error_type: str, message: str, status_code: int | None = None) -> None:
        self.url = url
        self.error_type = error_type
        self.status_code = status_code
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "error_type": self.error_type,
            "message": str(self),
            "status_code": self.status_code,
        }


class NewsContentFetcher(Protocol):
    def fetch_article(self, url: str) -> FetchedArticle: ...


class HttpArticleFetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout_seconds: float = 15.0,
        user_agent: str = "ImpactLens/1.0 (+research)",
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._user_agent = user_agent

    def fetch_article(self, url: str) -> FetchedArticle:
        try:
            response = bounded_get(self._client, url, headers={"User-Agent": self._user_agent}, retries=1)
        except HttpFetchError as exc:
            raise ArticleFetchError(url, exc.error_type, str(exc), exc.status_code) from exc
        title, text = html_to_text(response.text)
        if len(text) < MIN_TEXT_CHARS:
            raise ArticleFetchError(url, "NoContent", "fetched page contains no usable article text")
        return FetchedArticle(url=url, final_url=response.url, title=title, text=text[:MAX_TEXT_CHARS])


def build_manual_item(
    *,
    title: str,
    text: str,
    url: str | None = None,
    published_at: str | None = None,
    source_name: str = "Manual input",
    submitted_by: str | None = None,
) -> RawNewsItem:
    title = (title or "").strip()
    text = (text or "").strip()
    if not text:
        raise ManualInputError("empty_text", "news text must not be empty")
    if len(text) < MIN_TEXT_CHARS:
        raise ManualInputError("text_too_short", f"news text must be at least {MIN_TEXT_CHARS} characters")
    if len(text) > MAX_TEXT_CHARS:
        raise ManualInputError("text_too_long", f"news text exceeds {MAX_TEXT_CHARS} characters")
    if not title:
        title = text.split("\n", 1)[0][:200]
    if len(title) > MAX_TITLE_CHARS:
        raise ManualInputError("title_too_long", f"title exceeds {MAX_TITLE_CHARS} characters")
    extra = {"input": "text"}
    if submitted_by:
        extra["submitted_by"] = submitted_by
    return RawNewsItem(
        source_key=MANUAL_SOURCE_KEY,
        source_name=source_name,
        source_kind="manual",
        source_item_id=None,
        url=url,
        title=title,
        body=text,
        published_raw=published_at,
        retrieved_at=utc_now_iso(),
        extra=extra,
    )


def build_item_from_url(
    fetcher: NewsContentFetcher, url: str, *, published_at: str | None = None
) -> RawNewsItem:
    article = fetcher.fetch_article(url)
    item = build_manual_item(
        title=article.title or article.text[:120],
        text=article.text,
        url=article.final_url,
        published_at=published_at,
        source_name="Manual URL",
    )
    return item.model_copy(update={"extra": {"input": "url", "requested_url": url}})
