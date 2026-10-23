# ImpactLens Roadmap

Strategic product roadmap for **ImpactLens — Financial News → Portfolio Impact Engine**.

**Related documents:** [ARCHITECTURE.md](./ARCHITECTURE.md) · [PHASES.md](./PHASES.md) · [DIAGRAMS.md](./DIAGRAMS.md) · [TASKS.md](./TASKS.md)

---

## 1. Product Vision & Value Proposition

### Vision

ImpactLens turns the global financial-news stream into a **portfolio-aware research layer**. The product should answer four questions quickly and transparently:

1. **What happened?** — identify the event, entities, direction, severity, and horizon.
2. **Where am I exposed?** — map the event to direct and justified indirect portfolio relationships.
3. **How important is it?** — calculate a deterministic impact-priority score.
4. **What happened in similar cases?** — show reproducible historical reactions without look-ahead bias.

The product is designed for research, triage, and explanation—not autonomous order execution.

### Value Proposition

| Stakeholder | Value |
|---|---|
| Investor / analyst | Ranked news by portfolio relevance instead of generic headlines. |
| Quant / researcher | Structured event dataset, point-in-time event studies, and calibration metrics. |
| Portfolio manager | Fast exposure map with direct/indirect relationship labels and evidence. |
| Engineer | Modular provider adapters, deterministic scoring, testable LLM boundaries, and reproducible audit trail. |

### Non-Goals (v1)

- Brokerage/order execution.
- LLM-generated price targets or fabricated expected returns.
- Black-box scoring hidden in prompts.
- Real-time HFT latency guarantees.
- Causal claims from simple return windows.
- Automatically treating every co-mentioned company as portfolio exposure.

---

## 2. Release Horizons

### M1 — Portfolio & News Foundation (Alpha)

**Theme:** establish the system of record, portfolio snapshots, canonical securities, and reliable news ingestion.

| Area | Outcome |
|---|---|
| Project foundation | Python package, config, logging, testing, SQLite migrations. |
| Portfolio model | CSV portfolio import with validation and immutable snapshot identity. |
| Security master | Canonical company/security/ticker resolution contract. |
| News ingestion | Provider abstraction plus at least one working feed/manual path. |
| Provenance | Source URL/id, published/retrieved timestamps, hash, raw/normalized content metadata. |

**Business unlock:** a portfolio and a clean, deduplicated news corpus can be ingested and queried reproducibly.

**Exit criteria:** demo imports a sample portfolio, ingests sample/live-public news, deduplicates it, and persists provenance.

---

### M2 — News Intelligence & Exposure Mapping (Beta)

**Theme:** convert text into structured financial events and connect those events to holdings.

| Area | Outcome |
|---|---|
| Event taxonomy | Stable event categories and structured Pydantic schema. |
| LLM analysis | Event/entity/direction/severity/confidence/evidence extraction. |
| Entity linking | Model proposals validated against security master. |
| Exposure engine | Direct holdings plus explicitly modeled indirect relationships. |
| Impact score | Deterministic, decomposable portfolio-impact priority score. |

**Business unlock:** a news item becomes a ranked, evidence-backed portfolio-impact result.

**Exit criteria:** curated evaluation set produces valid schemas, evidence coverage, entity links, and deterministic scores for known portfolios.

---

### M3 — Historical Validation & Research Layer (Release Candidate)

**Theme:** prove whether the impact framework is informative using point-in-time market reactions.

| Area | Outcome |
|---|---|
| Market data | Replaceable market-data adapter and local cache. |
| Time alignment | Publication timestamp mapped to relevant trading session. |
| Event study | Deterministic return and benchmark-adjusted windows. |
| Historical analogs | Similar past events retrieved using approved features. |
| Calibration | Compare score buckets with observed reaction magnitude/direction. |

**Business unlock:** analysts can distinguish plausible narratives from empirically useful signals.

**Exit criteria:** event-study notebook/API reproduces results for a fixed labeled event set with explicit no-look-ahead tests.

---

### M4 — Product UX & Workflow Automation (v1.0)

**Theme:** make the system practical for daily use.

| Area | Outcome |
|---|---|
| REST API | Portfolio, news, analysis, impact, and research endpoints. |
| Dashboard | Ranked feed, portfolio exposure drilldown, evidence, history. |
| Alerts | Threshold-based high-impact notifications with cooldown/idempotency. |
| Jobs | Scheduled ingestion and analysis with retry/error states. |
| Export | Research brief / JSON/CSV export with audit metadata. |

**Business unlock:** a user can run ImpactLens continuously and review only high-relevance portfolio events.

**Exit criteria:** end-to-end walkthrough from news ingestion to alert/dashboard and historical context.

---

### M5 — Production Hardening (v1.1)

**Theme:** reliability, reproducibility, security, and release discipline.

| Area | Outcome |
|---|---|
| E2E | Full deterministic pipeline tests with provider fakes. |
| Observability | Structured logs, correlation IDs, health/readiness checks. |
| Deployment | Docker/Compose and environment templates. |
| CI/CD | Test/lint/security gates and tagged image releases. |
| Backup | SQLite backup/restore and operational runbook. |

**Business unlock:** repeatable deployment and safe research operations.

---

### Future Horizon

Directional extensions—not committed to v1:

| Direction | Description |
|---|---|
| Rich relationship graph | Verified supplier/customer/product/competitor relationships with source provenance. |
| Macro portfolio factors | Rates, FX, commodity, country and duration factor maps. |
| Multi-portfolio workspaces | Compare impact across funds/strategies. |
| Agentic research | Research agent produces a cited impact memo from already-validated pipeline outputs. |
| Alternative data | Transcripts, filings, social/newswire premium feeds where licensed. |
| Learned impact model | Supervised model calibrated on historical outcomes, kept separate from LLM narrative layer. |

---

## 3. Success Metrics & KPIs

### Intelligence Quality

| KPI | Initial Target | Definition |
|---|---:|---|
| Structured-output validity | 99%+ after retry/fallback | Analyses passing schema validation. |
| Material claim evidence coverage | 100% | Every event/direction claim used in impact has source evidence. |
| Direct entity-link accuracy | >95% on labeled set | Correct canonical security for clearly named public companies. |
| Event-type macro F1 | >0.85 on curated set | Classification quality across supported event taxonomy. |
| Duplicate suppression | >99% on known duplicates | Same/syndicated article not repeatedly analyzed as independent news. |

### Portfolio Quality

| KPI | Initial Target | Definition |
|---|---:|---|
| Score determinism | 100% | Same stored inputs/config produce same impact score. |
| Exposure traceability | 100% | Every affected position exposes the relationship path used. |
| Direct-holding recall | 100% on labeled fixtures | Named held security is not missed after successful entity resolution. |
| Unsupported indirect links | 0 accepted in test set | No indirect exposure without stored/verifiable relationship basis. |

### Research Integrity

| KPI | Target | Definition |
|---|---:|---|
| No-look-ahead regression tests | 100% pass | Future observations cannot enter historical feature windows. |
| Event-study reproducibility | 100% | Same config/data snapshot reproduces stored metrics. |
| Timestamp coverage | >98% | Analyzed news has usable publication time or explicit fallback quality flag. |

### Operational Metrics

- Mean ingestion-to-impact latency.
- News items analyzed per run/day.
- LLM cost per analyzed item.
- Provider error/rate-limit frequency.
- Entity-resolution ambiguous/unresolved rate.
- Alert volume and duplicate-alert suppression rate.
- High-impact score bucket vs observed absolute post-event return (research metric, not a guaranteed prediction KPI).

---

## 4. Milestone → Engineering Phase Mapping

| Roadmap Horizon | Primary Phases |
|---|---|
| M1 Alpha | Phases 1–2 |
| M2 Beta | Phases 3–4 |
| M3 RC | Phase 5 |
| M4 v1.0 | Phase 6 |
| M5 v1.1 | Phase 7 |

---

## 5. Strategic Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Hallucinated entity/ticker | Wrong portfolio exposure | Security-master validation; unresolved state; labeled eval set. |
| News timestamp ambiguity | Corrupt event study | Store timestamp quality and explicit session-alignment policy. |
| Duplicate syndicated news | Alert spam / biased research set | Canonical normalization + hash/similarity deduplication. |
| LLM severity drift | Score instability | Prompt/schema versioning; fixed eval fixtures; deterministic score layer. |
| Unsupported indirect exposure | Misleading portfolio impact | Relationship provenance requirement; direct/indirect labels. |
| Look-ahead bias | Invalid backtest/research claims | Point-in-time guards and mandatory tests. |
| Data-provider lock-in | Cost/reliability risk | Provider adapters and local normalized contracts. |
| Scope creep into trading bot | Delayed core value | Explicit non-goal; trading/execution outside v1. |

---

## 6. Roadmap Change Control

- Update this document when milestone scope or KPI definitions change.
- Reflect implementation progress in `TASKS.md`.
- New data/LLM providers must enter through adapters.
- A change from impact-priority scoring to predicted-return modeling requires an explicit new research/design task, dataset, evaluation protocol, and documentation.

## 7. Change Log

| Date | Change |
|---|---|
| 2026-10-13 | Roadmap created. |
| 2026-10-13 | M1–M5 scope delivered as v1.0.0 (all 35 tasks, Phases 1–7); see TASKS.md for verification evidence. |
