# ImpactLens Architecture Rules

## Core Pipeline

`Source → Collector → Normalizer/Deduplicator → Event Analyzer → Entity Resolver → Exposure Engine → Impact Scorer → Explanation → API/Dashboard`

Historical research extends the pipeline with:

`Impact Event → Market Data → Session Alignment → Event Study → Historical Analogs → Evaluation`

## Module Boundaries

Recommended modules:

- `ingestion` — provider adapters, RSS/HTTP/manual ingestion
- `news` — normalization, metadata, hashing, deduplication
- `intelligence` — LLM schemas, prompts, event extraction, evidence validation
- `entities` — canonical company/security/sector/country/factor resolution
- `portfolio` — holdings, snapshots, exposure relationships
- `impact` — deterministic scoring and explanation inputs
- `market` — price/yield data and trading-session alignment
- `research` — event studies, analogs, calibration/evaluation
- `storage` — database repositories and migrations
- `api` — FastAPI endpoints
- `dashboard` — Streamlit presentation only
- `jobs` — scheduled ingestion/analysis orchestration

## Dependency Direction

Domain/application logic must not depend on Streamlit, FastAPI route objects, or vendor-specific SDKs.

Vendor APIs are adapters behind stable contracts.

The dashboard may call application services/API but must not reproduce business rules.

## Persistence

SQLite is the MVP default. Repositories hide persistence details from core logic.

Persist source provenance, portfolio snapshots, analysis versions, impact components, and audit records needed for reproducibility.

## Simplicity

Use a modular monolith for v1. Do not introduce Kafka, Kubernetes, distributed queues, vector databases, or microservices unless a documented requirement justifies them.
