"""Tasks 6.2–6.5: dashboard smoke, alerts, scheduled workflow, exports."""

from __future__ import annotations

import ast
import csv
import io
import json
from datetime import timedelta

import pytest

from impactlens.alerts.service import AlertPolicy, AlertService, ConsoleChannel, idempotency_key
from impactlens.export.brief import build_export_record, to_csv, to_json, to_markdown
from impactlens.ingestion.contracts import AdapterRegistry
from impactlens.ingestion.fake import FakeNewsAdapter
from impactlens.ingestion.samples import load_sample_news
from impactlens.jobs.workflow import Scheduler, run_cycle
from impactlens.timeutil import parse_iso
from tests.conftest import ROOT, SAMPLES


def _registry():
    registry = AdapterRegistry()
    registry.register(FakeNewsAdapter("demo", load_sample_news(SAMPLES / "news")))
    return registry


@pytest.fixture
def ran(container, demo_snapshot):
    container.registry = _registry()
    summary = run_cycle(container)
    return container, demo_snapshot, summary


# ----------------------------------------------------------------------------- 6.2


def test_dashboard_pages_render_sample_data(ran, monkeypatch):
    from fastapi.testclient import TestClient
    from streamlit.testing.v1 import AppTest

    from impactlens.api.main import create_app
    from impactlens.dashboard import client as dash_client

    container, _, _ = ran
    container.research.run_event_studies(1, as_of="2025-03-31T21:00:00Z")
    test_client = TestClient(create_app(container))
    monkeypatch.setattr(dash_client, "make_client", lambda: test_client)
    app_path = ROOT / "src" / "impactlens" / "dashboard" / "app.py"
    for page in (
        "Portfolio",
        "Impact Feed",
        "News Detail",
        "Impact Detail",
        "Historical Context",
        "Alerts / System",
    ):
        at = AppTest.from_file(str(app_path), default_timeout=30)
        at.session_state["page"] = page
        at.run()
        assert not at.exception, (page, at.exception)
        assert not at.error, (page, [e.value for e in at.error])
        assert at.header[0].value.startswith(
            page.split(" /")[0].replace("Impact Detail", "Portfolio Impact Detail")
        )


def test_dashboard_source_contains_no_business_logic():
    source = (ROOT / "src" / "impactlens" / "dashboard" / "app.py").read_text()
    imports = {n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"__future__", "streamlit", "impactlens.dashboard.client"}
    for forbidden in ("score_matches", "sqlite3", "weight_cap", "abnormal_return =", "parse_portfolio_csv"):
        assert forbidden not in source


# ----------------------------------------------------------------------------- 6.3


def test_high_impact_fixture_alerts_once_and_rerun_is_suppressed(ran):
    container, snapshot, summary = ran
    assert summary["alerts"].get("sent") == 2
    sent = [a for a in container.alerts.list() if a["status"] == "sent"]
    assert len(sent) == 2
    impact = container.impacts.get(sent[0]["impact_id"])
    again = container.alert_service.evaluate(impact, snapshot.portfolio_id)
    assert again.status == "suppressed_duplicate"
    second_cycle = run_cycle(container)
    assert second_cycle["alerts"] == {} and second_cycle["impacts"] == 0
    assert len(container.alerts.list()) == 2
    # the syndicated duplicate article maps to the same canonical news id → same key
    dup = container.news.get(2)
    assert dup.canonical_news_id == 1
    key = idempotency_key(1, snapshot.snapshot_id, "impact-v1", "console")
    assert container.alerts.get_by_key(key) is not None


def _impact(level, priority, news_id=1, impact_id=1):
    return {
        "impact_id": impact_id,
        "news_id": news_id,
        "snapshot_id": "snap",
        "scoring_version": "impact-v1",
        "impact_level": level,
        "absolute_priority": priority,
        "signed_score": -priority,
        "result": {"components": [], "semantics": "priority"},
    }


@pytest.mark.parametrize(
    ("min_level", "level", "eligible"),
    [
        ("High", "Medium", False),
        ("High", "High", True),
        ("High", "Critical", True),
        ("Critical", "High", False),
        ("Low", "Low", True),
    ],
)
def test_policy_boundaries(min_level, level, eligible):
    assert AlertPolicy(min_level=min_level).eligible(level, 30.0) is eligible
    assert AlertPolicy(min_level="Low", min_priority=25.0).eligible("High", 24.99) is False


def test_cooldown_suppresses_then_expires(container):
    from impactlens.ingestion.manual import build_manual_item

    ids = [
        container.ingestion.ingest_item(
            build_manual_item(title=f"Story {i}", text=f"Body number {i} long enough.")
        ).news_id
        for i in range(4)
    ]
    clock = {"now": parse_iso("2025-03-03T15:00:00Z")}
    channel = ConsoleChannel(stream=io.StringIO())
    service = AlertService(
        container.alerts,
        container.news,
        channel,
        AlertPolicy(min_level="High", cooldown_seconds=600),
        clock=lambda: clock["now"],
    )
    container.db.conn.execute("PRAGMA foreign_keys = OFF")
    assert service.evaluate(_impact("High", 30, ids[0], 1), "pf").status == "sent"
    clock["now"] += timedelta(seconds=60)
    assert service.evaluate(_impact("High", 30, ids[1], 2), "pf").status == "suppressed_cooldown"
    assert service.evaluate(_impact("Critical", 80, ids[2], 3), "pf").status == "sent"  # bypass
    clock["now"] += timedelta(seconds=700)
    assert service.evaluate(_impact("High", 30, ids[3], 4), "pf").status == "sent"
    assert service.evaluate(_impact("Medium", 12, ids[3], 5), "pf").status == "below_threshold"
    assert len(channel.sent) == 3
    statuses = [a["status"] for a in container.alerts.list()]
    assert statuses.count("suppressed_cooldown") == 1


def test_failed_delivery_is_recorded(container):
    from impactlens.ingestion.manual import build_manual_item

    class Broken:
        name = "webhook"

        def send(self, message):
            raise RuntimeError("HTTP 500")

    nid = container.ingestion.ingest_item(
        build_manual_item(title="Broken", text="A body long enough to pass.")
    ).news_id
    container.db.conn.execute("PRAGMA foreign_keys = OFF")
    service = AlertService(container.alerts, container.news, Broken(), AlertPolicy())
    assert service.evaluate(_impact("High", 30, nid), "pf").status == "failed"
    assert container.alerts.list()[0]["status"] == "failed"


# ----------------------------------------------------------------------------- 6.4


def test_scheduled_run_processes_fixture_source_end_to_end(ran):
    container, _, summary = ran
    assert summary["status"] == "completed"
    assert summary["sources"][0]["new"] == 7 and summary["sources"][0]["duplicates"] == 1
    assert summary["analyses"] == {"Valid": 4, "Uncertain": 3}
    assert summary["impacts"] == 4
    statuses = {n.news_id: n.ingestion_status.value for n in container.news.list(limit=100)}
    assert statuses[1] == "Alerted" and statuses[2] == "Duplicate"
    assert container.job_runs.latest()["status"] == "completed"


def test_duplicate_item_does_not_repeat_llm_or_alert_work(container, demo_snapshot):
    from impactlens.intelligence.llm import FixtureLLMProvider

    calls = {"n": 0}
    provider = FixtureLLMProvider.from_directory(SAMPLES / "analyses")
    original = provider.complete

    def counting(request):
        calls["n"] += 1
        return original(request)

    provider.complete = counting  # type: ignore[method-assign]
    container.llm_client.provider = provider
    container.registry = _registry()
    run_cycle(container)
    first = calls["n"]
    assert first == 7  # 8 items, 1 duplicate never analyzed
    container.registry = AdapterRegistry()
    container.registry.register(FakeNewsAdapter("other-source", load_sample_news(SAMPLES / "news", "other")))
    run_cycle(container)
    assert calls["n"] == first and len(container.alerts.list()) == 2


def test_failure_in_one_item_does_not_stop_future_jobs(container, demo_snapshot, monkeypatch):
    container.registry = _registry()
    original = container.impact_service.score
    state = {"fail": True}

    def flaky(analysis_id, snapshot, force=False):
        if state["fail"] and analysis_id == 1:
            raise RuntimeError("transient scorer failure")
        return original(analysis_id, snapshot, force=force)

    monkeypatch.setattr(container.impact_service, "score", flaky)
    first = run_cycle(container)
    assert first["status"] == "completed_with_errors" and first["impacts"] == 3
    state["fail"] = False
    second = run_cycle(container)
    assert second["status"] == "completed" and second["impacts"] == 1


def test_scheduler_runs_cycles_and_stops_gracefully(container):
    calls = []

    def cycle(c):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return {"status": "completed"}

    scheduler = Scheduler(container, 0.01, cycle=cycle)
    results = scheduler.run(max_cycles=3)
    assert [r["status"] for r in results] == ["crashed", "completed", "completed"]
    scheduler.stop()
    assert scheduler.run() == results  # stop flag set: no further cycles


# ----------------------------------------------------------------------------- 6.5


def _record(container, impact_id):
    impact = container.impacts.get(impact_id)
    return build_export_record(
        impact,
        container.analyses.get(impact["analysis_id"]),
        container.news.get(impact["news_id"]).model_dump(mode="json"),
        container.studies.for_news(impact["news_id"]),
    )


def test_fixture_export_is_reproducible_with_provenance(ran):
    container, snapshot, _ = ran
    container.research.run_event_studies(1, as_of="2025-03-31T21:00:00Z")
    impact_id = next(i["impact_id"] for i in container.impacts.list_all() if i["news_id"] == 1)
    a, b = _record(container, impact_id), _record(container, impact_id)
    assert to_json(a) == to_json(b) and to_csv(a) == to_csv(b) and to_markdown(a) == to_markdown(b)
    data = json.loads(to_json(a))
    assert data["impact"]["snapshot_id"] == snapshot.snapshot_id
    for key in ("source_name", "source_url", "published_at", "retrieved_at", "content_hash"):
        assert key in data["source"]
    assert set(data["event"]["versions"]) == {
        "schema_version",
        "prompt_version",
        "model_provider",
        "model_name",
    }
    assert data["impact"]["scoring_version"] == "impact-v1" and data["impact"]["rules_version"]
    assert data["historical"][0]["config_version"] == "es-v1" and data["evidence"]
    assert "raw_response" not in to_json(a) and "api_key" not in to_json(a)
    rows = list(csv.DictReader(io.StringIO(to_csv(a))))
    assert rows and rows[0]["snapshot_id"] == snapshot.snapshot_id


def test_markdown_brief_separates_facts_score_and_history(ran):
    container, _, _ = ran
    container.research.run_event_studies(1, as_of="2025-03-31T21:00:00Z")
    impact_id = next(i["impact_id"] for i in container.impacts.list_all() if i["news_id"] == 1)
    md = to_markdown(_record(container, impact_id))
    facts, score, history = (
        md.index("## 1. Observed facts"),
        md.index("## 2. Computed impact priority"),
        md.index("## 3. Historical association (not causal)"),
    )
    assert facts < score < history
    assert "Not an expected return" in md and "Not evidence of causation" in md
