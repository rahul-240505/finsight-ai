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
| **S**poofing: password guessing | Argon2id hashing; 12–128 character passwords | No rate limit yet (planned with Redis limits) |
| **I**nfo disclosure: account enumeration via login | Same message and one Argon2 verify for unknown emails and wrong passwords | Registration returns 409 for an existing email |
| **I**nfo disclosure: credentials in responses/logs | Validation errors never echo input values; password hash never serialised | — |
| **D**oS: huge passwords | 128-character cap before hashing | No request rate limit yet |

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

### `PATCH /api/v1/users/{id}/role`
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **E**levation: self-promotion | Requires `user:manage` (admin only); roles limited by a DB CHECK constraint | Role changes are not yet written to an audit log |
| **R**epudiation | Request IDs on every response | Structured audit logging planned |

### `/health`, `/ready`
| Threat | Mitigation | Gap |
| --- | --- | --- |
| **I**nfo disclosure | Only `ok`/`down` per dependency; exception details only in server logs | Unauthenticated by design (bind to localhost) |
