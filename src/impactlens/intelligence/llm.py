"""Structured LLM provider abstraction, OpenAI-compatible adapter, fixture/fake providers.

The client returns a validated :class:`AnalysisOutput` or raises; malformed output never
silently becomes a valid analysis.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from impactlens.intelligence.schema import AnalysisOutput
from impactlens.logging_setup import get_logger, log_event, redactor

logger = get_logger("intelligence.llm")


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    news_id: int | None
    content_hash: str
    title: str
    text: str
    system_prompt: str
    user_prompt: str


class LLMTransientError(RuntimeError):
    """Timeout, rate limit or 5xx — safe to retry."""


class LLMPermanentError(RuntimeError):
    """Auth/config/4xx — retrying will not help."""


class MalformedOutputError(RuntimeError):
    def __init__(self, message: str, raw: str | None) -> None:
        self.raw = raw
        super().__init__(message)


class StructuredAnalysisProvider(Protocol):
    provider_name: str
    model_name: str

    def complete(self, request: AnalysisRequest) -> str: ...


class AnalysisAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)
    output: AnalysisOutput
    raw: str
    attempts: int


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def parse_output(raw: str) -> AnalysisOutput:
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise MalformedOutputError(f"output is not valid JSON: {exc.msg}", raw) from exc
    if not isinstance(data, dict):
        raise MalformedOutputError("output JSON must be an object", raw)
    try:
        return AnalysisOutput.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10])
        raise MalformedOutputError(f"output failed schema validation: {details}", raw) from exc


class StructuredLLMClient:
    """Bounded retries for transient failures and malformed output."""

    def __init__(
        self,
        provider: StructuredAnalysisProvider,
        *,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.provider = provider
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep

    def analyze(self, request: AnalysisRequest) -> AnalysisAttempt:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                raw = self.provider.complete(request)
                output = parse_output(raw)
                return AnalysisAttempt(output=output, raw=raw, attempts=attempt)
            except LLMTransientError as exc:
                last_error = exc
                log_event(logger, 30, "llm transient error", attempt=attempt, error_type=type(exc).__name__)
            except MalformedOutputError as exc:
                last_error = exc
                log_event(logger, 30, "llm malformed output", attempt=attempt, error=str(exc)[:200])
            if attempt <= self.max_retries:
                self._sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        assert last_error is not None
        raise last_error


class OpenAICompatibleProvider:
    """Chat Completions-compatible endpoint with JSON-object response format."""

    provider_name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        redactor.register(api_key)
        self._api_key = api_key
        self.model_name = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def __repr__(self) -> str:
        return f"OpenAICompatibleProvider(model={self.model_name!r}, url={self._url!r})"

    def complete(self, request: AnalysisRequest) -> str:
        body = {
            "model": self.model_name,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }
        try:
            response = self._client.post(
                self._url, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
            )
        except httpx.TimeoutException as exc:
            raise LLMTransientError("LLM request timed out") from exc
        except httpx.TransportError as exc:
            raise LLMTransientError(f"LLM transport error: {type(exc).__name__}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise LLMTransientError(f"LLM provider returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise LLMPermanentError(f"LLM provider returned HTTP {response.status_code}")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise MalformedOutputError("provider response missing choices[0].message.content", None) from exc
        if not isinstance(content, str):
            raise MalformedOutputError("provider content is not text", None)
        return content


UNCERTAIN_FALLBACK = {
    "event_type": "other_uncertain",
    "event_summary": "No curated fixture analysis exists for this article.",
    "direction": "uncertain",
    "severity": "low",
    "confidence": 0.0,
    "time_horizon": "unknown",
    "entities": [],
    "evidence": [],
    "uncertainties": ["fixture provider has no labelled analysis for this article"],
    "rationale": "Offline fixture provider returns an explicit uncertain result for unknown articles.",
    "is_uncertain": True,
}


class FixtureLLMProvider:
    """Offline demo provider: returns curated JSON keyed by content hash or exact title.

    Unknown articles get an explicit *uncertain* result, never a fabricated analysis.
    """

    provider_name = "fixture"

    def __init__(self, responses: Mapping[str, str | dict], model_name: str = "fixture-model") -> None:
        self.model_name = model_name
        self._responses = {k: v if isinstance(v, str) else json.dumps(v) for k, v in responses.items()}

    @classmethod
    def from_directory(cls, directory: str | Path, model_name: str = "fixture-model") -> FixtureLLMProvider:
        responses: dict[str, str | dict] = {}
        folder = Path(directory)
        if folder.is_dir():
            for path in sorted(folder.glob("*.json")):
                data = json.loads(path.read_text("utf-8"))
                for key in data.get("match", []):
                    responses[key] = data["response"]
        return cls(responses, model_name=model_name)

    def complete(self, request: AnalysisRequest) -> str:
        for key in (request.content_hash, request.title):
            if key in self._responses:
                return self._responses[key]
        return json.dumps(UNCERTAIN_FALLBACK)


class FakeLLMProvider:
    """Scripted provider for tests: each call pops the next string or raises the next exception."""

    provider_name = "fake"

    def __init__(self, script: Iterable[str | dict | Exception], model_name: str = "fake-model") -> None:
        self.model_name = model_name
        self._script = list(script)
        self.calls = 0

    def complete(self, request: AnalysisRequest) -> str:
        self.calls += 1
        if not self._script:
            raise AssertionError("FakeLLMProvider script exhausted")
        item = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)
