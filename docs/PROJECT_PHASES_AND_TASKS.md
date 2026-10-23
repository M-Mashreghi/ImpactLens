# ImpactLens — Project Phases & Atomic Tasks

**Single source of truth** for the complete ImpactLens delivery lifecycle.

This document decomposes the product into granular, testable tasks. No task may be marked complete merely because code was written; its tests and Definition of Done must also pass.

| Meta | Value |
|---|---|
| Project | ImpactLens — Financial News → Portfolio Impact Engine |
| Current status | `[x]` v1 implemented — all 35 tasks completed and verified (192 tests, ruff, mypy, Docker smoke) |
| Status legend | `[ ]` Not Started · `[-]` In Progress · `[x]` Completed |
| Governing rules | `CLAUDE.md` + `.claude/rules/*` |
| Related docs | [ARCHITECTURE](./ARCHITECTURE.md) · [ROADMAP](./ROADMAP.md) · [PHASES](./PHASES.md) · [DIAGRAMS](./DIAGRAMS.md) · [TASKS](./TASKS.md) |

## Global Definition of Done

Before any task may be marked `[x]`:

1. Implementation satisfies the task scope without unrelated refactors.
2. Required unit/integration/E2E tests for the task are green.
3. Finance-integrity rules remain satisfied: deterministic arithmetic in Python; no unsupported expected-return claims.
4. LLM-derived material claims are schema-validated and evidence-grounded where the task touches LLM analysis.
5. Historical tasks preserve point-in-time/no-look-ahead constraints.
6. No secrets or private real portfolio data are committed.
7. Relevant docs and task ledgers are synchronized.
8. New dependencies are justified by the current task.

---

## Phase 1: Foundation, Portfolio Model & Security Master

**Status:** `[x]` Completed

**Goal:** Build the Python/SQLite foundation, immutable portfolio snapshots, and canonical security resolver.

**Roadmap:** M1 Alpha

### Task 1.1: Python Project Scaffolding & Quality Baseline

**Status:** `[x]` Completed

**Business Value / User Story**  
As the engineering team, we need a clean Python project with repeatable tooling so every later financial/LLM component has stable boundaries.

**Technical Specification**

- Create `src/impactlens` package and test layout.
- Create `pyproject.toml`, Python 3.12+ requirement, pytest baseline, formatting/lint/type-check configuration as approved.
- Add `.gitignore`, `.env.example`, sample-data quarantine, and basic CLI/application bootstrap.

**Integrity / Safety Considerations**

Portfolio snapshots/security mappings must be deterministic; fixtures use synthetic/public demo data only.

**Definition of Done (DoD)**

- [x] Fresh environment install succeeds.
- [x] Baseline tests pass.
- [x] No secret or private portfolio file is tracked.
- [x] README/docs point to the SSOT task workflow.

### Task 1.2: Configuration, Secrets & Structured Logging

**Status:** `[x]` Completed

**Business Value / User Story**  
As an operator, I need environment-driven configuration and safe logs so providers can be changed without leaking credentials.

**Technical Specification**

- Typed settings for database, LLM, news, market-data, alerting, and app environment.
- Structured logging with correlation id hooks.
- Secret fields redacted from logs and reprs.

**Integrity / Safety Considerations**

Portfolio snapshots/security mappings must be deterministic; fixtures use synthetic/public demo data only.

**Definition of Done (DoD)**

- [x] Missing required production settings fail clearly.
- [x] `.env.example` contains placeholders only.
- [x] Logging tests prove configured secret values are not emitted.

### Task 1.3: SQLite Schema, Repositories & Migration Bootstrap

**Status:** `[x]` Completed

**Business Value / User Story**  
As the system of record, ImpactLens needs durable state and versionable schema before pipelines are built.

**Technical Specification**

- Create database bootstrap/migration mechanism.
- Repository interfaces for portfolios, securities, news, analyses, impacts, alerts.
- Initial indexes for snapshot/news hash/status/timestamps.

**Integrity / Safety Considerations**

Portfolio snapshots/security mappings must be deterministic; fixtures use synthetic/public demo data only.

**Definition of Done (DoD)**

- [x] Fresh DB initializes successfully.
- [x] Insert/read smoke tests pass.
- [x] Migration/version metadata is documented.

### Task 1.4: Portfolio Snapshot Domain & CSV Importer

**Status:** `[x]` Completed

**Business Value / User Story**  
As an analyst, I need to load a portfolio reproducibly so every impact result references a known holdings snapshot.

**Technical Specification**

- Define Portfolio, PortfolioSnapshot, Position models.
- CSV template and parser with row-level validation.
- Compute/validate portfolio weights or notionals according to explicit rules.
- Snapshots are immutable after creation.

**Integrity / Safety Considerations**

Portfolio snapshots/security mappings must be deterministic; fixtures use synthetic/public demo data only.

**Definition of Done (DoD)**

- [x] Synthetic portfolio imports and persists.
- [x] Invalid headers/numbers/duplicates produce useful errors.
- [x] Historical result can reference immutable snapshot id.
- [x] No real private portfolio in fixtures.

### Task 1.5: Security Master & Canonical Entity Resolver

**Status:** `[x]` Completed

**Business Value / User Story**  
As the exposure engine, I need reliable canonical security IDs so LLM-proposed names/tickers cannot silently map to the wrong asset.

**Technical Specification**

- Security master model with canonical name, ticker, exchange, sector/industry, aliases.
- Resolver returns Resolved / Ambiguous / Unresolved.
- Seed a small public/synthetic demo security set.

**Integrity / Safety Considerations**

Portfolio snapshots/security mappings must be deterministic; fixtures use synthetic/public demo data only.

**Definition of Done (DoD)**

- [x] Known aliases resolve deterministically.
- [x] Ambiguous ticker fixture remains ambiguous.
- [x] Unknown entity does not invent a ticker.
- [x] Resolver is callable without LLM.

---

## Phase 2: News Ingestion, Normalization & Deduplication

**Status:** `[x]` Completed

**Goal:** Create a provenance-preserving, idempotent news ingestion pipeline.

**Roadmap:** M1 Alpha

### Task 2.1: News Source Adapter Contract & Registry

**Status:** `[x]` Completed

**Business Value / User Story**  
As the ingestion layer, I need provider-neutral adapters so sources can be swapped without changing the pipeline.

**Technical Specification**

- Define RawNewsItem, SourceCursor/checkpoint, adapter protocol.
- Registry/config enablement and source priority.
- Fake adapter for tests.

**Integrity / Safety Considerations**

Preserve source provenance and timestamps; treat fetched article content as untrusted input; repeated polling must be idempotent.

**Definition of Done (DoD)**

- [x] Multiple adapters register and resolve by key.
- [x] Disabled adapter is not polled.
- [x] Contract tests use no live internet.

### Task 2.2: RSS/Atom Public Feed Adapter

**Status:** `[x]` Completed

**Business Value / User Story**  
As a user, I need at least one automated public news source to prove continuous ingestion.

**Technical Specification**

- Implement bounded RSS/Atom feed fetch/parse through provider adapter.
- Capture source item id, URL, title, published time, summary/body when available.
- Timeout/retry policy and polite polling.

**Integrity / Safety Considerations**

Preserve source provenance and timestamps; treat fetched article content as untrusted input; repeated polling must be idempotent.

**Definition of Done (DoD)**

- [x] Fixture feed parses expected records.
- [x] Malformed item is isolated without killing whole poll.
- [x] Re-poll supports checkpoint/idempotency behavior.

### Task 2.3: Manual URL/Text News Ingestion

**Status:** `[x]` Completed

**Business Value / User Story**  
As a researcher, I need to paste a news URL or text so I can analyze specific events without waiting for a feed.

**Technical Specification**

- Application command for manual text ingestion.
- Optional explicit URL fetch path behind fetcher abstraction.
- Source marked as manual with provenance metadata.

**Integrity / Safety Considerations**

Preserve source provenance and timestamps; treat fetched article content as untrusted input; repeated polling must be idempotent.

**Definition of Done (DoD)**

- [x] Manual text creates a canonical raw record.
- [x] Empty/oversized invalid input is rejected.
- [x] URL fetch failures return structured error.

### Task 2.4: News Normalizer, Timestamp Quality & Exact Deduplicator

**Status:** `[x]` Completed

**Business Value / User Story**  
As the pipeline, I need one canonical article representation so syndicated/repeated inputs do not create repeated LLM costs and alerts.

**Technical Specification**

- Normalize title/body whitespace and safe URL canonicalization.
- Compute stable content hash.
- Publication timestamp parser plus quality enum.
- Exact duplicate linkage by hash/source id/canonical URL.

**Integrity / Safety Considerations**

Preserve source provenance and timestamps; treat fetched article content as untrusted input; repeated polling must be idempotent.

**Definition of Done (DoD)**

- [x] Equivalent fixture articles produce same canonical hash when expected.
- [x] Distinct content remains distinct.
- [x] Missing publication time retains retrieval time but is flagged.
- [x] Duplicate links to canonical news record.

### Task 2.5: News Ingestion Orchestrator & Idempotent Polling

**Status:** `[x]` Completed

**Business Value / User Story**  
As the system, I need ingestion state transitions and safe repeat polling.

**Technical Specification**

- Compose adapters → normalize → dedup → persist.
- States Discovered/Fetched/Normalized/Duplicate/PendingAnalysis/Failed.
- Per-source checkpoint persistence and structured failure metadata.

**Integrity / Safety Considerations**

Preserve source provenance and timestamps; treat fetched article content as untrusted input; repeated polling must be idempotent.

**Definition of Done (DoD)**

- [x] First poll persists unique records.
- [x] Second identical poll creates no duplicate canonical records.
- [x] One bad item does not lose successful items.
- [x] Integration tests are deterministic.

---

## Phase 3: LLM Financial Event Intelligence & Entity Resolution

**Status:** `[x]` Completed

**Goal:** Extract source-grounded financial events and validate affected entities.

**Roadmap:** M2 Beta

### Task 3.1: Financial Event Taxonomy & Structured Analysis Schema

**Status:** `[x]` Completed

**Business Value / User Story**  
As the intelligence layer, I need a stable financial event vocabulary so outputs are comparable and testable.

**Technical Specification**

- Define event types, direction, severity, confidence, time horizon, entity roles.
- Pydantic schemas for event, entities, evidence, uncertainty.
- Schema/version constants.

**Integrity / Safety Considerations**

Model output is untrusted until schema/evidence/entity validation succeeds; never trust a model-generated ticker directly.

**Definition of Done (DoD)**

- [x] Invalid enum/range fails validation.
- [x] Multi-entity directions are representable.
- [x] Taxonomy documented in code/docs.

### Task 3.2: Structured LLM Provider Client

**Status:** `[x]` Completed

**Business Value / User Story**  
As the analyzer, I need a replaceable LLM client that returns validated structured data rather than free-form prose.

**Technical Specification**

- Provider interface and one OpenAI-compatible implementation or configured provider.
- Structured prompt with untrusted-article delimiters.
- Transient retry and malformed-output handling.
- Persist model/prompt/schema versions.

**Integrity / Safety Considerations**

Model output is untrusted until schema/evidence/entity validation succeeds; never trust a model-generated ticker directly.

**Definition of Done (DoD)**

- [x] Fake provider tests valid/malformed/timeout paths.
- [x] No API key logged.
- [x] Malformed output never silently becomes valid analysis.

### Task 3.3: Evidence Grounding Validator

**Status:** `[x]` Completed

**Business Value / User Story**  
As a user, I need every material event claim tied to actual article text.

**Technical Specification**

- Validate evidence excerpts/sentence refs against normalized input.
- Define normalization tolerance for evidence matching.
- Unsupported material claims route to uncertain/rejected analysis policy.

**Integrity / Safety Considerations**

Model output is untrusted until schema/evidence/entity validation succeeds; never trust a model-generated ticker directly.

**Definition of Done (DoD)**

- [x] Valid evidence accepted.
- [x] Fabricated evidence rejected.
- [x] Evidence coverage requirement enforced for impact-relevant claims.

### Task 3.4: Entity Proposal → Security Resolution Pipeline

**Status:** `[x]` Completed

**Business Value / User Story**  
As the portfolio mapper, I need model-proposed companies validated against the canonical security master.

**Technical Specification**

- Normalize entity names/aliases.
- Resolve public-company entities to canonical security IDs.
- Retain non-security entities such as regulator/country/commodity.
- Store ambiguous/unresolved state and candidates.

**Integrity / Safety Considerations**

Model output is untrusted until schema/evidence/entity validation succeeds; never trust a model-generated ticker directly.

**Definition of Done (DoD)**

- [x] Held-company fixture resolves correctly.
- [x] Wrong model ticker cannot override resolver.
- [x] Ambiguous company/ticker requires explicit ambiguity.

### Task 3.5: News Analysis Orchestrator & Offline Eval Harness

**Status:** `[x]` Completed

**Business Value / User Story**  
As the product, I need one analysis pipeline with measurable quality rather than ad-hoc prompts.

**Technical Specification**

- Compose pending news → LLM → schema → evidence → resolver → persist.
- States Analyzed/Uncertain/Failed/Resolved.
- Curated labeled fixture dataset and evaluation script for event/entity metrics.

**Integrity / Safety Considerations**

Model output is untrusted until schema/evidence/entity validation succeeds; never trust a model-generated ticker directly.

**Definition of Done (DoD)**

- [x] Fixture pipeline persists versioned analysis.
- [x] Uncertain fixture does not proceed as confident event.
- [x] Eval report runs reproducibly.
- [x] No portfolio score yet; Phase 4 owns scoring.

---

## Phase 4: Portfolio Exposure Mapping & Deterministic Impact Engine

**Status:** `[x]` Completed

**Goal:** Map events to held exposures and compute traceable portfolio impact priorities.

**Roadmap:** M2 Beta

### Task 4.1: Direct Portfolio Exposure Resolver

**Status:** `[x]` Completed

**Business Value / User Story**  
As an investor, I need news about a held company to map directly to the exact held position.

**Technical Specification**

- Match resolved security IDs to positions in a target snapshot.
- Represent direct ExposureMatch with position weight/notional and event direction.
- Support multiple held share classes/securities explicitly.

**Integrity / Safety Considerations**

Impact arithmetic is deterministic Python; indirect relationships require provenance; score is a priority measure, not expected return.

**Definition of Done (DoD)**

- [x] Direct held security maps with relationship type Direct.
- [x] Non-held resolved company creates no direct match.
- [x] Snapshot id is always recorded.

### Task 4.2: Indirect Exposure Rules & Relationship Provenance

**Status:** `[x]` Completed

**Business Value / User Story**  
As an analyst, I need sector/country/macro/relationship spillovers only when the relationship is explicit and auditable.

**Technical Specification**

- Config/data model for sector/industry, country, commodity/macro, and optional supplier/customer/competitor links.
- Every indirect ExposureMatch references relationship type and provenance/rule version.
- Ability to disable indirect families.

**Integrity / Safety Considerations**

Impact arithmetic is deterministic Python; indirect relationships require provenance; score is a priority measure, not expected return.

**Definition of Done (DoD)**

- [x] Allowed fixture creates expected indirect match.
- [x] Unsupported relationship is blocked.
- [x] LLM memory alone cannot create persisted relationship.

### Task 4.3: Versioned Deterministic Impact Scoring Engine

**Status:** `[x]` Completed

**Business Value / User Story**  
As a researcher, I need reproducible scoring whose arithmetic can be inspected and tested.

**Technical Specification**

- Implement documented formula from exposure magnitude, relationship weight, severity, confidence, relevance, direction.
- Produce signed score, absolute priority, level thresholds, component breakdown.
- Version scoring configuration/formula.

**Integrity / Safety Considerations**

Impact arithmetic is deterministic Python; indirect relationships require provenance; score is a priority measure, not expected return.

**Definition of Done (DoD)**

- [x] Hand-computed fixtures match code within tolerance.
- [x] Same inputs/version are deterministic.
- [x] Caps/threshold boundaries tested.
- [x] Score labeled priority, not expected return.

### Task 4.4: Evidence-Backed Portfolio Impact Explanation

**Status:** `[x]` Completed

**Business Value / User Story**  
As a user, I need to understand why a position was flagged without trusting a black box.

**Technical Specification**

- Compose impact explanation inputs from source evidence, event, exposure path, and score components.
- Template-first explanation; optional LLM prose may summarize only validated facts/numbers.
- Citation/source metadata included.

**Integrity / Safety Considerations**

Impact arithmetic is deterministic Python; indirect relationships require provenance; score is a priority measure, not expected return.

**Definition of Done (DoD)**

- [x] Explanation names the actual exposure path.
- [x] Numerical components match scorer output.
- [x] No unsupported claim introduced in deterministic template path.

### Task 4.5: Portfolio Impact Orchestrator & Ranking

**Status:** `[x]` Completed

**Business Value / User Story**  
As the product, I need a complete analysis→exposure→score pipeline and ranked impact feed data.

**Technical Specification**

- For resolved analysis and portfolio snapshot: resolve exposures, score components, persist impacts.
- Rank news impacts by absolute priority with stable tie behavior.
- Avoid recomputing same news/snapshot/scoring-version result unless forced.

**Integrity / Safety Considerations**

Impact arithmetic is deterministic Python; indirect relationships require provenance; score is a priority measure, not expected return.

**Definition of Done (DoD)**

- [x] End-to-end fixture returns affected positions and score breakdown.
- [x] Idempotent rerun does not duplicate impact rows.
- [x] Positive/negative/mixed fixtures rank deterministically.

---

## Phase 5: Market Data, Event Studies & Historical Validation

**Status:** `[x]` Completed

**Goal:** Add point-in-time empirical context and calibration.

**Roadmap:** M3 RC

### Task 5.1: Market Data Provider Contract & Cache

**Status:** `[x]` Completed

**Business Value / User Story**  
As the research layer, I need normalized price data independent of one vendor.

**Technical Specification**

- MarketDataProvider interface with timestamped series.
- Provider metadata and bounded local cache.
- Fake provider for deterministic tests.

**Integrity / Safety Considerations**

No look-ahead: only point-in-time eligible events/features/snapshots may enter historical analysis; numerical research never uses LLM arithmetic.

**Definition of Done (DoD)**

- [x] Fixture data normalize to common schema.
- [x] Cache keys include security/date/provider fields.
- [x] Research code consumes interface, not vendor-specific response.

### Task 5.2: Event Timestamp → Trading Session Alignment

**Status:** `[x]` Completed

**Business Value / User Story**  
As the event-study engine, I need correct event anchors for pre-open, intraday, after-close, weekends and holidays.

**Technical Specification**

- Exchange timezone/calendar abstraction.
- Document anchor policy.
- Return aligned event session plus alignment metadata.

**Integrity / Safety Considerations**

No look-ahead: only point-in-time eligible events/features/snapshots may enter historical analysis; numerical research never uses LLM arithmetic.

**Definition of Done (DoD)**

- [x] Before-open/in-session/after-close/weekend fixtures map as documented.
- [x] Low-quality news timestamp is flagged in research result.

### Task 5.3: Deterministic Event Study Engine

**Status:** `[x]` Completed

**Business Value / User Story**  
As a quant researcher, I need hand-verifiable return windows rather than LLM arithmetic.

**Technical Specification**

- Configurable event windows.
- Security return, benchmark return, abnormal return calculations.
- Missing-data policy and stored configuration.

**Integrity / Safety Considerations**

No look-ahead: only point-in-time eligible events/features/snapshots may enter historical analysis; numerical research never uses LLM arithmetic.

**Definition of Done (DoD)**

- [x] Hand-calculated [0,+1]/[0,+5] fixtures match.
- [x] Missing/non-trading data follows documented rule.
- [x] LLM is not called by calculation engine.

### Task 5.4: Historical Analog Retrieval

**Status:** `[x]` Completed

**Business Value / User Story**  
As an analyst, I need comparable past events and transparent similarity factors.

**Technical Specification**

- Retrieve prior events by event type/entity/sector/direction/severity/time horizon using only allowed historical data.
- Similarity components exposed.
- Exclude current/future events by cutoff.

**Integrity / Safety Considerations**

No look-ahead: only point-in-time eligible events/features/snapshots may enter historical analysis; numerical research never uses LLM arithmetic.

**Definition of Done (DoD)**

- [x] Known analog fixture ranks expected events.
- [x] Future event is never eligible.
- [x] Similarity inputs are visible in result.

### Task 5.5: Impact Score Calibration & Research Evaluation

**Status:** `[x]` Completed

**Business Value / User Story**  
As the project owner, I need evidence whether score buckets correspond to meaningful observed reactions.

**Technical Specification**

- Join stored impact scores with eligible event-study outcomes.
- Report reaction distributions by score level/event type.
- Direction-hit/absolute-move statistics where appropriate.
- Explicitly label association, not causality.

**Integrity / Safety Considerations**

No look-ahead: only point-in-time eligible events/features/snapshots may enter historical analysis; numerical research never uses LLM arithmetic.

**Definition of Done (DoD)**

- [x] Fixed dataset report reproduces.
- [x] No-look-ahead test fails when future feature injected.
- [x] Evaluation includes coverage/sample counts and avoids cherry-picking silent exclusions.

---

## Phase 6: API, Dashboard, Alerts & Workflow Automation

**Status:** `[x]` Completed

**Goal:** Turn the engine into a usable daily research workflow.

**Roadmap:** M4 v1.0

### Task 6.1: FastAPI Application & Core Resource Endpoints

**Status:** `[x]` Completed

**Business Value / User Story**  
As a client, I need stable endpoints for portfolios, news, analyses, impacts and research.

**Technical Specification**

- FastAPI app with health endpoint.
- Portfolio/news/impact/research read/create commands as phase scope requires.
- Pydantic request/response DTOs and error handling.

**Integrity / Safety Considerations**

UI/API must not duplicate business logic; alerts must be idempotent; exports must preserve provenance and avoid secrets.

**Definition of Done (DoD)**

- [x] API smoke tests pass.
- [x] Validation errors are structured.
- [x] Routes remain thin and call application services.

### Task 6.2: Streamlit Portfolio & Impact Dashboard

**Status:** `[x]` Completed

**Business Value / User Story**  
As a user, I need a visual ranked feed and drilldowns without reading raw JSON.

**Technical Specification**

- Portfolio import/view page.
- Impact feed ranked by absolute priority.
- News/evidence/event detail.
- Affected positions + score decomposition.
- Historical context page.

**Integrity / Safety Considerations**

UI/API must not duplicate business logic; alerts must be idempotent; exports must preserve provenance and avoid secrets.

**Definition of Done (DoD)**

- [x] Dashboard starts against sample DB/API.
- [x] Critical pages render sample fixture data.
- [x] No duplicate scoring logic in UI.

### Task 6.3: Threshold Alerts, Idempotency & Cooldown

**Status:** `[x]` Completed

**Business Value / User Story**  
As a user, I need high-impact news surfaced once without alert storms.

**Technical Specification**

- Alert policy by impact level/score and portfolio.
- Idempotency key per canonical news/portfolio/scoring version/channel.
- Cooldown/suppression and alert history.
- Initial output adapter such as console/webhook if approved.

**Integrity / Safety Considerations**

UI/API must not duplicate business logic; alerts must be idempotent; exports must preserve provenance and avoid secrets.

**Definition of Done (DoD)**

- [x] High-impact fixture alerts once.
- [x] Duplicate/rerun suppressed.
- [x] Policy boundary tests pass.

### Task 6.4: Scheduled News-to-Impact Workflow

**Status:** `[x]` Completed

**Business Value / User Story**  
As an operator, I need automated polling and processing without manually running each stage.

**Technical Specification**

- Lightweight scheduler/background job runner.
- Poll enabled sources, analyze new unique items, score configured active portfolio snapshots.
- Retry/failure visibility and graceful shutdown.

**Integrity / Safety Considerations**

UI/API must not duplicate business logic; alerts must be idempotent; exports must preserve provenance and avoid secrets.

**Definition of Done (DoD)**

- [x] Scheduled test run processes fixture source end-to-end.
- [x] Duplicate item does not repeat LLM/alert work.
- [x] Failure in one item does not stop future jobs.

### Task 6.5: Research Brief & Data Export

**Status:** `[x]` Completed

**Business Value / User Story**  
As an analyst, I need portable outputs for GitHub demos and research review.

**Technical Specification**

- Export impact result to JSON/CSV and a Markdown research brief.
- Include source, evidence, portfolio snapshot id, model/prompt/schema/scoring versions, historical config.
- Do not expose secrets/private fields unnecessarily.

**Integrity / Safety Considerations**

UI/API must not duplicate business logic; alerts must be idempotent; exports must preserve provenance and avoid secrets.

**Definition of Done (DoD)**

- [x] Fixture export is reproducible.
- [x] Required provenance fields present.
- [x] Markdown brief clearly separates observed facts, score, and historical association.

---

## Phase 7: Hardening, Docker, CI/CD & Operations

**Status:** `[x]` Completed

**Goal:** Make the project reproducible and production-minded.

**Roadmap:** M5 v1.1

### Task 7.1: End-to-End Pipeline & Regression Suite

**Status:** `[x]` Completed

**Business Value / User Story**  
As the engineering team, we need deterministic proof of the complete promise and key failure paths.

**Technical Specification**

- E2E fixtures for unique article, duplicate, uncertain analysis, unresolved entity, scored event, alert, event study.
- Use provider fakes; live tests optional/manual.

**Integrity / Safety Considerations**

Production artifacts must not leak secrets or private portfolios; CI uses deterministic fakes and backups protect the SQLite system of record.

**Definition of Done (DoD)**

- [x] All documented E2E paths pass.
- [x] Regression includes no-look-ahead and score determinism.
- [x] No private data required.

### Task 7.2: Observability, Health & Data-Safety Checks

**Status:** `[x]` Completed

**Business Value / User Story**  
As an operator, I need diagnosable failures without leaking portfolio/secrets.

**Technical Specification**

- Structured correlation logs across stages.
- Liveness/readiness for DB/config/job health.
- Log scrubbing and safe portfolio logging policy.

**Integrity / Safety Considerations**

Production artifacts must not leak secrets or private portfolios; CI uses deterministic fakes and backups protect the SQLite system of record.

**Definition of Done (DoD)**

- [x] Health tests pass.
- [x] Secret redaction tests pass.
- [x] A pipeline error can be traced by correlation/news id.

### Task 7.3: Docker & Docker Compose Deployment

**Status:** `[x]` Completed

**Business Value / User Story**  
As a contributor, I need a reproducible containerized demo/deployment.

**Technical Specification**

- Multi-stage/minimal Python image as appropriate.
- Compose services for API, dashboard, optional worker; persistent SQLite volume.
- Non-root and healthcheck where practical.
- .env runtime injection.

**Integrity / Safety Considerations**

Production artifacts must not leak secrets or private portfolios; CI uses deterministic fakes and backups protect the SQLite system of record.

**Definition of Done (DoD)**

- [x] Compose validates/starts.
- [x] Health endpoint becomes healthy.
- [x] Fixture/sample workflow works in container environment.

### Task 7.4: GitHub Actions CI/CD & Release Workflow

**Status:** `[x]` Completed

**Business Value / User Story**  
As a maintainer, I need every merge/release to pass quality gates before publishing artifacts.

**Technical Specification**

- CI for install, lint/type checks as configured, tests, coverage/security/dependency audit.
- Docker build on main/tag.
- Tagged release/container publishing as configured.

**Integrity / Safety Considerations**

Production artifacts must not leak secrets or private portfolios; CI uses deterministic fakes and backups protect the SQLite system of record.

**Definition of Done (DoD)**

- [x] Failed tests block publish.
- [x] Workflow syntax validated.
- [x] No deploy secrets exposed to untrusted PRs.

### Task 7.5: SQLite Backup/Restore & Operational Runbook

**Status:** `[x]` Completed

**Business Value / User Story**  
As an operator, I need to recover portfolio/news research state and handle provider incidents.

**Technical Specification**

- Consistent SQLite backup procedure/service/script.
- Restore drill verification.
- RUNBOOK for DB corruption, LLM failures, source outage, alert storm, resolver errors, cache issues.

**Integrity / Safety Considerations**

Production artifacts must not leak secrets or private portfolios; CI uses deterministic fakes and backups protect the SQLite system of record.

**Definition of Done (DoD)**

- [x] Backup can restore into clean instance.
- [x] Integrity/smoke checks pass after restore.
- [x] RUNBOOK matches deployed commands/config.

---

## Cross-Cutting Traceability Matrix

| Concern | Primary tasks |
|---|---|
| Portfolio snapshot & security identity | 1.4–1.5 |
| News provenance / deduplication | 2.1–2.5 |
| Structured LLM + evidence | 3.1–3.5 |
| Entity/ticker validation | 1.5, 3.4 |
| Direct/indirect exposure traceability | 4.1–4.2 |
| Deterministic impact scoring | 4.3–4.5 |
| No-look-ahead / event studies | 5.1–5.5 |
| API/dashboard/alerts/jobs | 6.1–6.5 |
| Observability/deployment/DR | 7.1–7.5 |
| Secrets/private portfolio safety | Global DoD + 1.2 + 7.x |

## Progress Summary

| Phase | Tasks | Not Started | In Progress | Completed |
|---|---|---:|---:|---:|
| 1 Foundation, Portfolio Model & Security Master | 1.1–1.5 | 0 | 0 | 5 |
| 2 News Ingestion, Normalization & Deduplication | 2.1–2.5 | 0 | 0 | 5 |
| 3 LLM Financial Event Intelligence & Entity Resolution | 3.1–3.5 | 0 | 0 | 5 |
| 4 Portfolio Exposure Mapping & Deterministic Impact Engine | 4.1–4.5 | 0 | 0 | 5 |
| 5 Market Data, Event Studies & Historical Validation | 5.1–5.5 | 0 | 0 | 5 |
| 6 API, Dashboard, Alerts & Workflow Automation | 6.1–6.5 | 0 | 0 | 5 |
| 7 Hardening, Docker, CI/CD & Operations | 7.1–7.5 | 0 | 0 | 5 |
| **Total** | **35 tasks** | **0** | **0** | **35** |

Update counts only when task statuses actually change.

## Initial Change Log

| Date | Change |
|---|---|
| 2026-10-13 | ImpactLens governance package created; 7 phases / 35 implementation tasks initialized as Not Started. |
| 2026-10-13 | Tasks 1.1–7.5 implemented and verified; all statuses and DoD items marked complete (evidence in TASKS.md). |
