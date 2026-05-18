# ── Build stage ──────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

# Install build deps only in the build stage so they don't bloat runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY prisma ./prisma
COPY scripts ./scripts

# Install Node.js in the build stage so prisma generate can use it
# (same version as the runtime stage to keep the nodeenv consistent).
RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# PRISMA_BINARY_CACHE_DIR redirects the engine binary download so it lands
# inside /build and can be copied to the runtime image — the non-root app
# user has no home directory and cannot create ~/.cache at runtime.
RUN pip install --no-cache-dir --prefix=/install . \
    && PYTHONPATH=/install/lib/python3.11/site-packages \
       PATH="/install/bin:$PATH" \
       PRISMA_BINARY_CACHE_DIR=/build/.prisma-cache \
       prisma generate --schema prisma/schema.prisma \
    && (PYTHONPATH=/install/lib/python3.11/site-packages \
           PATH="/install/bin:$PATH" \
           PRISMA_BINARY_CACHE_DIR=/build/.prisma-cache \
           prisma py fetch || true) \
    && (find /build/.prisma-cache /install/lib/python3.11/site-packages/prisma \
           -name "query-engine-debian-openssl-3.0.x" 2>/dev/null | head -1 | \
           xargs -I{} cp {} /build/.prisma-cache/prisma-query-engine-debian-openssl-3.0.x \
        || true)

# ── Runtime stage ────────────────────────────────────────────────────
# Slim, not distroless: the API needs to be able to handle TLS, env, and
# logging which are easier on slim. The OCR service (which is the high-risk
# component) gets distroless.
FROM python:3.11-slim-bookworm

# Install Node.js (Prisma CLI is Node-based; without it prisma tries to
# download Node via nodeenv which fails in the air-gapped internal network).
# Debian bookworm ships Node.js 18.x which satisfies Prisma 5.x (needs 16+).
RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user.
RUN groupadd --system --gid 65532 app \
    && useradd --system --uid 65532 --gid app --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --from=builder /build/prisma ./prisma
COPY --from=builder /build/scripts ./scripts
# Bake the Prisma engine binary into the image so it never needs downloading
# at runtime (the non-root app user has no home directory to cache into).
COPY --from=builder /build/.prisma-cache /var/cache/prisma
COPY app ./app

RUN chown -R 65532:65532 /var/cache/prisma \
    && chmod -R a+rx /var/cache/prisma

# Drop root.
USER 65532:65532

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PRISMA_BINARY_CACHE_DIR=/var/cache/prisma

EXPOSE 8989

# Use uvicorn directly. In production put this behind nginx or a service
# mesh proxy that terminates TLS.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8989", "--proxy-headers"]
