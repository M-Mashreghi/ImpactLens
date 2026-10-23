"""Structured logging with correlation context and secret redaction."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "impactlens_log_context", default=None
)

# Patterns that are always scrubbed, even if the value was not registered.
_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;'\"}]+"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[\"']?\s*[:=]\s*[\"']?)[^\s,;'\"}&]+"),
]
REDACTED = "***REDACTED***"


class SecretRedactor:
    """Registry of secret values to scrub from any emitted log text."""

    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, *values: str | None) -> None:
        for value in values:
            if value and len(value) >= 4:
                self._values.add(value)

    def scrub(self, text: str) -> str:
        for value in sorted(self._values, key=len, reverse=True):
            text = text.replace(value, REDACTED)
        for pattern in _PATTERNS:
            text = pattern.sub(lambda m: (m.group(1) or "") + REDACTED, text)
        return text


redactor = SecretRedactor()


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


def get_context() -> dict[str, Any]:
    return dict(_CONTEXT.get() or {})


@contextlib.contextmanager
def log_context(**fields: Any) -> Iterator[dict[str, Any]]:
    """Bind fields (correlation_id, news_id, snapshot_id, stage, ...) to logs in this scope."""
    current = get_context()
    if "correlation_id" not in current and "correlation_id" not in fields:
        fields["correlation_id"] = new_correlation_id()
    merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
    token = _CONTEXT.set(merged)
    try:
        yield merged
    finally:
        _CONTEXT.reset(token)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.context = get_context()
        return True


class RedactingFilter(logging.Filter):
    """Render the message once, scrub it, and freeze it so handlers never see raw secrets."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            message = str(record.msg)
        record.msg = redactor.scrub(message)
        record.args = None
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            record.fields = json.loads(redactor.scrub(json.dumps(extra, default=str)))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "context", {}) or {})
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = redactor.scrub(self.formatException(record.exc_info))
        return redactor.scrub(json.dumps(payload, default=str))


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = getattr(record, "context", {}) or {}
        ctx = " ".join(f"{k}={v}" for k, v in context.items())
        base = super().format(record)
        return redactor.scrub(f"{base} {ctx}".rstrip())


def configure_logging(level: str = "INFO", fmt: str = "json", secrets: list[str] | None = None) -> None:
    redactor.register(*(secrets or []))
    root = logging.getLogger("impactlens")
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(ContextFilter())
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        JsonFormatter() if fmt == "json" else TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("impactlens") else f"impactlens.{name}")


def log_event(logger: logging.Logger, level: int, message: str, /, **fields: Any) -> None:
    logger.log(level, message, extra={"fields": fields})
