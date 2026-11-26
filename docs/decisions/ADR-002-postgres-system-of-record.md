# ADR-002: PostgreSQL as the system of record; Qdrant for vectors only

- Status: Accepted · Date: 2026-11-26

## Context
The platform stores users, sessions, datasets, transactions, scores, documents, jobs and reports, and later needs vector search over document chunks. Data must be consistent under concurrent requests and safe to migrate.

## Options
1. **PostgreSQL only** (with pgvector for embeddings). One store, but vector search competes with transactional load and filtered ANN search is less mature.
2. **PostgreSQL + Qdrant.** Relational data and all authorization-relevant state in Postgres; Qdrant holds embeddings with payload filters (owner, document, page, version).
3. **Document store** for everything. Weak constraints and joins for transactional data.

## Decision
Option 2. Postgres is the source of truth: ownership, document metadata and chunk text live there; Qdrant stores only vectors plus the payload needed to filter and cite. If they disagree, Postgres wins and Qdrant is rebuilt from it.
- Access via SQLAlchemy 2.0 (typed `Mapped[]` models), psycopg 3, Alembic migrations with a fixed constraint naming convention.
- UUID primary keys for public resources; `timestamptz` everywhere; money as `NUMERIC(14,2)`.

## Consequences
- Two stores to keep in sync on upload, re-upload and delete (handled in the document pipeline).
- Integrity rules (UNIQUE, FK, CHECK) are enforced by the database, not only in code.

## Revisit when
Vector volume is small enough that pgvector alone is simpler, or Qdrant's filtering no longer meets isolation needs.
