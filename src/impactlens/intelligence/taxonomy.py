"""Financial event taxonomy (schema ``analysis-v1``).

The vocabulary below is the contract between the LLM prompt, validation, scoring and
evaluation. Changing a member requires a new ``SCHEMA_VERSION``.
"""

from __future__ import annotations

from enum import StrEnum

SCHEMA_VERSION = "analysis-v1"


class EventType(StrEnum):
    EARNINGS = "earnings"  # earnings/results
    GUIDANCE = "guidance"  # guidance/outlook
    MNA_CORPORATE_ACTION = "mna_corporate_action"
    REGULATION_POLICY = "regulation_policy"
    LITIGATION_LEGAL = "litigation_legal"
    CREDIT_RATING = "credit_rating"
    MANAGEMENT_GOVERNANCE = "management_governance"
    PRODUCT_TECHNOLOGY = "product_technology"
    SUPPLY_CHAIN_OPERATIONS = "supply_chain_operations"
    CYBERSECURITY = "cybersecurity"
    FRAUD_ACCOUNTING = "fraud_accounting"
    CAPITAL_RETURN_RAISE = "capital_return_raise"  # capital raise/buyback/dividend
    GEOPOLITICAL = "geopolitical"
    MACRO_RATES_INFLATION = "macro_rates_inflation"
    COMMODITY_ENERGY = "commodity_energy"
    ANALYST_RESEARCH = "analyst_research"
    OTHER_UNCERTAIN = "other_uncertain"


EVENT_TYPE_LABELS: dict[EventType, str] = {
    EventType.EARNINGS: "Earnings / results",
    EventType.GUIDANCE: "Guidance / outlook",
    EventType.MNA_CORPORATE_ACTION: "M&A / corporate action",
    EventType.REGULATION_POLICY: "Regulation / policy",
    EventType.LITIGATION_LEGAL: "Litigation / legal",
    EventType.CREDIT_RATING: "Credit / rating",
    EventType.MANAGEMENT_GOVERNANCE: "Management / governance",
    EventType.PRODUCT_TECHNOLOGY: "Product / technology",
    EventType.SUPPLY_CHAIN_OPERATIONS: "Supply chain / operations",
    EventType.CYBERSECURITY: "Cybersecurity",
    EventType.FRAUD_ACCOUNTING: "Fraud / accounting",
    EventType.CAPITAL_RETURN_RAISE: "Capital raise / buyback / dividend",
    EventType.GEOPOLITICAL: "Geopolitical",
    EventType.MACRO_RATES_INFLATION: "Macro / rates / inflation",
    EventType.COMMODITY_ENERGY: "Commodity / energy",
    EventType.ANALYST_RESEARCH: "Analyst / research update",
    EventType.OTHER_UNCERTAIN: "Other / uncertain",
}


class Direction(StrEnum):
    """Direction relative to the affected entity (for a factor: the factor's own move)."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"
    UNCERTAIN = "uncertain"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_ORDINAL = {Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}


class TimeHorizon(StrEnum):
    INTRADAY = "intraday"
    SHORT_TERM = "short_term"  # days to weeks
    MEDIUM_TERM = "medium_term"  # weeks to quarters
    LONG_TERM = "long_term"  # quarters to years
    UNKNOWN = "unknown"


class EntityType(StrEnum):
    COMPANY = "company"
    INDEX = "index"
    COUNTRY = "country"
    COMMODITY = "commodity"
    REGULATOR = "regulator"
    PRODUCT = "product"
    PERSON = "person"
    SECTOR = "sector"
    INDUSTRY = "industry"
    MACRO_FACTOR = "macro_factor"
    OTHER = "other"


class EntityRole(StrEnum):
    PRIMARY_SUBJECT = "primary_subject"  # the entity the event is about
    AFFECTED = "affected"  # explicitly described as affected
    COUNTERPARTY = "counterparty"  # acquirer/target/customer named in the event
    ACTOR = "actor"  # regulator/government taking the action
    MENTIONED = "mentioned"  # mentioned without a described effect


# Roles whose entities can drive portfolio impact (and therefore need evidence).
IMPACT_ROLES = {EntityRole.PRIMARY_SUBJECT, EntityRole.AFFECTED, EntityRole.COUNTERPARTY}
