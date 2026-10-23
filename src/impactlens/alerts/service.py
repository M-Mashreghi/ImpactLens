"""Alert policy, idempotency and cooldown (``alert-policy-v1``).

* Eligible when ``impact_level`` ≥ ``min_level`` (and optionally priority ≥ ``min_priority``).
* Idempotency key = sha256(canonical_news_id | snapshot_id | scoring_version | channel):
  reruns, duplicate articles (linked to the same canonical news) and recomputes never send twice.
* Cooldown: after a ``sent`` alert for a portfolio+channel, further eligible alerts inside
  ``cooldown_seconds`` are recorded as ``suppressed_cooldown`` (visible in history, not sent).
  ``Critical`` impacts bypass cooldown.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import timedelta
from typing import Protocol, TextIO

import httpx
from pydantic import BaseModel, ConfigDict

from impactlens.impact.scoring import LEVEL_ORDER
from impactlens.logging_setup import get_logger, log_event, redactor
from impactlens.news.models import NewsStatus
from impactlens.storage.repositories import AlertRepository, NewsRepository
from impactlens.timeutil import parse_iso, to_iso, utc_now

logger = get_logger("alerts")
POLICY_VERSION = "alert-policy-v1"


class AlertPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    min_level: str = "High"
    min_priority: float = 0.0
    cooldown_seconds: int = 3600
    critical_bypasses_cooldown: bool = True

    def eligible(self, level: str, priority: float) -> bool:
        return LEVEL_ORDER[level] >= LEVEL_ORDER[self.min_level] and priority >= self.min_priority


class AlertMessage(BaseModel):
    model_config = ConfigDict(frozen=True)
    idempotency_key: str
    portfolio_id: str
    snapshot_id: str
    news_id: int
    impact_id: int
    impact_level: str
    absolute_priority: float
    signed_score: float
    title: str
    source_url: str | None
    top_positions: list[str]
    disclaimer: str


class AlertChannel(Protocol):
    name: str

    def send(self, message: AlertMessage) -> None: ...


class ConsoleChannel:
    name = "console"

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout
        self.sent: list[AlertMessage] = []

    def send(self, message: AlertMessage) -> None:
        self.sent.append(message)
        self.stream.write(
            f"[ImpactLens ALERT] {message.impact_level} priority {message.absolute_priority:.1f} — "
            f"{message.title} — positions: {', '.join(message.top_positions)}\n"
        )


class WebhookChannel:
    name = "webhook"

    def __init__(self, url: str, client: httpx.Client | None = None, timeout_seconds: float = 10.0) -> None:
        redactor.register(url)
        self._url = url
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def __repr__(self) -> str:
        return "WebhookChannel(url=***REDACTED***)"

    def send(self, message: AlertMessage) -> None:
        response = self._client.post(
            self._url,
            content=json.dumps(message.model_dump(mode="json")),
            headers={"Content-Type": "application/json"},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"webhook returned HTTP {response.status_code}")


def idempotency_key(canonical_news_id: int, snapshot_id: str, scoring_version: str, channel: str) -> str:
    raw = f"{canonical_news_id}|{snapshot_id}|{scoring_version}|{channel}"
    return "alert:" + hashlib.sha256(raw.encode()).hexdigest()[:40]


class AlertDecision(BaseModel):
    status: str  # sent | suppressed_duplicate | suppressed_cooldown | below_threshold | failed
    alert_id: int | None = None
    idempotency_key: str | None = None


class AlertService:
    def __init__(
        self,
        alerts: AlertRepository,
        news: NewsRepository,
        channel: AlertChannel,
        policy: AlertPolicy,
        *,
        enabled: bool = True,
        clock=utc_now,
    ) -> None:
        self.alerts = alerts
        self.news = news
        self.channel = channel
        self.policy = policy
        self.enabled = enabled
        self._clock = clock

    def evaluate(self, impact: dict, portfolio_id: str) -> AlertDecision:
        if not self.enabled:
            return AlertDecision(status="disabled")
        if not self.policy.eligible(impact["impact_level"], impact["absolute_priority"]):
            return AlertDecision(status="below_threshold")
        news = self.news.get(impact["news_id"])
        assert news is not None
        canonical_id = news.canonical_news_id or news.news_id
        key = idempotency_key(
            canonical_id, impact["snapshot_id"], impact["scoring_version"], self.channel.name
        )
        if self.alerts.get_by_key(key):
            return AlertDecision(status="suppressed_duplicate", idempotency_key=key)
        now = self._clock()
        status = "pending"
        last = self.alerts.last_sent(portfolio_id, self.channel.name)
        in_cooldown = (
            last is not None
            and now - parse_iso(last["created_at"]) < timedelta(seconds=self.policy.cooldown_seconds)
            and not (self.policy.critical_bypasses_cooldown and impact["impact_level"] == "Critical")
        )
        if in_cooldown:
            status = "suppressed_cooldown"
        components = [c for c in impact["result"]["components"] if c["counted"]][:5]
        message = AlertMessage(
            idempotency_key=key,
            portfolio_id=portfolio_id,
            snapshot_id=impact["snapshot_id"],
            news_id=canonical_id,
            impact_id=impact["impact_id"],
            impact_level=impact["impact_level"],
            absolute_priority=impact["absolute_priority"],
            signed_score=impact["signed_score"],
            title=news.title,
            source_url=news.source_url,
            top_positions=[f"{c['ticker']} ({c['relationship_type']}, {c['direction']})" for c in components],
            disclaimer=impact["result"]["semantics"],
        )
        alert_id = self.alerts.insert(
            {
                "idempotency_key": key,
                "impact_id": impact["impact_id"],
                "news_id": canonical_id,
                "portfolio_id": portfolio_id,
                "snapshot_id": impact["snapshot_id"],
                "scoring_version": impact["scoring_version"],
                "channel": self.channel.name,
                "impact_level": impact["impact_level"],
                "status": status,
                "detail": {"policy": POLICY_VERSION, "priority": impact["absolute_priority"]},
                "created_at": to_iso(now),
            }
        )
        if alert_id is None:  # concurrent insert won the race
            return AlertDecision(status="suppressed_duplicate", idempotency_key=key)
        if status == "suppressed_cooldown":
            log_event(logger, logging.INFO, "alert suppressed by cooldown", alert_id=alert_id)
            return AlertDecision(status=status, alert_id=alert_id, idempotency_key=key)
        try:
            self.channel.send(message)
        except Exception as exc:
            self.alerts.set_status(
                alert_id, "failed", {"error_type": type(exc).__name__, "message": str(exc)[:300]}
            )
            log_event(
                logger,
                logging.WARNING,
                "alert delivery failed",
                alert_id=alert_id,
                error_type=type(exc).__name__,
            )
            return AlertDecision(status="failed", alert_id=alert_id, idempotency_key=key)
        self.alerts.set_status(
            alert_id, "sent", {"policy": POLICY_VERSION, "priority": impact["absolute_priority"]}
        )
        if news.ingestion_status is NewsStatus.SCORED:
            self.news.set_status(news.news_id, NewsStatus.ALERTED, detail={"alert_id": alert_id})
        log_event(logger, logging.INFO, "alert sent", alert_id=alert_id, level=impact["impact_level"])
        return AlertDecision(status="sent", alert_id=alert_id, idempotency_key=key)
