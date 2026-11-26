from app.core import security
from app.core.permissions import Permission, Role, has_permission


def test_password_hash_verifies_and_is_salted() -> None:
    first = security.hash_password("a-long-password-1")
    second = security.hash_password("a-long-password-1")
    assert first != second  # random salt per hash
    assert first.startswith("$argon2id$")
    assert security.verify_password(first, "a-long-password-1")


def test_wrong_password_and_missing_hash_are_rejected() -> None:
    stored = security.hash_password("a-long-password-1")
    assert not security.verify_password(stored, "a-long-password-2")
    assert not security.verify_password(None, "a-long-password-1")
    assert not security.verify_password("not-a-hash", "a-long-password-1")


def test_dummy_hash_password_never_logs_in_unknown_user() -> None:
    assert not security.verify_password(None, "timing-equaliser-not-a-real-password")


def test_session_tokens_are_random_and_stored_hashed() -> None:
    tokens = {security.new_session_token() for _ in range(100)}
    assert len(tokens) == 100
    token = tokens.pop()
    digest = security.hash_session_token(token)
    assert len(digest) == 64 and token not in digest
    assert digest == security.hash_session_token(token)


def test_role_permissions() -> None:
    assert has_permission(Role.VIEWER, Permission.DATASET_READ)
    assert not has_permission(Role.VIEWER, Permission.DATASET_WRITE)
    assert has_permission(Role.ANALYST, Permission.DATASET_WRITE)
    assert not has_permission(Role.ANALYST, Permission.REPORT_APPROVE)
    assert not has_permission(Role.ANALYST, Permission.USER_MANAGE)
    assert all(has_permission(Role.ADMIN, p) for p in Permission)
    assert not has_permission("superuser", Permission.DATASET_READ)  # unknown role: nothing
