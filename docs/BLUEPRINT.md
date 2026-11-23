**FINSIGHT AI**

Financial Intelligence & Risk Investigation Platform

**PROJECT BLUEPRINT • ARCHITECTURE • SYSTEM DESIGN • ZERO-COST
DEPLOYMENT**

  -----------------------------------------------------------------------
  **Document purpose**                **Project direction**
  ----------------------------------- -----------------------------------
  Portfolio-grade full-stack AI       A realistic financial-domain
  application                         application combining analytics, ML
                                      anomaly detection, RAG, tool-using
                                      agents and backend engineering.

  Primary objective                   Demonstrate engineering judgement
                                      and the ability to explain
                                      architecture, trade-offs,
                                      reliability, security and
                                      evaluation.

  Cost constraint                     Use free/open-source development
                                      tools and local inference. Public
                                      hosting is best-effort within
                                      changing free-tier quotas.
  -----------------------------------------------------------------------

*Prepared as an implementation plan --- not a claim that the features
have already been built.*

# 1. Product overview

FinSight AI is a portfolio simulation of a financial operations and risk
investigation platform. It lets a user import transaction data, inspect
analytics, flag unusual activity, search policy/report documents with
grounded answers, and assemble evidence into an investigation report.

The project is intentionally scoped as a demonstrator using synthetic or
public datasets. It is not a real fraud decision system, investment
recommendation engine, or production financial institution platform.

## Primary user journeys

1.  An analyst uploads a CSV transaction dataset, previews it, validates
    its schema and imports it.

2.  The platform computes summary statistics and visualizes transaction
    patterns.

3.  An ML model scores unusual transactions; an analyst reviews flags
    rather than treating them as proven fraud.

4.  A user uploads policy documents and asks questions; the assistant
    returns answers with source citations.

5.  A user asks for an investigation; a controlled workflow fetches
    transaction details, risk signals and relevant policy passages, then
    drafts a report for human review.

# 2. Product modules and acceptance criteria

## A. Financial data ingestion and analytics

-   CSV first; add XLSX only after the CSV workflow is reliable.

-   Validate required columns, data types, date formats, currency,
    missing values, duplicates and unreasonable values.

-   Show a preview and import summary before committing data.

-   Provide filters, date ranges, totals, averages, distributions and
    trend charts.

-   Store original import metadata and normalized transaction records;
    retain an import identifier for traceability.

Acceptance: a user can upload a supported dataset, see validation
errors, import valid rows, filter records and reproduce the displayed
summary from stored data.

## B. ML anomaly detection

-   Start with Isolation Forest as an unsupervised baseline.

-   Use a labelled public dataset only for a separate supervised
    classification experiment; do not confuse benchmark labels with
    production fraud truth.

-   Optionally train a PyTorch autoencoder after the baseline is
    measurable.

-   Persist model version, feature schema, score, threshold and
    inference timestamp with each assessment.

-   Show why a transaction was flagged using interpretable feature
    comparisons or local explanations; avoid claiming the model proves
    fraud.

Metrics: precision, recall, F1, confusion matrix and PR-AUC for
imbalanced labels; track false positives and threshold trade-offs.

## C. Document intelligence and RAG

-   Accept PDF and text documents initially; validate file type, size
    and page count.

-   Extract text, retain document/page metadata, chunk by
    token/character limits and generate embeddings.

-   Store vectors and metadata in Qdrant; retain document ownership and
    access metadata in PostgreSQL.

-   Retrieve relevant chunks with metadata filters; add keyword/hybrid
    retrieval and reranking only after a baseline.

-   Generate answers from retrieved context and return document/page
    citations. If evidence is insufficient, the assistant should say so.

Evaluation: create a small question set with expected source documents;
measure retrieval hit rate/recall@k, answer faithfulness, citation
correctness and latency.

## D. AI-assisted investigation workflow

-   Use explicit tools: get_transaction, get_related_transactions,
    get_risk_assessment, search_policy_documents and
    create_report_draft.

-   Agents may propose and sequence read-only tools; they must not
    execute arbitrary SQL, shell commands or Python.

-   Require human confirmation before any consequential write/action. In
    this portfolio app, report creation is a draft operation.

-   Persist workflow state, tool inputs/outputs, timestamps, errors and
    model/provider metadata.

Start with a deterministic workflow or a single tool-using agent.
Introduce multiple specialized agents only if evaluation shows a real
benefit.

## E. Reports and audit trail

-   Generate a structured report containing transaction facts, model
    signals, retrieved policy excerpts, caveats and reviewer notes.

-   Keep report drafts separate from approved/final reports.

-   Record who initiated an investigation, which tools ran and which
    evidence was used.

## F. Evaluation and reliability

-   Unit tests for parsing, preprocessing, feature generation, retrieval
    filters and tool validation.

-   Integration tests for database transactions, upload flows and
    end-to-end investigations.

-   Concurrency tests for duplicate imports, idempotent requests and
    simultaneous report updates.

-   Maintain a benchmark set for ML, RAG and agent workflows; report
    measured results rather than invented performance claims.

# 3. Recommended technology stack

  -----------------------------------------------------------------------
  **Layer**               **Choice**              **Reason / boundary**
  ----------------------- ----------------------- -----------------------
  Frontend                React + TypeScript +    Conventional SPA;
                          Vite                    type-safe UI; deploy
                                                  static build to Vercel.

  UI styling              Tailwind CSS +          Reusable components and
                          shadcn/ui               fast dashboard
                                                  development.

  Charts                  Recharts or Plotly.js   Use one chart library
                                                  initially; avoid
                                                  unnecessary overlap.

  Backend                 Python + FastAPI        Typed request/response
                                                  models, OpenAPI docs
                                                  and async-friendly API.

  Validation              Pydantic                Validate API payloads
                                                  and configuration.

  ORM/migrations          SQLAlchemy + Alembic    Relational persistence
                                                  and versioned schema
                                                  changes.

  Primary database        PostgreSQL              Users, imports,
                                                  transactions,
                                                  assessments, jobs,
                                                  conversations and
                                                  reports.

  Vector database         Qdrant                  Document embeddings and
                                                  similarity retrieval.

  Cache / coordination    Redis                   Rate-limit counters,
                                                  short-lived cache,
                                                  queue broker and
                                                  distributed
                                                  coordination when
                                                  needed.

  ML                      Pandas, NumPy,          Data preparation,
                          scikit-learn, PyTorch   baseline models and
                                                  optional neural model.

  LLM / embeddings        Ollama + Hugging Face   Local inference and
                          models                  local embedding models
                                                  without per-request API
                                                  cost.

  RAG orchestration       Start with direct       Use abstractions only
                          Python modules;         where they simplify;
                          optionally LangChain    understand the
                                                  underlying retrieval
                                                  steps.

  Background jobs         RQ + Redis (or a simple Long-running ingestion
                          worker)                 and model jobs outside
                                                  request/response cycle.

  Testing                 pytest + HTTPX          Unit and API
                                                  integration tests.

  Frontend hosting        Vercel Hobby            Static React/Vite
                                                  hosting for a personal
                                                  portfolio demo, subject
                                                  to plan terms.

  Backend hosting         Render Free as a demo   Python web service, but
                          option                  cold starts and
                                                  ephemeral filesystem
                                                  mean it is not
                                                  production-grade.
  -----------------------------------------------------------------------

# 4. Frontend decision: React, not Streamlit

Use React + TypeScript + Vite. Streamlit is a Python framework for
quickly building data apps; it is not required and is not the best fit
if the goal includes demonstrating conventional frontend engineering.

-   React owns the dashboard, tables, filters, forms, document viewer,
    chat UI and investigation timeline.

-   Vite builds static assets that can be hosted on Vercel.

-   The browser calls FastAPI over HTTPS. Keep secrets and provider keys
    on the backend, never in frontend environment variables exposed to
    the browser.

-   Use a typed API client and centralize authentication/error handling.

Vercel Hobby is intended for personal, non-commercial use; verify
current terms before using it for anything beyond a personal portfolio.
Vercel plan/limits: https://vercel.com/docs/plans/hobby and
https://vercel.com/docs/limits.

# 5. High-level architecture

Recommended first architecture: a modular monolith backend plus a
separate background worker. Do not begin with microservices. The
frontend is independently deployed; the API, worker and data stores are
logically separate components.

  -----------------------------------------------------------------------
  **Component**           **Responsibilities**    **Communication**
  ----------------------- ----------------------- -----------------------
  React SPA               User experience, forms, HTTPS REST; optional
                          charts, chat, review    SSE for progress
                          actions                 

  FastAPI API             Authentication,         SQL, Redis, Qdrant;
                          authorization,          enqueue jobs
                          validation, business    
                          rules, orchestration    

  Worker                  Document parsing,       Redis queue; SQL/Qdrant
                          embedding, dataset      
                          import, ML              
                          inference/training,     
                          report generation       

  PostgreSQL              Canonical structured    Transactions and
                          records and durable job constraints
                          state                   

  Qdrant                  Vector search over      Filtered vector queries
                          document chunks         

  Redis                   Rate limits, cache,     Atomic commands / queue
                          queue broker,           protocol
                          short-lived             
                          coordination            

  Ollama or model runtime Local LLM and embedding Private local HTTP
                          inference during        endpoint
                          development             
  -----------------------------------------------------------------------

Request flow: browser → API authentication/authorization → validation →
business service → database/vector store or queue → response. Long jobs
return a job ID; the UI polls job status or uses Server-Sent Events for
progress.

## Why not microservices initially?

-   A modular monolith is easier to debug, test, deploy and run on
    limited free resources.

-   Keep clean module boundaries so a worker or inference service can be
    separated later.

-   Split a service only when there is a concrete reason: independent
    scaling, isolation, different runtime requirements or team
    ownership.

# 6. System design decisions and trade-offs

## 6.1 Authentication

-   Use a well-reviewed password hashing function such as Argon2id;
    never store plaintext passwords or reversible password encryption.

-   For a same-site browser app, consider secure HttpOnly, Secure,
    SameSite cookies for session/refresh credentials; pair cookie-based
    auth with CSRF protection.

-   If using bearer JWTs, keep access tokens short-lived and avoid
    storing long-lived refresh tokens in localStorage. A
    backend-for-frontend or HttpOnly cookie design reduces token
    exposure.

-   Implement refresh-token rotation, revocation on logout, password
    reset with one-time expiring tokens, and login throttling.

-   Do not invent custom cryptography. Use maintained libraries and
    established standards.

Trade-off: JWTs are easy to validate without a database lookup, but
revocation and permission changes are harder. Opaque server-side
sessions simplify revocation but require shared session storage. For
this single-origin portfolio app, secure cookie-backed sessions are a
sensible default; document the alternative.

## 6.2 Authorization

-   Start with RBAC roles: admin, analyst and viewer.

-   Enforce authorization in the backend on every protected endpoint;
    hiding UI buttons is not security.

-   Use ownership/tenant checks on documents, datasets, conversations
    and reports. A user must not access another user\'s object by
    guessing an ID (IDOR prevention).

-   Separate permissions such as dataset:read, dataset:import,
    investigation:create, report:approve and user:manage.

-   Treat agent tools as service actions with explicit allowlists and
    scopes; pass the authenticated user\'s authorization context into
    every tool.

Trade-off: RBAC is simple and interview-friendly; attribute-based access
control is more flexible but adds complexity. Start with RBAC plus
resource ownership checks.

## 6.3 Rate limiting and abuse protection

-   Apply limits by IP for unauthenticated endpoints and by user/API key
    for authenticated endpoints.

-   Use Redis atomic counters with a sliding-window or token-bucket
    algorithm. Avoid in-process counters because multiple backend
    instances do not share memory.

-   Use different budgets for login, general API calls, file uploads,
    RAG queries and expensive agent runs.

-   Return HTTP 429 with Retry-After; log limit events without logging
    secrets or document contents.

-   Add request size limits, upload size/page limits, per-user
    concurrent-job limits and model token/output budgets.

Trade-off: fixed windows are simple but allow boundary bursts; sliding
windows are smoother but cost more state/operations; token bucket allows
controlled bursts. Start with a Redis-backed fixed/sliding-window
limiter, then use token bucket for expensive AI operations if needed.

## 6.4 Database transactions, isolation and locking

-   Use PostgreSQL transactions for multi-step state changes such as
    creating an import record and its normalized rows.

-   Use unique constraints and foreign keys as the final protection
    against duplicate or orphaned records.

-   Use SELECT \... FOR UPDATE for short critical sections where a row
    must be read and changed atomically, such as claiming a queued job.

-   Keep transactions short. Never hold a database lock while calling an
    LLM, parsing a large PDF or waiting on a remote service.

-   Use optimistic concurrency with a version column for editable
    reports; reject stale updates with a conflict response.

-   Understand Read Committed vs Repeatable Read vs Serializable; choose
    the weakest isolation level that preserves the invariant and retry
    serialization/deadlock failures where appropriate.

Trade-off: pessimistic row locks prevent conflicting updates but reduce
concurrency; optimistic version checks scale well when conflicts are
rare but require clients to handle conflicts.

## 6.5 Synchronization and background work

-   Do not parse large documents, create embeddings, import huge CSVs or
    run model training inside a normal HTTP request.

-   API creates a durable job row, commits it, enqueues the job and
    returns 202 Accepted with a job ID.

-   Worker claims jobs atomically, records status/progress and updates
    the job result.

-   Use bounded worker concurrency because local LLM inference and
    embedding generation can exhaust RAM/VRAM.

-   Use job leases/visibility timeouts and periodic recovery for workers
    that crash while processing.

-   Use an outbox pattern if reliable database-to-queue publication
    becomes necessary: write the business change and outbox event in one
    DB transaction, then publish asynchronously.

Trade-off: a simple Redis queue is easy to operate but Redis loss can
affect queued work depending on persistence/configuration.
PostgreSQL-backed job queues reduce infrastructure but may increase DB
load. For the demo, RQ + Redis is acceptable; keep durable job status in
PostgreSQL.

## 6.6 Idempotency and duplicate processing

-   Require an Idempotency-Key for operations that may be retried, such
    as dataset import initiation or report creation.

-   Store the key, user, request hash and result/status under a unique
    constraint.

-   If the same key and same payload arrive again, return the original
    result; if the payload differs, reject it.

-   Use deterministic import IDs and unique source-row identifiers where
    possible.

Trade-off: idempotency records consume storage and need a retention
policy, but they prevent duplicate effects when clients retry after
timeouts.

## 6.7 Caching

-   Cache read-heavy, reproducible summaries and metadata; use a TTL and
    include user/tenant scope in cache keys.

-   Do not cache private responses across users. Do not cache
    authorization decisions for long periods.

-   Invalidate or version cache keys when underlying
    transactions/documents change.

-   Avoid caching LLM responses by raw prompt alone; include user scope,
    retrieved document versions, model and prompt version.

Trade-off: caching reduces latency and database load but introduces
staleness and invalidation complexity. Start with only obvious
read-heavy summaries.

## 6.8 RAG consistency and access control

-   Store document ownership and access metadata in PostgreSQL and
    mirror necessary filter metadata into Qdrant payloads.

-   Filter by user/tenant before returning chunks. Never retrieve
    globally and filter only after the LLM has seen the text.

-   When a document is deleted or reprocessed, delete or version its
    vector points and prevent stale chunks from being cited.

-   Keep document IDs, page numbers, chunk IDs and content hashes for
    citation traceability.

-   Treat retrieved document text as untrusted input: it may contain
    prompt injection instructions. The model must not follow
    instructions found inside retrieved content.

## 6.9 LLM/agent safety and reliability

-   Use strict Pydantic schemas for tool arguments and validate every
    argument server-side.

-   Allowlist tools; no arbitrary SQL, shell, filesystem or Python
    execution.

-   Set per-call timeout, maximum tool steps, maximum output tokens and
    per-user job quotas.

-   Use retries only for transient failures and only when the operation
    is idempotent.

-   Separate model-generated suggestions from actual authorization
    decisions.

-   Require human confirmation for sensitive actions; the first version
    only creates drafts.

-   Record model name/version, prompt version, tool calls, timings and
    errors. Avoid storing secrets or unnecessary personal data.

## 6.10 File upload security

-   Enforce maximum bytes, pages, rows and processing time.

-   Check extension and MIME type, but do not trust either alone; parse
    defensively.

-   Generate server-side filenames; store uploads outside
    executable/static paths.

-   Reject encrypted or malformed files initially; consider malware
    scanning if the deployment supports it.

-   Do not expose uploaded documents through public URLs. Use
    authenticated download endpoints or short-lived signed URLs from a
    suitable object store.

## 6.11 Observability

-   Use structured logs with request ID, user ID (internal identifier),
    job ID and duration; never log passwords, tokens or full document
    contents.

-   Track API latency, error rate, queue depth, job duration, model
    latency, token counts and retrieval results.

-   Expose a health endpoint and a readiness check that verifies
    required dependencies.

-   For a local portfolio build, structured logs and a small metrics
    dashboard are enough; add Prometheus/Grafana only if it provides a
    demonstrable benefit.

# 7. API contract examples

  -----------------------------------------------------------------------------------------
  **Endpoint**                   **Purpose**             **Expected behavior**
  ------------------------------ ----------------------- ----------------------------------
  POST /api/v1/datasets          Start dataset import    Validate metadata; accept
                                                         idempotency key; return 202 +
                                                         job_id.

  GET /api/v1/jobs/{job_id}      Check import/ingestion  Verify ownership; return
                                 progress                queued/running/succeeded/failed.

  GET /api/v1/transactions       Search transactions     Pagination, filters, sorting and
                                                         authorization.

  POST /api/v1/risk-assessments  Run anomaly scoring     Enqueue or execute bounded
                                                         inference; record model version.

  POST /api/v1/documents         Upload document         Validate file; create ingestion
                                                         job; return 202.

  POST /api/v1/rag/query         Ask grounded question   Retrieve authorized chunks; return
                                                         answer, citations and retrieval
                                                         metadata.

  POST /api/v1/investigations    Start AI-assisted       Create job; use allowlisted tools;
                                 investigation           return job ID.

  POST                           Approve a draft         Require report:approve permission
  /api/v1/reports/{id}/approve                           and optimistic version check.
  -----------------------------------------------------------------------------------------

# 8. Suggested relational data model

  -----------------------------------------------------------------------
  **Entity**                          **Important fields / constraints**
  ----------------------------------- -----------------------------------
  users                               id, email UNIQUE, password_hash,
                                      role, created_at, disabled_at

  datasets                            id, owner_id FK, filename,
                                      content_hash, status, row_count,
                                      created_at

  transactions                        id, dataset_id FK, external_ref,
                                      amount, currency, occurred_at;
                                      unique(dataset_id, external_ref)
                                      where applicable

  model_versions                      id, name, version, feature_schema,
                                      metrics, artifact_reference

  risk_assessments                    id, transaction_id FK,
                                      model_version_id FK, score,
                                      threshold, label, created_at

  documents                           id, owner_id FK, filename,
                                      content_hash, status, version,
                                      created_at

  document_chunks                     id, document_id FK, page_number,
                                      chunk_index, content_hash,
                                      qdrant_point_id

  jobs                                id, owner_id FK, type, status,
                                      progress, attempts, started_at,
                                      finished_at, error_code

  investigations                      id, owner_id FK, transaction_id,
                                      status, summary, created_at

  reports                             id, investigation_id FK, version,
                                      status, content_json, created_by,
                                      approved_by

  conversations/messages              conversation owner and ordered
                                      messages; enforce ownership and
                                      bounded history

  idempotency_records                 user_id, key, request_hash,
                                      response/status, expires_at;
                                      unique(user_id, key)
  -----------------------------------------------------------------------

# 9. Deployment strategy with no paid infrastructure

The application should be fully usable locally first. Public hosting is
an optional showcase and must degrade gracefully if a free service
sleeps, reaches quota or removes a free tier.

  -----------------------------------------------------------------------
  **Part**                **Preferred approach**  **Important
                                                  limitation**
  ----------------------- ----------------------- -----------------------
  Frontend                Vercel Hobby for        Hobby is for personal,
                          React/Vite static       non-commercial use;
                          frontend                usage and plan limits
                                                  apply.

  Backend API             Render Free Python web  Sleeps after 15 minutes
                          service for demo        idle; cold start can
                                                  take about a minute;
                                                  filesystem is
                                                  ephemeral.

  Worker                  Run locally for full    Free web services may
                          features; optionally    not support durable
                          share a small demo      always-on background
                          worker if the host      workers or one-off
                          permits                 jobs.

  PostgreSQL              Use a currently         Check current storage,
                          available free managed  sleep, backup and
                          PostgreSQL tier, or     connection limits
                          local PostgreSQL        before selecting
                                                  provider.

  Qdrant                  Local Qdrant for        Free cluster has
                          development; Qdrant     limited CPU/RAM/disk;
                          Cloud free cluster for  monitor quota.
                          small demo if available 

  Redis                   Local Redis for         Do not assume a free
                          development; free       Redis service is
                          managed option only if  persistent or
                          available               always-on.

  LLM                     Ollama on developer     A public cloud app
                          laptop                  cannot call localhost
                                                  on a visitor\'s
                                                  machine; public demo
                                                  needs hosted inference
                                                  or a limited
                                                  precomputed/demo mode.
  -----------------------------------------------------------------------

Render free service limitations: https://render.com/docs/free. Vercel
Hobby details: https://vercel.com/docs/plans/hobby. Qdrant Cloud
pricing: https://qdrant.tech/pricing/.

Important practical design: offer two modes. Local full mode runs
FastAPI + PostgreSQL + Qdrant + Redis + Ollama on the developer machine.
Public demo mode uses a small hosted API and managed data stores,
disables expensive model execution or uses a quota-limited hosted model,
and clearly shows demo limitations.

Do not promise permanent free hosting. Free tiers, eligibility, quotas
and acceptable-use rules change. Re-check provider terms immediately
before deployment.

# 10. Repository layout

> finsight-ai/\
> ├── frontend/\
> │ ├── src/\
> │ │ ├── app/\
> │ │ ├── components/\
> │ │ ├── features/\
> │ │ │ ├── analytics/\
> │ │ │ ├── transactions/\
> │ │ │ ├── documents/\
> │ │ │ ├── assistant/\
> │ │ │ └── investigations/\
> │ │ ├── lib/ \# API client, auth, schemas\
> │ │ └── routes/\
> │ └── package.json\
> ├── backend/\
> │ ├── app/\
> │ │ ├── api/v1/\
> │ │ ├── core/ \# config, security, logging\
> │ │ ├── db/ \# models, session, migrations\
> │ │ ├── modules/\
> │ │ │ ├── analytics/\
> │ │ │ ├── transactions/\
> │ │ │ ├── ml/\
> │ │ │ ├── documents/\
> │ │ │ ├── rag/\
> │ │ │ ├── agents/\
> │ │ │ └── reports/\
> │ │ ├── services/\
> │ │ └── worker/\
> │ ├── tests/\
> │ └── pyproject.toml\
> ├── ml/\
> │ ├── notebooks/\
> │ ├── training/\
> │ ├── evaluation/\
> │ └── artifacts/ \# ignored from Git if large\
> ├── docs/\
> │ ├── architecture.md\
> │ ├── decisions/ \# ADR-001, ADR-002, \...\
> │ ├── api.md\
> │ ├── threat-model.md\
> │ └── evaluation.md\
> ├── infra/\
> │ └── local/ \# compose file for local dependencies\
> ├── .env.example\
> ├── .gitignore\
> └── README.md

# 11. Build roadmap

  -----------------------------------------------------------------------
  **Phase**               **Build**               **Definition of done**
  ----------------------- ----------------------- -----------------------
  0\. Foundation          Repo, Python            Frontend and API run
                          environment, React app, locally; CI runs
                          linting, tests, config  checks.

  1\. Core backend        PostgreSQL, SQLAlchemy, Users can sign in and
                          Alembic, auth, RBAC,    access only their own
                          ownership checks        resources.

  2\. Data analytics      CSV validation/import,  Repeatable imports,
                          transaction APIs,       pagination, filters and
                          dashboard               tests.

  3\. ML baseline         Feature pipeline,       Versioned model scores
                          Isolation Forest,       with documented
                          evaluation              metrics.

  4\. RAG                 Document parsing,       Known test questions
                          chunking, embeddings,   retrieve correct
                          Qdrant retrieval,       evidence.
                          citations               

  5\. Async processing    Redis queue, worker,    Long jobs do not block
                          job states, retries,    HTTP requests;
                          idempotency             duplicate retries are
                                                  safe.

  6\. Agent workflow      Allowlisted tools,      End-to-end
                          orchestration, report   investigation works and
                          drafts, human approval  is traceable.

  7\. Hardening           Rate limits,            Documented limits,
                          concurrency tests,      threat model and
                          security tests,         reproducible tests.
                          observability           

  8\. Showcase            Vercel frontend,        Public demo works
                          constrained free        within quotas; local
                          backend/data services,  full mode remains
                          demo data               available.
  -----------------------------------------------------------------------

# 12. Architecture decision records to maintain

For each important design choice, create a short ADR with: context,
options considered, decision, consequences, and revisit conditions.

-   ADR-001: React SPA + FastAPI modular monolith instead of Streamlit
    or microservices.

-   ADR-002: PostgreSQL as the system of record; Qdrant only for vector
    retrieval.

-   ADR-003: Local Ollama inference with a provider interface.

-   ADR-004: Background job queue for long-running imports, ingestion
    and agent runs.

-   ADR-005: Cookie-backed session strategy or short-lived JWT strategy,
    including CSRF/XSS trade-offs.

-   ADR-006: RBAC plus resource ownership checks.

-   ADR-007: Redis-backed rate limiting and cache policy.

-   ADR-008: Idempotency keys and optimistic/pessimistic locking
    boundaries.

-   ADR-009: RAG document isolation, deletion and versioning.

-   ADR-010: Public demo limitations and local full-feature mode.

# 13. What to learn and be ready to explain

  -----------------------------------------------------------------------
  **Area**                            **Interview-level questions**
  ----------------------------------- -----------------------------------
  API/backend                         REST semantics, status codes,
                                      validation, pagination, dependency
                                      injection, async vs sync.

  Database                            ACID, isolation levels, indexes,
                                      query plans, unique constraints,
                                      deadlocks, row locks.

  Concurrency                         Race conditions, optimistic vs
                                      pessimistic locking, idempotency,
                                      worker leases.

  Distributed systems                 At-least-once delivery, retries,
                                      duplicate messages, outbox pattern,
                                      cache invalidation.

  Security                            Hashing vs encryption, sessions vs
                                      JWT, CSRF, XSS, SQL injection,
                                      IDOR, RBAC.

  LLM/RAG                             Chunking, embeddings, retrieval,
                                      reranking, prompt injection,
                                      hallucination, evaluation.

  ML                                  Class imbalance, leakage, threshold
                                      selection, precision/recall,
                                      anomaly vs fraud.

  Reliability                         Timeouts, retries, circuit
                                      breakers, backpressure, rate
                                      limits, observability.
  -----------------------------------------------------------------------

# 14. Scope control: what not to build initially

-   No Kubernetes, Helm or cloud microservices in the first version.

-   No separate Django backend or MySQL database.

-   No unrestricted autonomous agents or arbitrary code execution.

-   No real payment processing, trading or financial decisions.

-   No multi-tenant enterprise permissions beyond a simple owner/role
    model until core flows work.

-   No elaborate multi-agent framework before a single-agent baseline is
    evaluated.

-   No claims of production scalability, fraud accuracy or uptime
    without measurements.

# 15. Resume positioning --- only after implementation

Potential project title: FinSight AI --- Financial Intelligence & Risk
Investigation Platform.

Potential stack line after genuine implementation: Python, FastAPI,
React, TypeScript, PostgreSQL, Redis, Qdrant, Scikit-learn, PyTorch,
Transformers, RAG, LLM Tool Calling.

Write bullets only for completed and measured work. Examples of evidence
to collect: dataset size processed, import throughput, API p95 latency
under a stated test, model precision/recall on a named dataset split,
retrieval recall@k on a documented evaluation set, job retry behavior
and concurrency test results.

Do not claim a technology merely because it appears in the architecture
plan. A planned feature is not project experience.

# 16. Free-tier references to verify before deployment

-   Vercel Hobby plan: https://vercel.com/docs/plans/hobby

-   Vercel limits: https://vercel.com/docs/limits

-   Render free services and limitations: https://render.com/docs/free

-   Qdrant Cloud pricing/free tier: https://qdrant.tech/pricing/

-   Railway Free plan (small monthly resource credit, not unlimited free
    hosting): https://docs.railway.com/pricing/free-plan
