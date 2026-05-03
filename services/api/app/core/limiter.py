"""Rate limiter — uses slowapi (a Starlette wrapper for the limits library).

We key on client IP for unauthenticated routes and on user.id for
authenticated routes. The key function below picks the right one.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _key(request: Request) -> str:
    """Per-user key when authenticated, per-IP otherwise.

    The user identity is set by the auth dependency on `request.state.user`.
    Falls back to remote IP when no user is bound (anonymous endpoints
    or pre-auth middleware).
    """
    user = getattr(request.state, "user", None)
    if user is not None:
        return f"user:{user.id}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_key)
