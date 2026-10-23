# ImpactLens — Repository Structure (v1)

```text
impactlens/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/   # ci.yml, release.yml
├── scripts/             # generate_sample_prices.py
├── .claude/
│   └── rules/
│       ├── architecture.md
│       ├── finance-integrity.md
│       ├── llm-analysis.md
│       ├── testing.md
│       └── documentation.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   ├── PHASES.md
│   ├── PROJECT_PHASES_AND_TASKS.md
│   ├── TASKS.md
│   ├── DIAGRAMS.md
│   ├── DEPLOYMENT.md
│   └── RUNBOOK.md
├── src/impactlens/
│   ├── app.py           # composition root (Container)
│   ├── cli.py           # `impactlens` command
│   ├── config.py · logging_setup.py · health.py · timeutil.py
│   ├── ingestion/
│   ├── news/
│   ├── intelligence/
│   ├── entities/
│   ├── portfolio/
│   ├── impact/
│   ├── market/
│   ├── research/
│   ├── storage/         # db.py, repositories.py, backup.py, migrations/
│   ├── alerts/
│   ├── export/
│   ├── jobs/
│   ├── api/
│   └── dashboard/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
└── data/
    └── samples/         # securities, relationships, factor exposures, demo portfolio,
                         # news n01–n08, fixture LLM analyses, synthetic prices, eval set
```

`data/samples/` must contain only synthetic/public demo data. Never commit a private real portfolio.
