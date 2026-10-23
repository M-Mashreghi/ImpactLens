"""Application container: wires settings, persistence, providers and services once.

The API, dashboard, CLI and worker all use this container so business logic lives in
exactly one place.
"""

from __future__ import annotations

from pathlib import Path

from impactlens.alerts.service import AlertChannel, AlertPolicy, AlertService, ConsoleChannel, WebhookChannel
from impactlens.config import Settings, ensure_runtime_dirs, load_settings
from impactlens.entities.resolver import SecurityResolver
from impactlens.entities.seed import load_reference_data
from impactlens.impact.exposure import ExposureEngine
from impactlens.impact.service import ImpactService
from impactlens.ingestion.contracts import AdapterRegistry
from impactlens.ingestion.manual import HttpArticleFetcher, NewsContentFetcher
from impactlens.ingestion.rss import RssFeedAdapter
from impactlens.ingestion.service import IngestionService
from impactlens.intelligence.llm import (
    FixtureLLMProvider,
    OpenAICompatibleProvider,
    StructuredAnalysisProvider,
    StructuredLLMClient,
)
from impactlens.intelligence.service import AnalysisService
from impactlens.logging_setup import configure_logging, redactor
from impactlens.market.provider import CachedMarketDataProvider, CsvMarketDataProvider, MarketDataProvider
from impactlens.portfolio.service import PortfolioService
from impactlens.research.service import ResearchService
from impactlens.storage.db import Database
from impactlens.storage.repositories import (
    AlertRepository,
    AnalysisRepository,
    CheckpointRepository,
    EventStudyRepository,
    ImpactRepository,
    JobRunRepository,
    NewsRepository,
    PortfolioRepository,
    RelationshipRepository,
    SecurityRepository,
)


def build_llm_provider(settings: Settings) -> StructuredAnalysisProvider:
    if settings.llm.provider == "openai_compatible":
        assert settings.llm.api_key is not None
        return OpenAICompatibleProvider(
            api_key=settings.llm.api_key.get_secret_value(),
            model=settings.llm.model,
            base_url=settings.llm.base_url,
            timeout_seconds=settings.llm.timeout_seconds,
        )
    return FixtureLLMProvider.from_directory(
        Path(settings.samples_dir) / "analyses", model_name=settings.llm.model
    )


def build_market_provider(settings: Settings) -> MarketDataProvider | None:
    if settings.market.provider == "none":
        return None
    return CachedMarketDataProvider(
        CsvMarketDataProvider(settings.market.csv_dir), settings.cache_dir, settings.market.cache_max_entries
    )


def build_registry(settings: Settings) -> AdapterRegistry:
    registry = AdapterRegistry()
    for priority, (key, url) in enumerate(settings.news.rss_feeds):
        registry.register(
            RssFeedAdapter(
                key,
                url,
                timeout_seconds=settings.news.http_timeout_seconds,
                user_agent=settings.news.user_agent,
            ),
            enabled=key not in settings.news.disabled_sources,
            priority=priority,
        )
    return registry


def build_alert_channel(settings: Settings) -> AlertChannel:
    if settings.alerts.channel == "webhook" and settings.alerts.webhook_url is not None:
        return WebhookChannel(settings.alerts.webhook_url.get_secret_value())
    return ConsoleChannel()


class Container:
    def __init__(
        self,
        settings: Settings,
        *,
        llm_provider: StructuredAnalysisProvider | None = None,
        market_provider: MarketDataProvider | None | str = "default",
        registry: AdapterRegistry | None = None,
        alert_channel: AlertChannel | None = None,
        article_fetcher: NewsContentFetcher | None = None,
        llm_backoff_seconds: float = 1.0,
    ) -> None:
        self.settings = settings
        redactor.register(*settings.secret_values())
        ensure_runtime_dirs(settings)
        self.db = Database(settings.database.path)
        self.db.initialize()
        self.securities = SecurityRepository(self.db)
        self.relationships = RelationshipRepository(self.db)
        self.portfolios = PortfolioRepository(self.db)
        self.news = NewsRepository(self.db)
        self.checkpoints = CheckpointRepository(self.db)
        self.analyses = AnalysisRepository(self.db)
        self.impacts = ImpactRepository(self.db)
        self.alerts = AlertRepository(self.db)
        self.studies = EventStudyRepository(self.db)
        self.job_runs = JobRunRepository(self.db)

        self.registry = registry if registry is not None else build_registry(settings)
        self.article_fetcher = article_fetcher or HttpArticleFetcher(
            timeout_seconds=settings.news.http_timeout_seconds, user_agent=settings.news.user_agent
        )
        self.llm_client = StructuredLLMClient(
            llm_provider or build_llm_provider(settings),
            max_retries=settings.llm.max_retries,
            backoff_seconds=llm_backoff_seconds,
        )
        self.market_provider: MarketDataProvider | None = (
            build_market_provider(settings) if isinstance(market_provider, str) else market_provider
        )
        self.alert_channel = alert_channel or build_alert_channel(settings)
        self.ingestion = IngestionService(self.news, self.checkpoints)
        self.portfolio_service = PortfolioService(self.portfolios, lambda: self.resolver)
        self.reload_reference_data()

    # Reference data (security master/relationships) can change; services are rebuilt on reload.
    def reload_reference_data(self) -> None:
        securities = self.securities.list()
        self.resolver = SecurityResolver(securities)
        self.exposure_engine = ExposureEngine(
            {s.security_id: s for s in securities},
            self.relationships.relationships(),
            self.relationships.factor_exposures(),
            disabled_families=self.settings.disabled_exposure_families,
        )
        self.analysis_service = AnalysisService(self.llm_client, self.resolver, self.news, self.analyses)
        self.impact_service = ImpactService(self.exposure_engine, self.news, self.analyses, self.impacts)
        self.alert_service = AlertService(
            self.alerts,
            self.news,
            self.alert_channel,
            AlertPolicy(
                min_level=self.settings.alerts.min_level,
                cooldown_seconds=self.settings.alerts.cooldown_seconds,
            ),
            enabled=self.settings.alerts.enabled,
        )
        self.research = ResearchService(
            self.market_provider,
            self.resolver,
            self.news,
            self.analyses,
            self.impacts,
            self.studies,
            self.portfolios,
        )

    def seed_reference_data(self, samples_dir: str | None = None) -> dict[str, int]:
        counts = load_reference_data(
            samples_dir or self.settings.samples_dir, self.securities, self.relationships
        )
        self.reload_reference_data()
        return counts

    def close(self) -> None:
        self.db.close()


def create_container(settings: Settings | None = None, **overrides) -> Container:
    settings = settings or load_settings()
    configure_logging(settings.log_level, settings.log_format, settings.secret_values())
    return Container(settings, **overrides)
