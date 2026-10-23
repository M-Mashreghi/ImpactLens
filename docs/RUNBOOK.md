# ImpactLens Operational Runbook

Operational incident and maintenance procedures for **ImpactLens — Financial News → Portfolio Impact Engine**.

This runbook describes the operational response model. Commands and endpoints below match the v1 implementation (see §0).

**Companion docs:** [DEPLOYMENT.md](./DEPLOYMENT.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [TASKS.md](./TASKS.md)

---

## 0. Command Reference (v1)

| Purpose | Local | Docker Compose |
|---|---|---|
| Liveness / readiness | `curl -fsS http://localhost:8000/health` · `curl -fsS http://localhost:8000/ready` | same (API bound to 127.0.0.1:8000) |
| CLI readiness check | `impactlens health` | `docker compose exec impactlens-api impactlens health` |
| Create/migrate DB | `impactlens init-db` | automatic on API start |
| Load demo security master | `impactlens seed` | `docker compose exec impactlens-api impactlens seed` |
| Offline end-to-end demo | `impactlens demo` | `docker compose exec impactlens-api impactlens demo` |
| One workflow cycle | `impactlens run-once` | `docker compose exec impactlens-worker impactlens run-once` |
| Scheduler | `python -m impactlens.jobs.run` | `impactlens-worker` service |
| Poll / analyze / score separately | `impactlens poll` · `impactlens analyze` · `impactlens score [--force]` | `docker compose exec impactlens-worker impactlens …` |
| Manual news | `impactlens ingest-text --title T --file article.txt` · `impactlens ingest-url URL` | API `POST /news` |
| Event study | `impactlens event-study NEWS_ID [--as-of ISO]` | API `POST /research/event-studies` |
| Calibration report | `impactlens calibrate` | API `GET /research/calibration` |
| Export | `impactlens export IMPACT_ID --format md|json|csv` | API `GET /impacts/{id}/export` |
| Offline LLM eval | `impactlens eval` | — |
| Backup | `impactlens backup --dir ./backups --keep 14` | `docker compose exec impactlens-api impactlens backup --dir /app/backups` |
| Restore | `impactlens restore BACKUP.db --force` (stop writers first) | stop api/worker, then `docker compose run --rm impactlens-api impactlens restore /app/backups/FILE.db --force` |
| Clear market cache | delete `$IMPACTLENS_CACHE_DIR/market/` (replaceable) | `docker volume rm impactlens_impactlens-cache` |

Useful SQL (read-only) for diagnosis: `news_status_history`, `ingestion_failures`, `job_runs`, `alerts`.

---

## 1. Operator Architecture Summary

| Component | Role | Durable state |
|---|---|---|
| FastAPI | portfolio/news/impact/research API | no separate authoritative state |
| Streamlit | operator/research UI | none |
| Worker/Scheduler | news polling, analysis, scoring, alerts | job metadata/state as implemented |
| SQLite | portfolios, securities, news, analyses, impacts, alerts, research metadata | yes |
| Cache | market/article retrieval cache | replaceable |
| External news sources | incoming financial news | external |
| LLM provider | structured event intelligence | external |
| Market-data provider | historical prices/yields | external |

---

## 2. Health Diagnostics

Start with:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

For Docker:

```bash
docker compose ps
docker compose logs --tail 200 impactlens-api
docker compose logs --tail 200 impactlens-worker
```

Logs are JSON lines on stderr. Filter by `correlation_id` (also returned as the `x-correlation-id`
response header), `news_id`, `snapshot_id`, `analysis_id` or `stage` (`ingestion`, `analysis`, `impact`,
`workflow`, `api`). `/ready` returns 503 when the database or configuration is not usable; job failures
show as `checks.jobs.degraded` without failing readiness.

---

## 3. No New News Appearing

**Symptoms**

- impact feed is stale;
- provider poll timestamps stop moving;
- worker logs show fetch errors.

**Procedure**

1. Confirm worker/scheduler is running.
2. Confirm source is enabled in configuration.
3. Inspect provider-specific errors/rate limits/timeouts.
4. Run the provider adapter against a known fixture to separate code failure from external outage.
5. Confirm checkpoint/cursor is not corrupt or incorrectly advanced.
6. Do not delete canonical news records as a first response.
7. If one provider is down, keep other sources running.

**Recovery validation**

- next poll succeeds;
- a genuinely new fixture/item reaches `PendingAnalysis`;
- repeated old items remain deduplicated.

---

## 4. Duplicate News / Alert Storm

**Symptoms**

- the same story appears many times;
- repeated LLM cost for syndications;
- multiple alerts for one canonical event.

**Procedure**

1. Compare `content_hash`, canonical URL, source item id, and canonical news linkage.
2. Verify text normalization has not changed unexpectedly.
3. Confirm ingestion reruns are idempotent.
4. Check alert idempotency key includes canonical news id + portfolio snapshot/scoring version + channel as designed.
5. Temporarily raise/disable alerts if necessary; do not disable dedup tests.
6. Fix normalization/dedup logic and replay only a bounded fixture/candidate set.

**Do not** merge distinct stories merely because titles are similar without a validated near-duplicate policy.

---

## 5. LLM Structured Output Failures

**Symptoms**

- malformed JSON/schema failures;
- out-of-range severity/confidence;
- frequent `Uncertain` items;
- provider 429/5xx.

**Procedure**

1. Identify model, prompt version, and schema version from logs/record.
2. Check provider availability and credentials without printing the key.
3. Inspect sanitized raw structured response if retention policy allows.
4. Confirm prompt and schema still agree.
5. Run local fake/fixture tests for the same expected shape.
6. For malformed output, apply only the documented bounded retry/fallback policy.
7. Do **not** bypass validation to keep pipeline moving.
8. If model quality degraded after model change, rollback model/prompt version or route uncertain until evaluation is rerun.

---

## 6. Evidence Validation Failures

**Symptoms**

- model output mentions claims not found in article;
- evidence spans fail matching;
- impact results lack citations.

**Procedure**

1. Inspect normalized input text and evidence-normalization rules.
2. Confirm the correct article body was fetched rather than cookie/landing-page text.
3. Confirm evidence matching tolerates approved whitespace/quote normalization but not semantic fabrication.
4. Route unsupported analyses to `Uncertain`.
5. Never manually force a confident impact score from unsupported model claims unless a future explicit human-review feature records that override.

---

## 7. Entity/Ticker Resolution Problems

**Symptoms**

- wrong ticker assigned;
- company unresolved;
- ambiguous ticker blocks direct exposure;
- held company not detected.

**Procedure**

1. Inspect LLM entity name/role proposal separately from resolver result.
2. Search security-master aliases/canonical name.
3. Check exchange/country disambiguation metadata.
4. Add/correct a verified alias in security master if appropriate.
5. Do not hardcode a model-proposed ticker as a shortcut.
6. Re-run resolution and downstream impact for affected records using an explicit force/recompute path if implemented.

**Validation**

- known alias fixture resolves;
- ambiguous fixture remains ambiguous;
- downstream impact identifies the intended security id.

---

## 8. Portfolio Import / Snapshot Issues

**Symptoms**

- CSV rejected;
- weights do not sum as expected;
- duplicate positions;
- impacts reference wrong/current holdings.

**Procedure**

1. Validate CSV against documented sample headers/types.
2. Check currency/notional/weight semantics.
3. Review duplicate-security policy.
4. Confirm a new import creates a new snapshot rather than mutating the old snapshot.
5. Historical impacts must continue referencing their original snapshot id.
6. If a portfolio was imported incorrectly, create a corrected snapshot; do not silently rewrite research history.

---

## 9. Impact Score Looks Wrong

**Symptoms**

- small position dominates unexpectedly;
- direction seems reversed;
- indirect match overpowers direct exposure;
- same input gives different score.

**Procedure**

1. Identify scoring version.
2. Inspect component decomposition:
   - exposure magnitude;
   - relationship weight;
   - event severity;
   - confidence;
   - relevance;
   - direction.
3. Confirm position/snapshot data.
4. Confirm relationship type/provenance.
5. Run the same inputs through the hand-computable scoring fixture/tests.
6. If score formula changes, create a new scoring version; do not silently mutate historical meanings.

**Critical:** do not ask the LLM to “fix” the numerical score.

---

## 10. Unsupported Indirect Exposure

**Symptoms**

- article about Company A flags unrelated held Company B;
- supplier/customer relationship appears without provenance.

**Procedure**

1. Inspect the `ExposureMatch.relationship_type`.
2. Inspect relationship/rule provenance.
3. If provenance is missing, disable/remove the match and treat it as a bug.
4. Verify sector/country/macro mappings are sufficiently specific for the configured rule.
5. Add a regression fixture before fixing logic.

LLM memory alone is never acceptable relationship provenance.

---

## 11. Historical Event Study Looks Incorrect

**Symptoms**

- reaction window starts on wrong day;
- weekend/after-hours event misaligned;
- future data appears in features;
- returns disagree with manual check.

**Procedure**

1. Inspect original `published_at` and timestamp-quality field.
2. Inspect exchange timezone/calendar and alignment result.
3. Verify pre-open/in-session/after-close policy.
4. Check price data source and missing-data behavior.
5. Recompute security and benchmark returns from the stored window manually/fixture script.
6. Run no-look-ahead guard tests.
7. Confirm portfolio snapshot/event features are valid at historical cutoff.
8. Do not describe simple post-event reaction as causal effect.

---

## 12. Market Data Provider Outage

**Symptoms**

- event-study requests fail;
- price downloads time out/429;
- cache misses increase.

**Procedure**

1. Confirm provider status/credentials/rate limits.
2. Serve existing stored impact analyses without fabricated historical results.
3. Use cached eligible market data if valid and provenance is preserved.
4. Mark new historical research as unavailable/degraded rather than substituting fake prices.
5. Retry according to bounded provider policy.

---

## 13. SQLite Lock / Corruption / Missing DB

### Lock symptoms

- `database is locked` errors;
- jobs/API repeatedly fail writes.

Actions:

1. inspect long-running transactions and concurrent writer pattern;
2. stop repeated tight retry loops;
3. ensure repository transactions are short;
4. restart only after preserving logs and confirming no migration process is in progress.

### Corruption/missing DB

1. stop all writers (`docker compose stop impactlens-api impactlens-worker`);
2. locate newest verified backup (`ls -t backups/impactlens-*.db | head -1`);
3. preserve the broken DB for diagnosis (`impactlens restore --force` moves it to `*.pre-restore-<ts>`);
4. restore backup to the configured DB path: `impactlens restore backups/impactlens-<ts>.db --force`;
5. the restore runs `PRAGMA integrity_check` on the backup and on the restored file;
6. start application;
7. verify `/ready` (or `impactlens health`);
8. spot-check a portfolio snapshot (`GET /portfolio-snapshots/{id}`), a canonical news record (`GET /news/{id}`) and an impact (`GET /impacts`).

Do not restore cache files as a substitute for the database.

---

## 14. Backup Verification

`impactlens backup` uses the SQLite online-backup API (safe while running), runs an integrity check on the
result and keeps the newest `--keep` files. The automated drill is
`tests/integration/test_phase7_ops.py::test_backup_restores_into_clean_instance`.

Routine verification should prove:

1. backup completes without blocking/invalidating DB;
2. integrity check is OK;
3. retention behaves as configured;
4. restore into a clean test directory succeeds;
5. restored app can read core entities;
6. backup does not contain `.env` or provider secrets unless a separately documented encrypted secret-backup process exists.

---

## 15. Secret Exposure Incident

If a provider key appears in logs/git/output:

1. revoke/rotate the exposed key at the provider;
2. stop publishing logs/artifacts containing it;
3. remove it from current configuration/history as appropriate;
4. add/update redaction regression test;
5. audit other secrets that used the same mechanism;
6. document incident without copying the secret into tickets/docs.

---

## 16. Private Portfolio Exposure Incident

If a real user portfolio is accidentally committed/shared:

1. stop distribution of the artifact;
2. remove the file from current branch and, if required, repository history using approved procedures;
3. rotate any linked identifiers/credentials if the file contained them;
4. replace test fixture with synthetic data;
5. audit logs/exports/backups for the same portfolio;
6. document and strengthen fixture/logging safeguards.

---

## 17. Release Smoke Checklist

After deploy:

- [ ] `/health` healthy;
- [ ] `/ready` healthy;
- [ ] sample portfolio snapshot visible;
- [ ] fixture/manual news can ingest;
- [ ] duplicate fixture suppresses repeat analysis;
- [ ] fake/live-approved LLM path returns schema-valid analysis;
- [ ] direct exposure fixture scores correctly;
- [ ] dashboard impact feed loads;
- [ ] historical fixture reproduces if market provider enabled;
- [ ] alerts do not duplicate;
- [ ] logs contain no secrets/private raw portfolio dump.

---

## Change Log

| Date | Change |
|---|---|
| 2026-10-13 | Initial ImpactLens operational runbook created. |
| 2026-10-13 | Synchronized with v1 implementation: command reference, health/log fields, backup/restore commands. |
