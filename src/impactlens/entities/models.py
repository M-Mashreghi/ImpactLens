"""Security master and relationship/factor-exposure models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Security(BaseModel):
    model_config = ConfigDict(frozen=True)

    security_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    mic: str | None = None
    country: str | None = None
    currency: str | None = None
    sector: str | None = None
    industry: str | None = None
    share_class: str | None = None
    aliases: tuple[str, ...] = ()
    active: bool = True

    @field_validator("ticker", "exchange")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()


class RelationshipType(StrEnum):
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    COMPETITOR = "competitor"


# Provenance sources that can never justify a persisted relationship/exposure.
FORBIDDEN_PROVENANCE = {"llm", "model", "llm_memory", "model_memory", "gpt", "ai"}


class _Provenanced(BaseModel):
    model_config = ConfigDict(frozen=True)

    provenance_source: str = Field(min_length=1, description="e.g. 'public_filing', 'synthetic_demo'")
    provenance_ref: str = Field(min_length=3, description="Citation/reference for the relationship")
    as_of: str = Field(min_length=10, description="ISO date the relationship was known to hold")

    @field_validator("provenance_source")
    @classmethod
    def _not_llm(cls, value: str) -> str:
        if value.strip().lower() in FORBIDDEN_PROVENANCE:
            raise ValueError("LLM/model memory is not acceptable provenance for a stored relationship")
        return value.strip()


class SecurityRelationship(_Provenanced):
    """Directed link: ``source`` relates to ``target`` as ``relationship_type``.

    Example: source=TSM, target=NVDA, type=supplier means TSM is a supplier to NVDA.
    """

    source_security_id: str
    target_security_id: str
    relationship_type: RelationshipType
    strength: float = Field(gt=0, le=1)


class FactorFamily(StrEnum):
    COUNTRY = "country"
    COMMODITY = "commodity"
    MACRO = "macro"


class FactorExposure(_Provenanced):
    """Stored sensitivity of a security to a country/commodity/macro factor in [-1, 1]."""

    security_id: str
    factor_key: str
    family: FactorFamily
    sensitivity: float = Field(ge=-1, le=1)

    @field_validator("sensitivity")
    @classmethod
    def _nonzero(cls, value: float) -> float:
        if value == 0:
            raise ValueError("sensitivity must be non-zero; omit the row instead")
        return value
