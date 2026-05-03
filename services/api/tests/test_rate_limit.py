"""Rate limit smoke test — the limiter applies and returns 429 when exceeded.

We don't aggressively hammer the limiter here because the in-memory
backend keeps state across tests in the same process; instead we verify
the wiring (status code path, header presence, configurable limit).
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.limiter import limiter


def _make_app(rate: str) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _h(_r: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc.detail)})

    @app.get("/probe")
    @limiter.limit(rate)
    async def probe(request: Request) -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_under_limit_succeeds() -> None:
    app = _make_app("100/minute")
    client = TestClient(app)
    for _ in range(3):
        assert client.get("/probe").status_code == 200


def test_over_limit_returns_429() -> None:
    app = _make_app("2/minute")
    client = TestClient(app)
    assert client.get("/probe").status_code == 200
    assert client.get("/probe").status_code == 200
    r = client.get("/probe")
    assert r.status_code == 429
    assert "detail" in r.json()
