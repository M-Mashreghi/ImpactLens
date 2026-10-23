"""Load sample news fixtures (``data/samples/news/*.json``) as RawNewsItems."""

from __future__ import annotations

import json
from pathlib import Path

from impactlens.ingestion.contracts import RawNewsItem


def load_sample_news(folder: str | Path, source_key: str = "demo-fixture") -> list[RawNewsItem]:
    items = []
    for path in sorted(Path(folder).glob("*.json")):
        data = json.loads(path.read_text("utf-8"))
        items.append(
            RawNewsItem(
                source_key=source_key,
                source_name=data.get("source_name", "Demo Fixture Wire"),
                source_kind="fixture",
                source_item_id=data["id"],
                url=data.get("url"),
                title=data["title"],
                body=data["body"],
                published_raw=data.get("published_at"),
                retrieved_at=data.get("retrieved_at", data.get("published_at") or "2025-01-01T00:00:00Z"),
            )
        )
    return items
