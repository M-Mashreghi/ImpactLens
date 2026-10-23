"""Score-bucket calibration against observed event-study reactions (``calib-v1``).

Each observation joins one *counted* impact component (position-level score) with the
stored event-study abnormal return for the same news/security and window.

Every candidate observation is accounted for: included, or excluded with an explicit
reason (no silent drops). Statistics describe association only — never causality.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from impactlens.research.pit import assert_point_in_time

CALIBRATION_VERSION = "calib-v1"
ASSOCIATION_NOTE = (
    "Association between impact-priority buckets and observed abnormal returns. "
    "Not causal and not a validated return forecast."
)


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)
    impact_id: int
    news_id: int
    security_id: str
    event_type: str
    position_level: str
    signed_component: float
    event_time: str
    feature_times: dict[str, str | None]  # e.g. analysis_created, snapshot_as_of
    abnormal_return: float | None
    study_status: str | None


class BucketStats(BaseModel):
    model_config = ConfigDict(frozen=True)
    key: str
    n: int
    mean_abs_ar: float | None
    median_abs_ar: float | None
    mean_ar: float | None
    direction_hits: int
    direction_total: int
    direction_hit_rate: float | None


class CalibrationReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str = CALIBRATION_VERSION
    window: tuple[int, int]
    candidates: int
    included: int
    excluded: dict[str, int]
    by_level: tuple[BucketStats, ...]
    by_event_type: tuple[BucketStats, ...]
    note: str = ASSOCIATION_NOTE


def _stats(key: str, rows: list[Observation]) -> BucketStats:
    ars = [r.abnormal_return for r in rows if r.abnormal_return is not None]
    abs_ars = [abs(a) for a in ars]
    directional = [r for r in rows if r.signed_component != 0 and r.abnormal_return not in (None, 0.0)]
    hits = sum(1 for r in directional if (r.signed_component > 0) == ((r.abnormal_return or 0.0) > 0))
    return BucketStats(
        key=key,
        n=len(rows),
        mean_abs_ar=round(statistics.fmean(abs_ars), 10) if abs_ars else None,
        median_abs_ar=round(statistics.median(abs_ars), 10) if abs_ars else None,
        mean_ar=round(statistics.fmean(ars), 10) if ars else None,
        direction_hits=hits,
        direction_total=len(directional),
        direction_hit_rate=round(hits / len(directional), 6) if directional else None,
    )


def calibrate(
    observations: list[Observation], window: tuple[int, int] = (0, 1), *, strict_point_in_time: bool = True
) -> CalibrationReport:
    """Strict mode raises on any feature timestamped after the event; otherwise it is excluded."""
    excluded: dict[str, int] = defaultdict(int)
    included: list[Observation] = []
    for obs in observations:
        try:
            assert_point_in_time(obs.event_time, obs.feature_times.items())
        except ValueError:
            if strict_point_in_time:
                raise
            excluded["look_ahead_feature"] += 1
            continue
        if obs.study_status is None:
            excluded["no_event_study"] += 1
        elif obs.study_status != "ok" or obs.abnormal_return is None:
            excluded[f"study_{obs.study_status}"] += 1
        else:
            included.append(obs)
    levels: dict[str, list[Observation]] = defaultdict(list)
    types: dict[str, list[Observation]] = defaultdict(list)
    for obs in included:
        levels[obs.position_level].append(obs)
        types[obs.event_type].append(obs)
    order = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    return CalibrationReport(
        window=window,
        candidates=len(observations),
        included=len(included),
        excluded=dict(sorted(excluded.items())),
        by_level=tuple(_stats(k, levels[k]) for k in sorted(levels, key=lambda k: order.get(k, 9))),
        by_event_type=tuple(_stats(k, types[k]) for k in sorted(types)),
    )
