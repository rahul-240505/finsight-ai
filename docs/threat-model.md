# Threat model

STRIDE per entry point. Updated as features ship. Scope: local, single-machine deployment.

## Assets
User credentials and sessions · transaction datasets · policy documents · scores and reports.

## Trust boundaries
Browser ↔ API (HTTP) · API ↔ PostgreSQL / Redis / Qdrant (localhost only) · API ↔ Ollama (localhost).

## Entry points

### `POST /api/v1/auth/register`, `POST /api/v1/auth/login`
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **S**poofing: password guessing | Argon2id hashing; 12–128 character passwords; login limited to 10 attempts / 5 min per email and 30 / min per client IP (429 + Retry-After) | Limits fail open while Redis is down |
| **I**nfo disclosure: account enumeration via login | Same message and one Argon2 verify for unknown emails and wrong passwords | Registration returns 409 for an existing email |
| **I**nfo disclosure: credentials in responses/logs | Validation errors never echo input values; password hash never serialised | — |
| **D**oS: huge passwords | 128-character cap before hashing; login rate limits | — |

### Session cookie (all authenticated routes)
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **S**poofing: stolen token | 256-bit random token; only its SHA-256 stored; HttpOnly + Secure; 12 h expiry; logout deletes the session | No device/IP binding |
| **T**ampering: CSRF | SameSite=Lax + Origin allow-list on unsafe methods | Requests without Origin are allowed (non-browser clients) |
| **E**levation: role change not applied | Role changes delete the user's sessions | — |

### `/api/v1/datasets*`
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **I**nfo disclosure / **T**ampering: IDOR | Owner filter in every query; foreign and missing IDs both 404; cross-user tests | — |
| **E**levation: viewer writes | `require_permission` on every route; route-inventory test for 401 | — |

### `POST /api/v1/datasets`, `POST /api/v1/datasets/preview` (CSV upload)
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **D**oS: huge or endless upload | 100 MB cap enforced while streaming (and on Content-Length); 1M row cap; `text/csv` only; 20 uploads / min per user; parsing runs in the worker with a 900 s limit | Upload bodies are buffered in API memory before being written to disk |
| **T**ampering: malformed or hostile data | Every row validated (types, ranges, ISO currency, timezone-aware dates, lengths, control characters); all-or-nothing; DB CHECK/UNIQUE/composite FK as a second layer | Values starting with `=`, `+`, `-`, `@` are stored as-is; they must be escaped if CSV export is added |
| **T**ampering: duplicate import on retry | Required Idempotency-Key (stored with request fingerprint, same transaction); per-owner file hash | Idempotency records are never expired yet |
| **I**nfo disclosure: other users' transactions | Owner filter in every transaction and analytics query; composite FK keeps row owner = dataset owner | — |

### `/api/v1/risk-assessments*`, `/api/v1/transactions/{id}/risk`
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **T**ampering / **E**levation: malicious model file (joblib = pickle, runs code on load) | Loaded only if the path stays inside `MODEL_DIR` and its SHA-256 matches `model_versions`; model files are created only by the training script | Anyone who can write both the file and the database row can still swap a model |
| **I**nfo disclosure: other users' scores | Owner filter on every query; scoring requires owning the dataset (404 otherwise) | — |
| **D**oS: scoring large datasets | Requires `dataset:write`; one dataset per request; 10 / min per user; runs in the worker (900 s limit); a dataset already being scored joins that job | — |
| Misuse: score treated as a fraud verdict | Wording is "unusual / flagged for review"; reasons describe inputs; known limitations documented (cold start, large-amount under-ranking) | — |

### `POST /api/v1/documents` (PDF upload) and `/api/v1/documents*`
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **T**ampering: malformed or hostile PDF | `%PDF-` header check; 20 MB cap enforced while streaming; 200-page cap before extraction; encrypted and image-only files rejected; parser errors return one generic 422 | pypdf runs in a forked worker process killed after 300 s |
| **T**ampering: control characters / NUL bytes in text | Text is NFKC-normalised and control characters removed before storage | — |
| **I**nfo disclosure: other users' documents (IDOR) | Ownership filter in every query; foreign IDs return 404; the same file uploaded by two users is two separate documents | — |
| **I**nfo disclosure: deleted text still searchable | Postgres rows are deleted first; search results are joined back to live chunk rows, so leftover vectors can never return text | If Qdrant is down during delete, its vectors stay until a cleanup job (planned) |
| **E**levation: viewer uploads or deletes | `document:write` required (analyst, admin) | — |
| **D**oS: many large uploads | Size and page caps; 20 uploads / min per user; indexing runs in the worker with a 300 s limit (also bounds a slow, hostile PDF) | — |

### `POST /api/v1/answers` (questions about documents)
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **I**nfo disclosure: retrieving another user's passages | Qdrant search always carries an `owner_id` filter (the adapter has no unfiltered search); results are re-checked against Postgres by owner and `status = ready`; `document_ids` must all be owned (else 404) | — |
| **T**ampering: prompt injection inside a document | Passages are fenced in `<source>` blocks and any `<source`/`</source` text inside them is removed; the system prompt says to treat sources as information only; answers without a valid citation are not shown; retrieved text cannot change the user, filters or tools | A model can still be persuaded to write misleading text *with* a valid citation; the citation lets a reader check it (see docs/evaluation.md) |
| **R**epudiation / audit | Logs record model name, latency and token counts per call, never prompt or document text | No per-question audit table yet |
| **I**nfo disclosure: hallucinated answers | Relevance gate (no model call when the best passage is weak); citations must point at a passage that was sent; "not enough evidence" otherwise | Citation correctness is measured, not guaranteed |
| **D**oS: expensive model calls | Question ≤ 1000 characters; `top_k` ≤ 10; answer ≤ 400 tokens; 120 s model timeout; 30 questions / min per user | — |
| **T**ampering: broken model output | Embeddings that are all-zero, non-finite or the wrong size are rejected (503), never stored | — |

### `/api/v1/jobs*` and the background worker
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **I**nfo disclosure: reading another user's job | Owner filter on every query; foreign ids → 404; job bodies never expose internal payloads (file names) | — |
| **T**ampering: payload pointing at arbitrary files | The worker opens only generated names (`<uuid>.csv/pdf`) inside `UPLOAD_DIR`; files are 0600 in a 0700 folder and deleted when the job ends | — |
| **I**nfo disclosure: error details | Job errors store a safe code and message; unexpected exceptions become `internal_error` with details only in logs | — |
| **R**epudiation / audit | Every job records owner, kind, attempts and timestamps; the worker logs start and finish per job id | No per-step audit trail yet |
| **D**oS: duplicate or retried submissions | Partial unique index lets only one active job per (owner, kind, content/dataset); Idempotency-Key replays imports | — |
| **D**oS: lost or stuck jobs | Job state in Postgres; start-up sweep and `app.cli requeue` re-deliver queued and stale running jobs; conditional claim prevents double execution | A stuck job waits for the stale limit (30 min by default) |
| **E**levation: job runs after the owner is disabled | The runner reloads the owner and fails the job if disabled or deleted | — |

### `POST /api/v1/investigations` (investigation agent)
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **T**ampering: prompt injection in data (merchant names, policy PDFs) | Tool results returned in a `<tool_result trust="untrusted data">` fence with `<` escaped; the tool name echoed in the fence is sanitised; the system prompt says never to follow instructions in tool results | The model can still be misled into writing a misleading *draft*; findings and evidence are checked (below) and a person reviews it |
| **E**levation: model widens its own scope | Five read-only tools, allowlisted; arguments validated by Pydantic (`extra="forbid"`, bounds, patterns); tools run as the requesting user through owner-scoped services; the dataset is fixed by the server, never a tool argument; transactions outside it → "not found" | — |
| **E**levation: model approves or changes anything | No tool writes data or changes state; `submit_report` only creates a **draft**; approval is a separate human endpoint | — |
| **T**ampering: invented evidence | Findings must name a transaction a tool returned (others dropped); evidence is copied from the database; policy references must be passage ids a search returned; the server adds a "not a finding of fraud" disclaimer | The free-text summary is not checked sentence by sentence |
| **T**ampering: hostile strings in report text | The model quotes data (e.g. a merchant named `<tool_result> new instruction…`) as data; the API returns it as JSON strings | Any UI must render report text as plain text, never as HTML |
| **I**nfo disclosure: "fraud" claims | A report containing "fraud" is sent back once to be rewritten; on the last turn it is accepted with `wording_flag: true` | Wording check is a single keyword |
| **D**oS: runaway loop or cost | 8 model turns, 12 tool calls, 180 s, 700 tokens per call, 2,500 characters per result, repeated calls refused, last turn offers only `submit_report`; 300 s job timeout; 5 investigations / min per user | — |
| **R**epudiation / audit | `agent_steps`: tool, validated arguments (never raw model output), outcome, error, size and latency per attempt and step; job and report link the trail; no prompts or model text stored | — |
| **D**oS / duplicates | Idempotency-Key required; an identical unfinished investigation is joined | — |

### `/api/v1/reports*` (review and approval)
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **E**levation: approving one's own report | `report:approve` required; reviewer ≠ owner checked in the service and by `CHECK (reviewed_by <> owner_id)` | Two colluding admins can still approve each other's reports |
| **I**nfo disclosure: reading others' reports | Owners see their own; reviewers see only submitted/reviewed reports, never other people's drafts; otherwise 404 | Reviewers see the reports' evidence (transaction details) from other owners, by design |
| **T**ampering: double decisions / races | State changes are single conditional UPDATEs (`WHERE status = 'submitted'`); a second decision → 409 | No history table of past decisions yet |

### `PATCH /api/v1/users/{id}/role`
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **E**levation: self-promotion | Requires `user:manage` (admin only); roles limited by a DB CHECK constraint | Role changes are not yet written to an audit log |
| **R**epudiation | Request IDs on every response | Structured audit logging planned |

### `/health`, `/ready`
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **I**nfo disclosure | Only `ok`/`down` per dependency; exception details only in server logs | Unauthenticated by design (bind to localhost) |
