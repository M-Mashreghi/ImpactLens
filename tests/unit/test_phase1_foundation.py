"""Tasks 1.1–1.2: scaffolding, configuration, secrets and structured logging."""

from __future__ import annotations

import io
import json
import logging
import re

import pytest

import impactlens
from impactlens.config import ConfigError, load_settings
from impactlens.logging_setup import (
    ContextFilter,
    JsonFormatter,
    RedactingFilter,
    SecretRedactor,
    configure_logging,
    get_logger,
    log_context,
    log_event,
    redactor,
)
from tests.conftest import ROOT


def test_package_imports_and_version():
    assert impactlens.__version__
    assert "not expected returns" in impactlens.DISCLAIMER


def test_env_example_has_placeholders_only():
    text = (ROOT / ".env.example").read_text()
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        value = value.split("#", 1)[0].strip()
        if key.strip() in {"LLM_API_KEY", "MARKET_DATA_API_KEY", "ALERT_WEBHOOK_URL"}:
            assert value in {"", "replace-me"}, key
        assert not re.search(r"sk-[A-Za-z0-9]{10,}", value)


def test_gitignore_quarantines_secrets_and_private_portfolios():
    text = (ROOT / ".gitignore").read_text()
    for pattern in (".env", "/data/private/", "*.db", "portfolio*.csv"):
        assert pattern in text


def test_sample_data_is_marked_synthetic():
    assert "synthetic" in (ROOT / "data" / "samples" / "README.md").read_text().lower()


def test_defaults_load_without_env():
    settings = load_settings({})
    assert settings.env.value == "development"
    assert settings.llm.provider == "fixture"
    assert settings.llm.api_key is None


def test_production_requires_real_providers():
    with pytest.raises(ConfigError) as exc:
        load_settings({"IMPACTLENS_ENV": "production"})
    assert "LLM_PROVIDER=fixture" in str(exc.value)


def test_openai_provider_requires_key_and_model():
    with pytest.raises(ConfigError) as exc:
        load_settings({"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": "replace-me"})
    msg = str(exc.value)
    assert "LLM_API_KEY is required" in msg and "LLM_MODEL is required" in msg


def test_webhook_alerts_require_url():
    with pytest.raises(ConfigError):
        load_settings({"ALERTS_ENABLED": "true", "ALERT_CHANNEL": "webhook"})


def test_invalid_values_fail_clearly():
    with pytest.raises(ConfigError):
        load_settings({"LLM_TIMEOUT_SECONDS": "-1"})
    with pytest.raises(ConfigError):
        load_settings({"EXPOSURE_DISABLED_FAMILIES": "sector,telepathy"})
    with pytest.raises(ConfigError):
        load_settings({"NEWS_RSS_FEEDS": "missing-separator"})


def test_secrets_are_hidden_in_repr_and_safe_view():
    secret = "sk-test-SUPERSECRET-123456"
    settings = load_settings({"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": secret, "LLM_MODEL": "m"})
    assert secret not in repr(settings)
    assert secret not in json.dumps(settings.safe_view())
    assert settings.safe_view()["llm"]["api_key_configured"] is True
    assert secret in settings.secret_values()


def _capture(secret_values: list[str]) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextFilter())
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("impactlens.test.capture")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    redactor.register(*secret_values)
    return logger, stream


def test_logging_never_emits_configured_secret_values():
    secret = "sk-live-ABCDEF0123456789"
    logger, stream = _capture([secret])
    logger.info("calling provider with key %s", secret)
    log_event(logger, logging.INFO, "headers", headers={"Authorization": f"Bearer {secret}"})
    try:
        raise RuntimeError(f"boom {secret}")
    except RuntimeError:
        logger.exception("failure")
    output = stream.getvalue()
    assert secret not in output
    assert "***REDACTED***" in output


def test_logging_scrubs_unregistered_auth_patterns():
    scrub = SecretRedactor().scrub
    assert "abc123def456ghi" not in scrub("Authorization: Bearer abc123def456ghi")
    assert "hunter2pass" not in scrub("password=hunter2pass&x=1")
    assert "zzzz-9999-key" not in scrub('{"api_key": "zzzz-9999-key"}')


def test_structured_logs_carry_correlation_context():
    logger, stream = _capture([])
    with log_context(correlation_id="cid-1", news_id=42, stage="analysis"):
        logger.info("hello")
    record = json.loads(stream.getvalue().strip())
    assert record["correlation_id"] == "cid-1" and record["news_id"] == 42 and record["stage"] == "analysis"


def test_configure_logging_installs_redacting_handler():
    configure_logging("INFO", "json", ["topsecretvalue-xyz"])
    handler = get_logger("impactlens").handlers[0]
    assert any(isinstance(f, RedactingFilter) for f in handler.filters)
