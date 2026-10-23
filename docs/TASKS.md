# ImpactLens — Task Progress Ledger

Structured delivery checklist for ImpactLens. Update only after verified task progress.

## Status Legend

| Marker | Meaning |
|---|---|
| `[ ]` | Pending |
| `[-]` | In Progress |
| `[x]` | Completed |

## Verification Log Format

For every completed task record: tests run/result, docs updated, and brief verification evidence.

## Phase 0 — Project Governance & Baseline

- [x] Create `CLAUDE.md` for Claude Code project rules.
- [x] Create `.claude/rules/architecture.md`.
- [x] Create `.claude/rules/finance-integrity.md`.
- [x] Create `.claude/rules/llm-analysis.md`.
- [x] Create `.claude/rules/testing.md`.
- [x] Create `.claude/rules/documentation.md`.
- [x] Create `README.md` and `PROJECT_STRUCTURE.md`.
- [x] Create all eight `docs/` governance/engineering templates.
- [x] Initialize Phase 1–7 implementation tasks as Not Started.

### Verification — Phase 0

| Item | Detail |
|---|---|
| Status | `[x]` Documentation baseline prepared |
| Tests | N/A — no implementation code yet |
| Notes | Implementation begins with Task 1.1 |

---

## Phase 1 — Foundation, Portfolio Model & Security Master

- [x] **Task 1.1** Python Project Scaffolding & Quality Baseline
- [x] **Task 1.2** Configuration, Secrets & Structured Logging
- [x] **Task 1.3** SQLite Schema, Repositories & Migration Bootstrap
- [x] **Task 1.4** Portfolio Snapshot Domain & CSV Importer
- [x] **Task 1.5** Security Master & Canonical Entity Resolver

### Verification

| Item | Detail |
|---|---|
| Status | `[x]` Completed (2026-10-13) |
| Tests | tests/unit/test_phase1_foundation.py (14), tests/unit/test_phase1_storage_portfolio.py (31) — all pass |
| Docs | ARCHITECTURE §16, DEPLOYMENT env reference, `.env.example`, README quickstart |
| Notes | Fresh venv `pip install -e .[dev,dashboard]` succeeds; settings fail with a full error list; configured secret values never appear in log output; migration 0001 with checksum + immutable snapshot triggers; CSV importer reports line/column errors; resolver keeps ambiguous ABC ambiguous and never invents tickers. |

---

## Phase 2 — News Ingestion, Normalization & Deduplication

- [x] **Task 2.1** News Source Adapter Contract & Registry
- [x] **Task 2.2** RSS/Atom Public Feed Adapter
- [x] **Task 2.3** Manual URL/Text News Ingestion
- [x] **Task 2.4** News Normalizer, Timestamp Quality & Exact Deduplicator
- [x] **Task 2.5** News Ingestion Orchestrator & Idempotent Polling

### Verification

| Item | Detail |
|---|---|
| Status | `[x]` Completed (2026-10-13) |
| Tests | tests/unit/test_phase2_news.py (32) — all pass; RSS/Atom fixtures under tests/fixtures/feeds, httpx MockTransport (no live internet) |
| Docs | ARCHITECTURE §16, RUNBOOK source-outage section |
| Notes | Registry resolves by key and skips disabled sources; malformed feed item isolated into `ingestion_failures`; checkpoint makes re-poll idempotent; content-hash-v1 links syndicated duplicate n02 to its canonical record; missing publish time flagged `retrieved_only`. |

---

## Phase 3 — LLM Financial Event Intelligence & Entity Resolution

- [x] **Task 3.1** Financial Event Taxonomy & Structured Analysis Schema
- [x] **Task 3.2** Structured LLM Provider Client
- [x] **Task 3.3** Evidence Grounding Validator
- [x] **Task 3.4** Entity Proposal → Security Resolution Pipeline
- [x] **Task 3.5** News Analysis Orchestrator & Offline Eval Harness

### Verification

| Item | Detail |
|---|---|
| Status | `[x]` Completed (2026-10-13) |
| Tests | tests/unit/test_phase3_intelligence.py (31) — all pass; `impactlens eval`: event_type accuracy 1.00, direction 0.857, entity F1 1.00 |
| Docs | ARCHITECTURE §16 taxonomy/evidence/resolver, prompt `system_v1.txt` |
| Notes | Schema `extra=forbid` rejects invalid enums/ranges; malformed/timeout provider output ends as Failed, never Valid; fabricated evidence (n06) → Uncertain; wrong model ticker cannot override resolver; no scoring in Phase 3 services. |

---

## Phase 4 — Portfolio Exposure Mapping & Deterministic Impact Engine

- [x] **Task 4.1** Direct Portfolio Exposure Resolver
- [x] **Task 4.2** Indirect Exposure Rules & Relationship Provenance
- [x] **Task 4.3** Versioned Deterministic Impact Scoring Engine
- [x] **Task 4.4** Evidence-Backed Portfolio Impact Explanation
- [x] **Task 4.5** Portfolio Impact Orchestrator & Ranking

### Verification

| Item | Detail |
|---|---|
| Status | `[x]` Completed (2026-10-13) |
| Tests | tests/unit/test_phase4_impact.py (21) — all pass, incl. hand-computed score fixtures and golden ranking |
| Docs | ARCHITECTURE §16 exposure/scoring tables |
| Notes | Direct + provenance-backed indirect matches only; relationship types restricted by CHECK constraint; provenance `llm`/`model` rejected; impact-v1 deterministic, caps/thresholds at 10/25/50 tested; explanation numbers equal scorer components; rerun does not duplicate impacts. |

---

## Phase 5 — Market Data, Event Studies & Historical Validation

- [x] **Task 5.1** Market Data Provider Contract & Cache
- [x] **Task 5.2** Event Timestamp → Trading Session Alignment
- [x] **Task 5.3** Deterministic Event Study Engine
- [x] **Task 5.4** Historical Analog Retrieval
- [x] **Task 5.5** Impact Score Calibration & Research Evaluation

### Verification

| Item | Detail |
|---|---|
| Status | `[x]` Completed (2026-10-13) |
| Tests | tests/unit/test_phase5_research.py (21) — all pass |
| Docs | ARCHITECTURE §16 alignment/event-study/analog/calibration |
| Notes | Pre-open/in-session/after-close/weekend alignment fixtures; low-quality timestamps flagged; [0,+1]/[0,+5] AR match hand calculation; future analogs ineligible; LookAheadViolation raised when a future feature is injected; calibration reports sample/coverage counts and exclusions. |

---

## Phase 6 — API, Dashboard, Alerts & Workflow Automation

- [x] **Task 6.1** FastAPI Application & Core Resource Endpoints
- [x] **Task 6.2** Streamlit Portfolio & Impact Dashboard
- [x] **Task 6.3** Threshold Alerts, Idempotency & Cooldown
- [x] **Task 6.4** Scheduled News-to-Impact Workflow
- [x] **Task 6.5** Research Brief & Data Export

### Verification

| Item | Detail |
|---|---|
| Status | `[x]` Completed (2026-10-13) |
| Tests | tests/integration/test_phase6_api.py (5), tests/integration/test_phase6_alerts_jobs_export.py (16) — all pass, incl. Streamlit AppTest pages |
| Docs | RUNBOOK §0, DEPLOYMENT app commands |
| Notes | FastAPI routes call services with structured 422 errors; dashboard renders 6 pages against the API with no scoring logic; Critical fixture alerts once, rerun suppressed by idempotency key, cooldown boundaries tested; scheduled cycle processes the fixture source end-to-end; Markdown/JSON/CSV exports reproducible with provenance. |

---

## Phase 7 — Hardening, Docker, CI/CD & Operations

- [x] **Task 7.1** End-to-End Pipeline & Regression Suite
- [x] **Task 7.2** Observability, Health & Data-Safety Checks
- [x] **Task 7.3** Docker & Docker Compose Deployment
- [x] **Task 7.4** GitHub Actions CI/CD & Release Workflow
- [x] **Task 7.5** SQLite Backup/Restore & Operational Runbook

### Verification

| Item | Detail |
|---|---|
| Status | `[x]` Completed (2026-10-13) |
| Tests | tests/e2e/test_pipeline_e2e.py (10), tests/integration/test_phase7_ops.py (11) — all pass; full suite 192 passed; `ruff check` clean; `mypy` clean (67 files) |
| Docs | RUNBOOK, DEPLOYMENT, README, ARCHITECTURE §16 |
| Notes | `docker compose config` valid; image built and `docker compose up` → api healthy, `/ready` 200, `impactlens demo` runs in the container as non-root uid 10001; CI workflow has read-only token and publish `needs: test`; backup → restore into clean instance passes integrity check. Docker build verified in a sandbox that needed a proxy CA injected at build time; the committed Dockerfile is unchanged. |

---

## Change Log

| Date | Change |
|---|---|
| 2026-10-13 | ImpactLens planning baseline created; Phase 0 docs complete; Tasks 1.1–7.5 pending. |
| 2026-10-13 | Tasks 1.1–7.5 implemented and verified (192 tests passing, ruff + mypy clean, Docker Compose smoke run). |
