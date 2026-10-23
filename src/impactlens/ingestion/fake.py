"""Deterministic in-memory adapter for tests and offline demos."""

from __future__ import annotations

from collections.abc import Sequence

from impactlens.ingestion.contracts import FetchResult, RawNewsItem, SourceCursor, SourceFetchError


class FakeNewsAdapter:
    def __init__(
        self,
        key: str,
        items: Sequence[RawNewsItem] = (),
        *,
        name: str | None = None,
        fail_with: str | None = None,
    ) -> None:
        self.key = key
        self.name = name or key
        self.items = list(items)
        self.fail_with = fail_with
        self.calls = 0

    def fetch(self, cursor: SourceCursor | None) -> FetchResult:
        self.calls += 1
        if self.fail_with:
            raise SourceFetchError(self.key, "FakeFailure", self.fail_with)
        seen = set(cursor.seen_item_ids) if cursor else set()
        fresh = [i for i in self.items if i.source_item_id not in seen]
        base = cursor or SourceCursor(source_key=self.key)
        return FetchResult(
            items=tuple(fresh),
            cursor=base.with_seen(i.source_item_id for i in fresh if i.source_item_id),
        )
