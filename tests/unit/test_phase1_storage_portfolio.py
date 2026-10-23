"""Tasks 1.3–1.5: SQLite schema, portfolio snapshots/CSV import, security resolver."""

from __future__ import annotations

import sqlite3

import pytest

from impactlens.entities.resolver import ResolutionStatus
from impactlens.portfolio.csv_importer import PortfolioImportError, parse_portfolio_csv
from impactlens.portfolio.models import WeightBasis
from impactlens.storage.db import Database, latest_known_version, schema_version
from impactlens.storage.repositories import PortfolioRepository

# ----------------------------------------------------------------------------- 1.3


def test_fresh_db_initializes_and_is_idempotent(tmp_path):
    db = Database(str(tmp_path / "x.db"))
    assert db.initialize() == [1]
    assert db.initialize() == []
    assert schema_version(db.conn) == latest_known_version() == 1
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in (
        "portfolios",
        "portfolio_snapshots",
        "positions",
        "securities",
        "news",
        "analyses",
        "impacts",
        "impact_components",
        "alerts",
        "event_studies",
        "schema_migrations",
        "source_checkpoints",
    ):
        assert t in tables
    indexes = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"ix_news_hash", "ix_news_status", "ix_snapshots_portfolio_asof", "ix_impacts_priority"} <= indexes


def test_modified_migration_is_detected(tmp_path):
    db = Database(str(tmp_path / "x.db"))
    db.initialize()
    db.conn.execute("UPDATE schema_migrations SET checksum = 'tampered'")
    from impactlens.storage.db import MigrationError

    with pytest.raises(MigrationError):
        db.initialize()


def test_insert_read_smoke(container, demo_snapshot):
    loaded = container.portfolios.get_snapshot(demo_snapshot.snapshot_id)
    assert loaded == demo_snapshot
    assert container.securities.get("sec_nvda").ticker == "NVDA"


# ----------------------------------------------------------------------------- 1.4


def test_synthetic_portfolio_imports_with_market_value_weights(container, demo_snapshot):
    weights = {p.ticker: p.weight for p in demo_snapshot.positions}
    assert weights["NVDA"] == pytest.approx(0.15)
    assert weights["CASH"] == pytest.approx(0.05)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert demo_snapshot.weight_basis is WeightBasis.MARKET_VALUE
    assert demo_snapshot.total_market_value == pytest.approx(1_000_000)
    googl = [p for p in demo_snapshot.positions if p.ticker in ("GOOGL", "GOOG")]
    assert {p.security_id for p in googl} == {"sec_googl", "sec_goog"}


def test_snapshots_are_immutable(container, demo_snapshot):
    with pytest.raises(sqlite3.IntegrityError):
        container.db.conn.execute(
            "UPDATE positions SET weight = 0.5 WHERE snapshot_id = ?", (demo_snapshot.snapshot_id,)
        )
    with pytest.raises(sqlite3.IntegrityError):
        container.db.conn.execute(
            "DELETE FROM portfolio_snapshots WHERE snapshot_id = ?", (demo_snapshot.snapshot_id,)
        )
    with pytest.raises((TypeError, ValueError)):
        demo_snapshot.positions[0].weight = 0.9  # type: ignore[misc]


def test_reimport_creates_new_snapshot_and_keeps_old(container, demo_snapshot, samples_dir):
    second, _ = container.portfolio_service.import_csv(
        "Demo Portfolio", "ticker,weight\nNVDA,0.5\nAAPL,0.5\n", as_of="2025-02-01T00:00:00Z"
    )
    assert second.snapshot_id != demo_snapshot.snapshot_id
    assert container.portfolios.get_snapshot(demo_snapshot.snapshot_id) == demo_snapshot
    assert (
        container.portfolios.snapshot_at(second.portfolio_id, "2025-01-15T00:00:00Z").snapshot_id
        == demo_snapshot.snapshot_id
    )
    assert [s.snapshot_id for s in container.portfolios.active_snapshots()] == [second.snapshot_id]


def test_snapshot_hash_is_deterministic(demo_snapshot):
    again = PortfolioRepository.snapshot_hash(list(demo_snapshot.positions), demo_snapshot.as_of)
    assert again == demo_snapshot.content_hash


@pytest.mark.parametrize(
    ("csv_text", "fragment"),
    [
        ("symbol,weight\nNVDA,1\n", "missing required column"),
        ("ticker,colour,weight\nNVDA,red,1\n", "unknown column"),
        ("ticker,weight\nNVDA,abc\n", "not a number"),
        ("ticker,weight\nNVDA,-0.1\nAMD,1.1\n", "negative values"),
        ("ticker,weight\nNVDA,0.5\nNVDA,0.5\n", "duplicate position NVDA"),
        ("ticker,weight\nNVDA,0.5\nAMD,0.3\n", "weights sum to 0.8000"),
        ("ticker,weight\nZZZZ,1\n", "unknown ticker"),
        ("ticker,weight\nABC,1\n", "ambiguous"),
        ("ticker,market_value,weight\nNVDA,100,0.9\nAMD,100,0.1\n", "inconsistent with market value share"),
        ("ticker,weight\nNVDA,15\n", "fractions in [0, 1]"),
        ("ticker,market_value\nNVDA,100\nAMD,\n", "every row needs market_value"),
    ],
)
def test_invalid_portfolio_csv_produces_row_level_errors(resolver, csv_text, fragment):
    with pytest.raises(PortfolioImportError) as exc:
        parse_portfolio_csv(csv_text, resolver)
    assert fragment in str(exc.value)
    assert all(e.line >= 0 for e in exc.value.errors)


def test_ambiguous_ticker_resolves_with_exchange(resolver):
    parsed = parse_portfolio_csv("ticker,exchange,weight\nABC,TSX,1\n", resolver)
    assert parsed.positions[0].security_id == "sec_abc_tsx"


def test_weights_within_tolerance_are_rescaled(resolver):
    parsed = parse_portfolio_csv("ticker,weight\nNVDA,0.502\nAMD,0.5\n", resolver)
    assert sum(p.weight for p in parsed.positions) == pytest.approx(1.0)
    assert parsed.warnings


def test_oversized_and_non_utf8_files_rejected(resolver):
    with pytest.raises(PortfolioImportError):
        parse_portfolio_csv(b"ticker,weight\n" + b"x" * 1_100_000, resolver)
    with pytest.raises(PortfolioImportError):
        parse_portfolio_csv(b"\xff\xfe\x00bad", resolver)


def test_no_real_private_portfolio_in_fixtures(samples_dir):
    csvs = list(samples_dir.rglob("*.csv"))
    portfolio_csvs = [p for p in csvs if "portfolio" in p.name]
    assert [p.name for p in portfolio_csvs] == ["portfolio_demo.csv"]


# ----------------------------------------------------------------------------- 1.5


@pytest.mark.parametrize("alias", ["NVIDIA", "Nvidia Corp", "NVIDIA Corporation", "nvidia corp.", "NVDA"])
def test_known_aliases_resolve_deterministically(resolver, alias):
    result = resolver.resolve_name(alias)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.security_ids == ("sec_nvda",)


def test_issuer_with_share_classes_returns_all_securities(resolver):
    result = resolver.resolve_name("Alphabet")
    assert result.status is ResolutionStatus.RESOLVED
    assert result.issuer_id == "iss_alphabet"
    assert result.security_ids == ("sec_goog", "sec_googl")


def test_ambiguous_ticker_and_name_remain_ambiguous(resolver):
    assert resolver.resolve_ticker("ABC").status is ResolutionStatus.AMBIGUOUS
    name = resolver.resolve_name("Acme")
    assert name.status is ResolutionStatus.AMBIGUOUS
    assert {c.security_id for c in name.candidates} == {"sec_acmi", "sec_acmf"}
    assert resolver.resolve_ticker("ABC", "NYSE").security_ids == ("sec_abc_nyse",)


def test_unknown_entity_does_not_invent_ticker(resolver):
    result = resolver.resolve_name("Zephyr Robotics")
    assert result.status is ResolutionStatus.UNRESOLVED
    assert result.security_ids == () and result.issuer_id is None


def test_resolver_is_callable_without_llm(securities):
    import ast
    import inspect

    import impactlens.entities.resolver as module
    from impactlens.entities.resolver import SecurityResolver

    assert SecurityResolver(securities).resolve_name("Apple").security_ids == ("sec_aapl",)
    imports = [
        n.module for n in ast.walk(ast.parse(inspect.getsource(module))) if isinstance(n, ast.ImportFrom)
    ]
    assert not any("intelligence" in (m or "") for m in imports)
