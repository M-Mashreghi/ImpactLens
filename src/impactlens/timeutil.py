"""UTC timestamp helpers. All persisted timestamps are ISO-8601 UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def utc_now_iso() -> str:
    return to_iso(utc_now())


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("naive datetimes are not allowed; attach a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
