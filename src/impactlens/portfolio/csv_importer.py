"""Portfolio CSV parser with row-level validation and deterministic weight computation.

Template (header row required, column order free)::

    ticker,exchange,quantity,market_value,weight,currency,name

Rules (documented in docs/ARCHITECTURE.md §3.5):

* ``ticker`` is required. ``CASH`` denotes a cash line (no security id).
* Either every row supplies ``market_value`` or every row supplies ``weight`` (or both).
* Market values given → weight = market_value / total. If weights are also given they
  must agree within ``WEIGHT_TOLERANCE`` (absolute).
* Weights only → they must sum to 1 within ``SUM_TOLERANCE``; they are then rescaled to sum
  exactly to 1.
* Negative values (short positions) are rejected in v1; duplicates (ticker+exchange) rejected.
* Every non-cash ticker must resolve to exactly one security in the security master.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field

from impactlens.entities.resolver import ResolutionStatus, SecurityResolver
from impactlens.portfolio.models import AssetType, Position, WeightBasis

REQUIRED_COLUMNS = {"ticker"}
KNOWN_COLUMNS = {"ticker", "exchange", "quantity", "market_value", "weight", "currency", "name"}
WEIGHT_TOLERANCE = 0.005
SUM_TOLERANCE = 0.01
MAX_BYTES = 1_000_000
MAX_ROWS = 5_000
CASH_TICKER = "CASH"


@dataclass(frozen=True)
class RowError:
    line: int
    column: str | None
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}" + (f", column '{self.column}'" if self.column else "")
        return f"{where}: {self.message}"


@dataclass
class ParsedPortfolio:
    positions: list[Position]
    weight_basis: WeightBasis
    total_market_value: float | None
    warnings: list[str] = field(default_factory=list)


class PortfolioImportError(ValueError):
    def __init__(self, errors: list[RowError]) -> None:
        self.errors = errors
        super().__init__("; ".join(str(e) for e in errors[:20]))


def _number(raw: str, line: int, column: str, errors: list[RowError]) -> float | None:
    raw = raw.strip().replace(",", "")
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        errors.append(RowError(line, column, f"not a number: {raw!r}"))
        return None
    if not math.isfinite(value):
        errors.append(RowError(line, column, "must be finite"))
        return None
    if value < 0:
        errors.append(RowError(line, column, "negative values (short positions) are not supported in v1"))
        return None
    return value


def parse_portfolio_csv(
    data: bytes | str, resolver: SecurityResolver, default_currency: str = "USD"
) -> ParsedPortfolio:
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise PortfolioImportError([RowError(0, None, f"file exceeds {MAX_BYTES} bytes")])
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise PortfolioImportError([RowError(0, None, "file must be UTF-8 text")]) from exc
    else:
        text = data.lstrip("﻿")
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise PortfolioImportError([RowError(0, None, f"file exceeds {MAX_BYTES} bytes")])

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise PortfolioImportError([RowError(1, None, "missing header row")])
    headers = [h.strip().lower() for h in reader.fieldnames]
    errors: list[RowError] = []
    missing = REQUIRED_COLUMNS - set(headers)
    if missing:
        errors.append(RowError(1, None, f"missing required column(s): {sorted(missing)}"))
    unknown = set(headers) - KNOWN_COLUMNS
    if unknown:
        errors.append(
            RowError(1, None, f"unknown column(s): {sorted(unknown)}; allowed: {sorted(KNOWN_COLUMNS)}")
        )
    if len(headers) != len(set(headers)):
        errors.append(RowError(1, None, "duplicate column names"))
    if "market_value" not in headers and "weight" not in headers:
        errors.append(RowError(1, None, "need a 'market_value' or 'weight' column"))
    if errors:
        raise PortfolioImportError(errors)

    rows: list[dict] = []
    seen: dict[tuple[str, str | None], int] = {}
    for idx, raw in enumerate(reader, start=2):
        if idx - 1 > MAX_ROWS:
            errors.append(RowError(idx, None, f"more than {MAX_ROWS} rows"))
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k is not None}
        if None in raw:
            errors.append(RowError(idx, None, "row has more fields than the header"))
            continue
        if not any(row.values()):
            continue
        ticker = row.get("ticker", "").upper().lstrip("$")
        if not ticker:
            errors.append(RowError(idx, "ticker", "required"))
            continue
        exchange = row.get("exchange", "").upper() or None
        key = (ticker, exchange)
        if key in seen:
            errors.append(RowError(idx, "ticker", f"duplicate position {ticker} (first at line {seen[key]})"))
            continue
        seen[key] = idx
        mv = _number(row.get("market_value", ""), idx, "market_value", errors)
        weight = _number(row.get("weight", ""), idx, "weight", errors)
        qty = _number(row.get("quantity", ""), idx, "quantity", errors)
        if weight is not None and weight > 1:
            errors.append(RowError(idx, "weight", "weights are fractions in [0, 1] (e.g. 0.15 for 15%)"))
        currency = (row.get("currency") or default_currency).upper()
        if len(currency) != 3 or not currency.isalpha():
            errors.append(RowError(idx, "currency", f"invalid ISO currency {currency!r}"))
        security_id = None
        display = row.get("name") or ticker
        asset_type = AssetType.CASH if ticker == CASH_TICKER else AssetType.SECURITY
        if asset_type is AssetType.SECURITY:
            resolution = resolver.resolve_ticker(ticker, exchange)
            if resolution.status is ResolutionStatus.RESOLVED:
                security_id = resolution.security_ids[0]
                sec = resolver.get(security_id)
                if sec is not None:
                    display = row.get("name") or sec.canonical_name
                    exchange = sec.exchange
            elif resolution.status is ResolutionStatus.AMBIGUOUS:
                options = ", ".join(f"{c.ticker}@{c.exchange}" for c in resolution.candidates)
                errors.append(
                    RowError(idx, "exchange", f"ticker {ticker} is ambiguous ({options}); set exchange")
                )
            else:
                errors.append(RowError(idx, "ticker", f"unknown ticker {ticker!r} (not in security master)"))
        rows.append(
            dict(
                line=idx,
                ticker=ticker,
                exchange=exchange,
                mv=mv,
                weight=weight,
                qty=qty,
                currency=currency,
                security_id=security_id,
                display=display,
                asset_type=asset_type,
            )
        )

    if not rows and not errors:
        errors.append(RowError(2, None, "no positions found"))
    if errors:
        raise PortfolioImportError(errors)

    all_mv = all(r["mv"] is not None for r in rows)
    all_w = all(r["weight"] is not None for r in rows)
    if not all_mv and not all_w:
        raise PortfolioImportError(
            [
                RowError(r["line"], None, "every row needs market_value, or every row needs weight")
                for r in rows
                if r["mv"] is None and r["weight"] is None
            ][:20]
            or [RowError(2, None, "mixed market_value/weight coverage; supply one consistently")]
        )

    warnings: list[str] = []
    if all_mv:
        total = math.fsum(r["mv"] for r in rows)
        if total <= 0:
            raise PortfolioImportError([RowError(2, "market_value", "total market value must be positive")])
        basis = WeightBasis.MARKET_VALUE
        for r in rows:
            computed = r["mv"] / total
            if r["weight"] is not None and abs(r["weight"] - computed) > WEIGHT_TOLERANCE:
                errors.append(
                    RowError(
                        r["line"],
                        "weight",
                        f"weight {r['weight']:.4f} inconsistent with market value share {computed:.4f}",
                    )
                )
            r["final_weight"] = computed
        total_mv: float | None = total
    else:
        total_w = math.fsum(r["weight"] for r in rows)
        if abs(total_w - 1.0) > SUM_TOLERANCE:
            raise PortfolioImportError(
                [RowError(2, "weight", f"weights sum to {total_w:.4f}; must be 1 ± {SUM_TOLERANCE}")]
            )
        if total_w != 1.0:
            warnings.append(f"weights summed to {total_w:.6f}; rescaled to 1.0")
        basis = WeightBasis.WEIGHT
        for r in rows:
            r["final_weight"] = r["weight"] / total_w
        total_mv = None
    if errors:
        raise PortfolioImportError(errors)

    positions = [
        Position(
            line_no=n,
            security_id=r["security_id"],
            ticker=r["ticker"],
            exchange=r["exchange"],
            display_name=r["display"],
            asset_type=r["asset_type"],
            quantity=r["qty"],
            market_value=r["mv"],
            weight=round(r["final_weight"], 10),
            currency=r["currency"],
        )
        for n, r in enumerate(rows, start=1)
    ]
    return ParsedPortfolio(
        positions=positions, weight_basis=basis, total_market_value=total_mv, warnings=warnings
    )
