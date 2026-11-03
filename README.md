# ImpactLens

**Financial News → Portfolio Impact Engine**

![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![Tests](https://img.shields.io/badge/tests-192%20passing-brightgreen)
![Lint](https://img.shields.io/badge/ruff%20%2B%20mypy-clean-brightgreen)
![Status](https://img.shields.io/badge/v1-complete-success)

ImpactLens turns raw financial news into evidence-backed, portfolio-specific impact assessments. Instead of
another generic news feed, it answers one question:

> **Why does this news matter to my holdings, which positions are exposed, and how important is it?**

An LLM is used only where language understanding is needed (event and entity extraction, with every claim tied to a
quoted sentence). Everything that decides *how much it matters* (entity resolution, exposure mapping, scoring) is
plain, deterministic, versioned Python, so the same inputs always give the same result.

> **Status:** v1 is complete. All 35 tasks across Phases 1–7 are implemented and verified: 192 tests pass,
> `ruff` and `mypy` are clean, and the Docker Compose stack runs end to end. Per-phase evidence is in
> [docs/TASKS.md](docs/TASKS.md).

---

## Contents

- [How it works](#how-it-works)
- [Features](#features)
- [Example output](#example-output)
- [Quickstart](#quickstart)
- [Running the services](#running-the-services)
- [Docker](#docker)
- [Configuration](#configuration)
- [CLI reference](#cli-reference)
- [REST API](#rest-api)
- [Testing and quality checks](#testing-and-quality-checks)
- [Project layout](#project-layout)
- [Documentation](#documentation)
- [Non-goals](#non-goals)
- [Disclaimer](#disclaimer)

---

## How it works

```text
News sources (RSS/Atom · URL · pasted text · fixtures)
        ↓
Ingest → normalize → deduplicate (canonical URL + content hash + syndication detection)
        ↓
LLM event & entity extraction (strict JSON schema, every claim grounded in quoted evidence)
        ↓
Canonical entity / ticker resolution (aliases, share classes, ambiguity guarded)
        ↓
Portfolio exposure mapping (direct + rule-based indirect: sector, industry, country,
                            commodity, macro factor, supplier/customer/competitor)
        ↓
Deterministic impact-priority scoring (0–100, versioned weights, full audit trail)
        ↓
Explanation · dashboard · alerts · research brief export
        ↓
Historical validation (event studies, analog events, score calibration)
```

The impact score is a **triage priority**, not an expected return, forecast or price target.

## Features

**Portfolio**
- CSV import with validation, ticker resolution and row-level error reports.
- Every import becomes an immutable, timestamped snapshot, so past impacts stay reproducible.

**News ingestion**
- Adapters for RSS/Atom feeds, explicit URLs, pasted text and offline fixtures.
- Normalization, HTML-to-text, URL canonicalization (tracking parameters stripped) and timestamp-quality tagging.
- Duplicate and syndicated-copy detection.
- Per-source enable/disable, timeouts, polite user agent and isolated source failures.

**LLM intelligence**
- Provider adapter: an offline `fixture` provider for demos and tests, and an `openai_compatible` provider for real
  models.
- Versioned prompt and strict output schema; responses that fail validation or cite evidence not present in the
  article are rejected or marked `Uncertain`, never silently accepted.
- Controlled event taxonomy (regulation, earnings, macro, commodity, legal and more).
- Offline evaluation harness on a labelled set (`impactlens eval`).

**Entities and exposure**
- Security master with aliases, share classes (for example GOOG/GOOGL) and factor exposures.
- Direct exposure plus indirect, rule-based exposure through sector, industry, country, commodity, macro factors and
  curated supplier/customer/competitor relationships. Each rule family can be disabled.
- No relationships invented from model memory: indirect links come only from curated data.

**Scoring and explanation**
- Deterministic priority score from portfolio weight, relationship weight, severity, confidence and relevance,
  with Low / Medium / High / Critical levels.
- Every component is stored and shown, so you can see exactly why a holding was flagged.
- Explanations clearly separate observed facts, model-extracted claims and computed numbers.

**Research and validation**
- Point-in-time event studies with abnormal returns against SPY, on a real exchange calendar.
- Historical analog search for comparable past events.
- Score-bucket calibration report.

**Delivery and operations**
- FastAPI REST API and Streamlit dashboard.
- Alerts (console or webhook) with minimum level and cooldown.
- Research brief export as JSON, CSV or Markdown.
- In-process scheduler / worker, structured JSON logging, `/health` and `/ready` endpoints.
- SQLite with migrations, plus consistent online backup and verified restore.
- CI (lint, type check, tests on 3.12 and 3.13, offline eval, dependency audit, secret guard) and a release workflow.

## Example output

Running `impactlens demo` on the bundled synthetic data ingests eight articles (one is detected as a syndicated
duplicate), analyses them, and ranks the impacts on the demo portfolio:

```text
impact 4  Critical  priority 100.00  "US tightens export rules on advanced AI chips to China"
impact 1  High      priority  35.63
impact 2  Medium    priority  18.75
impact 3  Medium    priority  11.10
```

An excerpt from the exported brief (`impactlens export 4 --format md`) for the top item:

```text
Model-extracted event: regulation_policy · direction negative · severity high · confidence 0.87
Impact level: Critical — priority 100.00/100, net direction negative

Ticker  Path                                          Direction  Weight  Component  Counted
NVDA    direct: NVIDIA → held security NVDA           negative   15.00%  -0.489375  yes
AMD     direct: AMD → held security AMD               negative   10.00%  -0.326250  yes
TSM     direct: TSMC → held security TSM              negative    7.00%  -0.182700  yes
ASML    supplier: TSMC → ASML is a supplier of TSMC   negative    8.00%  -0.075168  yes
```

Each row links back to quoted evidence from the article ([E1]–[E5] in the full brief), and the brief also contains
the historical-association section and the scoring and prompt versions used.

## Quickstart

Requires **Python 3.12+**. Everything below runs offline on synthetic data in `data/samples/` with the fixture LLM
provider; no API keys are needed.

```bash
git clone https://github.com/M-Mashreghi/ImpactLens.git
cd ImpactLens

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev,dashboard]"

impactlens demo                    # seed → import demo portfolio → ingest → analyze → score → alert
```

`impactlens demo` creates the database, loads the demo security master and relationships, imports
`data/samples/portfolio_demo.csv`, ingests the sample news, runs the analysis and scoring, and prints the ranked
impact feed.

## Running the services

```bash
uvicorn impactlens.api.main:app --reload          # API      → http://localhost:8000/docs
streamlit run src/impactlens/dashboard/app.py     # Dashboard → http://localhost:8501
python -m impactlens.jobs.run                     # Scheduler / worker (polls news, analyses, scores, alerts)
```

The dashboard talks to the API at `IMPACTLENS_API_URL` (default `http://localhost:8000`).

## Docker

```bash
cp .env.example .env               # optional: the defaults run the offline demo
docker compose up -d --build
docker compose exec impactlens-api impactlens demo
```

| Service | Purpose | Address |
|---|---|---|
| `impactlens-api` | FastAPI app (health-checked via `/ready`) | http://127.0.0.1:8000 |
| `impactlens-dashboard` | Streamlit dashboard | http://127.0.0.1:8501 |
| `impactlens-worker` | Scheduler running the news → impact workflow | n/a |

Data and cache live in named volumes (`impactlens-data`, `impactlens-cache`). Secrets are read from `.env` at runtime
and never baked into the image. Ports are bound to localhost only. See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for
production notes.

## Configuration

All settings come from environment variables (or `.env`). Copy [`.env.example`](.env.example) to `.env` and edit it.
The most important ones:

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `fixture` | `fixture` (offline) or `openai_compatible` |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | placeholders | Needed for a real LLM |
| `NEWS_RSS_FEEDS` | empty | Comma-separated `key\|url` pairs |
| `MARKET_DATA_PROVIDER` | `csv` | `csv` (reads `MARKET_DATA_CSV_DIR`) or `none` |
| `EXPOSURE_DISABLED_FAMILIES` | empty | Any of `sector,industry,country,commodity,macro,relationship` |
| `ALERTS_ENABLED` / `ALERT_CHANNEL` | `false` / `console` | Turn on alerts; `console` or `webhook` |
| `ALERT_MIN_LEVEL` | `High` | Lowest level that triggers an alert |
| `IMPACTLENS_DB_PATH` | `./var/impactlens.db` | SQLite database location |

To use a real model, set `LLM_PROVIDER=openai_compatible` together with `LLM_BASE_URL`, `LLM_MODEL` and
`LLM_API_KEY`. Never commit `.env` or real credentials.

## CLI reference

All commands are available as `impactlens <command>` (or `python -m impactlens <command>`). Run
`impactlens <command> --help` for options.

| Command | What it does |
|---|---|
| `demo` | Offline end-to-end demo on synthetic data |
| `init-db` | Create or migrate the SQLite database |
| `seed` | Load the demo security master and relationships |
| `import-portfolio` | Import a portfolio CSV as a new immutable snapshot |
| `ingest-text` / `ingest-url` | Ingest pasted news text or an explicit article URL |
| `poll` | Poll enabled news sources once |
| `analyze` | Analyse pending news with the configured LLM provider |
| `score` | Score valid analyses against portfolio snapshots |
| `run-once` / `worker` | Run one full workflow cycle, or the scheduler until stopped |
| `event-study` | Run event studies for a news item |
| `calibrate` | Score-bucket calibration report |
| `export` | Export an impact as `json`, `csv` or `md` |
| `eval` | Offline analysis evaluation on the labelled fixture set |
| `backup` / `restore` | Consistent online SQLite backup, and verified restore |
| `health` | Readiness check |

Operational procedures for each are in the [Runbook](docs/RUNBOOK.md).

## REST API

Interactive docs are served at `/docs` when the API is running. Main endpoints:

| Area | Endpoints |
|---|---|
| System | `GET /health`, `GET /ready`, `GET /system/config` |
| Portfolios | `GET /portfolios`, `POST /portfolios/import`, `GET /portfolios/{id}/snapshots`, `GET /portfolio-snapshots/{id}` |
| News | `GET /news`, `POST /news`, `GET /news/{id}` |
| Analyses | `GET /analyses`, `GET /analyses/{id}` |
| Impacts | `GET /impacts`, `POST /impacts/score`, `GET /impacts/{id}`, `GET /impacts/{id}/export` |
| Alerts | `GET /alerts` |
| Research | `POST /research/event-studies`, `GET /research/event-studies`, `GET /research/analogs/{analysis_id}`, `GET /research/calibration` |

## Testing and quality checks

```bash
pytest -q                          # 192 tests: unit, integration and end-to-end, no network
ruff check src tests               # lint
mypy                               # type check
impactlens eval                    # offline LLM-analysis evaluation report
```

Tests use deterministic fakes and fixtures only. Tests that would hit real services are marked `live` and are
excluded in CI with `pytest -m "not live"`. The same checks run in GitHub Actions on every push and pull request
([ci.yml](.github/workflows/ci.yml)).

## Project layout

```text
src/impactlens/
├── app.py · cli.py · config.py   # composition root, CLI, settings
├── ingestion/   news/            # source adapters, normalization, dedup
├── intelligence/                 # LLM adapter, prompt, schema, evidence checks, eval
├── entities/    portfolio/       # security master, resolver, CSV import, snapshots
├── impact/                       # exposure mapping, scoring, explanation
├── market/      research/        # prices, calendar, event studies, analogs, calibration
├── storage/                      # SQLite, migrations, repositories, backup
├── alerts/  export/  jobs/       # alerting, research briefs, scheduler
├── api/         dashboard/       # FastAPI app, Streamlit UI
tests/   unit/ integration/ e2e/ fixtures/
data/samples/                     # synthetic demo data only
```

The full tree is in [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

## Documentation

| Document | Contents |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | Components, data model, design decisions |
| [Diagrams](docs/DIAGRAMS.md) | System and data-flow diagrams |
| [Roadmap](docs/ROADMAP.md) | v1 scope and what comes next |
| [Implementation phases](docs/PHASES.md) | Phase 1–7 overview |
| [Phases and tasks (SSOT)](docs/PROJECT_PHASES_AND_TASKS.md) | Atomic tasks and their Definitions of Done |
| [Task ledger](docs/TASKS.md) | Completion status and verification evidence |
| [Deployment](docs/DEPLOYMENT.md) | Docker and production deployment |
| [Runbook](docs/RUNBOOK.md) | Operations, CLI usage, backup and restore, troubleshooting |

New work starts as a new task in [PROJECT_PHASES_AND_TASKS.md](docs/PROJECT_PHASES_AND_TASKS.md), the
implementation source of truth.

## Non-goals

- Autonomous trading or order execution.
- LLM-generated price targets or expected returns.
- Supplier/customer graphs inferred only from model memory.
- High-frequency event trading.
- Claiming causality from simple post-news price moves.
- Replacing professional investment judgment.

## Disclaimer

ImpactLens is a research and decision-support project. Impact scores are deterministic priority measures, not
expected returns, and nothing it produces is personalized investment advice or a recommendation to trade.
