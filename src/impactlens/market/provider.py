"""Vendor-neutral daily price contract, CSV/fake providers and a bounded local cache."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Bar(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    close: float = Field(gt=0)

    @field_validator("close")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("close must be finite")
        return value


class PriceSeries(BaseModel):
    """Normalized daily close series (dates are exchange-local trading dates)."""

    model_config = ConfigDict(frozen=True)
    symbol: str
    provider: str
    currency: str = "USD"
    timezone: str = "America/New_York"
    price_field: str = "close"
    vintage: str | None = Field(default=None, description="When the provider data was retrieved/frozen")
    bars: tuple[Bar, ...]

    def as_map(self) -> dict[str, float]:
        return {b.date: b.close for b in self.bars}


class MarketDataUnavailable(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    provider_name: str

    def get_daily_closes(self, symbol: str, start: str, end: str) -> PriceSeries: ...


class FakeMarketDataProvider:
    provider_name = "fake"

    def __init__(self, data: Mapping[str, Mapping[str, float]], vintage: str | None = "fixture") -> None:
        self._data = {k.upper(): dict(v) for k, v in data.items()}
        self.vintage = vintage
        self.calls = 0

    def get_daily_closes(self, symbol: str, start: str, end: str) -> PriceSeries:
        self.calls += 1
        series = self._data.get(symbol.upper())
        if series is None:
            raise MarketDataUnavailable(f"no data for {symbol}")
        bars = tuple(Bar(date=d, close=c) for d, c in sorted(series.items()) if start <= d <= end)
        return PriceSeries(
            symbol=symbol.upper(), provider=self.provider_name, vintage=self.vintage, bars=bars
        )


_DATE_COLS = ("date", "timestamp", "day")
_CLOSE_COLS = ("adj_close", "adj close", "adjusted_close", "close", "price")


class CsvMarketDataProvider:
    """Reads ``<dir>/<SYMBOL>.csv``; tolerates common vendor header variants.

    Prefers an adjusted close column when present, recording which field was used.
    """

    provider_name = "csv"

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def get_daily_closes(self, symbol: str, start: str, end: str) -> PriceSeries:
        path = self.directory / f"{symbol.upper()}.csv"
        if not path.is_file():
            raise MarketDataUnavailable(f"no CSV price file for {symbol}")
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
            date_col = next((headers[c] for c in _DATE_COLS if c in headers), None)
            close_key = next((c for c in _CLOSE_COLS if c in headers), None)
            if date_col is None or close_key is None:
                raise MarketDataUnavailable(f"{path.name}: needs date and close columns")
            close_col = headers[close_key]
            bars = []
            for row in reader:
                day = (row.get(date_col) or "").strip()[:10]
                raw = (row.get(close_col) or "").strip()
                if not day or not raw:
                    continue
                if start <= day <= end:
                    bars.append(Bar(date=day, close=float(raw)))
        vintage = f"file-mtime:{int(path.stat().st_mtime)}"
        return PriceSeries(
            symbol=symbol.upper(),
            provider=self.provider_name,
            vintage=vintage,
            price_field="adj_close" if "adj" in close_key else "close",
            bars=tuple(sorted(bars, key=lambda b: b.date)),
        )


class CachedMarketDataProvider:
    """Bounded on-disk JSON cache. Keys include provider, symbol and date range.

    The cache is replaceable and never authoritative: deleting it only costs refetches.
    """

    def __init__(self, inner: MarketDataProvider, cache_dir: str | Path, max_entries: int = 500) -> None:
        self.inner = inner
        self.provider_name = inner.provider_name
        self.cache_dir = Path(cache_dir) / "market"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0

    @staticmethod
    def cache_key(provider: str, symbol: str, start: str, end: str) -> str:
        return f"{provider}|{symbol.upper()}|{start}|{end}"

    def _path(self, key: str) -> Path:
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")

    def get_daily_closes(self, symbol: str, start: str, end: str) -> PriceSeries:
        key = self.cache_key(self.inner.provider_name, symbol, start, end)
        path = self._path(key)
        if path.is_file():
            try:
                payload = json.loads(path.read_text("utf-8"))
                if payload.get("key") == key:
                    self.hits += 1
                    os.utime(path)
                    return PriceSeries.model_validate(payload["series"])
            except (ValueError, KeyError):
                path.unlink(missing_ok=True)
        self.misses += 1
        series = self.inner.get_daily_closes(symbol, start, end)
        path.write_text(json.dumps({"key": key, "series": series.model_dump(mode="json")}), "utf-8")
        self._evict()
        return series

    def _evict(self) -> None:
        files = sorted(self.cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for stale in files[: max(0, len(files) - self.max_entries)]:
            stale.unlink(missing_ok=True)

    def clear(self) -> int:
        files = list(self.cache_dir.glob("*.json"))
        for f in files:
            f.unlink(missing_ok=True)
        return len(files)
