"""Portfolio domain. Snapshots and positions are immutable once created."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AssetType(StrEnum):
    SECURITY = "security"
    CASH = "cash"


class WeightBasis(StrEnum):
    MARKET_VALUE = "market_value"  # weights derived from market values
    WEIGHT = "weight"  # weights supplied directly


class Portfolio(BaseModel):
    model_config = ConfigDict(frozen=True)
    portfolio_id: str
    name: str = Field(min_length=1, max_length=120)
    base_currency: str = "USD"
    created_at: str


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)
    line_no: int = Field(ge=1)
    security_id: str | None
    ticker: str
    exchange: str | None = None
    display_name: str
    asset_type: AssetType = AssetType.SECURITY
    quantity: float | None = None
    market_value: float | None = Field(default=None, ge=0)
    weight: float = Field(ge=0, le=1)
    currency: str = "USD"


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    snapshot_id: str
    portfolio_id: str
    as_of: str
    created_at: str
    source: str
    weight_basis: WeightBasis
    total_market_value: float | None = None
    content_hash: str
    positions: tuple[Position, ...]

    def security_positions(self) -> list[Position]:
        return [p for p in self.positions if p.asset_type is AssetType.SECURITY and p.security_id]
