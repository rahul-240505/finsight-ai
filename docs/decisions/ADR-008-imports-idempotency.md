# ADR-008: All-or-nothing CSV imports with idempotency keys

- Status: Accepted · Date: 2026-11-26

## Context
Analysts upload transaction files of up to hundreds of thousands of rows. Networks fail and clients retry; a retry must never create a second copy of the data. A file with a few bad rows must not leave a half-imported dataset that silently misses transactions.

## Options
- **Partial import** (save valid rows, report the rest) vs **all-or-nothing**.
- **Duplicate protection:** client-supplied `Idempotency-Key` vs content hash only vs both.
- **Insert method:** ORM row inserts vs `INSERT … VALUES` batches vs Postgres `COPY`.

## Decision
- **All-or-nothing.** Every row is validated in memory first; any invalid row → 422 with the first 50 errors (line, column, reason) and nothing saved. `POST /api/v1/datasets/preview` runs the same checks without saving, so the file can be fixed first.
- **Idempotency-Key is required** on import. Stored per user with a SHA-256 fingerprint of method, path, query and body:
  - same key + same request → the saved response is replayed (`Idempotent-Replayed: true`);
  - same key + different request → 422 `idempotency_key_reused`;
  - the key record is inserted in the **same transaction** as the import, so `UNIQUE(user_id, key)` makes a concurrent duplicate wait and then fail; a failed import rolls back and releases the key.
- **Content hash:** `UNIQUE(owner_id, content_hash)` rejects the same file under a new key with 409 and the existing dataset ID.
- **COPY** inside the request's transaction for bulk insert. No transaction is held open while parsing (parse first, then write).
- **Integrity in the database:** composite FK `transactions(dataset_id, owner_id) → datasets(id, owner_id)` guarantees a row's owner always matches its dataset; `UNIQUE(dataset_id, external_ref)`; currency CHECK; money as `NUMERIC(14,2)`.

## Consequences
- Simple mental model: a dataset either exists completely or not at all.
- A large file with one typo is rejected entirely (mitigated by preview).
- The whole file is held in memory during import (100 MB cap, 1M rows cap) and the request is synchronous (≈ 11 s for 500k rows without query indexes, ≈ 21 s with them; see docs/evaluation.md). Moving imports to a background worker is planned.
- Idempotency records are kept indefinitely until a cleanup job exists.

## Revisit when
Files grow beyond memory limits (stream + COPY in a worker), or analysts need partial imports with a quarantine table.
