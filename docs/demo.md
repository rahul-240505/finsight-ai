# Demo walkthrough

A five-minute tour of FinSight AI on a laptop. Start the data stores, API, worker and web UI as in the [README quick start](../README.md#quick-start), and pull both Ollama models.

## Before the demo
1. Generate and import the synthetic dataset, and train and activate the risk model (README, "Load sample data" and "Train and activate").
2. Create a second account with the `admin` role to act as the reviewer:
   `uv run python -m app.cli create-user reviewer@example.com --role admin`.
3. Keep one of the fictional policy PDFs ready to upload (`eval/run_rag_eval.py` builds them in `data/policies/`).

## Script
| # | Screen | What to do | What to point out |
| --- | --- | --- | --- |
| 1 | Sign in | Try a wrong password, then the right one | Same message for wrong email or password; the error shows a request id that matches the server log line |
| 2 | Datasets | Show the 500,000-row dataset; press **Score risk** | Scoring runs in the background worker; the page polls the job |
| 3 | Transactions | Filter by category, page through with **Older →** | Keyset pagination: deep pages stay fast; per-currency totals are computed in SQL |
| 4 | Transactions → Flagged | Open the review queue | Highest risk first, each with plain-language reasons; the banner says these are flags for review, not fraud findings |
| 5 | Policy Q&A | Upload a policy PDF; ask a question it answers | Answer cites file and page; the excerpt is the passage the model was given |
| 6 | Policy Q&A | Ask something unrelated | "Not enough evidence", answered without calling the model |
| 7 | Investigations | Start one with a focus such as "bursts of many quick transactions on one account" | Takes about a minute on a laptop GPU; the agent can only read this user's dataset and only writes a draft |
| 8 | Report | Read findings, policy reference, audit trail; press **Submit for review** | Amounts and scores come from the database, not the model; every tool call is in the audit trail |
| 9 | Report (as reviewer) | Sign in as the admin; approve with a note | The owner cannot approve their own report: enforced in the service and by a database constraint |
| 10 | Terminal | `grep <request id>` in the API log | One JSON line per request with route, status, duration and user id; no passwords, tokens or document text |

## If something goes wrong
- **Jobs stay `queued`:** the worker is not running; start it and it re-delivers queued jobs.
- **Answers fail with 503:** Ollama is not running or the models are not pulled.
- **`/ready` is 503:** one of PostgreSQL, Redis or Qdrant is down; `docker compose ... up -d`.
