"""Task 6.1: FastAPI smoke, structured validation errors, thin routes."""

from __future__ import annotations

import ast
import inspect

import pytest
from fastapi.testclient import TestClient

from impactlens.api import main as api_main
from impactlens.api.main import create_app
from tests.conftest import SAMPLES

ARTICLE = {
    "title": "US tightens export rules on advanced AI chips to China",
    "text": (SAMPLES / "news" / "n01_export_controls.json").read_text(),
}


@pytest.fixture
def client(container):
    with TestClient(create_app(container)) as c:
        yield c


def _load_article():
    import json

    data = json.loads((SAMPLES / "news" / "n01_export_controls.json").read_text())
    return {"title": data["title"], "text": data["body"], "published_at": data["published_at"]}


def test_health_ready_and_config(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json()["checks"]["database"]["ok"]
    cfg = client.get("/system/config").json()
    assert "api_key" not in str(cfg["config"]["llm"]).replace("api_key_configured", "")
    assert client.get("/health").headers["x-correlation-id"]


def test_portfolio_import_and_snapshot_endpoints(client):
    csv_text = (SAMPLES / "portfolio_demo.csv").read_text()
    created = client.post(
        "/portfolios/import", json={"name": "Demo", "csv_text": csv_text, "as_of": "2025-01-02T00:00:00Z"}
    )
    assert created.status_code == 201
    snap_id = created.json()["snapshot"]["snapshot_id"]
    portfolios = client.get("/portfolios").json()
    assert portfolios[0]["latest_snapshot_id"] == snap_id
    assert len(client.get(f"/portfolio-snapshots/{snap_id}").json()["positions"]) == 12
    assert client.get(f"/portfolios/{portfolios[0]['portfolio_id']}/snapshots").status_code == 200


def test_validation_errors_are_structured(client):
    bad_csv = client.post("/portfolios/import", json={"name": "X", "csv_text": "ticker,weight\nZZZ,1\n"})
    assert bad_csv.status_code == 422
    err = bad_csv.json()["error"]
    assert err["code"] == "portfolio_invalid" and err["details"][0]["line"] == 2
    missing = client.post("/portfolios/import", json={"csv_text": "x"})
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "validation_error"
    empty = client.post("/news", json={"title": "t", "text": ""})
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "empty_text"
    assert client.get("/news/999").json()["error"]["code"] == "not_found"
    assert client.get("/impacts", params={"min_level": "Huge"}).status_code == 422
    assert client.get("/news", params={"limit": 0}).status_code == 422


def test_news_analysis_impact_flow_via_api(client):
    csv_text = (SAMPLES / "portfolio_demo.csv").read_text()
    snap_id = client.post(
        "/portfolios/import", json={"name": "Demo", "csv_text": csv_text, "as_of": "2025-01-02T00:00:00Z"}
    ).json()["snapshot"]["snapshot_id"]
    created = client.post("/news", json=_load_article())
    assert created.status_code == 201
    body = created.json()
    assert body["analysis"]["status"] == "Valid" and body["status"] == "Resolved"
    dup = client.post("/news", json=_load_article()).json()
    assert dup["duplicate"] and dup["analysis"] is None
    detail = client.get(f"/news/{body['news_id']}").json()
    assert (
        detail["analysis"]["event_type"] == "regulation_policy" and "raw_response" not in detail["analysis"]
    )
    scored = client.post(
        "/impacts/score", json={"analysis_id": body["analysis"]["analysis_id"], "snapshot_id": snap_id}
    )
    assert scored.status_code == 201
    feed = client.get("/impacts").json()
    assert feed[0]["impact_level"] == "Critical" and feed[0]["news"]["news_id"] == body["news_id"]
    impact_id = feed[0]["impact_id"]
    assert client.get(f"/impacts/{impact_id}").json()["result"]["components"]
    md = client.get(f"/impacts/{impact_id}/export", params={"format": "md"}).text
    assert "Observed facts" in md and "Historical association" in md
    studies = client.post(
        "/research/event-studies", json={"news_id": body["news_id"], "as_of": "2025-03-31T21:00:00Z"}
    )
    assert studies.status_code == 201 and studies.json()
    assert client.get("/research/event-studies", params={"news_id": body["news_id"]}).json()
    assert client.get(f"/research/analogs/{body['analysis']['analysis_id']}").status_code == 200
    assert "by_level" in client.get("/research/calibration").json()
    assert client.post("/impacts/score", json={"analysis_id": 999, "snapshot_id": snap_id}).status_code == 404


def test_routes_remain_thin():
    """Routes must not implement scoring/parsing/persistence: no SQL, no arithmetic engines."""
    source = inspect.getsource(api_main)
    tree = ast.parse(source)
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "impactlens.impact.scoring" not in imported and "sqlite3" not in source
    assert "SELECT " not in source and "score_matches" not in source
