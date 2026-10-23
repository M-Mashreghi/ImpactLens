"""Task 7.1: end-to-end pipeline and regression suite (deterministic fakes, no network)."""

from __future__ import annotations

import json

import pytest

from impactlens.ingestion.contracts import AdapterRegistry
from impactlens.ingestion.fake import FakeNewsAdapter
from impactlens.ingestion.samples import load_sample_news
from impactlens.jobs.workflow import run_cycle
from impactlens.research.pit import LookAheadViolation
from tests.conftest import FIXTURES, SAMPLES

GOLDEN = FIXTURES / "golden_impacts.json"


@pytest.fixture
def pipeline(container, demo_snapshot):
    container.registry = AdapterRegistry()
    container.registry.register(FakeNewsAdapter("demo", load_sample_news(SAMPLES / "news")))
    summary = run_cycle(container)
    for news in container.news.list(limit=100, include_duplicates=False):
        if news.ingestion_status.value in {"Scored", "Alerted"}:
            container.research.run_event_studies(news.news_id, as_of="2025-03-31T21:00:00Z")
    return container, demo_snapshot, summary


def by_title(container, fragment):
    return next(n for n in container.news.list(limit=100, include_duplicates=False) if fragment in n.title)


def test_unique_article_scores_and_alerts(pipeline):
    c, snap, _ = pipeline
    news = by_title(c, "US tightens export rules")
    assert news.ingestion_status.value == "Alerted"
    impact = c.impact_service.feed(snap.snapshot_id)[0]
    assert impact["news_id"] == news.news_id and impact["impact_level"] == "Critical"
    alert = next(a for a in c.alerts.list() if a["news_id"] == news.news_id)
    assert alert["status"] == "sent"


def test_duplicate_is_linked_and_never_analyzed(pipeline):
    c, _, _ = pipeline
    dup = next(n for n in c.news.list(limit=100) if n.source_name == "Demo Syndication Wire")
    assert dup.ingestion_status.value == "Duplicate" and dup.canonical_news_id is not None
    assert c.analyses.latest_for_news(dup.news_id) is None


@pytest.mark.parametrize("fragment", ["Unconfirmed chatter", "Apple supplier update"])
def test_uncertain_paths_produce_no_impact(pipeline, fragment):
    c, _, _ = pipeline
    news = by_title(c, fragment)
    assert news.ingestion_status.value == "Uncertain"
    assert all(i["news_id"] != news.news_id for i in c.impacts.list_all())


def test_unresolved_entity_path(pipeline):
    c, _, _ = pipeline
    news = by_title(c, "Zephyr Robotics")
    analysis = c.analyses.latest_for_news(news.news_id)
    assert analysis["status"] == "Uncertain"
    assert analysis["resolution"]["entities"][0]["status"] == "Unresolved"
    assert analysis["resolution"]["entities"][0]["security_ids"] == []


def test_event_study_path(pipeline):
    c, _, _ = pipeline
    news = by_title(c, "US tightens export rules")
    studies = {s["security_id"]: s["result"] for s in c.studies.for_news(news.news_id)}
    nvda = studies["sec_nvda"]
    assert nvda["alignment"]["session"] == "pre_open" and nvda["alignment"]["anchor_date"] == "2025-03-03"
    w01 = nvda["windows"][0]
    assert w01["status"] == "ok" and w01["abnormal_return"] < 0
    oil = by_title(c, "Oil prices jump")
    xom = {s["security_id"]: s["result"] for s in c.studies.for_news(oil.news_id)}["sec_xom"]
    assert xom["alignment"]["session"] == "after_close" and xom["alignment"]["anchor_date"] == "2025-03-10"


def _golden_view(c):
    rows = []
    for impact in c.impacts.list_all():
        news = c.news.get(impact["news_id"])
        rows.append(
            {
                "title": news.title,
                "scoring_version": impact["scoring_version"],
                "level": impact["impact_level"],
                "absolute_priority": impact["absolute_priority"],
                "signed_score": impact["signed_score"],
                "components": [
                    [x["ticker"], x["relationship_type"], x["signed_component"], x["counted"]]
                    for x in impact["result"]["components"]
                ],
            }
        )
    return sorted(rows, key=lambda r: r["title"])


def test_regression_scores_match_golden_fixture(pipeline):
    c, _, _ = pipeline
    view = _golden_view(c)
    if not GOLDEN.exists():  # pragma: no cover - bootstrap only
        GOLDEN.write_text(json.dumps(view, indent=2) + "\n")
    assert view == json.loads(GOLDEN.read_text()), (
        "scoring output changed: bump scoring version and update golden"
    )


def test_regression_score_determinism_across_fresh_runs(pipeline, settings, tmp_path):
    from impactlens.app import Container
    from impactlens.intelligence.llm import FixtureLLMProvider
    from impactlens.market.provider import CsvMarketDataProvider

    c, _, _ = pipeline
    other_settings = settings.model_copy(
        update={"database": settings.database.model_copy(update={"path": str(tmp_path / "second.db")})}
    )
    c2 = Container(
        other_settings,
        llm_provider=FixtureLLMProvider.from_directory(SAMPLES / "analyses"),
        market_provider=CsvMarketDataProvider(SAMPLES / "prices"),
        llm_backoff_seconds=0,
    )
    c2.seed_reference_data(str(SAMPLES))
    c2.portfolio_service.import_csv(
        "Demo Portfolio", (SAMPLES / "portfolio_demo.csv").read_bytes(), as_of="2025-01-02T00:00:00Z"
    )
    c2.registry = AdapterRegistry()
    c2.registry.register(FakeNewsAdapter("demo", load_sample_news(SAMPLES / "news")))
    run_cycle(c2)
    assert _golden_view(c2) == _golden_view(c)
    c2.close()


def test_regression_no_look_ahead(pipeline):
    c, snap, _ = pipeline
    report = c.research.calibration((0, 1), strict=True)
    assert report.included > 0
    # A snapshot dated after the events is future information for every event.
    future, _ = c.portfolio_service.import_csv(
        "Future", "ticker,weight\nNVDA,1\n", as_of="2025-06-01T00:00:00Z"
    )
    analysis_id = c.analyses.latest_for_news(by_title(c, "US tightens export rules").news_id)["analysis_id"]
    c.impact_service.score(analysis_id, future)
    with pytest.raises(LookAheadViolation):
        c.research.calibration((0, 1), strict=True)
    lenient = c.research.calibration((0, 1), strict=False)
    assert lenient.excluded.get("look_ahead_feature") == 1
    # Analogs for the March event only use earlier events.
    analogs = c.research.analogs(analysis_id)
    assert analogs["analogs"] and all(a["event_time"] < analogs["cutoff"] for a in analogs["analogs"])


def test_no_private_data_required(pipeline):
    c, _, _ = pipeline
    for p in c.portfolios.list():
        assert p.name in {"Demo Portfolio", "Future"}
