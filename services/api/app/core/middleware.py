"""Body size enforcement.

Returns 413 if the Content-Length header exceeds the configured limit.
Note: clients can lie about Content-Length; the check below is a fast
first-line of defense. The streaming reader in the upload route also
enforces the actual byte count.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared Content-Length exceeds the cap."""

    def __init__(self, app, *, max_upload: int, max_json: int) -> None:
        super().__init__(app)
        self.max_upload = max_upload
        self.max_json = max_json

    async def dispatch(self, request: Request, call_next):
        # Determine which limit applies based on path.
        is_upload = request.url.path.endswith("/documents") and request.method == "POST"
        limit = self.max_upload if is_upload else self.max_json

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": "Payload too large",
                            "max_bytes": limit,
                        },
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length"},
                )

        return await call_next(request)
