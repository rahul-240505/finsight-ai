"""Role-based access control (ADR-006): roles map to permissions; routes require permissions.

Permissions decide *what kind* of action a user may take. Ownership checks in the services
decide *which objects* they may take it on. Both are always needed.
"""

from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"


class Permission(StrEnum):
    DATASET_READ = "dataset:read"
    DATASET_WRITE = "dataset:write"
    DOCUMENT_READ = "document:read"  # includes asking questions about documents
    DOCUMENT_WRITE = "document:write"
    REPORT_READ = "report:read"
    REPORT_WRITE = "report:write"
    REPORT_APPROVE = "report:approve"
    USER_MANAGE = "user:manage"


_VIEWER = {Permission.DATASET_READ, Permission.DOCUMENT_READ, Permission.REPORT_READ}
_ANALYST = _VIEWER | {
    Permission.DATASET_WRITE,
    Permission.DOCUMENT_WRITE,
    Permission.REPORT_WRITE,
}
_ADMIN = _ANALYST | {Permission.REPORT_APPROVE, Permission.USER_MANAGE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(_VIEWER),
    Role.ANALYST: frozenset(_ANALYST),
    Role.ADMIN: frozenset(_ADMIN),
}


def has_permission(role: str, permission: Permission) -> bool:
    """Unknown roles get no permissions (fail closed)."""
    try:
        return permission in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False
