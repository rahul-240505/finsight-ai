# FinSight AI

A local financial-risk investigation demo. An analyst imports transaction CSVs, sees summaries, gets unusual transactions scored by ML for human review, asks cited questions over policy PDFs (RAG), and has a constrained agent draft an investigation report that a human approves.

Synthetic and public data only. This is **not** a fraud detection system: it flags unusual activity for review.

## Status

Phase 0 (foundation) in progress. Nothing is claimed as working until tests show it.

| Phase | Focus | Status |
| --- | --- | --- |
| 0 | Foundation: Compose, `/health` + `/ready`, config, tests, CI | In progress |
| 1–7 | Auth, data + SQL, ML, RAG, async jobs, agent, finish | Not started |

## Measured results

None yet. Every number here will come from `docs/evaluation.md`.

## Docs

- `docs/BLUEPRINT.md` — original design
- `docs/STUDY_GUIDE.md` — phase-by-phase guide
- `docs/decisions/` — architecture decision records
