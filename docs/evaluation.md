# Evaluation log

Append-only. One entry per measurement (template: CLAUDE.md §12). Mark superseded entries instead of deleting them. Only numbers from commands we actually ran.

### 2026-11-24 · Phase 0 test suite and CI
- Phase: 0 · Commit: pre-history (history reset 2026-11-24; re-run after Rahul's first commit)
- Dataset: none (no data yet)
- Machine: i5-12500H, 15 GiB RAM, RTX 4050 6 GB (local) · GitHub-hosted `ubuntu-latest` (CI) · Data stores: local Docker / CI service containers
- Command: `cd backend && uv run pytest` (local) · GitHub Actions run 45271304202 (CI)
- Result: 8 tests passed locally (7 unit + 1 integration against real Postgres/Redis/Qdrant). CI job `backend` succeeded; wall time 24 s including container start-up (single run).
- Notes: one third-party warning (Starlette suggests `httpx2` for TestClient); not from our code.

### 2026-11-24 · /ready behaviour with a stopped dependency
- Phase: 0 · Commit: pre-history (same code as the Phase 0 commit Rahul will make)
- Dataset: none
- Machine: local (as above) · Data stores: local Docker
- Command: `docker stop finsight-redis-1` then `curl localhost:8000/ready`; `docker start` then `curl` again
- Result: Redis stopped → HTTP 503, `{"redis":"down"}`, response in 0.047 s (connection refused, single run). Redis restarted → HTTP 200, all `ok`, no app restart. Log line contained only `redis (ConnectionError)`.
- Notes: a hanging (not refusing) dependency would take up to `READY_TIMEOUT_SECONDS` (2 s); not measured yet.
