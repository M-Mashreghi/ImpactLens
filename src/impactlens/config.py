"""Typed, environment-driven settings.

Secrets are held as ``SecretStr`` so they never appear in reprs, and every configured
secret value is registered with the logging redactor.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str = "./var/impactlens.db"


class LLMSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str = "fixture"
    api_key: SecretStr | None = None
    base_url: str = "https://api.openai.com/v1"
    model: str = "fixture-model"
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    max_retries: int = Field(default=2, ge=0, le=10)


class NewsSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    poll_interval_seconds: int = Field(default=900, ge=10)
    rss_feeds: tuple[tuple[str, str], ...] = ()
    disabled_sources: tuple[str, ...] = ()
    http_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    user_agent: str = "ImpactLens/1.0 (+research)"


class MarketDataSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str = "csv"
    api_key: SecretStr | None = None
    csv_dir: str = "./data/samples/prices"
    cache_max_entries: int = Field(default=500, ge=1)


class AlertSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled: bool = False
    channel: str = "console"
    webhook_url: SecretStr | None = None
    min_level: str = "High"
    cooldown_seconds: int = Field(default=3600, ge=0)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    log_format: str = "json"
    cache_dir: str = "./var/cache"
    samples_dir: str = "./data/samples"
    api_url: str = "http://localhost:8000"
    disabled_exposure_families: tuple[str, ...] = ()
    database: DatabaseSettings = DatabaseSettings()
    llm: LLMSettings = LLMSettings()
    news: NewsSettings = NewsSettings()
    market: MarketDataSettings = MarketDataSettings()
    alerts: AlertSettings = AlertSettings()

    def secret_values(self) -> list[str]:
        """All configured secret values, for log redaction."""
        values = []
        for secret in (self.llm.api_key, self.market.api_key, self.alerts.webhook_url):
            if secret is not None and secret.get_secret_value():
                values.append(secret.get_secret_value())
        return values

    def safe_view(self) -> dict[str, object]:
        """Configuration safe to expose via API/UI (no secret values)."""
        return {
            "env": self.env.value,
            "log_level": self.log_level,
            "database_path_configured": bool(self.database.path),
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "api_key_configured": self.llm.api_key is not None,
            },
            "news": {
                "poll_interval_seconds": self.news.poll_interval_seconds,
                "rss_sources": [key for key, _ in self.news.rss_feeds],
                "disabled_sources": list(self.news.disabled_sources),
            },
            "market": {"provider": self.market.provider},
            "alerts": {
                "enabled": self.alerts.enabled,
                "channel": self.alerts.channel,
                "min_level": self.alerts.min_level,
                "cooldown_seconds": self.alerts.cooldown_seconds,
                "webhook_configured": self.alerts.webhook_url is not None,
            },
            "disabled_exposure_families": list(self.disabled_exposure_families),
        }


_PLACEHOLDERS = {"", "replace-me", "changeme", "xxx"}


def _get(env: Mapping[str, str], key: str, default: str | None = None) -> str | None:
    value = env.get(key)
    if value is None:
        return default
    value = value.split(" #", 1)[0].strip()
    return value if value else default


def _secret(env: Mapping[str, str], key: str) -> SecretStr | None:
    value = _get(env, key)
    if value is None or value.lower() in _PLACEHOLDERS:
        return None
    return SecretStr(value)


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _feeds(value: str | None) -> tuple[tuple[str, str], ...]:
    feeds = []
    for part in _csv(value):
        if "|" not in part:
            raise ConfigError(f"NEWS_RSS_FEEDS entry must be 'key|url', got {part!r}")
        key, url = part.split("|", 1)
        feeds.append((key.strip(), url.strip()))
    return tuple(feeds)


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build settings from environment variables and validate production requirements."""
    env = os.environ if env is None else env
    try:
        settings = Settings(
            env=AppEnv(_get(env, "IMPACTLENS_ENV", "development") or "development"),
            log_level=(_get(env, "IMPACTLENS_LOG_LEVEL", "INFO") or "INFO").upper(),
            log_format=_get(env, "IMPACTLENS_LOG_FORMAT", "json") or "json",
            cache_dir=_get(env, "IMPACTLENS_CACHE_DIR", "./var/cache") or "./var/cache",
            samples_dir=_get(env, "IMPACTLENS_SAMPLES_DIR", "./data/samples") or "./data/samples",
            api_url=_get(env, "IMPACTLENS_API_URL", "http://localhost:8000") or "",
            disabled_exposure_families=_csv(_get(env, "EXPOSURE_DISABLED_FAMILIES")),
            database=DatabaseSettings(path=_get(env, "IMPACTLENS_DB_PATH", "./var/impactlens.db") or ""),
            llm=LLMSettings(
                provider=_get(env, "LLM_PROVIDER", "fixture") or "fixture",
                api_key=_secret(env, "LLM_API_KEY"),
                base_url=_get(env, "LLM_BASE_URL", "https://api.openai.com/v1") or "",
                model=_get(env, "LLM_MODEL", "fixture-model") or "fixture-model",
                timeout_seconds=float(_get(env, "LLM_TIMEOUT_SECONDS", "30") or 30),
                max_retries=int(_get(env, "LLM_MAX_RETRIES", "2") or 2),
            ),
            news=NewsSettings(
                poll_interval_seconds=int(_get(env, "NEWS_POLL_INTERVAL_SECONDS", "900") or 900),
                rss_feeds=_feeds(_get(env, "NEWS_RSS_FEEDS")),
                disabled_sources=_csv(_get(env, "NEWS_DISABLED_SOURCES")),
                http_timeout_seconds=float(_get(env, "NEWS_HTTP_TIMEOUT_SECONDS", "15") or 15),
                user_agent=_get(env, "NEWS_USER_AGENT", "ImpactLens/1.0 (+research)") or "",
            ),
            market=MarketDataSettings(
                provider=_get(env, "MARKET_DATA_PROVIDER", "csv") or "csv",
                api_key=_secret(env, "MARKET_DATA_API_KEY"),
                csv_dir=_get(env, "MARKET_DATA_CSV_DIR", "./data/samples/prices") or "",
                cache_max_entries=int(_get(env, "MARKET_DATA_CACHE_MAX_ENTRIES", "500") or 500),
            ),
            alerts=AlertSettings(
                enabled=_bool(_get(env, "ALERTS_ENABLED")),
                channel=_get(env, "ALERT_CHANNEL", "console") or "console",
                webhook_url=_secret(env, "ALERT_WEBHOOK_URL"),
                min_level=_get(env, "ALERT_MIN_LEVEL", "High") or "High",
                cooldown_seconds=int(_get(env, "ALERT_COOLDOWN_SECONDS", "3600") or 3600),
            ),
        )
    except (ValidationError, ValueError) as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    """Fail clearly when required settings are missing for the selected providers/env."""
    problems: list[str] = []
    if settings.llm.provider not in {"fixture", "openai_compatible"}:
        problems.append(
            f"LLM_PROVIDER must be 'fixture' or 'openai_compatible', got {settings.llm.provider!r}"
        )
    if settings.market.provider not in {"csv", "none"}:
        problems.append(f"MARKET_DATA_PROVIDER must be 'csv' or 'none', got {settings.market.provider!r}")
    if settings.alerts.channel not in {"console", "webhook"}:
        problems.append(f"ALERT_CHANNEL must be 'console' or 'webhook', got {settings.alerts.channel!r}")
    if settings.alerts.min_level not in {"Low", "Medium", "High", "Critical"}:
        problems.append("ALERT_MIN_LEVEL must be one of Low, Medium, High, Critical")
    unknown_families = set(settings.disabled_exposure_families) - {
        "sector",
        "industry",
        "country",
        "commodity",
        "macro",
        "relationship",
    }
    if unknown_families:
        problems.append(f"EXPOSURE_DISABLED_FAMILIES has unknown families: {sorted(unknown_families)}")
    if settings.llm.provider == "openai_compatible":
        if settings.llm.api_key is None:
            problems.append("LLM_API_KEY is required when LLM_PROVIDER=openai_compatible")
        if not settings.llm.model or settings.llm.model in {"fixture-model", "replace-me"}:
            problems.append("LLM_MODEL is required when LLM_PROVIDER=openai_compatible")
    if (
        settings.alerts.enabled
        and settings.alerts.channel == "webhook"
        and settings.alerts.webhook_url is None
    ):
        problems.append("ALERT_WEBHOOK_URL is required when ALERTS_ENABLED=true and ALERT_CHANNEL=webhook")
    if settings.env is AppEnv.PRODUCTION:
        if not settings.database.path or settings.database.path == ":memory:":
            problems.append("IMPACTLENS_DB_PATH must be a durable file path in production")
        if settings.llm.provider == "fixture":
            problems.append("LLM_PROVIDER=fixture is a demo provider and is not allowed in production")
    if problems:
        raise ConfigError("Configuration invalid:\n- " + "\n- ".join(problems))


def ensure_runtime_dirs(settings: Settings) -> None:
    if settings.database.path and settings.database.path != ":memory:":
        Path(settings.database.path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.cache_dir).mkdir(parents=True, exist_ok=True)
