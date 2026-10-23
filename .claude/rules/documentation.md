# Documentation Rules

All project documentation is written in English.

## Required Synchronization

When a task changes behavior, update as applicable:

- `docs/PROJECT_PHASES_AND_TASKS.md`
- `docs/TASKS.md`
- `docs/ARCHITECTURE.md`
- `docs/DIAGRAMS.md`
- `docs/ROADMAP.md`
- `docs/DEPLOYMENT.md`
- `docs/RUNBOOK.md`
- root `README.md`

## Task Completion

Do not mark a task `[x]` until implementation and verification are complete.

Verification notes should state what tests were run and what behavior was proven.

## Diagrams

Prefer Mermaid so diagrams remain reviewable in GitHub.

Update diagrams whenever pipeline stages, states, or major service boundaries change.

## Configuration

Document environment variables and defaults without committing secrets.
