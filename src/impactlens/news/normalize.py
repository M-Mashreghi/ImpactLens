"""Deterministic normalization, URL canonicalization, hashing and timestamp parsing."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from impactlens.ingestion.contracts import RawNewsItem
from impactlens.news.models import NormalizedNews, TimestampQuality
from impactlens.timeutil import parse_iso, to_iso

HASH_VERSION = "content-hash-v1"
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "cmpid", "ref", "ref_src", "spm", "igshid"}
_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n\s*\n+")
FUTURE_TOLERANCE = timedelta(minutes=10)


def normalize_text(text: str) -> str:
    """NFKC, typographic quote/dash folding, whitespace collapse. Case is preserved."""
    text = unicodedata.normalize("NFKC", text or "").translate(_TRANSLATE)
    text = "".join(ch for ch in text if ch == "\n" or unicodedata.category(ch)[0] != "C")
    lines = [_WS.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def normalize_title(title: str) -> str:
    return " ".join(normalize_text(title).split())


def canonicalize_url(url: str | None) -> str | None:
    """Lowercase scheme/host, drop fragment/default port/tracking params, sort query."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if parts.port and not (
        (scheme == "http" and parts.port == 80) or (scheme == "https" and parts.port == 443)
    ):
        host = f"{host}:{parts.port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    )
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def content_hash(normalized_title: str, normalized_body: str) -> str:
    """Stable hash over casefolded, whitespace-collapsed title + body."""
    basis = (
        " ".join(normalized_title.casefold().split()) + "\n" + " ".join(normalized_body.casefold().split())
    )
    return "sha256:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()


def parse_published(raw: str | None, retrieved_at: str) -> tuple[str | None, TimestampQuality]:
    """Parse a provider publication timestamp and grade its quality.

    Missing/invalid values return ``None`` (the record keeps ``retrieved_at``) — we never
    pretend to know a publication time we do not have.
    """
    if raw is None or not raw.strip():
        return None, TimestampQuality.MISSING
    raw = raw.strip()
    parsed: datetime | None = None
    quality = TimestampQuality.EXACT
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            parsed = datetime.fromisoformat(raw).replace(tzinfo=UTC)
            quality = TimestampQuality.DATE_ONLY
        except ValueError:
            return None, TimestampQuality.INVALID
    else:
        try:
            iso = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            parsed = iso
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError, IndexError):
                return None, TimestampQuality.INVALID
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
            quality = TimestampQuality.ASSUMED_UTC
        elif "-0000" in raw and not raw.endswith("Z"):
            # RFC 2822 "-0000" explicitly means "offset unknown".
            quality = TimestampQuality.ASSUMED_UTC
    retrieved = parse_iso(retrieved_at)
    if parsed.astimezone(UTC) > retrieved + FUTURE_TOLERANCE and quality is not TimestampQuality.DATE_ONLY:
        return to_iso(parsed), TimestampQuality.SUSPECT_FUTURE
    return to_iso(parsed), quality


def normalize_item(item: RawNewsItem) -> NormalizedNews:
    title = normalize_title(item.title)
    if not title:
        raise ValueError("news item has an empty title after normalization")
    body = normalize_text(item.body)
    published_at, quality = parse_published(item.published_raw, item.retrieved_at)
    provenance = {"source_key": item.source_key, "hash_version": HASH_VERSION, **item.extra}
    if item.published_raw:
        provenance["published_raw"] = item.published_raw[:100]
    return NormalizedNews(
        source_key=item.source_key,
        source_name=item.source_name,
        source_kind=item.source_kind,
        source_item_id=item.source_item_id,
        source_url=item.url,
        canonical_url=canonicalize_url(item.url),
        title=item.title.strip(),
        normalized_title=title,
        body_text=item.body,
        normalized_text=body or title,
        published_at=published_at,
        published_at_quality=quality,
        retrieved_at=item.retrieved_at,
        content_hash=content_hash(title, body or title),
        provenance=provenance,
    )
