# ADR-004: Background jobs with RQ, job state in Postgres

- Status: Accepted · Date: 2026-11-26

## Context
CSV import (500k rows ≈ 20 s), risk scoring (≈ 21 s) and PDF indexing (parsing untrusted files, calling the embedding model) ran inside the HTTP request. A request that long ties up a server thread, times out behind proxies and browsers, and gives a parser bug no time limit. A retry by an impatient client could start the same work twice.

## Options
1. **Keep it synchronous**, raise timeouts. Simple; none of the problems above go away.
2. **FastAPI `BackgroundTasks`.** Runs in the API process after the response: no isolation, no retries, lost on restart.
3. **Celery.** Mature, many features (chords, beat, many brokers); heavy for three job kinds.
4. **RQ on Redis.** Small, synchronous Python, a fork per job (crash and timeout isolation), retries with delays; Redis is already in the stack.
5. **A Postgres queue (`SELECT … FOR UPDATE SKIP LOCKED`).** No extra service; we would write the worker loop, timeouts and scheduling ourselves.

## Decision
- **RQ** delivers job ids; **Postgres `jobs` is the source of truth** (kind, status, attempts, result, safe error, timestamps). Losing Redis loses no job.
- Slow endpoints return **202 + `Location: /api/v1/jobs/{id}`**; clients poll `GET /api/v1/jobs/{id}`.
- The job row is committed *before* enqueueing. If enqueueing fails the job stays `queued`; the worker's start-up sweep and `python -m app.cli requeue` re-deliver queued jobs older than 60 s and `running` jobs older than `JOB_STALE_AFTER_SECONDS`.
- **At-least-once delivery, idempotent handlers.** A worker claims a job with one conditional `UPDATE … WHERE status = 'queued' OR (running AND stale) RETURNING`, so two deliveries can't both run it. Import checks the content hash first, scoring replaces its rows in one transaction, indexing is idempotent by content hash.
- **Deduplication:** a partial unique index `(owner_id, kind, dedupe_key) WHERE status IN ('queued','running')` makes a second identical request join the job in progress (content hash for uploads, dataset id for scoring).
- **Errors:** transient (model, vector store or database unreachable) → back to `queued`, retried up to 3 attempts (RQ `Retry`, 5 s then 30 s); job timeout → `failed/job_timeout`; validation errors → `failed` with the error's code and details; anything else → `failed/internal_error` (details only in logs).
- **Time limits** per kind: import and scoring 900 s, PDF indexing 300 s (also bounds a hostile PDF).
- Uploads wait in `UPLOAD_DIR` (git-ignored, mode 0700/0600), named by job id, deleted when the job ends.
- The worker disposes the parent's database pool before forking and preloads the handler modules.

## Consequences
- Accepting a 500k-row import takes 0.13 s instead of 20.5 s; `/health` stays at ~2 ms while it runs (docs/evaluation.md).
- A killed worker's job is recovered after the stale limit and runs again without duplicate rows (verified live).
- Clients must poll. A job's total time is slightly higher than the synchronous call (fork, polling interval).
- Re-scoring deletes and re-inserts 500k rows, leaving dead tuples until autovacuum runs; measured scoring time rose from ~22 s to ~31 s before a VACUUM.

## Revisit when
Jobs need fan-out or chaining (Celery or a workflow engine), progress reporting matters (store progress on the job row, or push via SSE), or Redis must be removed (Postgres queue).
