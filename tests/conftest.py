from __future__ import annotations

import json
from pathlib import Path

import pytest

from impactlens.app import Container
from impactlens.config import load_settings
from impactlens.entities.models import Security
from impactlens.entities.resolver import SecurityResolver
from impactlens.intelligence.llm import FixtureLLMProvider
from impactlens.market.provider import CsvMarketDataProvider

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def samples_dir() -> Path:
    return SAMPLES


@pytest.fixture
def securities() -> list[Security]:
    return [Security.model_validate(r) for r in json.loads((SAMPLES / "securities.json").read_text())]


@pytest.fixture
def resolver(securities) -> SecurityResolver:
    return SecurityResolver(securities)


@pytest.fixture
def env(tmp_path) -> dict[str, str]:
    return {
        "IMPACTLENS_ENV": "test",
        "IMPACTLENS_DB_PATH": str(tmp_path / "db" / "impactlens.db"),
        "IMPACTLENS_CACHE_DIR": str(tmp_path / "cache"),
        "IMPACTLENS_SAMPLES_DIR": str(SAMPLES),
        "MARKET_DATA_CSV_DIR": str(SAMPLES / "prices"),
        "ALERTS_ENABLED": "true",
        "ALERT_MIN_LEVEL": "High",
        "LLM_MAX_RETRIES": "1",
    }


@pytest.fixture
def settings(env):
    return load_settings(env)


@pytest.fixture
def container(settings, tmp_path):
    from impactlens.alerts.service import ConsoleChannel

    c = Container(
        settings,
        llm_provider=FixtureLLMProvider.from_directory(SAMPLES / "analyses"),
        market_provider=CsvMarketDataProvider(SAMPLES / "prices"),
        alert_channel=ConsoleChannel(stream=open(tmp_path / "alerts.log", "w")),  # noqa: SIM115
        llm_backoff_seconds=0,
    )
    c.seed_reference_data(str(SAMPLES))
    yield c
    c.close()


@pytest.fixture
def demo_snapshot(container):
    snapshot, _ = container.portfolio_service.import_csv(
        "Demo Portfolio", (SAMPLES / "portfolio_demo.csv").read_bytes(), as_of="2025-01-02T00:00:00Z"
    )
    return snapshot
