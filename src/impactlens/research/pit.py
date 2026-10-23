"""Point-in-time (no-look-ahead) guard."""

from __future__ import annotations

from collections.abc import Iterable

from impactlens.timeutil import parse_iso


class LookAheadViolation(ValueError):
    """Raised when information timestamped after the decision time would be used."""


def assert_point_in_time(decision_time: str, items: Iterable[tuple[str, str | None]]) -> None:
    """``items`` are (label, available_at) pairs; every available_at must be ≤ decision_time."""
    cutoff = parse_iso(decision_time)
    violations = [
        f"{label} available at {ts}" for label, ts in items if ts is not None and parse_iso(ts) > cutoff
    ]
    if violations:
        raise LookAheadViolation(
            f"look-ahead at decision time {decision_time}: " + "; ".join(violations[:10])
        )
