# ImpactLens — Deployment & CI/CD

Production-minded deployment guide for **ImpactLens — Financial News → Portfolio Impact Engine**.

This document describes the v1 deployment as implemented in Phase 7 (`Dockerfile`, `docker-compose.yml`, `.github/workflows/`).

**Related:** [ARCHITECTURE.md](./ARCHITECTURE.md) · [RUNBOOK.md](./RUNBOOK.md) · [PROJECT_PHASES_AND_TASKS.md](./PROJECT_PHASES_AND_TASKS.md)

---

## 1. Deployment Principles

1. **One codebase, modular monolith.** API, dashboard, and scheduler/worker may run as separate processes from the same image/package.
2. **SQLite is durable state for v1.** Keep it on a persistent volume and back it up.
3. **Caches are replaceable.** Market-data/article caches must not be treated as the sole source of portfolio/news research state.
4. **Secrets are runtime-only.** Never bake API keys into images or commit `.env`.
5. **Private portfolio data stays out of repository fixtures.** Use synthetic/public demo portfolios in CI.
6. **Provider boundaries degrade gracefully.** News/LLM/market outages should not corrupt persisted state.

---

## 2. Target Runtime Topology

```text
Docker Compose / Single Host

impactlens-api
    FastAPI application
        │
        ├── SQLite volume
        └── optional cache volume

impactlens-dashboard
    Streamlit
        │
        └── calls FastAPI / shared application service mode

impactlens-worker
    scheduled ingestion + analysis + scoring
        │
        ├── News providers
        ├── LLM provider
        └── Market-data provider
```

For a minimal local demo, API/dashboard/jobs may run from one process if the implementation task chooses that path. Deployment separation must not force duplicated business logic.

---

## 3. Environment Variables

`.env.example` is the authoritative list (placeholders only). Validation runs at start-up and fails with a
list of every problem, e.g. a missing `LLM_API_KEY` for `LLM_PROVIDER=openai_compatible`, or the offline
`fixture` provider in `IMPACTLENS_ENV=production`.

Recommended groups:

### Application

```text
IMPACTLENS_ENV=development
IMPACTLENS_LOG_LEVEL=INFO
IMPACTLENS_DB_PATH=/app/data/impactlens.db
IMPACTLENS_CACHE_DIR=/app/cache
```

### LLM

```text
LLM_PROVIDER=fixture            # fixture (offline demo) | openai_compatible
LLM_API_KEY=...                 # required for openai_compatible
LLM_BASE_URL=https://api.example.com/v1
LLM_MODEL=...
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=2
```

### News

```text
NEWS_POLL_INTERVAL_SECONDS=900
NEWS_RSS_FEEDS=key|https://example.com/feed.xml,other|https://...
NEWS_DISABLED_SOURCES=
NEWS_HTTP_TIMEOUT_SECONDS=15
NEWS_USER_AGENT=ImpactLens/1.0 (+research; contact: ...)
```

### Market Data

```text
MARKET_DATA_PROVIDER=csv        # csv | none
MARKET_DATA_CSV_DIR=./data/samples/prices
MARKET_DATA_CACHE_MAX_ENTRIES=500
MARKET_DATA_API_KEY=...         # reserved for a future vendor adapter
```

### Alerts

```text
ALERTS_ENABLED=false
ALERT_CHANNEL=console           # console | webhook
ALERT_WEBHOOK_URL=...           # secret; required for webhook
ALERT_MIN_LEVEL=High            # Low | Medium | High | Critical
ALERT_COOLDOWN_SECONDS=3600
EXPOSURE_DISABLED_FAMILIES=     # sector,industry,country,commodity,macro,relationship
IMPACTLENS_API_URL=http://localhost:8000   # dashboard → API
```

Never put real values in `.env.example`.

---

## 4. Local Development

Developer flow:

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
cp .env.example .env
pytest
```

Application commands:

```bash
impactlens demo                                  # offline end-to-end demo on synthetic data
uvicorn impactlens.api.main:app --reload         # API on :8000 (OpenAPI docs at /docs)
streamlit run src/impactlens/dashboard/app.py    # dashboard on :8501 (talks to IMPACTLENS_API_URL)
python -m impactlens.jobs.run                    # scheduler (add --once for a single cycle)
```

### Docker Compose

```bash
cp .env.example .env            # optional; compose starts without it using demo defaults
docker compose up -d --build
docker compose ps               # api becomes healthy once /ready returns 200
docker compose exec impactlens-api impactlens demo
open http://localhost:8501
```

Services: `impactlens-api` (healthcheck on `/ready`), `impactlens-dashboard` (healthcheck on Streamlit
`/_stcore/health`), `impactlens-worker` (scheduler). All share one image, run as the non-root user
`impactlens` (uid 10001), and mount the `impactlens-data` (SQLite, durable) and `impactlens-cache`
(replaceable) volumes. Ports are bound to `127.0.0.1` only; add authentication/reverse proxy before
exposing beyond localhost.

---

## 5. Docker Target

### Image

Use a Python 3.12 slim-style base or equivalent approved image.

Goals:

- reproducible dependency install;
- application runs as non-root where practical;
- no secrets copied into image;
- no private portfolio/demo artifacts baked into image;
- health command/endpoints available.

### Compose Volumes

| Mount | Purpose | Durable? |
|---|---|---|
| `/app/data` | SQLite system of record | Yes |
| `/app/cache` | market/article cache | Optional / replaceable |
| runtime env/secrets | API credentials | Secret, not source-controlled |

A private portfolio uploaded through the app may exist in the database; raw upload staging should be removed after parsing unless a future requirement explicitly retains it.

---

## 6. Health & Readiness

Target probes:

| Probe | Meaning |
|---|---|
| `GET /health` | process alive |
| `GET /ready` | database reachable and core configuration valid |
| optional detailed health | provider/config diagnostics without leaking secrets |

External providers should not necessarily make liveness fail. Readiness policy should distinguish hard dependencies from temporarily degraded optional providers.

---

## 7. CI Quality Pipeline

`.github/workflows/ci.yml` on PR/push (read-only token):

1. checkout;
2. setup supported Python version;
3. install package/dev dependencies;
4. run formatting/lint checks configured by Phase 1;
5. run type checks if configured;
6. run full `pytest` suite;
7. coverage threshold/report if adopted;
8. dependency/security audit;
9. secret/private-data guard (no tracked `.env`, `*.db`, `data/private/`, or API-key-shaped strings);
10. on push to `main`: `docker compose config`, image build and container smoke test (`/ready`, `impactlens demo`, `/impacts`).

A failing required test must block release artifacts.

---

## 8. Release / CD Target

`.github/workflows/release.yml` on a version tag such as `v1.0.0` (the `publish` job `needs: test`, so a
failing test blocks publishing; it never runs on `pull_request`, and only `GITHUB_TOKEN` is used):

- rerun quality gates;
- build container image;
- push to configured registry (e.g. GHCR) if enabled;
- generate GitHub Release notes;
- optional deployment only from protected trusted context.

Do not expose deployment credentials to fork/untrusted PR contexts.

---

## 9. Database Backup

The SQLite database contains the reproducible research state:

- portfolio snapshots/positions;
- security master/relationships;
- news/provenance;
- analyses and versions;
- impact score components;
- alerts;
- event-study result metadata.

`impactlens backup` uses the SQLite online backup API and verifies the copy with `PRAGMA integrity_check`;
`impactlens restore` verifies the backup, preserves any existing DB as `*.pre-restore-<ts>`, and re-checks
the restored file. See RUNBOOK §0/§13.

Back up the database, not transient caches.

### Backup Acceptance Criteria

- backup file opens with integrity check;
- clean deployment can restore it;
- restored API can load at least one portfolio/news/impact record;
- backup never includes environment secrets unless explicitly encrypted and documented.

---

## 10. Data/Secret Handling

### Never commit

- `.env`
- LLM/news/market API keys
- webhook tokens
- private portfolio CSV files
- private database dumps

### Safe to commit

- `.env.example` with placeholders
- synthetic sample portfolios
- public news fixture snippets within copyright/testing limits
- deterministic fabricated fixtures
- schema and migrations

Logs must not print complete credentials or authentication headers.

---

## 11. Provider Failure Strategy

### News Provider

- fail one source independently;
- record structured provider error;
- do not mark previously stored news corrupt;
- continue other enabled sources.

### LLM Provider

- bounded retry on transient errors;
- malformed schema → retry/fallback/uncertain according to policy;
- do not score unvalidated confident analysis.

### Market Data Provider

- cached historical results may remain readable;
- new event-study requests can surface degraded/unavailable state;
- no fabricated price data.

---

## 12. Deployment Checklist

Before a tagged production/demo release:

- [ ] required CI checks green;
- [ ] no secrets/private portfolio data in git history/change set;
- [ ] `.env.example` current;
- [ ] database migration path tested;
- [ ] Docker image builds;
- [ ] `/health` and `/ready` pass;
- [ ] sample fixture pipeline works;
- [ ] backup/restore procedure has been verified for the current schema;
- [ ] RUNBOOK matches the actual commands;
- [ ] user-facing disclaimer remains present.

---

## 13. Troubleshooting Matrix

| Symptom | First checks |
|---|---|
| API fails to start | env/config validation; DB path permissions; migration error |
| Dashboard empty | API URL/config; active portfolio snapshot; impacts present |
| No new news | source enabled; provider/network errors; polling job state |
| LLM analysis stuck/failed | provider credentials/rate limit; schema errors; prompt version |
| No affected positions | entity resolution; target snapshot; direct/indirect rule config |
| Event study missing | timestamp quality; security mapping; market data/window availability |
| Alert spam | canonical duplicate linkage; idempotency key; cooldown policy |
| DB locked | concurrent writer/job pattern; long transaction investigation |

---

## Change Log

| Date | Change |
|---|---|
| 2026-10-13 | Initial ImpactLens deployment/CI contract created. |
| 2026-10-13 | Implemented: Dockerfile, docker-compose.yml, CI/release workflows, env reference, backup/restore. |
