"""Generate deterministic SYNTHETIC daily closes for the demo (not real market data).

Usage: python scripts/generate_sample_prices.py [output_dir]
"""

from __future__ import annotations

import csv
import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from impactlens.market.calendar import nyse_calendar  # noqa: E402

START, END = date(2024, 12, 2), date(2025, 3, 31)
BASE = {
    "SPY": 600.0,
    "NVDA": 135.0,
    "AMD": 120.0,
    "ASML": 700.0,
    "TSM": 190.0,
    "AAPL": 235.0,
    "MSFT": 420.0,
    "GOOGL": 190.0,
    "GOOG": 191.0,
    "XOM": 110.0,
    "DAL": 62.0,
    "JPM": 240.0,
}
# Scripted synthetic "event" moves (daily return overrides) to make the demo legible.
SHOCKS = {
    ("NVDA", "2025-01-13"): -0.030,
    ("NVDA", "2025-03-03"): -0.055,
    ("NVDA", "2025-03-04"): -0.012,
    ("AMD", "2025-03-03"): -0.040,
    ("TSM", "2025-03-03"): -0.025,
    ("ASML", "2025-03-03"): -0.018,
    ("XOM", "2025-03-10"): 0.035,
    ("DAL", "2025-03-10"): -0.045,
    ("GOOGL", "2025-03-10"): -0.030,
    ("GOOG", "2025-03-10"): -0.029,
}


def daily_return(symbol: str, day: str) -> float:
    if (symbol, day) in SHOCKS:
        return SHOCKS[(symbol, day)]
    h = int(hashlib.sha256(f"{symbol}|{day}".encode()).hexdigest()[:8], 16)
    return ((h / 0xFFFFFFFF) - 0.5) * 0.02  # uniform in ±1%


def main(out_dir: str = "data/samples/prices") -> None:
    cal = nyse_calendar()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    days = []
    d = START
    while d <= END:
        if cal.is_trading_day(d):
            days.append(d.isoformat())
        d += timedelta(days=1)
    for symbol, base in BASE.items():
        price = base
        with (out / f"{symbol}.csv").open("w", newline="") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(["date", "close"])
            for i, day in enumerate(days):
                if i:
                    price *= 1 + daily_return(symbol, day)
                writer.writerow([day, f"{price:.4f}"])


if __name__ == "__main__":
    main(*sys.argv[1:])
