"""Market-adjusted event study (config ``es-v1``).

For window ``[a, b]`` around anchor day 0 (trading days)::

    R_sec   = close(sec, day b) / close(sec, day a−1) − 1
    R_bench = close(bench, day b) / close(bench, day a−1) − 1
    AR      = R_sec − R_bench          (market-adjusted abnormal return)

Missing-data rule: every required close (day a−1 and day b, for security and benchmark)
must exist on the exact trading date. No forward/backward filling; otherwise the window
is ``insufficient_data`` with the missing dates listed.

Look-ahead rule: bars dated after ``as_of`` are discarded before computation, and a
window whose day-b session close is after ``as_of`` is ``not_yet_observable``.

Results describe observed market reaction / association, never causation.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from impactlens.market.calendar import ExchangeCalendar, SessionAlignment
from impactlens.market.provider import MarketDataProvider, MarketDataUnavailable
from impactlens.timeutil import parse_iso

INTERPRETATION = "Observed post-event market reaction (association). Not evidence of causation."


class EventStudyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str = "es-v1"
    windows: tuple[tuple[int, int], ...] = ((0, 1), (0, 5))
    benchmark: str = "SPY"
    model: str = "market_adjusted"
    missing_data_policy: str = "exact-date-required; no fill"


class WindowResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    window: tuple[int, int]
    status: str  # ok | insufficient_data | not_yet_observable
    base_date: str
    end_date: str
    security_return: float | None = None
    benchmark_return: float | None = None
    abnormal_return: float | None = None
    abnormal_return_bps: float | None = None
    missing: tuple[str, ...] = ()


class EventStudyResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    config: EventStudyConfig
    security_symbol: str
    benchmark_symbol: str
    alignment: SessionAlignment
    as_of: str
    provider: str
    data_vintage: dict[str, str | None]
    windows: tuple[WindowResult, ...]
    interpretation: str = INTERPRETATION
    notes: tuple[str, ...] = ()


def _ret(closes: dict[str, float], base: str, end: str) -> float:
    return closes[end] / closes[base] - 1.0


def run_event_study(
    *,
    security_symbol: str,
    alignment: SessionAlignment,
    calendar: ExchangeCalendar,
    provider: MarketDataProvider,
    as_of: str,
    config: EventStudyConfig = EventStudyConfig(),
) -> EventStudyResult:
    anchor = date.fromisoformat(alignment.anchor_date)
    cutoff = parse_iso(as_of)
    spans = [(calendar.shift(anchor, a - 1), calendar.shift(anchor, b)) for a, b in config.windows]
    start = min(s for s, _ in spans).isoformat()
    end = max(e for _, e in spans).isoformat()
    as_of_day = cutoff.date().isoformat()
    fetch_end = min(end, as_of_day)
    notes: list[str] = []

    def load(symbol: str) -> tuple[dict[str, float], str | None]:
        try:
            series = provider.get_daily_closes(symbol, start, fetch_end)
        except MarketDataUnavailable as exc:
            notes.append(f"{symbol}: market data unavailable ({exc})")
            return {}, None
        closes = {
            d: c
            for d, c in series.as_map().items()
            if calendar.session_close_utc(date.fromisoformat(d)) <= cutoff
        }
        return closes, series.vintage

    sec, sec_vintage = load(security_symbol)
    bench, bench_vintage = load(config.benchmark)
    results = []
    for (a, b), (base_day, end_day) in zip(config.windows, spans, strict=True):
        base_s, end_s = base_day.isoformat(), end_day.isoformat()
        if calendar.session_close_utc(end_day) > cutoff:
            results.append(
                WindowResult(window=(a, b), status="not_yet_observable", base_date=base_s, end_date=end_s)
            )
            continue
        missing = [
            f"{sym}:{d}"
            for sym, closes in ((security_symbol, sec), (config.benchmark, bench))
            for d in (base_s, end_s)
            if d not in closes
        ]
        if missing:
            results.append(
                WindowResult(
                    window=(a, b),
                    status="insufficient_data",
                    base_date=base_s,
                    end_date=end_s,
                    missing=tuple(missing),
                )
            )
            continue
        r_sec = _ret(sec, base_s, end_s)
        r_bench = _ret(bench, base_s, end_s)
        ar = r_sec - r_bench
        results.append(
            WindowResult(
                window=(a, b),
                status="ok",
                base_date=base_s,
                end_date=end_s,
                security_return=round(r_sec, 10),
                benchmark_return=round(r_bench, 10),
                abnormal_return=round(ar, 10),
                abnormal_return_bps=round(ar * 10_000, 4),
            )
        )
    if alignment.timestamp_flagged:
        notes.append(f"news timestamp quality is '{alignment.timestamp_quality}'")
    return EventStudyResult(
        config=config,
        security_symbol=security_symbol.upper(),
        benchmark_symbol=config.benchmark,
        alignment=alignment,
        as_of=as_of,
        provider=provider.provider_name,
        data_vintage={security_symbol.upper(): sec_vintage, config.benchmark: bench_vintage},
        windows=tuple(results),
        notes=tuple(notes),
    )
