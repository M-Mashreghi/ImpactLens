# Financial Research & Portfolio Integrity

## Core Principle

ImpactLens is an analysis and prioritization system, not a system that invents price targets from language-model intuition.

## Deterministic Quantitative Calculations

Python code, not the LLM, must calculate:

- portfolio weights
- position notionals
- exposure contributions
- impact-priority score arithmetic
- returns and log returns
- benchmark-adjusted returns
- cumulative abnormal returns
- yield/basis-point changes
- volatility/statistical summaries
- event-study windows and historical analog statistics

LLMs may explain these calculated values after they exist.

## No Look-Ahead Bias

Historical evaluation must respect point-in-time availability.

Do not use:

- news published after the event cutoff
- closing prices not yet observable at decision time
- portfolio snapshots from the future
- future analyst estimates
- revised economic data unavailable at the historical timestamp
- future entity relationships when reconstructing old events unless explicitly labeled as retrospective

## Portfolio Snapshot Integrity

Every analysis should identify the portfolio snapshot used.

If holdings are changed, historical analyses must continue to reference the original snapshot unless intentionally rerun as a counterfactual.

## Impact Score Semantics

The default impact score is a **priority/relevance score**, not a forecast return.

The score may combine deterministic components such as:

`Exposure × Relevance × Event Severity × Direction × Confidence × Relationship Weight`

All components and scaling rules must be documented and testable.

## Direct vs Indirect Exposure

Always label exposure type.

Examples:

- Direct holding
- Sector/industry peer
- Supplier/customer relationship
- Country/geographic exposure
- Commodity exposure
- Interest-rate/macro factor exposure

Indirect relationships must not be presented as facts unless supported by stored relationship data or a cited source.

## Historical Event Studies

Event studies must explicitly define:

- event timestamp
- relevant exchange/session timezone
- benchmark
- estimation/event window if applicable
- same-day after-close handling
- missing/non-trading-day behavior

Results must be reproducible from stored configuration.

## Claims

Never call a relationship "causal" based only on contemporaneous returns.

Use language such as association, market reaction, historical analogue, or observed post-event return unless a causal design has been implemented.
