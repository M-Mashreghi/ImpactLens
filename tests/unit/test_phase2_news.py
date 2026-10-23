"""Tasks 2.1–2.5: adapters, RSS, manual ingestion, normalization/dedup, orchestration."""

from __future__ import annotations

import httpx
import pytest

from impactlens.ingestion.contracts import AdapterRegistry, RawNewsItem, SourceCursor
from impactlens.ingestion.fake import FakeNewsAdapter
from impactlens.ingestion.manual import (
    ArticleFetchError,
    HttpArticleFetcher,
    ManualInputError,
    build_item_from_url,
    build_manual_item,
)
from impactlens.ingestion.rss import RssFeedAdapter, parse_feed
from impactlens.news.models import NewsStatus, TimestampQuality
from impactlens.news.normalize import (
    canonicalize_url,
    content_hash,
    normalize_item,
    normalize_text,
    parse_published,
)
from tests.conftest import FIXTURES

NOW = "2025-03-03T15:00:00Z"


def item(item_id: str, title: str = "Title", body: str = "Body text for the article.", **kw) -> RawNewsItem:
    return RawNewsItem(
        source_key=kw.pop("source_key", "src"),
        source_name=kw.pop("source_name", "Src"),
        source_item_id=item_id,
        title=title,
        body=body,
        retrieved_at=kw.pop("retrieved_at", NOW),
        **kw,
    )


# ----------------------------------------------------------------------------- 2.1


def test_registry_resolves_by_key_and_skips_disabled():
    registry = AdapterRegistry()
    a, b, c = FakeNewsAdapter("a"), FakeNewsAdapter("b"), FakeNewsAdapter("c")
    registry.register(b, priority=2)
    registry.register(a, priority=1)
    registry.register(c, enabled=False)
    assert registry.get("a") is a and registry.get("c") is c
    assert [x.key for x in registry.enabled_adapters()] == ["a", "b"]
    with pytest.raises(ValueError):
        registry.register(FakeNewsAdapter("a"))
    with pytest.raises(KeyError):
        registry.get("missing")


def test_disabled_adapter_is_not_polled(container):
    registry = AdapterRegistry()
    off = FakeNewsAdapter("off", [item("1")])
    registry.register(off, enabled=False)
    assert container.ingestion.poll_all(registry) == []
    assert off.calls == 0


def test_fake_adapter_follows_contract():
    adapter = FakeNewsAdapter("fx", [item("1"), item("2")])
    first = adapter.fetch(None)
    assert len(first.items) == 2 and set(first.cursor.seen_item_ids) == {"1", "2"}
    assert adapter.fetch(first.cursor).items == ()


# ----------------------------------------------------------------------------- 2.2


def test_fixture_rss_parses_expected_records_and_isolates_bad_item():
    xml = (FIXTURES / "feeds" / "sample_rss.xml").read_text()
    items, errors = parse_feed(xml, "rss", "Example RSS", NOW)
    assert [i.source_item_id for i in items] == ["guid-001", "guid-002"]
    assert items[0].title == "Chipmaker shares fall on export news"
    assert items[0].published_raw == "Mon, 03 Mar 2025 14:05:00 +0000"
    assert "<p>" not in items[0].body
    assert len(errors) == 1 and errors[0].item_ref == "index:1"


def test_atom_feed_parses():
    xml = (FIXTURES / "feeds" / "sample_atom.xml").read_text()
    items, errors = parse_feed(xml, "atom", "Example Atom", NOW)
    assert (
        not errors
        and items[0].url == "https://example.com/a/1"
        and items[0].source_item_id == "tag:example,1"
    )


def test_feed_with_doctype_is_rejected():
    from impactlens.ingestion.contracts import SourceFetchError

    with pytest.raises(SourceFetchError):
        parse_feed('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss><channel/></rss>', "k", "n", NOW)


def _transport(xml: str, calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text=xml, headers={"ETag": '"v1"'})

    return httpx.MockTransport(handler)


def test_rss_repoll_uses_checkpoint_and_is_idempotent(container):
    xml = (FIXTURES / "feeds" / "sample_rss.xml").read_text()
    calls: list = []
    adapter = RssFeedAdapter(
        "rss", "https://feeds.example.com/rss", client=httpx.Client(transport=_transport(xml, calls))
    )
    first = container.ingestion.poll_source(adapter)
    assert first.new == 2 and first.item_errors == 1
    second = container.ingestion.poll_source(adapter)
    assert second.not_modified and second.new == 0
    assert calls[1].headers["if-none-match"] == '"v1"'
    assert container.news.count() == 2


def test_rss_timeout_retries_then_records_failure(container):
    attempts = []

    def handler(request):
        attempts.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    adapter = RssFeedAdapter(
        "slow",
        "https://feeds.example.com/slow",
        retries=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    import impactlens.ingestion.http as http_mod

    original = http_mod.time.sleep
    http_mod.time.sleep = lambda s: None
    try:
        summary = container.ingestion.poll_source(adapter)
    finally:
        http_mod.time.sleep = original
    assert summary.failed and "Timeout" in summary.error
    assert len(attempts) == 2
    assert container.checkpoints.failures()[0]["error_type"] == "Timeout"


# ----------------------------------------------------------------------------- 2.3


def test_manual_text_creates_canonical_record(container):
    raw = build_manual_item(
        title="Manual headline",
        text="Some sufficiently long manual news text.",
        published_at="2025-03-03T10:00:00Z",
    )
    outcome = container.ingestion.ingest_item(raw)
    record = container.news.get(outcome.news_id)
    assert record.source_kind == "manual" and record.ingestion_status is NewsStatus.PENDING_ANALYSIS
    assert record.provenance["input"] == "text" and record.content_hash.startswith("sha256:")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "empty_text"),
        ("   ", "empty_text"),
        ("short", "text_too_short"),
        ("x" * 100_001, "text_too_long"),
    ],
)
def test_invalid_manual_input_rejected(text, code):
    with pytest.raises(ManualInputError) as exc:
        build_manual_item(title="t", text=text)
    assert exc.value.code == code


def test_url_fetch_failure_returns_structured_error():
    fetcher = HttpArticleFetcher(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    )
    with pytest.raises(ArticleFetchError) as exc:
        build_item_from_url(fetcher, "https://example.com/missing")
    assert exc.value.to_dict()["error_type"] == "HttpStatus" and exc.value.status_code == 404
    with pytest.raises(ArticleFetchError) as exc:
        fetcher.fetch_article("file:///etc/passwd")
    assert exc.value.error_type == "InvalidUrl"


def test_url_fetch_extracts_text_not_scripts():
    html = "<html><head><title>T</title><script>evil()</script></head><body><p>Real article body text here.</p></body></html>"
    fetcher = HttpArticleFetcher(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html)))
    )
    raw = build_item_from_url(fetcher, "https://example.com/a")
    assert "evil" not in raw.body and "Real article body" in raw.body and raw.title == "T"


# ----------------------------------------------------------------------------- 2.4


def test_equivalent_articles_hash_equal_distinct_differ():
    a = normalize_item(item("1", "Chip  rules—tighten", "Line one.\n\n\nLine   two."))
    b = normalize_item(item("2", "chip rules-tighten", "Line one.\nLine two."))
    c = normalize_item(item("3", "chip rules-tighten", "Line one.\nLine three."))
    assert a.content_hash == b.content_hash
    assert a.content_hash != c.content_hash
    assert content_hash("x", "y") == content_hash("x", "y")


def test_url_canonicalization():
    assert (
        canonicalize_url("HTTPS://News.Example.com:443/a/b/?utm_source=x&b=2&a=1#frag")
        == "https://news.example.com/a/b?a=1&b=2"
    )
    assert canonicalize_url("javascript:alert(1)") is None
    assert canonicalize_url(None) is None


@pytest.mark.parametrize(
    ("raw", "quality", "value"),
    [
        ("Mon, 03 Mar 2025 14:05:00 +0000", TimestampQuality.EXACT, "2025-03-03T14:05:00Z"),
        ("2025-03-03T09:05:00-05:00", TimestampQuality.EXACT, "2025-03-03T14:05:00Z"),
        ("2025-03-03T14:05:00", TimestampQuality.ASSUMED_UTC, "2025-03-03T14:05:00Z"),
        ("2025-03-03", TimestampQuality.DATE_ONLY, "2025-03-03T00:00:00Z"),
        (None, TimestampQuality.MISSING, None),
        ("yesterday-ish", TimestampQuality.INVALID, None),
        ("2030-01-01T00:00:00Z", TimestampQuality.SUSPECT_FUTURE, "2030-01-01T00:00:00Z"),
    ],
)
def test_timestamp_parser_and_quality(raw, quality, value):
    assert parse_published(raw, NOW) == (value, quality)


def test_missing_publication_time_keeps_retrieval_time_and_is_flagged(container):
    outcome = container.ingestion.ingest_item(item("x", published_raw=None))
    record = container.news.get(outcome.news_id)
    assert record.published_at is None and record.retrieved_at == NOW
    assert record.published_at_quality is TimestampQuality.MISSING and record.event_time == NOW


def test_duplicate_links_to_canonical_record(container):
    first = container.ingestion.ingest_item(
        item("a1", "Same story", "Identical body text.", source_name="Wire A")
    )
    dup = container.ingestion.ingest_item(
        item("b7", "Same story", "Identical body text.", source_name="Wire B")
    )
    assert dup.duplicate and dup.status is NewsStatus.DUPLICATE and dup.canonical_news_id == first.news_id
    url_dup = container.ingestion.ingest_item(
        item("c1", "Different words", "Other body.", source_name="Wire C", url="https://x.com/s?utm_medium=e")
    )
    url_dup2 = container.ingestion.ingest_item(
        item("d1", "Different words 2", "Other body 2.", source_name="Wire D", url="https://X.com/s")
    )
    assert url_dup2.canonical_news_id == url_dup.news_id
    assert container.news.duplicates_of(first.news_id) == [dup.news_id]


def test_normalize_text_folds_typography():
    assert normalize_text("A “quote”  – dash") == 'A "quote" - dash'


# ----------------------------------------------------------------------------- 2.5


def test_orchestrator_first_poll_persists_second_creates_nothing(container):
    items = [item("1", "One", "First body text."), item("2", "Two", "Second body text.")]
    adapter = FakeNewsAdapter("fx", items)
    first = container.ingestion.poll_source(adapter)
    assert (first.new, first.duplicates) == (2, 0)
    # A fresh adapter instance without memory, but same items: checkpoint + dedup keep it idempotent.
    again = container.ingestion.poll_source(FakeNewsAdapter("fx", items))
    assert again.new == 0
    no_cursor = FakeNewsAdapter("fx2", items)
    third = container.ingestion.poll_source(no_cursor)
    assert third.new == 0 and third.duplicates == 2
    assert container.news.count(canonical_only=True) == 2


def test_one_bad_item_does_not_lose_successful_items(container):
    bad = item("bad", title=" ")  # empty after normalization
    adapter = FakeNewsAdapter(
        "fx", [item("1", "Good one", "Body one text."), bad, item("2", "Good two", "B2 text.")]
    )
    summary = container.ingestion.poll_source(adapter)
    assert summary.new == 2 and summary.item_errors == 1
    assert container.checkpoints.failures()[0]["stage"] == "normalize"


def test_source_failure_is_isolated(container):
    registry = AdapterRegistry()
    registry.register(FakeNewsAdapter("down", fail_with="503"))
    registry.register(FakeNewsAdapter("up", [item("1", "Alive", "Alive body text.")]))
    results = {r.source_key: r for r in container.ingestion.poll_all(registry)}
    assert results["down"].failed and results["up"].new == 1


def test_state_history_is_recorded(container):
    outcome = container.ingestion.ingest_item(item("h", "History", "History body text."))
    states = [h["status"] for h in container.news.history(outcome.news_id)]
    assert states == ["Discovered", "Fetched", "Normalized", "PendingAnalysis"]


def test_checkpoint_cursor_is_bounded():
    cursor = SourceCursor(source_key="k", max_seen=3).with_seen(["a", "b", "c", "d"])
    assert len(cursor.seen_item_ids) == 3
