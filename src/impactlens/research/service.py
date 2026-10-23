"""Research application service: event studies, analogs and calibration over stored data."""

from __future__ import annotations

from impactlens.entities.resolver import SecurityResolver
from impactlens.intelligence.entity_pipeline import ResolutionSummary
from impactlens.market.calendar import calendar_for
from impactlens.market.provider import MarketDataProvider
from impactlens.research.analogs import AnalogFeatures, find_analogs
from impactlens.research.calibration import CalibrationReport, Observation, calibrate
from impactlens.research.event_study import EventStudyConfig, run_event_study
from impactlens.storage.repositories import (
    AnalysisRepository,
    EventStudyRepository,
    ImpactRepository,
    NewsRepository,
    NotFoundError,
    PortfolioRepository,
)
from impactlens.timeutil import utc_now_iso


class ResearchService:
    def __init__(
        self,
        provider: MarketDataProvider | None,
        resolver: SecurityResolver,
        news: NewsRepository,
        analyses: AnalysisRepository,
        impacts: ImpactRepository,
        studies: EventStudyRepository,
        portfolios: PortfolioRepository,
        config: EventStudyConfig = EventStudyConfig(),
    ) -> None:
        self.provider = provider
        self.resolver = resolver
        self.news = news
        self.analyses = analyses
        self.impacts = impacts
        self.studies = studies
        self.portfolios = portfolios
        self.config = config

    def _study_securities(self, news_id: int) -> list[str]:
        ids: list[str] = []
        for impact in self.impacts.list_all():
            if impact["news_id"] == news_id:
                ids.extend(
                    c["security_id"] for c in self.impacts.components(impact["impact_id"]) if c["counted"]
                )
        analysis = self.analyses.latest_for_news(news_id)
        if analysis and analysis["status"] == "Valid" and analysis["resolution"]:
            for entity in ResolutionSummary.model_validate(analysis["resolution"]).impact_entities:
                ids.extend(entity.security_ids)
        return sorted(dict.fromkeys(ids))

    def run_event_studies(self, news_id: int, *, as_of: str | None = None) -> list[dict]:
        if self.provider is None:
            raise RuntimeError("market data provider is disabled (MARKET_DATA_PROVIDER=none)")
        news = self.news.get(news_id)
        if news is None:
            raise NotFoundError(f"news {news_id} not found")
        as_of = as_of or utc_now_iso()
        out = []
        for security_id in self._study_securities(news_id):
            sec = self.resolver.get(security_id)
            if sec is None:
                continue
            calendar = calendar_for(sec.exchange)
            alignment = calendar.align(news.event_time, news.published_at_quality.value)
            result = run_event_study(
                security_symbol=sec.ticker,
                alignment=alignment,
                calendar=calendar,
                provider=self.provider,
                as_of=as_of,
                config=self.config,
            )
            payload = result.model_dump(mode="json")
            if calendar.name == "XNYS" and sec.exchange not in {"NYSE", "NASDAQ", "XNYS", "XNAS"}:
                payload["notes"] = [*payload["notes"], f"no calendar for {sec.exchange}; NYSE calendar used"]
            study_id = self.studies.upsert(
                news_id, security_id, self.config.benchmark, self.config.version, as_of, payload
            )
            out.append({"id": study_id, "security_id": security_id, **payload})
        return out

    def stored_studies(self, news_id: int) -> list[dict]:
        return self.studies.for_news(news_id)

    def _features(self, analysis: dict, event_time: str, title: str) -> AnalogFeatures:
        issuers: set[str] = set()
        sectors: set[str] = set()
        if analysis.get("resolution"):
            for entity in ResolutionSummary.model_validate(analysis["resolution"]).impact_entities:
                if entity.issuer_id:
                    issuers.add(entity.issuer_id)
                for sid in entity.security_ids:
                    sec = self.resolver.get(sid)
                    if sec and sec.sector:
                        sectors.add(sec.sector)
                if entity.kind == "sector" and entity.factor_key:
                    sectors.add(entity.factor_key.split(":", 1)[1])
        return AnalogFeatures(
            analysis_id=analysis["analysis_id"],
            news_id=analysis["news_id"],
            event_time=event_time,
            event_type=analysis["event_type"],
            direction=analysis["direction"],
            severity=analysis["severity"],
            time_horizon=analysis["time_horizon"],
            issuers=frozenset(issuers),
            sectors=frozenset(sectors),
            title=title,
        )

    def analogs(self, analysis_id: int, limit: int = 5) -> dict:
        target = self.analyses.get(analysis_id)
        if target is None or target["status"] != "Valid":
            raise NotFoundError(f"valid analysis {analysis_id} not found")
        news = self.news.get(target["news_id"])
        assert news is not None
        query = self._features(target, news.event_time, news.title)
        candidates = []
        for row in self.analyses.valid_with_news():
            cand_news = self.news.get(row["news_id"])
            if cand_news is None:
                continue
            candidates.append(self._features(row, cand_news.event_time, cand_news.title))
        results = find_analogs(query, candidates, limit=limit)
        return {
            "query": query.model_dump(mode="json"),
            "cutoff": query.event_time,
            "analogs": [a.model_dump(mode="json") for a in results],
        }

    def observations(self, window: tuple[int, int] = (0, 1)) -> list[Observation]:
        studies = {(s["news_id"], s["security_id"]): s for s in self.studies.all()}
        obs = []
        for impact in self.impacts.list_all():
            news = self.news.get(impact["news_id"])
            analysis = self.analyses.get(impact["analysis_id"])
            snapshot = self.portfolios.get_snapshot(impact["snapshot_id"])
            if news is None or analysis is None or snapshot is None:
                continue
            for comp in self.impacts.components(impact["impact_id"]):
                if not comp["counted"]:
                    continue
                study = studies.get((impact["news_id"], comp["security_id"]))
                ar, status = None, None
                if study:
                    match = [w for w in study["result"]["windows"] if tuple(w["window"]) == tuple(window)]
                    if match:
                        ar, status = match[0]["abnormal_return"], match[0]["status"]
                    else:
                        status = "window_not_computed"
                provenance_times = [v.get("as_of") for v in [comp["provenance"]] if v.get("as_of")]
                obs.append(
                    Observation(
                        impact_id=impact["impact_id"],
                        news_id=impact["news_id"],
                        security_id=comp["security_id"],
                        event_type=analysis["event_type"],
                        position_level=comp["position_level"],
                        signed_component=comp["signed_component"],
                        event_time=news.event_time,
                        feature_times={
                            "news_published_at": news.published_at,
                            "snapshot_as_of": snapshot.as_of,
                            **(
                                {
                                    "relationship_as_of": provenance_times[0]
                                    + ("T00:00:00Z" if len(provenance_times[0]) == 10 else "")
                                }
                                if provenance_times
                                else {}
                            ),
                        },
                        abnormal_return=ar,
                        study_status=status,
                    )
                )
        return obs

    def calibration(self, window: tuple[int, int] = (0, 1), strict: bool = False) -> CalibrationReport:
        return calibrate(self.observations(window), window, strict_point_in_time=strict)
