"""Controlled vocabulary for non-security entities (countries, commodities, macro factors).

Factor keys look like ``country:CN``, ``commodity:crude_oil``, ``macro:interest_rates``.
This vocabulary is deliberately small and explicit; unknown factors stay unresolved.
"""

from __future__ import annotations

from impactlens.entities.normalize import normalize_name

COUNTRIES: dict[str, tuple[str, ...]] = {
    "country:US": ("united states", "usa", "us", "u s", "america"),
    "country:CN": ("china", "prc", "people's republic of china", "mainland china"),
    "country:TW": ("taiwan",),
    "country:NL": ("netherlands", "the netherlands", "holland"),
    "country:JP": ("japan",),
    "country:KR": ("south korea", "korea"),
    "country:DE": ("germany",),
    "country:GB": ("united kingdom", "uk", "britain", "great britain"),
    "country:RU": ("russia", "russian federation"),
    "country:SA": ("saudi arabia",),
    "country:IN": ("india",),
    "country:CH": ("switzerland",),
}

COMMODITIES: dict[str, tuple[str, ...]] = {
    "commodity:crude_oil": ("crude oil", "oil", "brent", "wti", "brent crude", "oil prices"),
    "commodity:natural_gas": ("natural gas", "lng", "gas prices"),
    "commodity:gold": ("gold",),
    "commodity:copper": ("copper",),
    "commodity:jet_fuel": ("jet fuel",),
}

MACRO: dict[str, tuple[str, ...]] = {
    "macro:interest_rates": (
        "interest rates",
        "rates",
        "policy rate",
        "federal funds rate",
        "fed funds rate",
    ),
    "macro:inflation": ("inflation", "cpi", "consumer prices"),
    "macro:usd": ("us dollar", "dollar", "usd"),
    "macro:economic_growth": ("gdp", "economic growth", "recession"),
}

FAMILY_BY_PREFIX = {"country": "country", "commodity": "commodity", "macro": "macro"}


def _index(*tables: dict[str, tuple[str, ...]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for table in tables:
        for key, aliases in table.items():
            for alias in aliases:
                index[normalize_name(alias)] = key
    return index


_COUNTRY_INDEX = _index(COUNTRIES)
_COMMODITY_INDEX = _index(COMMODITIES)
_MACRO_INDEX = _index(MACRO)


def resolve_factor(name: str, entity_type: str) -> str | None:
    """Map a named factor entity of a given type to its canonical key, or None."""
    key = normalize_name(name)
    if entity_type == "country":
        return _COUNTRY_INDEX.get(key)
    if entity_type == "commodity":
        return _COMMODITY_INDEX.get(key)
    if entity_type == "macro_factor":
        return _MACRO_INDEX.get(key)
    return None
