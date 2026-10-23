"""Evidence grounding: every material claim must quote the article it came from.

Matching tolerance (documented contract):

* Unicode NFKC, typographic quotes/dashes folded to ASCII, whitespace collapsed, casefolded.
* A leading/trailing ellipsis ("..." or "…") and surrounding quote marks are stripped.
* After normalization the quote must be an exact substring of the normalized article.
* Quotes shorter than ``MIN_QUOTE_CHARS`` normalized characters are rejected (too weak).

No fuzzy/semantic matching: paraphrases are treated as unsupported.

Policy:

* Any fabricated (non-matching) evidence span → analysis is routed to ``Uncertain``.
* ``event_type``, ``direction`` and ``severity`` each need ≥1 grounded span, else ``Uncertain``.
* Impact-role entities (primary_subject/affected/counterparty) need ≥1 grounded span; an
  entity without one is excluded from impact (``unsupported_entities``). If no grounded
  impact entity remains, the analysis is ``Uncertain``.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict

from impactlens.intelligence.schema import CLAIM_FIELDS, AnalysisOutput
from impactlens.intelligence.taxonomy import IMPACT_ROLES

MIN_QUOTE_CHARS = 12
_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalize_for_evidence(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_FOLD)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _clean_quote(quote: str) -> str:
    q = normalize_for_evidence(quote)
    q = q.strip("\"' ")
    for marker in ("...", "…"):
        q = q.removeprefix(marker).removesuffix(marker)
    return q.strip("\"' ").strip()


class SpanCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int
    grounded: bool
    reason: str | None = None


class EvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    spans: tuple[SpanCheck, ...]
    fabricated_ids: tuple[int, ...]
    unsupported_claims: tuple[str, ...]
    unsupported_entities: tuple[str, ...]
    supported_entities: tuple[str, ...]
    passed: bool
    reasons: tuple[str, ...]


def validate_evidence(analysis: AnalysisOutput, article_text: str) -> EvidenceReport:
    haystack = normalize_for_evidence(article_text)
    checks: list[SpanCheck] = []
    grounded: set[int] = set()
    for span in analysis.evidence:
        quote = _clean_quote(span.quote)
        if len(quote) < MIN_QUOTE_CHARS:
            checks.append(SpanCheck(id=span.id, grounded=False, reason="quote too short"))
        elif quote in haystack:
            checks.append(SpanCheck(id=span.id, grounded=True))
            grounded.add(span.id)
        else:
            checks.append(SpanCheck(id=span.id, grounded=False, reason="quote not found in article"))
    fabricated = tuple(c.id for c in checks if not c.grounded)

    support = analysis.claims_supported()
    unsupported_claims = tuple(c for c in CLAIM_FIELDS if not (support[c] & grounded))

    supported_entities, unsupported_entities = [], []
    for entity in analysis.entities:
        if entity.role not in IMPACT_ROLES:
            continue
        if set(entity.evidence_ids) & grounded:
            supported_entities.append(entity.name)
        else:
            unsupported_entities.append(entity.name)

    reasons: list[str] = []
    if fabricated:
        reasons.append(f"evidence spans not grounded in article: {list(fabricated)}")
    if unsupported_claims:
        reasons.append(f"claims without grounded evidence: {list(unsupported_claims)}")
    if not supported_entities:
        reasons.append("no impact-relevant entity has grounded evidence")
    return EvidenceReport(
        spans=tuple(checks),
        fabricated_ids=fabricated,
        unsupported_claims=unsupported_claims,
        unsupported_entities=tuple(unsupported_entities),
        supported_entities=tuple(supported_entities),
        passed=not reasons,
        reasons=tuple(reasons),
    )
