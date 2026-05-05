"""Password hashing with argon2id (OWASP 2024 parameters)."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

# Pre-hashed dummy used on unknown-user path to keep login timing uniform.
_DUMMY_HASH = _HASHER.hash("_dummy_constant_time_placeholder_")  # noqa: S106


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(plain: str, hashed: str | None) -> bool:
    """Constant-time verify. Returns False (without short-circuiting) when hashed is None."""
    if hashed is None:
        # Run dummy verify so timing matches a real verify attempt.
        try:
            _HASHER.verify(_DUMMY_HASH, plain)
        except VerifyMismatchError:
            pass
        return False
    try:
        return _HASHER.verify(hashed, plain)
    except VerifyMismatchError:
        return False
