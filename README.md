# ImpactLens

**Financial News → Portfolio Impact Engine**

ImpactLens is an LLM-assisted financial-news intelligence platform that converts raw financial news into evidence-backed portfolio impact assessments.

Instead of showing another generic news feed, ImpactLens answers a portfolio-specific question:

> **Why does this news matter to my holdings, which positions are exposed, and how important is it?**

## Core Workflow

```text
Financial News
      ↓
Ingest + Normalize + Deduplicate
      ↓
LLM Event & Entity Extraction
      ↓
Canonical Entity / Ticker Resolution
      ↓
Portfolio Exposure Mapping
      ↓
Deterministic Impact Scoring
      ↓
Evidence-backed Explanation
      ↓
Dashboard / Alerts
      ↓
Historical Event Validation
```

## Example

Input news:

> A new export restriction limits advanced semiconductor shipments to a major market.

A portfolio containing semiconductor names may produce:

```text
Portfolio Impact: HIGH

Direct exposure
- NVDA: Negative / High relevance
- AMD: Negative / High relevance

Indirect exposure
- ASML: Negative / Medium relevance
- TSM: Mixed-to-negative / Medium relevance

Drivers
- Regulatory restriction
- Revenue-market exposure
- Semiconductor supply-chain spillover

Confidence: 0.87
Evidence: linked to source sentences
```

The impact score is a deterministic **priority score**, not an LLM-generated expected return.

## v1 Scope

- Import portfolio snapshots from CSV.
- Ingest financial news from configurable adapters and manual inputs.
- Normalize and deduplicate articles.
- Extract events, affected entities, direction, severity, time horizon, and evidence using an LLM.
- Resolve company/entity mentions to canonical securities.
- Map direct and selected indirect exposures to portfolio holdings.
- Compute reproducible impact-priority scores in Python.
- Present ranked portfolio-impact cards with source evidence.
- Run historical event studies and retrieve comparable past events.
- Provide API, dashboard, alerts, audit trail, tests, and Docker deployment.

## Non-Goals for v1

- Autonomous live trading or order execution.
- LLM-generated price targets.
- Unverifiable supplier/customer graphs inferred only from model memory.
- High-frequency event trading.
- Claiming causality from simple post-news price moves.
- Replacing professional investment judgment.

## Technology Baseline

| Area | Baseline |
|---|---|
| Language | Python 3.12+ |
| API | FastAPI |
| Dashboard | Streamlit |
| Persistence | SQLite |
| Data/analytics | Python standard library (`statistics`); pandas/NumPy not needed in v1 |
| Validation | Pydantic |
| HTTP | httpx |
| LLM | Provider adapter with structured output |
| Jobs | in-process scheduler (`python -m impactlens.jobs.run`) |
| Tests | pytest |
| Deployment | Docker / Docker Compose |

Runtime dependencies are listed in `pyproject.toml` (pydantic, httpx, FastAPI, uvicorn, python-multipart; Streamlit as the `dashboard` extra).

## Quickstart

Everything below runs offline on synthetic data (`data/samples/`) with a fixture LLM provider.

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,dashboard]"
impactlens demo                                     # seed → import demo portfolio → ingest → analyze → score → alert
pytest -q                                           # 192 tests
python -m impactlens eval                           # offline LLM-analysis eval report
```

Run the services:

```bash
uvicorn impactlens.api.main:app --reload            # http://localhost:8000/docs
streamlit run src/impactlens/dashboard/app.py       # http://localhost:8501
python -m impactlens.jobs.run                       # scheduler
```

Or with Docker: `docker compose up -d --build`, then `docker compose exec impactlens-api impactlens demo`.

To use a real LLM copy `.env.example` to `.env` and set `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`,
`LLM_MODEL` and `LLM_API_KEY`. All CLI commands are listed in [RUNBOOK §0](docs/RUNBOOK.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Implementation Phases](docs/PHASES.md)
- [Atomic Tasks / SSOT](docs/PROJECT_PHASES_AND_TASKS.md)
- [Task Ledger](docs/TASKS.md)
- [Diagrams](docs/DIAGRAMS.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Runbook](docs/RUNBOOK.md)

## Development Model

`docs/PROJECT_PHASES_AND_TASKS.md` is the implementation source of truth. Complete one atomic task at a time and satisfy its Definition of Done before moving on.

All 35 v1 tasks (Phases 1–7) are implemented and verified; see [TASKS.md](docs/TASKS.md) for per-phase
verification evidence. New work starts as a new task in the SSOT document.

## Disclaimer

ImpactLens is a research and decision-support project. Outputs are informational and are not personalized investment advice or an execution recommendation.
