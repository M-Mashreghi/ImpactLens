# ImpactLens Architecture

**ImpactLens** is a financial-news intelligence and portfolio-impact platform. It ingests news, extracts structured events with an LLM, resolves mentioned entities to securities, maps those events to a portfolio's direct and supported indirect exposures, computes deterministic impact-priority scores, and optionally validates the signal with historical event studies.

This document defines the end-to-end architecture and non-negotiable system boundaries.

---

## 1. High-Level Overview

```text
┌─────────────────────┐          ┌────────────────────┐
│ News Sources        │          │ Portfolio Inputs   │
│ RSS / HTTP / Manual │          │ CSV / API later    │
└─────────┬───────────┘          └──────────┬─────────┘
          │                                 │
          ▼                                 ▼
┌─────────────────────┐          ┌────────────────────┐
│ News Ingestion      │          │ Portfolio Service  │
│ normalize/dedup     │          │ snapshots/weights  │
└─────────┬───────────┘          └──────────┬─────────┘
          │                                 │
          ▼                                 ▼
┌─────────────────────┐          ┌────────────────────┐
│ LLM Event Analyzer  │───────┐  │ Entity/Security    │
│ event/entities/etc. │       └─▶│ Resolver           │
└─────────┬───────────┘          └──────────┬─────────┘
          │                                 │
          └──────────────┬──────────────────┘
                         ▼
                ┌────────────────────┐
                │ Exposure Engine    │
                │ direct + justified │
                │ indirect links     │
                └──────────┬─────────┘
                           ▼
                ┌────────────────────┐
                │ Impact Scorer      │
                │ deterministic      │
                └──────────┬─────────┘
                           ▼
                ┌────────────────────┐
                │ Explanation / API  │
                │ Dashboard / Alerts │
                └──────────┬─────────┘
                           ▼
                ┌────────────────────┐
                │ Historical Research│
                │ market/event study │
                └────────────────────┘
```

---

## 2. Architectural Style

ImpactLens v1 is a **modular monolith**.

Rationale:

- the domain is still evolving;
- deterministic finance logic benefits from in-process traceability;
- a small research/product project does not need distributed-systems overhead;
- adapters preserve future replaceability without premature microservices.

Recommended runtime split:

- one Python application package containing domain/application modules;
- FastAPI process for API;
- Streamlit process for UI;
- optional lightweight scheduler/worker process using the same application package;
- SQLite durable state for MVP;
- filesystem only for bounded cache/artifacts explicitly documented in deployment.

---

## 3. Core Domains and Modules

### 3.1 Ingestion

Responsibilities:

- discover/fetch news from configured providers;
- accept manual URL/text input for testing and analyst workflows;
- capture provider metadata;
- respect rate limits and timeouts;
- emit a normalized ingestion DTO.

Conceptual contracts:

```python
class NewsSourceAdapter(Protocol):
    async def fetch(self, cursor: SourceCursor | None) -> list[RawNewsItem]: ...

class NewsContentFetcher(Protocol):
    async def fetch_article(self, url: str) -> FetchedArticle: ...
```

Adapters must not perform portfolio scoring.

### 3.2 News Normalization & Deduplication

Responsibilities:

- canonicalize URL when possible;
- normalize title/body whitespace and obvious boilerplate;
- preserve original text separately or as provenance metadata;
- compute stable content hash;
- detect exact duplicates;
- optionally detect near-duplicate syndicated items using a deterministic similarity layer approved by task scope;
- store publication/retrieval timestamps and timestamp-quality flags.

A duplicate should reference the canonical news record rather than trigger full LLM analysis again.

### 3.3 Event Intelligence

Responsibilities:

- call the configured LLM provider through an adapter;
- return structured, schema-validated financial event analysis;
- extract entities and roles;
- classify event type;
- assign qualitative direction, severity, confidence, and horizon;
- attach evidence spans to material claims;
- emit `uncertain` instead of hallucinating.

LLM output is **not** the portfolio impact score.

### 3.4 Entity & Security Resolution

Responsibilities:

- map company/entity mentions to canonical entities;
- map canonical public companies to security identifiers/tickers;
- handle exchange/ticker ambiguity;
- distinguish company, index, country, commodity, regulator, product, and person entities;
- record unresolved/ambiguous outcomes.

The resolver, not the LLM, is authoritative for ticker mapping.

MVP security master fields may include:

- `security_id`
- canonical company name
- ticker
- exchange
- MIC/country where available
- sector/industry
- aliases
- active flag

### 3.5 Portfolio Domain

A portfolio is represented by immutable **snapshots**.

Core entities:

- `Portfolio`
- `PortfolioSnapshot`
- `Position`
- optional `CashPosition`

Each position should support:

- canonical security id
- ticker/display name
- quantity (optional)
- market value or notional
- portfolio weight
- currency
- snapshot timestamp

If both market value and weight are supplied, validation must detect inconsistent inputs according to configured tolerance.

Historical analyses reference a specific snapshot id.

### 3.6 Exposure Engine

The exposure engine turns an analyzed event into one or more `ExposureMatch` objects.

Supported relationship categories in v1:

1. **Direct** — the canonical security is held.
2. **Sector/industry** — the event has a justified sector-wide effect and the held security shares that classification.
3. **Country/geographic** — event is explicitly country/regulatory/geopolitical and portfolio security has stored geographic exposure metadata or approved coarse country mapping.
4. **Commodity/macro factor** — only when a stored mapping defines the security's exposure.
5. **Relationship graph** — supplier/customer/competitor relationships only when the relationship exists in a stored, provenance-backed relationship table.

The engine must never infer persistent indirect relationships from model memory alone.

### 3.7 Deterministic Impact Scoring

The scoring engine consumes validated event and exposure components.

A conceptual baseline:

```text
signed_component =
    exposure_magnitude
  × relationship_weight
  × event_severity
  × model_confidence
  × relevance_weight
  × direction_sign
```

Then portfolio/event scores aggregate components using a documented deterministic equation.

The exact equation, normalization range, and caps are versioned in configuration/code and covered by numerical tests.

Output semantics:

- `signed_score` — optional signed qualitative impact-priority score;
- `absolute_priority` — urgency/relevance regardless of direction;
- `impact_level` — Low / Medium / High / Critical based on documented thresholds;
- decomposed component list.

This is not an expected-return forecast.

### 3.8 Explanation Layer

The explanation composer may use templates or an LLM **after** deterministic impact computation.

It must receive the already validated:

- event fields;
- evidence;
- resolved entities;
- portfolio positions;
- exposure paths;
- score components;
- historical analytics if available.

It must not modify numerical results.

### 3.9 Market Data & Research

Market-data adapters provide timestamped price/yield series.

Responsibilities:

- market data retrieval/caching;
- exchange calendar/session alignment;
- after-close/pre-open event handling;
- benchmark selection;
- return calculations;
- benchmark-adjusted event windows;
- historical analog retrieval;
- score-bucket calibration/evaluation.

All numerical research lives here, not in prompts.

---

## 4. Core Data Model

### NewsRecord

Conceptual fields:

- `id`
- `source_name`
- `source_item_id`
- `source_url`
- `canonical_url`
- `title`
- `normalized_title`
- `body_text`
- `normalized_text`
- `published_at`
- `published_at_quality`
- `retrieved_at`
- `content_hash`
- `canonical_news_id` for duplicate linkage
- `ingestion_status`

### NewsAnalysis

- `id`
- `news_id`
- `schema_version`
- `prompt_version`
- `model_provider`
- `model_name`
- `event_type`
- `event_summary`
- `direction`
- `severity`
- `confidence`
- `time_horizon`
- `status` (`Valid`, `Uncertain`, `Failed`)
- structured entities
- evidence spans
- uncertainties
- raw structured response retained according to policy

### PortfolioImpact

- `id`
- `news_analysis_id`
- `portfolio_snapshot_id`
- `scoring_version`
- `signed_score`
- `absolute_priority`
- `impact_level`
- component/exposure rows
- calculation timestamp

### ExposureMatch

- affected position/security
- source entity/event
- relationship type
- relationship provenance id where indirect
- exposure magnitude
- relationship weight
- direction
- severity
- confidence
- relevance weight
- component score
- explanation metadata

### MarketReaction

- event timestamp
- aligned session/event anchor
- security/benchmark ids
- window definition
- raw return
- benchmark return
- abnormal return
- optional volume/volatility fields
- market-data source/version metadata

---

## 5. News Lifecycle

Recommended operational states:

| State | Meaning |
|---|---|
| `Discovered` | Provider item identified. |
| `Fetched` | Required text/metadata retrieved. |
| `Normalized` | Canonical text/hash prepared. |
| `Duplicate` | Linked to an existing canonical item; no reanalysis needed by default. |
| `PendingAnalysis` | Ready for LLM event extraction. |
| `Analyzed` | Structured analysis valid. |
| `Uncertain` | Analysis intentionally withheld/ambiguous. |
| `Resolved` | Entities/security mappings processed. |
| `Scored` | Portfolio impact computed for target snapshot(s). |
| `Alerted` | Optional high-impact alert emitted. |
| `Failed` | Terminal/repairable failure with structured error metadata. |

Persist state transitions or sufficient timestamps for auditability.

---

## 6. Provider Abstractions

### News Providers

v1 may support:

- RSS/Atom feeds;
- public company/agency press-release feeds where practical;
- generic HTTP article fetch for explicitly supplied URLs;
- manual text ingestion for fixtures/research.

Paid newswire licensing is outside the baseline and must respect provider terms.

### LLM Providers

Use an `LLMClient`/`StructuredAnalysisProvider` abstraction.

Provider-specific request/response details stay in infrastructure/adapters.

### Market Data Providers

Use `MarketDataProvider` abstraction with normalized OHLC/close/timezone contract.

Do not make research logic depend on one vendor's dataframe shape.

---

## 7. Point-in-Time Rules

For historical research, the system must be able to answer:

> What information was available at the event decision timestamp?

Mandatory controls:

- use original `published_at`, not retrieval time, when quality is reliable;
- retain timestamp-quality flag;
- map events to exchange calendar and timezone;
- define after-close policy;
- use the portfolio snapshot valid at/reconstructed for the intended timestamp;
- exclude post-event articles/features from pre-event inputs;
- do not tune thresholds on a test period without documenting leakage risk.

---

## 8. API Layer

FastAPI endpoints should remain thin.

Representative v1 resource groups:

- `/health`
- `/portfolios`
- `/portfolio-snapshots`
- `/news`
- `/analyses`
- `/impacts`
- `/alerts`
- `/research/event-studies`
- `/system/config` (read-only safe config if exposed)

Routes call application services and return DTOs/Pydantic response models.

---

## 9. Dashboard

Streamlit is a presentation client.

Core screens:

1. **Portfolio** — import/view current snapshot and exposure summary.
2. **Impact Feed** — ranked news by portfolio impact priority.
3. **News Detail** — source, evidence, event structure, entity resolution.
4. **Portfolio Impact Detail** — affected positions and score decomposition.
5. **Historical Context** — event windows and analogs.
6. **Alerts / System** — alert history, provider/system status.

Never calculate final scores only in Streamlit code.

---

## 10. Persistence & Caching

SQLite is the v1 system of record.

Recommended durable categories:

- portfolios/snapshots/positions;
- security master and relationship metadata;
- news/provenance/dedup links;
- LLM analysis/version metadata;
- impact scores/components;
- alerts;
- research result metadata/config.

Market data may use a bounded local cache with provenance. Cache files are not authoritative portfolio/news records.

Database schema changes require migrations.

---

## 11. Security & Privacy

- Secrets only via environment/config secret injection.
- Never commit `.env`.
- Avoid logging complete private portfolios at INFO level.
- Validate uploaded CSV size/type and parse as data, never executable content.
- Treat news/article text as prompt-injection-capable untrusted input.
- Restrict dashboard/API exposure appropriately before hosting beyond localhost/private network.

---

## 12. Observability

Structured logs should include where relevant:

- correlation id
- news id
- portfolio snapshot id
- provider
- pipeline stage
- analysis id
- impact id
- retry/error type
- duration

Never log API keys or authorization headers.

Health/readiness should distinguish process liveness from dependencies such as DB and provider configuration.

---

## 13. Deployment Baseline

Production-shaped v1 deployment:

- Docker image for application package/API;
- Streamlit service may share the same image with a different command;
- scheduler/worker may share image if separated;
- SQLite durable volume;
- optional bounded cache volume;
- environment secrets supplied at runtime;
- health checks;
- backup of database, not ephemeral caches.

See `DEPLOYMENT.md`.

---

## 14. Architectural Invariants

1. **Evidence before narrative** — material LLM claims require source evidence.
2. **Resolver before ticker trust** — model-generated tickers are proposals only.
3. **Deterministic finance math** — portfolio/market calculations live in Python.
4. **No-look-ahead historical analytics** — enforced by code and tests.
5. **Impact score ≠ expected return** — do not conflate prioritization with prediction.
6. **Indirect exposure requires provenance** — never rely solely on LLM memory.
7. **Portfolio snapshots are immutable references** — historical results stay reproducible.
8. **Adapters isolate providers** — news, LLM, and market vendors are replaceable.
9. **Thin UI/API** — business logic remains in application/domain modules.
10. **Task-by-task delivery** — implementation follows `PROJECT_PHASES_AND_TASKS.md`.

---

## 15. Baseline Technology Stack

| Area | Technology |
|---|---|
| Runtime | Python 3.12+ |
| Models/validation | Pydantic |
| API | FastAPI |
| UI | Streamlit |
| Database | SQLite |
| Data analysis | Python standard library (`statistics`); pandas/NumPy deferred until a task needs them |
| HTTP | httpx |
| Testing | pytest |
| Packaging | `pyproject.toml` |
| Deployment | Docker / Docker Compose |

Additional libraries require task-level justification.

---

## 16. Implementation Reference (v1, as built)

This section records the concrete contracts implemented for Tasks 1.1–7.5. Every versioned
identifier below is persisted with the records it produced.

### 16.1 Module map

| Module | Implementation |
|---|---|
| `impactlens.config` / `logging_setup` | Typed env settings (`SecretStr` secrets), JSON logs, correlation context, secret redaction |
| `impactlens.storage` | SQLite connection, forward-only migrations (`storage/migrations/NNNN_*.sql`), repositories, backup/restore |
| `impactlens.portfolio` | `Portfolio`, `PortfolioSnapshot`, `Position`; CSV importer; immutable snapshots (DB triggers) |
| `impactlens.entities` | Security master models, name normalizer, factor vocabulary, `SecurityResolver`, demo seed loader |
| `impactlens.ingestion` | `NewsSourceAdapter` contract + registry, RSS/Atom adapter, manual text/URL ingestion, fake adapter, orchestrator |
| `impactlens.news` | `NewsRecord`, lifecycle states, normalization, URL canonicalization, content hash, timestamp quality |
| `impactlens.intelligence` | Taxonomy, Pydantic schema, prompt, LLM client/providers, evidence validator, entity pipeline, analysis service, offline eval |
| `impactlens.impact` | Exposure engine, scoring engine, explanation composer, impact orchestrator |
| `impactlens.market` | `MarketDataProvider` contract, CSV/fake providers, bounded cache, exchange calendar + session alignment |
| `impactlens.research` | Event study, historical analogs, calibration, point-in-time guard, research service |
| `impactlens.alerts` | Alert policy, idempotency, cooldown, console/webhook channels |
| `impactlens.jobs` | Workflow cycle + interval scheduler (`python -m impactlens.jobs.run`) |
| `impactlens.export` | JSON/CSV/Markdown research brief |
| `impactlens.api` | FastAPI app (`impactlens.api.main:app`) |
| `impactlens.dashboard` | Streamlit client over the API (`streamlit run src/impactlens/dashboard/app.py`) |
| `impactlens.app` | Composition root used by API, dashboard (via API), CLI and worker |

### 16.2 Version identifiers

| Identifier | Meaning |
|---|---|
| schema migration `1` | `0001_initial.sql`; recorded in `schema_migrations` with checksum (edits to applied migrations are rejected) |
| `content-hash-v1` | sha256 over casefolded, whitespace-collapsed normalized title + body |
| `analysis-v1` | LLM output schema and event taxonomy |
| `prompt-v1` | System prompt `intelligence/prompts/system_v1.txt` + delimited user prompt |
| `exposure-rules-v1` | Direct/indirect exposure rules (§16.6) |
| `impact-v1` | Scoring formula/config (§16.7) |
| `anchor-v1` | Event timestamp → session alignment (§16.8) |
| `es-v1` | Event-study config (windows `[0,+1]`, `[0,+5]`, benchmark `SPY`, market-adjusted) |
| `analog-v1` / `calib-v1` | Analog similarity and calibration report |
| `alert-policy-v1` | Alert threshold/idempotency/cooldown policy |
| `export-v1` | Export format |

### 16.3 Event taxonomy (`analysis-v1`)

Event types: `earnings`, `guidance`, `mna_corporate_action`, `regulation_policy`, `litigation_legal`,
`credit_rating`, `management_governance`, `product_technology`, `supply_chain_operations`,
`cybersecurity`, `fraud_accounting`, `capital_return_raise`, `geopolitical`, `macro_rates_inflation`,
`commodity_energy`, `analyst_research`, `other_uncertain`.

Direction: `positive`, `negative`, `mixed`, `neutral`, `uncertain` (relative to the affected entity;
per-entity override allowed). Severity: `low`, `medium`, `high`, `critical`. Confidence: `[0, 1]`.
Time horizon: `intraday`, `short_term`, `medium_term`, `long_term`, `unknown`.
Entity types: `company`, `index`, `country`, `commodity`, `regulator`, `product`, `person`, `sector`,
`industry`, `macro_factor`, `other`. Entity roles: `primary_subject`, `affected`, `counterparty`,
`actor`, `mentioned` (the first three are impact roles).

The schema forbids unknown fields (e.g. a model-invented `expected_return`), requires unique evidence
ids and rejects entity references to unknown evidence ids.

### 16.4 Evidence policy

Normalization: NFKC, typographic quote/dash folding, whitespace collapse, casefold; leading/trailing
ellipses and quote marks stripped; the quote must then be an exact substring of the article text and at
least 12 characters. No fuzzy matching. Any non-matching span, or `event_type`/`direction`/`severity`
lacking a grounded span, routes the analysis to `Uncertain`. Impact-role entities need a grounded span
or they are excluded from impact; if none remain, the analysis is `Uncertain`.

### 16.5 Resolver policy

Names/aliases (normalized: accents, punctuation, corporate suffixes removed) map to an issuer; all active
securities of that issuer are returned (share classes). A name matching several issuers is `Ambiguous`.
A ticker resolves only to exactly one active listing (optionally filtered by exchange). The LLM's
`proposed_ticker` is never used to resolve; a mismatch is recorded as a note. Countries, commodities and
macro factors resolve through a small explicit vocabulary (`entities/factors.py`); sectors/industries
resolve only to classifications present in the security master.

### 16.6 Exposure rules (`exposure-rules-v1`)

| Family | Trigger | Link | Direction |
|---|---|---|---|
| direct | company entity resolved to securities | held `security_id` | entity direction |
| supplier / customer / competitor | company entity | stored `security_relationships` row | same; competitor flips positive↔negative |
| sector / industry | sector/industry entity | security master classification | entity direction |
| country / commodity / macro | factor entity | stored `security_factor_exposures` row (sensitivity ∈ [−1, 1]) | flipped when sensitivity < 0 |

Relationship/factor rows require provenance (`provenance_source`, `provenance_ref`, `as_of`); sources such
as `llm`/`model` are rejected by validation. Families can be disabled with `EXPOSURE_DISABLED_FAMILIES`.
An optional `as_of` excludes links recorded after the event date.

### 16.7 Scoring formula (`impact-v1`)

```text
exposure_magnitude = min(weight, 0.20) / 0.20
relevance_weight   = role_relevance[role] × link_strength
base               = exposure_magnitude × relationship_weight × severity_value × confidence × relevance_weight
signed_component   = base × direction_sign          (positive +1, negative −1, mixed/neutral 0)
absolute_component = base × direction_priority      (positive/negative/mixed 1, neutral 0.5)

relationship_weight: direct 1.0 · supplier 0.6 · customer 0.6 · industry 0.5 · commodity 0.5
                     competitor 0.4 · country 0.4 · macro 0.4 · sector 0.35
severity_value:      low 0.25 · medium 0.5 · high 0.75 · critical 1.0
role_relevance:      primary_subject 1.0 · affected 0.8 · counterparty 0.6

Per position only the strongest match is counted (others are shown with counted = false).
signed_score       = 100 × clamp(Σ counted signed_component, −1, 1)
absolute_priority  = 100 × min(Σ counted absolute_component, 1)
impact_level       = Critical ≥ 50 · High ≥ 25 · Medium ≥ 10 · Low otherwise
```

Uncertain-direction matches are excluded with a reason. The score is an impact **priority**, never an
expected return. Any change to weights/thresholds requires a new scoring version and golden-fixture update
(`tests/fixtures/golden_impacts.json`).

### 16.8 Session alignment (`anchor-v1`) and event studies (`es-v1`)

Exchange-local time (NYSE calendar, `America/New_York`, 09:30–16:00, static 2024–2026 holiday list):
pre-open and in-session events anchor to the same day, after-close (≥ 16:00) and weekend/holiday events
to the next trading day, date-only timestamps to that calendar date (or next trading day). Non-`exact`
timestamp quality is flagged on the result.

Window `[a, b]`: `R = close(day b) / close(day a−1) − 1`, abnormal return = security − benchmark
(market-adjusted). Required closes must exist on the exact dates (no filling) or the window is
`insufficient_data`; bars after `as_of` are discarded and windows ending after `as_of` are
`not_yet_observable`. Results are labelled as association, not causation.

### 16.9 Analogs and calibration

Analog similarity = 0.40·event_type + 0.25·issuer Jaccard + 0.15·sector Jaccard + 0.10·direction +
0.05·severity closeness + 0.05·horizon; only events published strictly before the query event are
eligible. Calibration joins counted impact components with stored event studies, reports per-level and
per-event-type counts, mean/median absolute abnormal return and direction hit rate, accounts for every
excluded observation by reason, and raises `LookAheadViolation` (strict mode) when any feature
(news time, snapshot `as_of`, relationship `as_of`) post-dates the event.

### 16.10 Alerts

Eligible when level ≥ `ALERT_MIN_LEVEL`. Idempotency key = sha256(canonical news id | snapshot id |
scoring version | channel), unique in `alerts`. A `sent` alert starts a per-portfolio/channel cooldown
(`ALERT_COOLDOWN_SECONDS`); eligible alerts inside it are stored as `suppressed_cooldown`, except
`Critical`. Delivery failures are stored as `failed`.

### 16.11 Lifecycle as implemented

`Discovered → Fetched → Normalized → (Duplicate | PendingAnalysis)`; analysis moves news to
`Analyzed → Resolved`, or `Uncertain` / `Failed`; scoring moves `Resolved → Scored`; a sent alert moves
`Scored → Alerted`. Every transition is appended to `news_status_history`.
