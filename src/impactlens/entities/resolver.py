"""Deterministic security/entity resolver. Authoritative for ticker mapping — never the LLM."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from impactlens.entities.models import Security
from impactlens.entities.normalize import normalize_name, normalize_ticker


class ResolutionStatus(StrEnum):
    RESOLVED = "Resolved"
    AMBIGUOUS = "Ambiguous"
    UNRESOLVED = "Unresolved"


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True)
    security_id: str
    issuer_id: str
    ticker: str
    exchange: str
    canonical_name: str


class SecurityResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    status: ResolutionStatus
    method: str
    issuer_id: str | None = None
    security_ids: tuple[str, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    notes: tuple[str, ...] = ()


class SecurityResolver:
    """Resolves names/aliases/tickers to issuers and securities.

    * A name/alias maps to an *issuer*; all active securities of that issuer are returned
      (e.g. multiple share classes). Names matching more than one issuer are Ambiguous.
    * A ticker resolves only if exactly one active listing matches (optionally filtered by
      exchange). Tickers listed on several exchanges stay Ambiguous unless disambiguated.
    * Nothing outside the security master is ever invented: misses are Unresolved.
    """

    def __init__(self, securities: Iterable[Security]) -> None:
        self._securities = {s.security_id: s for s in securities if s.active}
        self._by_name: dict[str, set[str]] = defaultdict(set)
        self._by_ticker: dict[str, set[str]] = defaultdict(set)
        self._issuer_securities: dict[str, list[str]] = defaultdict(list)
        for sec in sorted(self._securities.values(), key=lambda s: s.security_id):
            self._issuer_securities[sec.issuer_id].append(sec.security_id)
            self._by_ticker[normalize_ticker(sec.ticker)].add(sec.security_id)
            for name in (sec.canonical_name, *sec.aliases):
                normalized = normalize_name(name)
                if normalized:
                    self._by_name[normalized].add(sec.issuer_id)

    def get(self, security_id: str) -> Security | None:
        return self._securities.get(security_id)

    @property
    def securities(self) -> list[Security]:
        return sorted(self._securities.values(), key=lambda s: s.security_id)

    def sectors(self) -> set[str]:
        return {s.sector for s in self._securities.values() if s.sector}

    def industries(self) -> set[str]:
        return {s.industry for s in self._securities.values() if s.industry}

    def _candidate(self, security_id: str) -> Candidate:
        sec = self._securities[security_id]
        return Candidate(
            security_id=sec.security_id,
            issuer_id=sec.issuer_id,
            ticker=sec.ticker,
            exchange=sec.exchange,
            canonical_name=sec.canonical_name,
        )

    def resolve_ticker(self, ticker: str, exchange: str | None = None) -> SecurityResolution:
        key = normalize_ticker(ticker)
        matches = sorted(self._by_ticker.get(key, set()))
        if exchange:
            matches = [m for m in matches if self._securities[m].exchange == exchange.strip().upper()]
        if not matches:
            return SecurityResolution(query=ticker, status=ResolutionStatus.UNRESOLVED, method="ticker")
        if len(matches) > 1:
            return SecurityResolution(
                query=ticker,
                status=ResolutionStatus.AMBIGUOUS,
                method="ticker",
                candidates=tuple(self._candidate(m) for m in matches),
                notes=("ticker listed on multiple exchanges; exchange required",),
            )
        sec = self._securities[matches[0]]
        return SecurityResolution(
            query=ticker,
            status=ResolutionStatus.RESOLVED,
            method="ticker",
            issuer_id=sec.issuer_id,
            security_ids=(sec.security_id,),
            candidates=(self._candidate(sec.security_id),),
        )

    def resolve_name(self, name: str) -> SecurityResolution:
        """Resolve a company name/alias; falls back to the text being a bare ticker symbol."""
        key = normalize_name(name)
        issuers = sorted(self._by_name.get(key, set()))
        if len(issuers) == 1:
            ids = tuple(self._issuer_securities[issuers[0]])
            return SecurityResolution(
                query=name,
                status=ResolutionStatus.RESOLVED,
                method="name",
                issuer_id=issuers[0],
                security_ids=ids,
                candidates=tuple(self._candidate(i) for i in ids),
            )
        if len(issuers) > 1:
            ids = tuple(sid for issuer in issuers for sid in self._issuer_securities[issuer])
            return SecurityResolution(
                query=name,
                status=ResolutionStatus.AMBIGUOUS,
                method="name",
                candidates=tuple(self._candidate(i) for i in ids),
                notes=("name matches multiple issuers",),
            )
        stripped = name.strip()
        if stripped and stripped.lstrip("$").isupper() and " " not in stripped and len(stripped) <= 6:
            by_ticker = self.resolve_ticker(stripped)
            if by_ticker.status is not ResolutionStatus.UNRESOLVED:
                return by_ticker.model_copy(update={"method": "name_as_ticker"})
        return SecurityResolution(query=name, status=ResolutionStatus.UNRESOLVED, method="name")
