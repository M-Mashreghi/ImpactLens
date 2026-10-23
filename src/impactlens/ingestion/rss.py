"""RSS 2.0 / Atom feed adapter.

* Conditional GET (ETag / Last-Modified) for polite polling.
* Bounded response size, timeout and retry via :func:`bounded_get`.
* Feeds containing a DOCTYPE are rejected (entity-expansion defence).
* A malformed item is reported in ``FetchResult.errors``; other items still flow.
* Items already in the cursor's ``seen_item_ids`` are skipped (idempotent re-poll).
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Callable

import httpx

from impactlens.ingestion.contracts import (
    FetchResult,
    ItemError,
    RawNewsItem,
    SourceCursor,
    SourceFetchError,
)
from impactlens.ingestion.html_text import strip_tags
from impactlens.ingestion.http import HttpFetchError, bounded_get
from impactlens.timeutil import utc_now_iso

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
DC = "{http://purl.org/dc/elements/1.1/}"
MAX_ITEMS_PER_POLL = 200


def _text(element: ET.Element | None) -> str:
    return "".join(element.itertext()).strip() if element is not None else ""


def parse_feed(
    xml_text: str, source_key: str, source_name: str, retrieved_at: str
) -> tuple[list[RawNewsItem], list[ItemError]]:
    if "<!DOCTYPE" in xml_text[:2000].upper() or "<!ENTITY" in xml_text.upper():
        raise SourceFetchError(
            source_key, "UnsafeFeed", "feeds with DOCTYPE/ENTITY declarations are rejected"
        )
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceFetchError(source_key, "MalformedFeed", str(exc)) from exc

    if root.tag == f"{ATOM}feed":
        entries = root.findall(f"{ATOM}entry")
        parser: Callable[[ET.Element, str, str, str], RawNewsItem] = _parse_atom_entry
    else:
        channel = root.find("channel")
        if root.tag != "rss" or channel is None:
            raise SourceFetchError(source_key, "UnsupportedFeed", f"unrecognised root element {root.tag!r}")
        entries = channel.findall("item")
        parser = _parse_rss_item

    items, errors = [], []
    for index, entry in enumerate(entries[:MAX_ITEMS_PER_POLL]):
        try:
            items.append(parser(entry, source_key, source_name, retrieved_at))
        except Exception as exc:  # isolate one bad item from the rest of the poll
            errors.append(
                ItemError(item_ref=f"index:{index}", error_type=type(exc).__name__, message=str(exc)[:300])
            )
    return items, errors


def _item_id(explicit: str, link: str, title: str) -> str:
    if explicit:
        return explicit
    if link:
        return link
    return "sha256:" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:32]


def _parse_rss_item(item: ET.Element, source_key: str, source_name: str, retrieved_at: str) -> RawNewsItem:
    title = strip_tags(_text(item.find("title")))
    link = _text(item.find("link"))
    if not title:
        raise ValueError("item has no title")
    body = strip_tags(_text(item.find(f"{CONTENT}encoded")) or _text(item.find("description")))
    published = _text(item.find("pubDate")) or _text(item.find(f"{DC}date")) or None
    return RawNewsItem(
        source_key=source_key,
        source_name=source_name,
        source_kind="feed",
        source_item_id=_item_id(_text(item.find("guid")), link, title),
        url=link or None,
        title=title,
        body=body,
        published_raw=published,
        retrieved_at=retrieved_at,
    )


def _parse_atom_entry(entry: ET.Element, source_key: str, source_name: str, retrieved_at: str) -> RawNewsItem:
    title = strip_tags(_text(entry.find(f"{ATOM}title")))
    if not title:
        raise ValueError("entry has no title")
    link = ""
    for link_el in entry.findall(f"{ATOM}link"):
        if link_el.get("rel", "alternate") == "alternate" and link_el.get("href"):
            link = link_el.get("href", "")
            break
    body = strip_tags(_text(entry.find(f"{ATOM}content")) or _text(entry.find(f"{ATOM}summary")))
    published = _text(entry.find(f"{ATOM}published")) or _text(entry.find(f"{ATOM}updated")) or None
    return RawNewsItem(
        source_key=source_key,
        source_name=source_name,
        source_kind="feed",
        source_item_id=_item_id(_text(entry.find(f"{ATOM}id")), link, title),
        url=link or None,
        title=title,
        body=body,
        published_raw=published,
        retrieved_at=retrieved_at,
    )


class RssFeedAdapter:
    def __init__(
        self,
        key: str,
        url: str,
        *,
        name: str | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 15.0,
        user_agent: str = "ImpactLens/1.0 (+research)",
        retries: int = 2,
    ) -> None:
        self.key = key
        self.name = name or key
        self.url = url
        self.user_agent = user_agent
        self.retries = retries
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def fetch(self, cursor: SourceCursor | None) -> FetchResult:
        cursor = cursor or SourceCursor(source_key=self.key)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml",
        }
        if cursor.etag:
            headers["If-None-Match"] = cursor.etag
        if cursor.last_modified:
            headers["If-Modified-Since"] = cursor.last_modified
        try:
            response = bounded_get(self._client, self.url, headers=headers, retries=self.retries)
        except HttpFetchError as exc:
            raise SourceFetchError(self.key, exc.error_type, str(exc)) from exc
        if response.status_code == 304:
            return FetchResult(cursor=cursor, not_modified=True)
        items, errors = parse_feed(response.text, self.key, self.name, utc_now_iso())
        seen = set(cursor.seen_item_ids)
        fresh = [i for i in items if i.source_item_id not in seen]
        lower = {k.lower(): v for k, v in response.headers.items()}
        next_cursor = cursor.with_seen(
            (i.source_item_id for i in fresh if i.source_item_id),
            etag=lower.get("etag"),
            last_modified=lower.get("last-modified"),
        )
        return FetchResult(items=tuple(fresh), errors=tuple(errors), cursor=next_cursor)
