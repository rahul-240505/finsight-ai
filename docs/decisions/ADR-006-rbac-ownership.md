# ADR-006: Role-based permissions plus per-object ownership

- Status: Accepted · Date: 2026-11-26

## Context
Users import sensitive transaction data. Some users only read, some write, a few administer. No user may ever reach another user's objects, even by guessing or enumerating IDs (IDOR).

## Options
1. **Roles only.** Simple, but says nothing about *which* objects a user may touch.
2. **RBAC + ownership.** Roles grant permissions for kinds of action; every query on user-owned data is filtered by `owner_id`.
3. **ABAC / policy engine** (rules on attributes such as department or amount). Flexible, but more moving parts than this domain needs.

## Decision
Option 2.
- Roles → permissions (`app/core/permissions.py`):
  - `viewer`: `dataset:read`, `report:read`
  - `analyst`: viewer + `dataset:write`, `report:write`
  - `admin`: analyst + `report:approve`, `user:manage`
- Routes declare a permission with `require_permission(...)`: 401 if not signed in, 403 if the role lacks it.
- Services take the current user and filter in the query (`WHERE id = :id AND owner_id = :user`). Missing and foreign objects both return **404**, so responses don't reveal which IDs exist.
- Self-registration creates `analyst`. Admins are created with `python -m app.cli create-user --role admin`; only `user:manage` can change roles, and a change ends the user's sessions.
- Admins have no implicit access to other users' data.
- Unknown roles get no permissions (fail closed). A database CHECK constraint limits `role` to known values.

## Consequences
- Every new service function must apply the owner filter; a route-inventory test checks that every `/api/v1` route rejects anonymous requests, and IDOR tests cover read and delete.
- Sharing data between users would need a new model (memberships or grants).

## Revisit when
Teams or shared workspaces are needed, or rules depend on attributes (amount limits, departments).
