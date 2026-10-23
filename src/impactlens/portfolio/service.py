"""Portfolio application service: import CSV into an immutable snapshot."""

from __future__ import annotations

import logging

from impactlens.entities.resolver import SecurityResolver
from impactlens.logging_setup import get_logger, log_event
from impactlens.portfolio.csv_importer import parse_portfolio_csv
from impactlens.portfolio.models import PortfolioSnapshot
from impactlens.storage.repositories import PortfolioRepository
from impactlens.timeutil import parse_iso, to_iso, utc_now_iso

logger = get_logger("portfolio")


class PortfolioService:
    def __init__(self, repo: PortfolioRepository, resolver_factory) -> None:
        self.repo = repo
        self._resolver_factory = resolver_factory

    @property
    def resolver(self) -> SecurityResolver:
        return self._resolver_factory()

    def import_csv(
        self,
        name: str,
        data: bytes | str,
        *,
        as_of: str | None = None,
        base_currency: str = "USD",
        source: str = "csv",
    ) -> tuple[PortfolioSnapshot, list[str]]:
        as_of = to_iso(parse_iso(as_of)) if as_of else utc_now_iso()
        parsed = parse_portfolio_csv(data, self.resolver, default_currency=base_currency)
        portfolio = self.repo.get_or_create(name, base_currency)
        snapshot = self.repo.create_snapshot(
            portfolio,
            parsed.positions,
            as_of=as_of,
            source=source,
            weight_basis=parsed.weight_basis,
            total_market_value=parsed.total_market_value,
        )
        # Counts only: never log holdings.
        log_event(
            logger,
            logging.INFO,
            "portfolio snapshot created",
            snapshot_id=snapshot.snapshot_id,
            positions=len(snapshot.positions),
        )
        return snapshot, parsed.warnings
