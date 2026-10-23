"""Tasks 7.2–7.5: observability/health, Docker/CI config, backup/restore."""

from __future__ import annotations

import io
import json
import logging
import sqlite3

import pytest
import yaml
from fastapi.testclient import TestClient

from impactlens.api.main import create_app
from impactlens.health import readiness
from impactlens.logging_setup import ContextFilter, JsonFormatter, RedactingFilter, redactor
from impactlens.storage.backup import BackupError, backup_database, integrity_check, restore_database
from tests.conftest import ROOT, SAMPLES

# ----------------------------------------------------------------------------- 7.2


def test_health_and_readiness(container):
    result = readiness(container)
    assert result["status"] == "ready"
    assert result["checks"]["database"]["schema_version"] == 1
    container.db.conn.execute("DELETE FROM schema_migrations")
    assert readiness(container)["status"] == "not_ready"


def test_ready_endpoint_reports_503_when_db_unavailable(container):
    client = TestClient(create_app(container))
    container.db.conn.close()
    response = client.get("/ready")
    assert response.status_code == 503 and response.json()["checks"]["database"]["ok"] is False
    assert client.get("/health").status_code == 200  # liveness independent of dependencies


def test_secret_redaction_end_to_end(container, monkeypatch):
    secret = "whsec-topsecret-0000-1111"
    redactor.register(secret)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    for f in (ContextFilter(), RedactingFilter()):
        handler.addFilter(f)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("impactlens")
    root.addHandler(handler)
    try:
        logging.getLogger("impactlens.alerts").warning("posting to https://hooks.example.com/%s", secret)
    finally:
        root.removeHandler(handler)
    assert secret not in stream.getvalue()


def test_pipeline_error_traceable_by_correlation_and_news_id(container):
    from impactlens.ingestion.manual import build_manual_item
    from impactlens.intelligence.llm import FakeLLMProvider, StructuredLLMClient
    from impactlens.intelligence.service import AnalysisService

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    for f in (ContextFilter(), RedactingFilter()):
        handler.addFilter(f)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("impactlens")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        nid = container.ingestion.ingest_item(
            build_manual_item(title="T", text="Some sufficiently long text.")
        ).news_id
        service = AnalysisService(
            StructuredLLMClient(FakeLLMProvider(["{oops"]), max_retries=0, sleep=lambda s: 0),
            container.resolver,
            container.news,
            container.analyses,
        )
        service.analyze(container.news.get(nid))
    finally:
        root.removeHandler(handler)
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    failed = [r for r in records if r["message"] == "analysis failed"]
    assert (
        failed
        and failed[0]["news_id"] == nid
        and failed[0]["correlation_id"]
        and failed[0]["stage"] == "analysis"
    )


def test_portfolio_logging_policy_logs_counts_not_holdings(container, caplog):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("impactlens")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        container.portfolio_service.import_csv("Private", (SAMPLES / "portfolio_demo.csv").read_bytes())
    finally:
        root.removeHandler(handler)
    out = stream.getvalue()
    assert '"positions": 12' in out and "NVDA" not in out and "150000" not in out


# ----------------------------------------------------------------------------- 7.3 / 7.4


def test_compose_file_is_valid_and_production_shaped():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    assert {"impactlens-api", "impactlens-dashboard", "impactlens-worker"} <= set(services)
    api = services["impactlens-api"]
    assert "healthcheck" in api and any("/app/data" in v for v in api["volumes"])
    assert "impactlens-data" in compose["volumes"]
    for svc in services.values():
        assert "environment" not in svc or not any(
            "KEY=" in str(e) and "${" not in str(e) for e in svc.get("environment", [])
        )
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "USER impactlens" in dockerfile and "HEALTHCHECK" in dockerfile and ".env" not in dockerfile
    dockerignore = (ROOT / ".dockerignore").read_text()
    assert ".env" in dockerignore and "data/private" in dockerignore


def test_ci_workflows_are_valid_and_gate_publishing():
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    release = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
    ci_on = ci.get("on", ci.get(True))
    assert "pull_request" in ci_on and "push" in ci_on
    steps = " ".join(str(s.get("run", "")) for s in ci["jobs"]["test"]["steps"])
    assert "pytest" in steps and "ruff" in steps and "mypy" in steps and "pip-audit" in steps
    assert ci["permissions"] == {"contents": "read"}
    publish = release["jobs"]["publish"]
    assert "test" in publish["needs"]
    rel_on = release.get("on", release.get(True))
    assert "pull_request" not in rel_on and "tags" in rel_on["push"]
    assert "pull_request_target" not in json.dumps(ci) + json.dumps(release)


# ----------------------------------------------------------------------------- 7.5


def test_backup_restores_into_clean_instance(container, demo_snapshot, tmp_path, settings):
    from impactlens.app import Container
    from impactlens.ingestion.manual import build_manual_item

    nid = container.ingestion.ingest_item(
        build_manual_item(title="Backup me", text="Body long enough for backup.")
    ).news_id
    backup = backup_database(settings.database.path, tmp_path / "backups")
    assert integrity_check(backup) == "ok"
    restored_path = tmp_path / "clean" / "impactlens.db"
    restore_database(backup, restored_path)
    assert integrity_check(restored_path) == "ok"
    clean = Container(
        settings.model_copy(
            update={"database": settings.database.model_copy(update={"path": str(restored_path)})}
        ),
        llm_backoff_seconds=0,
    )
    try:
        assert readiness(clean)["status"] == "ready"
        assert clean.portfolios.get_snapshot(demo_snapshot.snapshot_id) == demo_snapshot
        assert clean.news.get(nid).title == "Backup me"
    finally:
        clean.close()


def test_restore_refuses_overwrite_and_corrupt_backups(tmp_path, settings, container):
    backup = backup_database(settings.database.path, tmp_path / "b")
    with pytest.raises(BackupError):
        restore_database(backup, settings.database.path)
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database at all" * 100)
    with pytest.raises((BackupError, sqlite3.DatabaseError)):
        restore_database(bad, tmp_path / "x.db")
    target = tmp_path / "existing.db"
    target.write_bytes(backup.read_bytes())
    restore_database(backup, target, force=True)
    assert list(tmp_path.glob("existing.db.pre-restore-*"))


def test_backup_retention(tmp_path, settings, container):
    for _ in range(3):
        backup_database(settings.database.path, tmp_path / "r", keep=2)
    assert len(list((tmp_path / "r").glob("impactlens-*.db"))) == 2


def test_runbook_matches_commands():
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text()
    from impactlens.cli import build_parser

    commands = set(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
    for cmd in ("backup", "restore", "health", "run-once", "demo"):
        assert cmd in commands and f"impactlens {cmd}" in runbook
    for endpoint in ("/health", "/ready"):
        assert endpoint in runbook
