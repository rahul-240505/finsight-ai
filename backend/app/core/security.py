"""Password hashing (Argon2id) and session tokens (ADR-005)."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# argon2-cffi defaults follow RFC 9106's low-memory profile: Argon2id, 64 MiB, 3 passes,
# 4 lanes, random 16-byte salt per hash. Slow and memory-hard on purpose.
_hasher = PasswordHasher()

# Verified when the email is unknown, so "no such user" costs the same time as
# "wrong password" and response timing doesn't reveal which emails exist.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """True only for a correct password. Never raises for a wrong password or a bad hash."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash used weaker parameters than today's; re-hash after a successful login."""
    return _hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    """256 bits from the OS random generator, URL-safe. Goes only into the cookie."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """What the database stores. A fast hash is fine here: the token is random, not guessable,
    so there is nothing to brute-force (unlike a password)."""
    return hashlib.sha256(token.encode()).hexdigest()
