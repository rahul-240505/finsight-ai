# ADR-007: Redis fixed-window rate limits, failing open fast

- Status: Accepted · Date: 2026-11-26

## Context
Login invites password guessing; uploads, scoring and questions are expensive (CPU, GPU model calls). Limits must be shared by every API process, cheap to check, and must not take the API down when Redis is unavailable.

## Options
1. **In-process counters.** Free; wrong as soon as there are two processes, reset on restart.
2. **Redis fixed window** (`INCR` + `EXPIRE NX` on a key per window). One round trip; can let up to 2× the limit through across a window boundary.
3. **Redis sliding window / token bucket** (sorted sets or a Lua script). Smoother; more work per request.
4. **A reverse proxy limiter** (nginx). Good at the edge; doesn't know users or buckets, and this app runs without a proxy.

## Decision
- Fixed windows in Redis, configured as `RATE_LIMITS` (`"<requests>/<seconds>"` per bucket): `login_ip` 30/60, `login_email` 10/300, `upload` 20/60, `scoring` 10/60, `answers` 30/60.
- Per user for authenticated routes; login is limited per client IP **and** per email (every attempt counts). Keys contain a SHA-256 of the email, not the address.
- Over the limit → **429 `rate_limited`** with `Retry-After` (seconds to the next window).
- **Fail open, fast:** if Redis errors, the request is allowed and a warning logged. The client has no retries (redis-py's default retries cost ~4 s per request against a dead server) and Redis is skipped for 5 s after a failure.

## Consequences
- Verified live: 30 questions per minute pass, the 31st gets 429 with `Retry-After`.
- During a Redis outage there are no limits, including on login. Acceptable for a local single-user deployment; a public deployment should fail closed on login.
- Window-edge bursts up to 2× the limit are possible.

## Revisit when
The API is exposed publicly (fail closed for login, add a proxy limit), limits need to be smoother (token bucket), or per-plan quotas are needed.
