# Testing Rules

## General

Every task must add the smallest meaningful test coverage needed to prove its Definition of Done.

Tests should be deterministic and should not depend on live APIs by default.

## Required Test Areas

- news metadata parsing
- canonical text normalization
- hashing and duplicate detection
- provider adapter contract behavior
- malformed/partial LLM output
- schema validation
- missing or invalid evidence
- entity/security matching
- ambiguous ticker handling
- portfolio CSV validation
- portfolio weight/notional calculations
- direct and indirect exposure mapping
- impact score fixture calculations
- event-time/session alignment
- market-data gaps/non-trading days
- no-look-ahead guards
- event-study arithmetic
- API validation/error paths
- E2E news → portfolio impact flow

## LLM Tests

Mock the provider. Test the application's handling of:

- valid structured output
- malformed JSON
- missing evidence
- out-of-range scores
- unknown event types
- provider timeout/rate limit
- explicit uncertain result

Do not assert exact prose wording.

## Numerical Tests

Use hand-computable fixtures and explicit tolerances.

A change to scoring equations must update tests and documentation together.

## Completion Gate

A task cannot be marked completed while required tests fail or required regression tests are skipped without a documented reason.
