"""``impactlens`` command-line interface (thin wrapper over application services)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from impactlens import DISCLAIMER


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def _container():
    from impactlens.app import create_container

    return create_container()


def cmd_init_db(args) -> int:
    c = _container()
    from impactlens.storage.db import schema_version

    _print({"database": c.settings.database.path, "schema_version": schema_version(c.db.conn)})
    return 0


def cmd_seed(args) -> int:
    c = _container()
    _print(c.seed_reference_data(args.samples_dir))
    return 0


def cmd_import_portfolio(args) -> int:
    from impactlens.portfolio.csv_importer import PortfolioImportError

    c = _container()
    try:
        snapshot, warnings = c.portfolio_service.import_csv(
            args.name, Path(args.csv).read_bytes(), as_of=args.as_of
        )
    except PortfolioImportError as exc:
        for err in exc.errors:
            print(f"error: {err}", file=sys.stderr)
        return 2
    _print({"snapshot_id": snapshot.snapshot_id, "positions": len(snapshot.positions), "warnings": warnings})
    return 0


def cmd_ingest_text(args) -> int:
    from impactlens.ingestion.manual import ManualInputError, build_manual_item

    c = _container()
    text = Path(args.file).read_text("utf-8") if args.file else args.text
    try:
        item = build_manual_item(
            title=args.title or "", text=text or "", url=args.url, published_at=args.published_at
        )
    except ManualInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print(c.ingestion.ingest_item(item).model_dump(mode="json"))
    return 0


def cmd_ingest_url(args) -> int:
    from impactlens.ingestion.manual import ArticleFetchError, build_item_from_url

    c = _container()
    try:
        item = build_item_from_url(c.article_fetcher, args.url, published_at=args.published_at)
    except ArticleFetchError as exc:
        _print({"error": exc.to_dict()})
        return 2
    _print(c.ingestion.ingest_item(item).model_dump(mode="json"))
    return 0


def cmd_poll(args) -> int:
    c = _container()
    _print([s.model_dump() for s in c.ingestion.poll_all(c.registry)])
    return 0


def cmd_analyze(args) -> int:
    c = _container()
    _print([o.model_dump(mode="json") for o in c.analysis_service.analyze_pending(args.limit)])
    return 0


def cmd_score(args) -> int:
    c = _container()
    snapshots = (
        [c.portfolios.get_snapshot(args.snapshot_id)] if args.snapshot_id else c.portfolios.active_snapshots()
    )
    out = []
    for analysis in c.analyses.list(status="Valid", limit=1000):
        for snap in snapshots:
            if snap is not None:
                out.append(
                    c.impact_service.score(analysis["analysis_id"], snap, force=args.force).model_dump()
                )
    _print(out)
    return 0


def cmd_run_once(args) -> int:
    from impactlens.jobs.workflow import run_cycle

    _print(run_cycle(_container()))
    return 0


def cmd_worker(args) -> int:
    from impactlens.jobs.run import main as worker_main

    return worker_main([])


def cmd_demo(args) -> int:
    """Seed reference data, import the synthetic portfolio, ingest sample news, run the pipeline."""
    from impactlens.ingestion.fake import FakeNewsAdapter
    from impactlens.ingestion.samples import load_sample_news
    from impactlens.jobs.workflow import run_cycle

    c = _container()
    samples = Path(args.samples_dir or c.settings.samples_dir)
    c.seed_reference_data(str(samples))
    if not c.portfolios.list():
        c.portfolio_service.import_csv(
            "Demo Portfolio", (samples / "portfolio_demo.csv").read_bytes(), as_of="2025-01-02T00:00:00Z"
        )
    if "demo-fixture" not in c.registry.keys():
        c.registry.register(
            FakeNewsAdapter("demo-fixture", load_sample_news(samples / "news"), name="Demo Fixture Wire"),
            priority=0,
        )
    summary = run_cycle(c)
    for news in c.news.list(limit=500, include_duplicates=False):
        if news.ingestion_status.value in {"Scored", "Alerted"} and c.market_provider is not None:
            c.research.run_event_studies(news.news_id, as_of=args.as_of)
    summary["feed"] = [
        {
            "impact_id": i["impact_id"],
            "level": i["impact_level"],
            "priority": i["absolute_priority"],
            "news_id": i["news_id"],
        }
        for i in c.impact_service.feed()
    ]
    summary["disclaimer"] = DISCLAIMER
    _print(summary)
    return 0


def cmd_event_study(args) -> int:
    c = _container()
    _print(c.research.run_event_studies(args.news_id, as_of=args.as_of))
    return 0


def cmd_calibrate(args) -> int:
    c = _container()
    _print(c.research.calibration((args.start, args.end)).model_dump(mode="json"))
    return 0


def cmd_export(args) -> int:
    from impactlens.export.brief import build_export_record, to_csv, to_json, to_markdown

    c = _container()
    impact = c.impacts.get(args.impact_id)
    if impact is None:
        print("error: impact not found", file=sys.stderr)
        return 2
    record = build_export_record(
        impact,
        c.analyses.get(impact["analysis_id"]),
        c.news.get(impact["news_id"]).model_dump(mode="json"),
        c.studies.for_news(impact["news_id"]),
    )
    text = {"json": to_json, "csv": to_csv, "md": to_markdown}[args.format](record)
    if args.output:
        Path(args.output).write_text(text, "utf-8")
        print(args.output)
    else:
        sys.stdout.write(text)
    return 0


def cmd_eval(args) -> int:
    from impactlens.intelligence.eval import main as eval_main

    return eval_main([args.dataset] if args.dataset else [])


def cmd_backup(args) -> int:
    from impactlens.config import load_settings
    from impactlens.storage.backup import backup_database

    settings = load_settings()
    print(backup_database(settings.database.path, args.dir, keep=args.keep))
    return 0


def cmd_restore(args) -> int:
    from impactlens.config import load_settings
    from impactlens.storage.backup import restore_database

    settings = load_settings()
    print(restore_database(args.backup, args.db or settings.database.path, force=args.force))
    return 0


def cmd_health(args) -> int:
    from impactlens.health import readiness

    result = readiness(_container())
    _print(result)
    return 0 if result["status"] == "ready" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="impactlens", description="ImpactLens CLI. " + DISCLAIMER)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create/migrate the SQLite database").set_defaults(func=cmd_init_db)
    p = sub.add_parser("seed", help="load the demo security master/relationships")
    p.add_argument("--samples-dir")
    p.set_defaults(func=cmd_seed)
    p = sub.add_parser("import-portfolio", help="import a portfolio CSV as a new immutable snapshot")
    p.add_argument("csv")
    p.add_argument("--name", required=True)
    p.add_argument("--as-of")
    p.set_defaults(func=cmd_import_portfolio)
    p = sub.add_parser("ingest-text", help="ingest pasted news text")
    p.add_argument("--title")
    p.add_argument("--text")
    p.add_argument("--file")
    p.add_argument("--url")
    p.add_argument("--published-at")
    p.set_defaults(func=cmd_ingest_text)
    p = sub.add_parser("ingest-url", help="fetch and ingest an explicit article URL")
    p.add_argument("url")
    p.add_argument("--published-at")
    p.set_defaults(func=cmd_ingest_url)
    sub.add_parser("poll", help="poll enabled news sources once").set_defaults(func=cmd_poll)
    p = sub.add_parser("analyze", help="analyze pending news")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_analyze)
    p = sub.add_parser("score", help="score valid analyses against snapshots")
    p.add_argument("--snapshot-id")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_score)
    sub.add_parser("run-once", help="one full workflow cycle").set_defaults(func=cmd_run_once)
    sub.add_parser("worker", help="run the scheduler until stopped").set_defaults(func=cmd_worker)
    p = sub.add_parser("demo", help="offline end-to-end demo on synthetic data")
    p.add_argument("--samples-dir")
    p.add_argument("--as-of", default="2025-03-31T21:00:00Z")
    p.set_defaults(func=cmd_demo)
    p = sub.add_parser("event-study", help="run event studies for a news item")
    p.add_argument("news_id", type=int)
    p.add_argument("--as-of")
    p.set_defaults(func=cmd_event_study)
    p = sub.add_parser("calibrate", help="score-bucket calibration report")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=1)
    p.set_defaults(func=cmd_calibrate)
    p = sub.add_parser("export", help="export an impact as json/csv/md")
    p.add_argument("impact_id", type=int)
    p.add_argument("--format", choices=["json", "csv", "md"], default="md")
    p.add_argument("--output")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("eval", help="offline analysis evaluation on the labelled fixture set")
    p.add_argument("--dataset")
    p.set_defaults(func=cmd_eval)
    p = sub.add_parser("backup", help="consistent online SQLite backup")
    p.add_argument("--dir", default="./backups")
    p.add_argument("--keep", type=int, default=14)
    p.set_defaults(func=cmd_backup)
    p = sub.add_parser("restore", help="verify and restore a SQLite backup")
    p.add_argument("backup")
    p.add_argument("--db")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_restore)
    sub.add_parser("health", help="readiness check").set_defaults(func=cmd_health)
    return parser


def main(argv: list[str] | None = None) -> int:
    from impactlens.config import ConfigError

    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
