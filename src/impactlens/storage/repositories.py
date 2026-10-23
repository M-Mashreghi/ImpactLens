"""Repositories hiding SQLite details from application services."""

from __future__ import annotations

import builtins
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from impactlens.entities.models import FactorExposure, Security, SecurityRelationship
from impactlens.ingestion.contracts import SourceCursor
from impactlens.news.models import NewsRecord, NewsStatus, NormalizedNews, TimestampQuality
from impactlens.portfolio.models import Portfolio, PortfolioSnapshot, Position, WeightBasis
from impactlens.storage.db import Database
from impactlens.timeutil import utc_now_iso


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _loads(value: str | None) -> Any:
    return json.loads(value) if value else None


class NotFoundError(LookupError):
    pass


# --------------------------------------------------------------------------- securities
class SecurityRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, security: Security) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO securities (security_id, issuer_id, canonical_name, ticker, exchange, mic, country,"
                " currency, sector, industry, share_class, aliases_json, active)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(security_id) DO UPDATE SET issuer_id=excluded.issuer_id,"
                " canonical_name=excluded.canonical_name, ticker=excluded.ticker, exchange=excluded.exchange,"
                " mic=excluded.mic, country=excluded.country, currency=excluded.currency, sector=excluded.sector,"
                " industry=excluded.industry, share_class=excluded.share_class, aliases_json=excluded.aliases_json,"
                " active=excluded.active",
                (
                    security.security_id,
                    security.issuer_id,
                    security.canonical_name,
                    security.ticker,
                    security.exchange,
                    security.mic,
                    security.country,
                    security.currency,
                    security.sector,
                    security.industry,
                    security.share_class,
                    _dumps(list(security.aliases)),
                    int(security.active),
                ),
            )

    def list(self) -> builtins.list[Security]:
        rows = self.db.query("SELECT * FROM securities ORDER BY security_id")
        return [self._row(r) for r in rows]

    def get(self, security_id: str) -> Security | None:
        row = self.db.query_one("SELECT * FROM securities WHERE security_id = ?", (security_id,))
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> Security:
        return Security(
            security_id=row["security_id"],
            issuer_id=row["issuer_id"],
            canonical_name=row["canonical_name"],
            ticker=row["ticker"],
            exchange=row["exchange"],
            mic=row["mic"],
            country=row["country"],
            currency=row["currency"],
            sector=row["sector"],
            industry=row["industry"],
            share_class=row["share_class"],
            aliases=tuple(_loads(row["aliases_json"]) or []),
            active=bool(row["active"]),
        )

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM securities")
        return int(row["n"]) if row else 0


class RelationshipRepository:
    """Stores only provenance-backed relationships/exposures (validated by the models)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add_relationship(self, rel: SecurityRelationship) -> None:
        rel = SecurityRelationship.model_validate(rel.model_dump())  # re-validate provenance
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO security_relationships (source_security_id, target_security_id, relationship_type,"
                " strength, provenance_source, provenance_ref, as_of) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(source_security_id, target_security_id, relationship_type) DO UPDATE SET"
                " strength=excluded.strength, provenance_source=excluded.provenance_source,"
                " provenance_ref=excluded.provenance_ref, as_of=excluded.as_of",
                (
                    rel.source_security_id,
                    rel.target_security_id,
                    rel.relationship_type.value,
                    rel.strength,
                    rel.provenance_source,
                    rel.provenance_ref,
                    rel.as_of,
                ),
            )

    def add_factor_exposure(self, exp: FactorExposure) -> None:
        exp = FactorExposure.model_validate(exp.model_dump())
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO security_factor_exposures (security_id, factor_key, family, sensitivity,"
                " provenance_source, provenance_ref, as_of) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(security_id, factor_key) DO UPDATE SET family=excluded.family,"
                " sensitivity=excluded.sensitivity, provenance_source=excluded.provenance_source,"
                " provenance_ref=excluded.provenance_ref, as_of=excluded.as_of",
                (
                    exp.security_id,
                    exp.factor_key,
                    exp.family.value,
                    exp.sensitivity,
                    exp.provenance_source,
                    exp.provenance_ref,
                    exp.as_of,
                ),
            )

    def relationships(self) -> builtins.list[tuple[int, SecurityRelationship]]:
        rows = self.db.query("SELECT * FROM security_relationships ORDER BY id")
        return [
            (
                r["id"],
                SecurityRelationship(
                    source_security_id=r["source_security_id"],
                    target_security_id=r["target_security_id"],
                    relationship_type=r["relationship_type"],
                    strength=r["strength"],
                    provenance_source=r["provenance_source"],
                    provenance_ref=r["provenance_ref"],
                    as_of=r["as_of"],
                ),
            )
            for r in rows
        ]

    def factor_exposures(self) -> builtins.list[tuple[int, FactorExposure]]:
        rows = self.db.query("SELECT * FROM security_factor_exposures ORDER BY id")
        return [
            (
                r["id"],
                FactorExposure(
                    security_id=r["security_id"],
                    factor_key=r["factor_key"],
                    family=r["family"],
                    sensitivity=r["sensitivity"],
                    provenance_source=r["provenance_source"],
                    provenance_ref=r["provenance_ref"],
                    as_of=r["as_of"],
                ),
            )
            for r in rows
        ]


# --------------------------------------------------------------------------- portfolios
class PortfolioRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_or_create(self, name: str, base_currency: str = "USD") -> Portfolio:
        row = self.db.query_one("SELECT * FROM portfolios WHERE name = ?", (name,))
        if row:
            return Portfolio(**dict(row))
        portfolio = Portfolio(
            portfolio_id="pf_" + uuid.uuid4().hex[:12],
            name=name,
            base_currency=base_currency,
            created_at=utc_now_iso(),
        )
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO portfolios (portfolio_id, name, base_currency, created_at) VALUES (?,?,?,?)",
                (portfolio.portfolio_id, portfolio.name, portfolio.base_currency, portfolio.created_at),
            )
        return portfolio

    def list(self) -> builtins.list[Portfolio]:
        return [Portfolio(**dict(r)) for r in self.db.query("SELECT * FROM portfolios ORDER BY name")]

    def get(self, portfolio_id: str) -> Portfolio | None:
        row = self.db.query_one("SELECT * FROM portfolios WHERE portfolio_id = ?", (portfolio_id,))
        return Portfolio(**dict(row)) if row else None

    @staticmethod
    def snapshot_hash(positions: builtins.list[Position], as_of: str) -> str:
        payload = _dumps({"as_of": as_of, "positions": [p.model_dump(mode="json") for p in positions]})
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

    def create_snapshot(
        self,
        portfolio: Portfolio,
        positions: builtins.list[Position],
        *,
        as_of: str,
        source: str,
        weight_basis: WeightBasis,
        total_market_value: float | None,
    ) -> PortfolioSnapshot:
        snapshot = PortfolioSnapshot(
            snapshot_id="snap_" + uuid.uuid4().hex[:16],
            portfolio_id=portfolio.portfolio_id,
            as_of=as_of,
            created_at=utc_now_iso(),
            source=source,
            weight_basis=weight_basis,
            total_market_value=total_market_value,
            content_hash=self.snapshot_hash(positions, as_of),
            positions=tuple(positions),
        )
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO portfolio_snapshots (snapshot_id, portfolio_id, as_of, created_at, source,"
                " weight_basis, total_market_value, content_hash) VALUES (?,?,?,?,?,?,?,?)",
                (
                    snapshot.snapshot_id,
                    snapshot.portfolio_id,
                    snapshot.as_of,
                    snapshot.created_at,
                    snapshot.source,
                    snapshot.weight_basis.value,
                    snapshot.total_market_value,
                    snapshot.content_hash,
                ),
            )
            conn.executemany(
                "INSERT INTO positions (snapshot_id, line_no, security_id, ticker, exchange, display_name,"
                " asset_type, quantity, market_value, weight, currency) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        snapshot.snapshot_id,
                        p.line_no,
                        p.security_id,
                        p.ticker,
                        p.exchange,
                        p.display_name,
                        p.asset_type.value,
                        p.quantity,
                        p.market_value,
                        p.weight,
                        p.currency,
                    )
                    for p in positions
                ],
            )
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> PortfolioSnapshot | None:
        row = self.db.query_one("SELECT * FROM portfolio_snapshots WHERE snapshot_id = ?", (snapshot_id,))
        if not row:
            return None
        positions = [
            Position(**{k: r[k] for k in r.keys() if k != "snapshot_id"})
            for r in self.db.query(
                "SELECT * FROM positions WHERE snapshot_id = ? ORDER BY line_no", (snapshot_id,)
            )
        ]
        return PortfolioSnapshot(**dict(row), positions=tuple(positions))

    def list_snapshots(self, portfolio_id: str) -> builtins.list[PortfolioSnapshot]:
        rows = self.db.query(
            "SELECT snapshot_id FROM portfolio_snapshots WHERE portfolio_id = ? ORDER BY as_of DESC, created_at DESC",
            (portfolio_id,),
        )
        return [s for s in (self.get_snapshot(r["snapshot_id"]) for r in rows) if s]

    def snapshot_at(self, portfolio_id: str, at: str) -> PortfolioSnapshot | None:
        """Latest snapshot whose as_of <= ``at`` (point-in-time holdings)."""
        row = self.db.query_one(
            "SELECT snapshot_id FROM portfolio_snapshots WHERE portfolio_id = ? AND as_of <= ?"
            " ORDER BY as_of DESC, created_at DESC LIMIT 1",
            (portfolio_id, at),
        )
        return self.get_snapshot(row["snapshot_id"]) if row else None

    def active_snapshots(self) -> builtins.list[PortfolioSnapshot]:
        """Latest snapshot of every portfolio."""
        rows = self.db.query(
            "SELECT s.snapshot_id FROM portfolio_snapshots s WHERE s.snapshot_id = ("
            " SELECT s2.snapshot_id FROM portfolio_snapshots s2 WHERE s2.portfolio_id = s.portfolio_id"
            " ORDER BY s2.as_of DESC, s2.created_at DESC LIMIT 1) ORDER BY s.portfolio_id"
        )
        return [s for s in (self.get_snapshot(r["snapshot_id"]) for r in rows) if s]


# --------------------------------------------------------------------------- news
class NewsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def find_duplicate(self, item: NormalizedNews) -> NewsRecord | None:
        """Exact duplicate by content hash, then source item id, then canonical URL."""
        checks: builtins.list[tuple[str, tuple]] = [("content_hash = ?", (item.content_hash,))]
        if item.source_item_id:
            checks.append(("source_name = ? AND source_item_id = ?", (item.source_name, item.source_item_id)))
        if item.canonical_url:
            checks.append(("canonical_url = ?", (item.canonical_url,)))
        for where, params in checks:
            row = self.db.query_one(
                f"SELECT * FROM news WHERE {where} ORDER BY news_id LIMIT 1",
                params,  # noqa: S608 - fixed clauses
            )
            if row:
                record = self._row(row)
                if record.canonical_news_id is not None:
                    return self.get(record.canonical_news_id)
                return record
        return None

    def insert(
        self, item: NormalizedNews, status: NewsStatus, canonical_news_id: int | None = None
    ) -> NewsRecord:
        now = utc_now_iso()
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO news (source_name, source_kind, source_item_id, source_url, canonical_url, title,"
                " normalized_title, body_text, normalized_text, published_at, published_at_quality, retrieved_at,"
                " content_hash, canonical_news_id, ingestion_status, provenance_json, status_updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.source_name,
                    item.source_kind,
                    item.source_item_id,
                    item.source_url,
                    item.canonical_url,
                    item.title,
                    item.normalized_title,
                    item.body_text,
                    item.normalized_text,
                    item.published_at,
                    item.published_at_quality.value,
                    item.retrieved_at,
                    item.content_hash,
                    canonical_news_id,
                    status.value,
                    _dumps(item.provenance),
                    now,
                ),
            )
            news_id = int(cur.lastrowid or 0)
            for state in (NewsStatus.DISCOVERED, NewsStatus.FETCHED, NewsStatus.NORMALIZED, status):
                conn.execute(
                    "INSERT INTO news_status_history (news_id, status, at, detail_json) VALUES (?,?,?,?)",
                    (
                        news_id,
                        state.value,
                        now,
                        _dumps({"canonical_news_id": canonical_news_id})
                        if state is NewsStatus.DUPLICATE
                        else None,
                    ),
                )
        record = self.get(news_id)
        assert record is not None
        return record

    def set_status(
        self, news_id: int, status: NewsStatus, detail: dict | None = None, error: dict | None = None
    ) -> None:
        now = utc_now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE news SET ingestion_status = ?, status_updated_at = ?, error_json = COALESCE(?, error_json)"
                " WHERE news_id = ?",
                (status.value, now, _dumps(error) if error else None, news_id),
            )
            conn.execute(
                "INSERT INTO news_status_history (news_id, status, at, detail_json) VALUES (?,?,?,?)",
                (news_id, status.value, now, _dumps(detail) if detail else None),
            )

    def get(self, news_id: int) -> NewsRecord | None:
        row = self.db.query_one("SELECT * FROM news WHERE news_id = ?", (news_id,))
        return self._row(row) if row else None

    def history(self, news_id: int) -> builtins.list[dict]:
        return [
            {"status": r["status"], "at": r["at"], "detail": _loads(r["detail_json"])}
            for r in self.db.query(
                "SELECT * FROM news_status_history WHERE news_id = ? ORDER BY id", (news_id,)
            )
        ]

    def list(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0, include_duplicates: bool = True
    ) -> builtins.list[NewsRecord]:
        clauses, params = [], []
        if status:
            clauses.append("ingestion_status = ?")
            params.append(status)
        if not include_duplicates:
            clauses.append("canonical_news_id IS NULL")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.query(
            f"SELECT * FROM news {where} ORDER BY COALESCE(published_at, retrieved_at) DESC, news_id DESC"  # noqa: S608
            " LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [self._row(r) for r in rows]

    def pending_analysis(self, limit: int = 100) -> builtins.list[NewsRecord]:
        rows = self.db.query(
            "SELECT * FROM news WHERE ingestion_status = ? AND canonical_news_id IS NULL ORDER BY news_id LIMIT ?",
            (NewsStatus.PENDING_ANALYSIS.value, limit),
        )
        return [self._row(r) for r in rows]

    def count(self, canonical_only: bool = False) -> int:
        sql = "SELECT COUNT(*) AS n FROM news" + (
            " WHERE canonical_news_id IS NULL" if canonical_only else ""
        )
        row = self.db.query_one(sql)
        return int(row["n"]) if row else 0

    def duplicates_of(self, news_id: int) -> builtins.list[int]:
        return [
            r["news_id"]
            for r in self.db.query(
                "SELECT news_id FROM news WHERE canonical_news_id = ? ORDER BY news_id", (news_id,)
            )
        ]

    @staticmethod
    def _row(row: sqlite3.Row) -> NewsRecord:
        return NewsRecord(
            news_id=row["news_id"],
            source_key=(_loads(row["provenance_json"]) or {}).get("source_key", ""),
            source_name=row["source_name"],
            source_kind=row["source_kind"],
            source_item_id=row["source_item_id"],
            source_url=row["source_url"],
            canonical_url=row["canonical_url"],
            title=row["title"],
            normalized_title=row["normalized_title"],
            body_text=row["body_text"],
            normalized_text=row["normalized_text"],
            published_at=row["published_at"],
            published_at_quality=TimestampQuality(row["published_at_quality"]),
            retrieved_at=row["retrieved_at"],
            content_hash=row["content_hash"],
            canonical_news_id=row["canonical_news_id"],
            ingestion_status=NewsStatus(row["ingestion_status"]),
            error=_loads(row["error_json"]),
            provenance=_loads(row["provenance_json"]) or {},
            status_updated_at=row["status_updated_at"],
        )


class CheckpointRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, source_key: str) -> SourceCursor | None:
        row = self.db.query_one(
            "SELECT cursor_json FROM source_checkpoints WHERE source_key = ?", (source_key,)
        )
        return SourceCursor.model_validate_json(row["cursor_json"]) if row else None

    def save(self, cursor: SourceCursor) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO source_checkpoints (source_key, cursor_json, updated_at) VALUES (?,?,?)"
                " ON CONFLICT(source_key) DO UPDATE SET cursor_json=excluded.cursor_json, updated_at=excluded.updated_at",
                (cursor.source_key, cursor.model_dump_json(), utc_now_iso()),
            )

    def record_failure(
        self, source_key: str, item_ref: str | None, stage: str, error_type: str, message: str
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO ingestion_failures (source_key, item_ref, stage, error_type, message, at)"
                " VALUES (?,?,?,?,?,?)",
                (source_key, item_ref, stage, error_type, message[:1000], utc_now_iso()),
            )

    def failures(self, limit: int = 100) -> builtins.list[dict]:
        return [
            dict(r)
            for r in self.db.query("SELECT * FROM ingestion_failures ORDER BY id DESC LIMIT ?", (limit,))
        ]


# --------------------------------------------------------------------------- analyses
class AnalysisRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def find(
        self, news_id: int, schema_version: str, prompt_version: str, model_provider: str, model_name: str
    ) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM analyses WHERE news_id=? AND schema_version=? AND prompt_version=? AND model_provider=?"
            " AND model_name=?",
            (news_id, schema_version, prompt_version, model_provider, model_name),
        )
        return self._row(row) if row else None

    def insert(self, record: dict) -> int:
        cols = list(record.keys())
        values = [(_dumps(v) if isinstance(v, (dict, list)) else v) for v in record.values()]
        with self.db.transaction() as conn:
            cur = conn.execute(
                f"INSERT INTO analyses ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",  # noqa: S608
                values,
            )
            return int(cur.lastrowid or 0)

    def update_resolution(self, analysis_id: int, resolution: dict) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE analyses SET resolution_json = ? WHERE analysis_id = ?",
                (_dumps(resolution), analysis_id),
            )

    def get(self, analysis_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,))
        return self._row(row) if row else None

    def latest_for_news(self, news_id: int) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM analyses WHERE news_id = ? ORDER BY analysis_id DESC LIMIT 1", (news_id,)
        )
        return self._row(row) if row else None

    def list(self, *, status: str | None = None, limit: int = 100) -> builtins.list[dict]:
        if status:
            rows = self.db.query(
                "SELECT * FROM analyses WHERE status = ? ORDER BY analysis_id DESC LIMIT ?", (status, limit)
            )
        else:
            rows = self.db.query("SELECT * FROM analyses ORDER BY analysis_id DESC LIMIT ?", (limit,))
        return [self._row(r) for r in rows]

    def valid_with_news(self) -> builtins.list[dict]:
        rows = self.db.query(
            "SELECT a.*, n.published_at AS news_published_at, n.retrieved_at AS news_retrieved_at,"
            " n.published_at_quality AS news_ts_quality FROM analyses a JOIN news n ON n.news_id = a.news_id"
            " WHERE a.status = 'Valid' ORDER BY a.analysis_id"
        )
        out = []
        for r in rows:
            d = self._row(r)
            d["news_published_at"] = r["news_published_at"]
            d["news_retrieved_at"] = r["news_retrieved_at"]
            d["news_ts_quality"] = r["news_ts_quality"]
            out.append(d)
        return out

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        for key in ("analysis_json", "evidence_report_json", "resolution_json", "failure_json"):
            d[key.removesuffix("_json")] = _loads(d.pop(key))
        return d


# --------------------------------------------------------------------------- impacts
class ImpactRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def find(self, analysis_id: int, snapshot_id: str, scoring_version: str) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM impacts WHERE analysis_id=? AND snapshot_id=? AND scoring_version=?",
            (analysis_id, snapshot_id, scoring_version),
        )
        return self._row(row) if row else None

    def upsert(self, impact: dict, components: builtins.list[dict]) -> int:
        existing = self.find(impact["analysis_id"], impact["snapshot_id"], impact["scoring_version"])
        with self.db.transaction() as conn:
            if existing:
                impact_id = existing["impact_id"]
                conn.execute(
                    "UPDATE impacts SET rules_version=?, signed_score=?, absolute_priority=?, impact_level=?,"
                    " result_json=?, explanation_json=?, computed_at=? WHERE impact_id=?",
                    (
                        impact["rules_version"],
                        impact["signed_score"],
                        impact["absolute_priority"],
                        impact["impact_level"],
                        _dumps(impact["result"]),
                        _dumps(impact["explanation"]),
                        impact["computed_at"],
                        impact_id,
                    ),
                )
                conn.execute("DELETE FROM impact_components WHERE impact_id = ?", (impact_id,))
            else:
                cur = conn.execute(
                    "INSERT INTO impacts (analysis_id, news_id, snapshot_id, scoring_version, rules_version,"
                    " signed_score, absolute_priority, impact_level, result_json, explanation_json, computed_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        impact["analysis_id"],
                        impact["news_id"],
                        impact["snapshot_id"],
                        impact["scoring_version"],
                        impact["rules_version"],
                        impact["signed_score"],
                        impact["absolute_priority"],
                        impact["impact_level"],
                        _dumps(impact["result"]),
                        _dumps(impact["explanation"]),
                        impact["computed_at"],
                    ),
                )
                impact_id = int(cur.lastrowid or 0)
            conn.executemany(
                "INSERT INTO impact_components (impact_id, security_id, ticker, relationship_type, direction,"
                " signed_component, absolute_component, counted, component_json) VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        impact_id,
                        c["security_id"],
                        c["ticker"],
                        c["relationship_type"],
                        c["direction"],
                        c["signed_component"],
                        c["absolute_component"],
                        int(c["counted"]),
                        _dumps(c),
                    )
                    for c in components
                ],
            )
        return impact_id

    def get(self, impact_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM impacts WHERE impact_id = ?", (impact_id,))
        return self._row(row) if row else None

    def components(self, impact_id: int) -> builtins.list[dict]:
        return [
            _loads(r["component_json"])
            for r in self.db.query(
                "SELECT component_json FROM impact_components WHERE impact_id = ? ORDER BY id", (impact_id,)
            )
        ]

    def feed(
        self,
        *,
        snapshot_id: str | None = None,
        min_level: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[dict]:
        """Ranked by absolute priority desc; ties → newer news first, then lower impact id."""
        clauses, params = [], []
        if snapshot_id:
            clauses.append("i.snapshot_id = ?")
            params.append(snapshot_id)
        if min_level:
            from impactlens.impact.scoring import LEVEL_ORDER

            allowed = [lvl for lvl, rank in LEVEL_ORDER.items() if rank >= LEVEL_ORDER[min_level]]
            clauses.append(f"i.impact_level IN ({','.join('?' * len(allowed))})")
            params.extend(allowed)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.query(
            "SELECT i.* FROM impacts i JOIN news n ON n.news_id = i.news_id "
            f"{where} ORDER BY i.absolute_priority DESC, COALESCE(n.published_at, n.retrieved_at) DESC,"  # noqa: S608
            " i.impact_id ASC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [self._row(r) for r in rows]

    def list_all(self) -> builtins.list[dict]:
        return [self._row(r) for r in self.db.query("SELECT * FROM impacts ORDER BY impact_id")]

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM impacts")
        return int(row["n"]) if row else 0

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["result"] = _loads(d.pop("result_json"))
        d["explanation"] = _loads(d.pop("explanation_json"))
        return d


# --------------------------------------------------------------------------- alerts
class AlertRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_by_key(self, key: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM alerts WHERE idempotency_key = ?", (key,))
        return self._row(row) if row else None

    def insert(self, alert: dict) -> int | None:
        """Insert; returns None if the idempotency key already exists."""
        try:
            with self.db.transaction() as conn:
                cur = conn.execute(
                    "INSERT INTO alerts (idempotency_key, impact_id, news_id, portfolio_id, snapshot_id,"
                    " scoring_version, channel, impact_level, status, detail_json, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        alert["idempotency_key"],
                        alert["impact_id"],
                        alert["news_id"],
                        alert["portfolio_id"],
                        alert["snapshot_id"],
                        alert["scoring_version"],
                        alert["channel"],
                        alert["impact_level"],
                        alert["status"],
                        _dumps(alert.get("detail") or {}),
                        alert["created_at"],
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.IntegrityError:
            return None

    def set_status(self, alert_id: int, status: str, detail: dict | None = None) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE alerts SET status = ?, detail_json = ? WHERE alert_id = ?",
                (status, _dumps(detail or {}), alert_id),
            )

    def last_sent(self, portfolio_id: str, channel: str) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM alerts WHERE portfolio_id = ? AND channel = ? AND status = 'sent'"
            " ORDER BY created_at DESC, alert_id DESC LIMIT 1",
            (portfolio_id, channel),
        )
        return self._row(row) if row else None

    def list(self, limit: int = 100) -> builtins.list[dict]:
        return [
            self._row(r)
            for r in self.db.query("SELECT * FROM alerts ORDER BY alert_id DESC LIMIT ?", (limit,))
        ]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["detail"] = _loads(d.pop("detail_json"))
        return d


# --------------------------------------------------------------------------- research / jobs
class EventStudyRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(
        self, news_id: int, security_id: str, benchmark: str, config_version: str, as_of: str, result: dict
    ) -> int:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO event_studies (news_id, security_id, benchmark_symbol, config_version, as_of,"
                " result_json, created_at) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(news_id, security_id, benchmark_symbol, config_version, as_of)"
                " DO UPDATE SET result_json = excluded.result_json",
                (news_id, security_id, benchmark, config_version, as_of, _dumps(result), utc_now_iso()),
            )
            row = conn.execute(
                "SELECT id FROM event_studies WHERE news_id=? AND security_id=? AND benchmark_symbol=?"
                " AND config_version=? AND as_of=?",
                (news_id, security_id, benchmark, config_version, as_of),
            ).fetchone()
        return int(row["id"])

    def for_news(self, news_id: int) -> builtins.list[dict]:
        return [
            {**{k: r[k] for k in r.keys() if k != "result_json"}, "result": _loads(r["result_json"])}
            for r in self.db.query("SELECT * FROM event_studies WHERE news_id = ? ORDER BY id", (news_id,))
        ]

    def all(self) -> builtins.list[dict]:
        return [
            {**{k: r[k] for k in r.keys() if k != "result_json"}, "result": _loads(r["result_json"])}
            for r in self.db.query("SELECT * FROM event_studies ORDER BY id")
        ]


class JobRunRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def start(self, job_name: str) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO job_runs (job_name, started_at, status) VALUES (?,?,?)",
                (job_name, utc_now_iso(), "running"),
            )
            return int(cur.lastrowid or 0)

    def finish(self, run_id: int, status: str, summary: dict | None = None, error: str | None = None) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE job_runs SET finished_at = ?, status = ?, summary_json = ?, error = ? WHERE run_id = ?",
                (utc_now_iso(), status, _dumps(summary or {}), error, run_id),
            )

    def latest(self, job_name: str | None = None) -> dict | None:
        if job_name:
            row = self.db.query_one(
                "SELECT * FROM job_runs WHERE job_name = ? ORDER BY run_id DESC LIMIT 1", (job_name,)
            )
        else:
            row = self.db.query_one("SELECT * FROM job_runs ORDER BY run_id DESC LIMIT 1")
        if not row:
            return None
        d = dict(row)
        d["summary"] = _loads(d.pop("summary_json"))
        return d
