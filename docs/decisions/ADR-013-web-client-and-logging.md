# ADR-013: A small React client behind a same-origin proxy, and JSON logs

- Status: Accepted · Date: 2026-11-27

## Context
The API was usable only through curl and the OpenAPI page. Reviewers and analysts need a screen for the main flows: import, browse, review flagged rows, ask policy questions, read and approve reports. The UI also displays text that came from users' files and from the model, so it is an XSS target. Separately, the app's own log lines were not emitted under uvicorn, and API and worker logs could not be tied to a request or a job.

## Options
1. **Server-rendered templates (Jinja) in FastAPI.** One process; but mixes UI into the API and needs CSRF tokens for forms.
2. **React SPA with a router, state library and component kit.** Familiar; many dependencies for five screens.
3. **Small React + TypeScript SPA** (Vite, Tailwind), plain `fetch`, hash-based navigation, no other runtime libraries.
4. Logging: **stdlib `logging` with a JSON formatter** vs. a logging library (structlog).

## Decision
- Option 3. Runtime dependencies: `react`, `react-dom` only. Build: Vite, Tailwind, TypeScript (versions pinned, lockfile committed).
- The Vite dev server proxies `/api` to the API, so the browser sees one origin: the HttpOnly session cookie is first-party, JavaScript never handles a token, and the API's existing Origin check and SameSite cookie stay the CSRF defence.
- Untrusted text (merchant names, PDF excerpts, model output) is rendered only as React text. No `dangerouslySetInnerHTML`, no Markdown, no links built from data. The production build adds a strict Content-Security-Policy meta tag (`script-src 'self'`, no inline script, `object-src 'none'`).
- The UI hides actions a role cannot take (submit, approve) for convenience only; the API enforces every rule.
- Logging: stdlib `logging` with a `JsonFormatter` and a filter that adds `request_id` / `job_id` from context variables. One access line per request (method, route template, status, duration, user id). Uvicorn's own access log is turned off. The worker uses the same setup, and every line during a job carries its `job_id`.

## Consequences
- Five screens in about 760 lines of TypeScript, 76.6 kB of gzipped JavaScript; CI type-checks and builds it.
- A request can be followed through the logs by `X-Request-ID`, and a job by its id, without logging any content.
- The dev server runs without the CSP (React Fast Refresh injects an inline script); the CSP applies to the built app.
- No frontend unit tests yet; the walkthrough in docs/evaluation.md is the end-to-end check.

## Revisit when
The UI grows beyond a handful of screens (add a router and component tests), the app is served beyond localhost (serve the built files with security headers from the API or a reverse proxy, add HSTS), or logs need to leave the machine (ship JSON lines to a log store with retention).
