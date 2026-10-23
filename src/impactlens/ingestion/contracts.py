"""Provider-neutral news ingestion contract and adapter registry."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class SourceCursor(BaseModel):
    """Opaque per-source checkpoint. Adapters decide what goes in ``state``."""

    model_config = ConfigDict(frozen=True)
    source_key: str
    seen_item_ids: tuple[str, ...] = ()
    etag: str | None = None
    last_modified: str | None = None
    last_published_at: str | None = None
    max_seen: int = 2000

    def with_seen(self, ids: Iterable[str], **updates: object) -> SourceCursor:
        merged = list(dict.fromkeys([*ids, *self.seen_item_ids]))[: self.max_seen]
        return self.model_copy(update={"seen_item_ids": tuple(merged), **updates})


class RawNewsItem(BaseModel):
    """What an adapter hands to the pipeline. Content is untrusted input."""

    model_config = ConfigDict(frozen=True)
    source_key: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_kind: str = Field(default="feed", description="feed | manual | fixture")
    source_item_id: str | None = None
    url: str | None = None
    title: str
    body: str = ""
    published_raw: str | None = None
    retrieved_at: str
    extra: dict[str, str] = Field(default_factory=dict)


class ItemError(BaseModel):
    model_config = ConfigDict(frozen=True)
    item_ref: str | None
    error_type: str
    message: str


class FetchResult(BaseModel):
    """Adapter output: successfully parsed items, isolated per-item errors, next cursor."""

    model_config = ConfigDict(frozen=True)
    items: tuple[RawNewsItem, ...] = ()
    errors: tuple[ItemError, ...] = ()
    cursor: SourceCursor | None = None
    not_modified: bool = False


class SourceFetchError(RuntimeError):
    """Whole-source failure (network, HTTP status, unparseable feed)."""

    def __init__(self, source_key: str, error_type: str, message: str) -> None:
        self.source_key = source_key
        self.error_type = error_type
        super().__init__(f"{source_key}: {error_type}: {message}")


@runtime_checkable
class NewsSourceAdapter(Protocol):
    key: str
    name: str

    def fetch(self, cursor: SourceCursor | None) -> FetchResult: ...


class AdapterRegistration(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    key: str
    adapter: object
    enabled: bool = True
    priority: int = 100


class AdapterRegistry:
    """Registry with config enablement and priority (lower number polls first)."""

    def __init__(self) -> None:
        self._entries: dict[str, AdapterRegistration] = {}

    def register(self, adapter: NewsSourceAdapter, *, enabled: bool = True, priority: int = 100) -> None:
        if adapter.key in self._entries:
            raise ValueError(f"adapter key already registered: {adapter.key}")
        self._entries[adapter.key] = AdapterRegistration(
            key=adapter.key, adapter=adapter, enabled=enabled, priority=priority
        )

    def set_enabled(self, key: str, enabled: bool) -> None:
        self._entries[key] = self._entries[key].model_copy(update={"enabled": enabled})

    def get(self, key: str) -> NewsSourceAdapter:
        try:
            return self._entries[key].adapter  # type: ignore[return-value]
        except KeyError as exc:
            raise KeyError(f"unknown news source: {key}") from exc

    def keys(self) -> list[str]:
        return sorted(self._entries)

    def enabled_adapters(self) -> list[NewsSourceAdapter]:
        entries = sorted((e for e in self._entries.values() if e.enabled), key=lambda e: (e.priority, e.key))
        return [e.adapter for e in entries]  # type: ignore[misc]

    def describe(self) -> list[dict[str, object]]:
        return [
            {"key": e.key, "enabled": e.enabled, "priority": e.priority}
            for e in sorted(self._entries.values(), key=lambda e: (e.priority, e.key))
        ]
