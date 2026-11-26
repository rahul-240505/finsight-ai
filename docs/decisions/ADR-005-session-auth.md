# ADR-005: Server-side sessions in an HttpOnly cookie (not JWT)

- Status: Accepted · Date: 2026-11-26

## Context
The API serves one first-party web UI from a known origin. Users must be able to sign out, and an admin must be able to cut off a user immediately (role change, disabled account). Credentials must not be readable by JavaScript, so an XSS bug can't steal them.

## Options
1. **JWT access token** (+ refresh token). No database lookup per request; but a token can't be revoked before it expires without adding a deny-list, which brings the lookup back. Often stored in localStorage, which XSS can read.
2. **Server-side session, opaque token in a cookie.** One indexed lookup per request; revocation is a row delete.
3. **Third-party identity provider (OIDC).** Best for real products; too heavy for a local, single-machine deployment.

## Decision
Option 2.
- Token: 256 random bits (`secrets.token_urlsafe(32)`), sent only as the cookie `finsight_session`.
- Storage: `sessions` table holds `sha256(token)`, the user, and `expires_at` (12 h by default, `SESSION_TTL_HOURS`). A leaked database does not contain usable tokens.
- Cookie flags: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`.
- CSRF: `SameSite=Lax` plus an `Origin` check on POST/PUT/PATCH/DELETE (allow-list `ALLOWED_ORIGINS`, or same origin).
- Passwords: Argon2id (argon2-cffi defaults, RFC 9106 low-memory profile), re-hashed on login if parameters change. Unknown emails still run one Argon2 verify so timing doesn't reveal which accounts exist.
- Logout deletes the session row; role changes delete all of that user's sessions.

## Consequences
- One indexed query per authenticated request (unique index on `token_hash`).
- Immediate revocation for logout, role change and disabled users.
- Cookie auth means CSRF must be handled (done above). A future non-browser client would need API tokens.
- Expired rows accumulate until a cleanup job exists (planned with background jobs).

## Revisit when
Multiple services need to verify identity without a shared database, or an external identity provider is introduced.
