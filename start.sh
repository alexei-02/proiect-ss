#!/usr/bin/env bash
# Start the full dev stack in containers.
#
# Prerequisites: docker (with compose plugin), openssl, curl
# Optional (only for --test-image): python3 + paho-mqtt  (`pip install paho-mqtt`)
#
# Usage:
#   ./start.sh              — bring up all services
#   ./start.sh --test-image — also send a sample image via MQTT after startup
#   ./start.sh --down       — tear down all services and remove volumes
set -euo pipefail

COMPOSE="docker compose -f infrastructure/docker/docker-compose.dev.yml"
CERT_DIR="infrastructure/mosquitto/certs"
DEVICE_ID="device_dev_001"
SAMPLE_IMAGE="services/ocr/tests/fixtures/sample_prescription_01.png"
MIGRATIONS_DIR="services/api/prisma/migrations"

# ── Argument parsing ────────────────────────────────────────────────────────
SEND_TEST=false
TEARDOWN=false
for arg in "$@"; do
  case "$arg" in
    --test-image) SEND_TEST=true ;;
    --down)       TEARDOWN=true ;;
  esac
done

if $TEARDOWN; then
  echo ">> Tearing down stack..."
  $COMPOSE down -v
  exit 0
fi

# ── Prerequisites ────────────────────────────────────────────────────────────
for cmd in docker openssl curl; do
  if ! command -v "$cmd" &> /dev/null; then
    echo "ERROR: '$cmd' is required but not installed."
    exit 1
  fi
done
if ! docker compose version &> /dev/null; then
  echo "ERROR: 'docker compose' plugin is required."
  exit 1
fi
if $SEND_TEST; then
  if ! python3 -c "import paho.mqtt.client" &> /dev/null; then
    echo "ERROR: --test-image requires paho-mqtt: pip install paho-mqtt"
    exit 1
  fi
fi

# ── Certs ───────────────────────────────────────────────────────────────────
if [ ! -f "$CERT_DIR/ca.crt" ]; then
  echo ">> Dev certs not found — generating..."
  ./scripts/gen-dev-certs.sh
else
  echo ">> Dev certs already exist, skipping generation."
fi

# ── Start stack ─────────────────────────────────────────────────────────────
# NOTE: The OCR service (Dockerfile.ocr) downloads and bakes in ~500 MB of
# EasyOCR model weights during the build. First build takes 10–15 minutes.
# Subsequent builds reuse the Docker layer cache and are fast.
echo ">> Building and starting all services (first OCR build may take 10–15 min)..."
$COMPOSE up --build -d

# ── Prisma migrations ────────────────────────────────────────────────────────
# On first run there are no migration files, so entrypoint.sh's
# `prisma migrate deploy` is a no-op and the `documents` table is never
# created. Detect this, generate the migration non-interactively, copy it
# back to the host, then rebuild so future starts apply it automatically.
if [ ! -d "$MIGRATIONS_DIR" ] || [ -z "$(ls -A "$MIGRATIONS_DIR" 2>/dev/null)" ]; then
  echo ">> No Prisma migrations found — waiting for postgres to be ready..."
  sleep 5

  API_CONTAINER=$($COMPOSE ps -q api)
  echo ">> Creating initial migration..."
  docker exec "$API_CONTAINER" sh -c \
    "DATABASE_URL=postgresql://medical:dev_only_replace_me@postgres:5432/medical_ocr \
     prisma migrate dev --name init --schema /app/prisma/schema.prisma \
     --skip-generate --create-only" < /dev/null

  docker exec "$API_CONTAINER" sh -c \
    "DATABASE_URL=postgresql://medical:dev_only_replace_me@postgres:5432/medical_ocr \
     prisma migrate deploy --schema /app/prisma/schema.prisma"

  echo ">> Copying migration files to host..."
  docker cp "$API_CONTAINER":/app/prisma/migrations ./"$MIGRATIONS_DIR"

  echo ">> Rebuilding API image with baked-in migrations..."
  $COMPOSE up --build -d api
fi

# ── Wait for API ─────────────────────────────────────────────────────────────
echo ">> Waiting for API to become healthy..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8989/health > /dev/null 2>&1; then
    echo ">> API is up."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: API did not become healthy in time. Check logs:"
    echo "  $COMPOSE logs api"
    exit 1
  fi
  sleep 2
done

# ── Optional test image ─────────────────────────────────────────────────────
if $SEND_TEST; then
  if [ ! -f "$SAMPLE_IMAGE" ]; then
    echo "WARNING: Sample image not found at $SAMPLE_IMAGE — skipping MQTT test."
  else
    echo ">> Sending test image via MQTT..."
    python3 scripts/send_test_image.py \
      --device "$DEVICE_ID" \
      --file   "$SAMPLE_IMAGE" \
      --cert   "$CERT_DIR/${DEVICE_ID}.crt" \
      --key    "$CERT_DIR/${DEVICE_ID}.key" \
      --ca     "$CERT_DIR/ca.crt"
  fi
fi

echo ""
echo "Stack is running. Useful commands:"
echo "  API logs:       $COMPOSE logs -f api"
echo "  OCR logs:       $COMPOSE logs -f ocr"
echo "  Swagger UI:     http://localhost:8989/docs"
echo "  Prisma Studio:  http://localhost:5555"
echo "  Tear down:      ./start.sh --down"
