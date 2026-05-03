# ── Build stage ──────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

# Install build deps only in the build stage so they don't bloat runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir --prefix=/install .

# ── Runtime stage ────────────────────────────────────────────────────
# Slim, not distroless: the API needs to be able to handle TLS, env, and
# logging which are easier on slim. The OCR service (which is the high-risk
# component) gets distroless.
FROM python:3.11-slim-bookworm

# Create non-root user.
RUN groupadd --system --gid 65532 app \
    && useradd --system --uid 65532 --gid app --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder /install /usr/local
COPY app ./app

# Drop root.
USER 65532:65532

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8989

# Use uvicorn directly. In production put this behind nginx or a service
# mesh proxy that terminates TLS.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8989", "--proxy-headers"]
