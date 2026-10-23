# ImpactLens — Claude Code Project Instructions

ImpactLens is a financial-news intelligence platform that maps news events to a user's investment portfolio and produces evidence-backed portfolio-impact assessments.

## Product Objective

The core workflow is:

`News Source → Ingestion → Normalize/Deduplicate → LLM Event Extraction → Entity Linking → Portfolio Exposure Mapping → Deterministic Impact Scoring → Explanation/Citations → Dashboard/Alerts → Historical Validation`

The system must distinguish **what the news says** from **what the code calculates**.

## Source of Truth

Before implementing any task, read:

1. `docs/PROJECT_PHASES_AND_TASKS.md`
2. `docs/ARCHITECTURE.md`
3. `docs/TASKS.md`
4. the relevant phase in `docs/PHASES.md`
5. any referenced contract or diagram

Do not invent requirements that conflict with these documents.

## Task Execution Workflow

For every implementation task:

1. Read the complete task specification and Definition of Done.
2. Inspect the existing repository before editing.
3. Identify the smallest implementation that satisfies the task.
4. Implement only the current task scope.
5. Add/update tests for all critical paths.
6. Run targeted tests, then the relevant regression suite.
7. Fix failures before marking the task complete.
8. Update `docs/TASKS.md` and `docs/PROJECT_PHASES_AND_TASKS.md` only after verification succeeds.
9. Record meaningful architecture/config changes in the appropriate docs.
10. Do not start the next task unless explicitly requested.

## Architecture Boundaries

Maintain explicit separation between:

- news collection/adapters
- document normalization and deduplication
- event/entity extraction
- security/entity resolution
- portfolio ingestion and exposure modeling
- deterministic impact scoring
- market-data/event-study analytics
- persistence
- API
- dashboard/alerting

UI code must not contain core scoring, market-data, parsing, or persistence logic.

External services must be wrapped behind interfaces/adapters so they can be replaced and mocked.

## Financial Integrity

LLMs must NOT perform or fabricate quantitative finance calculations.

LLMs may:

- identify companies, sectors, countries, commodities, and macro factors mentioned in news
- classify the event type
- estimate qualitative direction and severity according to the project schema
- extract evidence spans
- explain why a portfolio holding may be exposed
- summarize validated numerical outputs produced by code

Deterministic Python code must calculate:

- portfolio weights and notional exposure
- direct/indirect exposure contribution
- impact-priority scores
- market returns
- benchmark-adjusted returns
- basis-point changes
- event windows
- historical analog statistics
- calibration metrics

Never label a model-generated score as an expected return unless a validated statistical model explicitly produces that estimate.

## No Look-Ahead Bias

Historical analytics must use only information available at the relevant historical timestamp.

Store and respect:

- news `published_at`
- news `retrieved_at`
- market timezone/session
- portfolio snapshot timestamp
- model/prompt version
- market-data vintage when relevant

Future prices, future articles, revised data unavailable at event time, or future portfolio weights must never leak into historical evaluation.

## Evidence & Provenance

Every analyzed news item must preserve:

- source name
- source URL or source identifier
- original published timestamp when available
- retrieval timestamp
- content hash
- normalized text or bounded extracted text
- analysis model/version
- prompt/schema version

Every material LLM classification must include evidence tied to the source text.

If evidence is insufficient or ambiguous, return an `uncertain` result instead of inventing a conclusion.

## LLM Structured Output

Application-facing LLM output must be schema-validated.

At minimum, a news analysis should contain:

- `event_type`
- `entities`
- `direction`
- `severity`
- `confidence`
- `time_horizon`
- `evidence`
- `rationale`

Entity objects should distinguish canonical entity, ticker/security mapping when known, and entity role.

Never silently accept malformed model output.

## Impact Scoring Rules

Impact scoring must be reproducible and inspectable.

A portfolio-impact result must expose its components, such as:

- position weight/exposure
- relationship type (direct, sector, supplier/customer, country, commodity, macro factor)
- event direction
- severity
- confidence
- relevance/relationship weight
- final deterministic score

Do not bury scoring logic inside prompts.

## Data Safety & Secrets

Never hardcode or commit:

- LLM API keys
- news-provider API keys
- market-data credentials
- database passwords
- alert/webhook tokens

Use environment variables and `.env.example` placeholders.

Do not log secrets or full authorization headers.

Portfolio data may be sensitive. Logs should avoid dumping full portfolios unless explicitly required for local debugging.

## Testing

Every implementation task requires appropriate tests.

Critical test families include:

- news parser/normalizer tests
- deduplication/hash tests
- structured LLM schema tests
- evidence validation tests
- entity/security resolution tests
- portfolio import/weight tests
- impact scoring numerical fixtures
- event-time/session alignment tests
- no-look-ahead tests
- event-study calculation tests
- API tests
- E2E pipeline tests

Do not weaken tests simply to make failing implementation pass unless the test is demonstrably wrong.

## Scope Discipline

- No unrelated refactors.
- No speculative microservices for an MVP.
- No new external dependency unless justified by the current task.
- Prefer standard library or already-approved dependencies where practical.
- Prefer a simple modular monolith before distributed infrastructure.

## Documentation

All repository documentation and code comments should be in English.

When behavior changes, update the corresponding architecture/task/config docs in the same change set.

Mermaid diagrams must remain aligned with the implementation.

## Definition of Complete

Never claim a task is complete unless:

- the implementation exists,
- required tests pass,
- the task DoD is satisfied,
- documentation is synchronized,
- no secrets were introduced,
- finance-integrity rules remain satisfied.
