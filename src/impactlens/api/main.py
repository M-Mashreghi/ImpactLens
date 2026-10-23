"""FastAPI app. Routes validate input, call application services and shape DTOs only."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from impactlens import DISCLAIMER, __version__
from impactlens.api.dto import (
    EventStudyRequest,
    ImportResult,
    IngestResponse,
    ManualNewsRequest,
    NewsDetail,
    NewsOut,
    PortfolioImportRequest,
    PortfolioOut,
    ScoreRequest,
    SnapshotOut,
)
from impactlens.export.brief import build_export_record, to_csv, to_json, to_markdown
from impactlens.health import liveness, readiness
from impactlens.ingestion.manual import (
    ArticleFetchError,
    ManualInputError,
    build_item_from_url,
    build_manual_item,
)
from impactlens.logging_setup import log_context, new_correlation_id
from impactlens.market.provider import MarketDataUnavailable
from impactlens.portfolio.csv_importer import PortfolioImportError
from impactlens.storage.repositories import NotFoundError


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None) -> None:
        self.status, self.code, self.message, self.details = status, code, message, details


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message, "details": details}}
    )


def get_container(request: Request) -> Any:
    app = request.app
    if getattr(app.state, "container", None) is None:
        from impactlens.app import create_container

        app.state.container = create_container()
        app.state.owns_container = True
    return app.state.container


C = Annotated[Any, Depends(get_container)]


def create_app(container=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if getattr(app.state, "owns_container", False) and app.state.container is not None:
            app.state.container.close()
            app.state.container = None

    app = FastAPI(
        title="ImpactLens API",
        version=__version__,
        lifespan=lifespan,
        description=f"Financial news → portfolio impact engine. {DISCLAIMER}",
    )
    app.state.container = container
    app.state.owns_container = False

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        cid = request.headers.get("x-correlation-id") or new_correlation_id()
        with log_context(correlation_id=cid[:64], stage="api"):
            response = await call_next(request)
        response.headers["x-correlation-id"] = cid[:64]
        return response

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return _error(422, "validation_error", "request validation failed", details)

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError):
        return _error(404, "not_found", str(exc))

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        return _error(exc.status_code, "http_error", str(exc.detail))

    # ------------------------------------------------------------------ health
    @app.get("/health")
    def health():
        return liveness()

    @app.get("/ready")
    def ready(c: C):
        result = readiness(c)
        return JSONResponse(status_code=200 if result["status"] == "ready" else 503, content=result)

    @app.get("/system/config")
    def system_config(c: C):
        return {"config": c.settings.safe_view(), "sources": c.registry.describe(), "disclaimer": DISCLAIMER}

    # ------------------------------------------------------------------ portfolios
    def _snapshot_out(snapshot) -> SnapshotOut:
        return SnapshotOut(**snapshot.model_dump(mode="json"))

    @app.get("/portfolios", response_model=list[PortfolioOut])
    def list_portfolios(c: C):
        out = []
        for p in c.portfolios.list():
            snaps = c.portfolios.list_snapshots(p.portfolio_id)
            out.append(
                PortfolioOut(**p.model_dump(), latest_snapshot_id=snaps[0].snapshot_id if snaps else None)
            )
        return out

    @app.post("/portfolios/import", response_model=ImportResult, status_code=201)
    def import_portfolio(body: PortfolioImportRequest, c: C):
        try:
            snapshot, warnings = c.portfolio_service.import_csv(
                body.name, body.csv_text, as_of=body.as_of, base_currency=body.base_currency.upper()
            )
        except PortfolioImportError as exc:
            raise ApiError(
                422,
                "portfolio_invalid",
                "portfolio CSV failed validation",
                [{"line": e.line, "column": e.column, "message": e.message} for e in exc.errors],
            ) from exc
        except ValueError as exc:
            raise ApiError(422, "portfolio_invalid", str(exc)) from exc
        return ImportResult(snapshot=_snapshot_out(snapshot), warnings=warnings)

    @app.get("/portfolios/{portfolio_id}/snapshots", response_model=list[SnapshotOut])
    def portfolio_snapshots(portfolio_id: str, c: C):
        if c.portfolios.get(portfolio_id) is None:
            raise NotFoundError(f"portfolio {portfolio_id} not found")
        return [_snapshot_out(s) for s in c.portfolios.list_snapshots(portfolio_id)]

    @app.get("/portfolio-snapshots/{snapshot_id}", response_model=SnapshotOut)
    def get_snapshot(snapshot_id: str, c: C):
        snapshot = c.portfolios.get_snapshot(snapshot_id)
        if snapshot is None:
            raise NotFoundError(f"snapshot {snapshot_id} not found")
        return _snapshot_out(snapshot)

    # ------------------------------------------------------------------ news
    @app.get("/news", response_model=list[NewsOut])
    def list_news(
        c: C,
        status: str | None = None,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        include_duplicates: bool = True,
    ):
        return [
            NewsOut(**n.model_dump(mode="json"))
            for n in c.news.list(
                status=status, limit=limit, offset=offset, include_duplicates=include_duplicates
            )
        ]

    @app.post("/news", response_model=IngestResponse, status_code=201)
    def ingest_news(body: ManualNewsRequest, c: C):
        try:
            if body.fetch_url:
                if not body.url:
                    raise ApiError(422, "validation_error", "url is required when fetch_url is true")
                item = build_item_from_url(c.article_fetcher, body.url, published_at=body.published_at)
            else:
                item = build_manual_item(
                    title=body.title or "", text=body.text or "", url=body.url, published_at=body.published_at
                )
        except ManualInputError as exc:
            raise ApiError(422, exc.code, str(exc)) from exc
        except ArticleFetchError as exc:
            raise ApiError(502, "url_fetch_failed", str(exc), exc.to_dict()) from exc
        outcome = c.ingestion.ingest_item(item)
        analysis = None
        if body.analyze and not outcome.duplicate:
            record = c.news.get(outcome.news_id)
            analysis = c.analysis_service.analyze(record).model_dump(mode="json")
        record = c.news.get(outcome.news_id)
        return IngestResponse(
            news_id=outcome.news_id,
            status=record.ingestion_status.value,
            duplicate=outcome.duplicate,
            canonical_news_id=outcome.canonical_news_id,
            analysis=analysis,
        )

    @app.get("/news/{news_id}", response_model=NewsDetail)
    def get_news(news_id: int, c: C):
        record = c.news.get(news_id)
        if record is None:
            raise NotFoundError(f"news {news_id} not found")
        analysis = c.analyses.latest_for_news(record.canonical_news_id or news_id)
        if analysis:
            analysis.pop("raw_response", None)
        return NewsDetail(
            **record.model_dump(mode="json"),
            history=c.news.history(news_id),
            duplicates=c.news.duplicates_of(news_id),
            analysis=analysis,
        )

    # ------------------------------------------------------------------ analyses
    @app.get("/analyses")
    def list_analyses(c: C, status: str | None = None, limit: int = Query(50, ge=1, le=500)):
        rows = c.analyses.list(status=status, limit=limit)
        for r in rows:
            r.pop("raw_response", None)
        return rows

    @app.get("/analyses/{analysis_id}")
    def get_analysis(analysis_id: int, c: C):
        row = c.analyses.get(analysis_id)
        if row is None:
            raise NotFoundError(f"analysis {analysis_id} not found")
        row.pop("raw_response", None)
        return row

    # ------------------------------------------------------------------ impacts
    @app.get("/impacts")
    def impact_feed(
        c: C,
        snapshot_id: str | None = None,
        min_level: str | None = Query(None, pattern="^(Low|Medium|High|Critical)$"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        feed = c.impact_service.feed(snapshot_id, min_level=min_level, limit=limit, offset=offset)
        for item in feed:
            news = c.news.get(item["news_id"])
            item["news"] = NewsOut(**news.model_dump(mode="json")).model_dump() if news else None
        return feed

    @app.post("/impacts/score", status_code=201)
    def score_impact(body: ScoreRequest, c: C):
        snapshot = c.portfolios.get_snapshot(body.snapshot_id)
        if snapshot is None:
            raise NotFoundError(f"snapshot {body.snapshot_id} not found")
        try:
            outcome = c.impact_service.score(body.analysis_id, snapshot, force=body.force)
        except ValueError as exc:
            raise ApiError(409, "analysis_not_scorable", str(exc)) from exc
        return outcome.model_dump()

    @app.get("/impacts/{impact_id}")
    def get_impact(impact_id: int, c: C):
        impact = c.impacts.get(impact_id)
        if impact is None:
            raise NotFoundError(f"impact {impact_id} not found")
        return impact

    @app.get("/impacts/{impact_id}/export")
    def export_impact(impact_id: int, c: C, format: str = Query("json", pattern="^(json|csv|md)$")):
        impact = c.impacts.get(impact_id)
        if impact is None:
            raise NotFoundError(f"impact {impact_id} not found")
        analysis = c.analyses.get(impact["analysis_id"])
        news = c.news.get(impact["news_id"])
        record = build_export_record(
            impact, analysis, news.model_dump(mode="json"), c.studies.for_news(impact["news_id"])
        )
        if format == "csv":
            return PlainTextResponse(to_csv(record), media_type="text/csv")
        if format == "md":
            return PlainTextResponse(to_markdown(record), media_type="text/markdown")
        return PlainTextResponse(to_json(record), media_type="application/json")

    # ------------------------------------------------------------------ alerts
    @app.get("/alerts")
    def list_alerts(c: C, limit: int = Query(100, ge=1, le=500)):
        return c.alerts.list(limit)

    # ------------------------------------------------------------------ research
    @app.post("/research/event-studies", status_code=201)
    def run_event_studies(body: EventStudyRequest, c: C):
        try:
            return c.research.run_event_studies(body.news_id, as_of=body.as_of)
        except (RuntimeError, MarketDataUnavailable) as exc:
            raise ApiError(503, "market_data_unavailable", str(exc)) from exc

    @app.get("/research/event-studies")
    def get_event_studies(news_id: int, c: C):
        return c.research.stored_studies(news_id)

    @app.get("/research/analogs/{analysis_id}")
    def analogs(analysis_id: int, c: C, limit: int = Query(5, ge=1, le=50)):
        return c.research.analogs(analysis_id, limit)

    @app.get("/research/calibration")
    def calibration(c: C, start: int = 0, end: int = 1):
        return c.research.calibration((start, end)).model_dump(mode="json")

    return app


app = create_app()
