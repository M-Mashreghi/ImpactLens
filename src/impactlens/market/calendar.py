"""Exchange calendar and event-timestamp → trading-session alignment (policy ``anchor-v1``).

Anchor policy (exchange-local time):

=================  ==========================================  ==================================
Case               Condition                                   Anchor session (event day 0)
=================  ==========================================  ==================================
pre_open           trading day, before the open                same day
in_session         trading day, open ≤ t < close               same day
after_close        trading day, t ≥ close                      next trading day
non_trading_day    weekend/holiday                             next trading day
date_only          publication time has no clock time          that date if trading, else next
=================  ==========================================  ==================================

Day-0 returns are measured close(anchor−1) → close(anchor). For ``in_session`` events this
includes pre-publication intraday moves; this limitation is recorded in the alignment.
Any timestamp whose quality is not ``exact`` is flagged on the research result.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from impactlens.timeutil import parse_iso

ALIGNMENT_POLICY = "anchor-v1"

# NYSE full-day closures 2024–2026 (public exchange calendar).
NYSE_HOLIDAYS = {
    "2024-01-01",
    "2024-01-15",
    "2024-02-19",
    "2024-03-29",
    "2024-05-27",
    "2024-06-19",
    "2024-07-04",
    "2024-09-02",
    "2024-11-28",
    "2024-12-25",
    "2025-01-01",
    "2025-01-09",
    "2025-01-20",
    "2025-02-17",
    "2025-04-18",
    "2025-05-26",
    "2025-06-19",
    "2025-07-04",
    "2025-09-01",
    "2025-11-27",
    "2025-12-25",
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-04-03",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
}


class SessionAlignment(BaseModel):
    model_config = ConfigDict(frozen=True)
    policy: str = ALIGNMENT_POLICY
    exchange: str
    timezone: str
    event_time_utc: str
    event_local_time: str
    session: str
    anchor_date: str
    timestamp_quality: str
    timestamp_flagged: bool
    notes: tuple[str, ...] = ()


class ExchangeCalendar:
    def __init__(self, name: str, tz: str, open_time: time, close_time: time, holidays: set[str]) -> None:
        self.name = name
        self.tz = ZoneInfo(tz)
        self.tz_name = tz
        self.open_time = open_time
        self.close_time = close_time
        self.holidays = holidays

    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5 and day.isoformat() not in self.holidays

    def next_trading_day(self, day: date) -> date:
        nxt = day + timedelta(days=1)
        while not self.is_trading_day(nxt):
            nxt += timedelta(days=1)
        return nxt

    def previous_trading_day(self, day: date) -> date:
        prev = day - timedelta(days=1)
        while not self.is_trading_day(prev):
            prev -= timedelta(days=1)
        return prev

    def shift(self, day: date, offset: int) -> date:
        """Move ``offset`` trading days from a trading day (offset 0 returns ``day``)."""
        current = day
        step = self.next_trading_day if offset > 0 else self.previous_trading_day
        for _ in range(abs(offset)):
            current = step(current)
        return current

    def session_close_utc(self, day: date) -> datetime:
        return datetime.combine(day, self.close_time, self.tz).astimezone(ZoneInfo("UTC"))

    def align(self, event_time_iso: str, timestamp_quality: str = "exact") -> SessionAlignment:
        utc = parse_iso(event_time_iso)
        local = utc.astimezone(self.tz)
        day = local.date()
        notes: list[str] = []
        if timestamp_quality == "date_only":
            # Date-only values are stored as 00:00Z of the published calendar date; use that date as-is
            # instead of converting midnight UTC into the previous local day.
            session, day = "date_only", utc.date()
            anchor = day if self.is_trading_day(day) else self.next_trading_day(day)
            notes.append("publication time unknown; anchored to calendar date")
        elif not self.is_trading_day(day):
            session, anchor = "non_trading_day", self.next_trading_day(day)
        elif local.time() < self.open_time:
            session, anchor = "pre_open", day
        elif local.time() < self.close_time:
            session, anchor = "in_session", day
            notes.append("day-0 return includes intraday moves before publication")
        else:
            session, anchor = "after_close", self.next_trading_day(day)
        flagged = timestamp_quality != "exact"
        if flagged and timestamp_quality != "date_only":
            notes.append(f"timestamp quality '{timestamp_quality}': alignment may be imprecise")
        return SessionAlignment(
            exchange=self.name,
            timezone=self.tz_name,
            event_time_utc=utc.isoformat().replace("+00:00", "Z"),
            event_local_time=local.isoformat(),
            session=session,
            anchor_date=anchor.isoformat(),
            timestamp_quality=timestamp_quality,
            timestamp_flagged=flagged,
            notes=tuple(notes),
        )


def nyse_calendar() -> ExchangeCalendar:
    return ExchangeCalendar("XNYS", "America/New_York", time(9, 30), time(16, 0), NYSE_HOLIDAYS)


CALENDARS = {"XNYS": nyse_calendar, "NYSE": nyse_calendar, "NASDAQ": nyse_calendar, "XNAS": nyse_calendar}


def calendar_for(exchange: str | None) -> ExchangeCalendar:
    """v1 supports US equity sessions; other exchanges fall back to NYSE with a note upstream."""
    return CALENDARS.get((exchange or "").upper(), nyse_calendar)()
