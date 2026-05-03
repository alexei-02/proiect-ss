# ─────────────────────────────────────────────────────────────────────
# OCR worker Dockerfile — sandboxed runtime.
#
# Why distroless: the OCR worker processes attacker-controlled image bytes
# through C-language image decoders (libpng, libjpeg, libwebp). These
# libraries have a long CVE history. If a malicious image triggers RCE
# inside the OCR process, distroless minimizes what the attacker can do:
#   - No shell (no /bin/sh, /bin/bash) → no easy reverse shell.
#   - No package manager → can't install tools.
#   - Minimal libc surface → fewer privesc primitives.
#   - Runs as nonroot UID 65532 by default.
#
# Pair this image with these runtime flags (see docker-compose.yml):
#   --read-only
#   --tmpfs /tmp:size=100m,rw,exec=false,nosuid
#   --cap-drop=ALL
#   --security-opt=no-new-privileges
#   --network=ocr-internal      # no internet egress
#
# ─────────────────────────────────────────────────────────────────────

# ── Build stage ──────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

# Install with the optional [ocr] extra to pull in easyocr.
# In CI for unit tests only, build with --build-arg INSTALL_OCR=0.
ARG INSTALL_OCR=1
RUN if [ "$INSTALL_OCR" = "1" ]; then \
        pip install --no-cache-dir --prefix=/install ".[ocr]"; \
    else \
        pip install --no-cache-dir --prefix=/install .; \
    fi

# ── Runtime stage (distroless) ───────────────────────────────────────
FROM gcr.io/distroless/python3-debian12:nonroot

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY app ./app

# Distroless nonroot is UID 65532. Just to be explicit.
USER 65532:65532

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OCR_QUEUE_DIR=/queue

# No EXPOSE — the worker has no listening ports; it pulls from a shared volume.

# Distroless has no shell, so we can't use a shell-form CMD.
ENTRYPOINT ["python", "-m", "app.worker"]
