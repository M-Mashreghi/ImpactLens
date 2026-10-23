"""Deterministic name normalization for entity matching."""

from __future__ import annotations

import re
import unicodedata

_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "plc",
    "llc",
    "holdings",
    "holding",
    "group",
    "sa",
    "ag",
    "nv",
    "se",
    "the",
}
_NON_ALNUM = re.compile(r"[^a-z0-9& ]+")
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Casefold, strip accents/punctuation/corporate suffixes: 'NVIDIA Corp.' -> 'nvidia'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = text.casefold().replace("’", "'").replace("'s ", " ")
    text = _NON_ALNUM.sub(" ", text)
    tokens = [t for t in _SPACES.split(text) if t]
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    while tokens and tokens[0] == "the":
        tokens.pop(0)
    return " ".join(tokens)


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper().lstrip("$")
