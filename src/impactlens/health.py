"""Liveness/readiness checks that never expose secrets."""

from __future__ import annotations

from impactlens import __version__
from impactlens.config import ConfigError, validate_settings
from impactlens.storage.db import latest_known_version, schema_version


def liveness() -> dict:
    return {"status": "ok", "version": __version__}


def readiness(container) -> dict:
    checks: dict[str, dict] = {}
    try:
        container.db.query_one("SELECT 1")
        current = schema_version(container.db.conn)
        expected = latest_known_version()
        checks["database"] = {"ok": current == expected, "schema_version": current, "expected": expected}
    except Exception as exc:
        checks["database"] = {"ok": False, "error": type(exc).__name__}
    try:
        validate_settings(container.settings)
        checks["config"] = {"ok": True}
    except ConfigError as exc:
        checks["config"] = {"ok": False, "error": str(exc).splitlines()[0]}
    try:
        checks["security_master"] = {"ok": True, "securities": container.securities.count()}
        last = container.job_runs.latest()
        # Job health is informational (degraded), not a hard readiness dependency.
        checks["jobs"] = {
            "ok": True,
            "last_run_status": last["status"] if last else None,
            "last_run_at": last["started_at"] if last else None,
            "degraded": bool(last and last["status"] == "failed"),
        }
    except Exception as exc:
        checks["security_master"] = {"ok": False, "error": type(exc).__name__}
        checks["jobs"] = {"ok": False, "error": type(exc).__name__}
    checks["market_data"] = {"ok": True, "enabled": container.market_provider is not None}
    hard = ("database", "config")
    ready = all(checks[name]["ok"] for name in hard)
    return {"status": "ready" if ready else "not_ready", "checks": checks}
