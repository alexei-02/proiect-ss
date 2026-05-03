#!/usr/bin/env bash
# Start the full dev stack in containers.
#
# Usage:
#   ./start.sh              — bring up all services
#   ./start.sh --test-image — also send a sample image via MQTT after startup
#   ./start.sh --down       — tear down all services and remove volumes
set -euo pipefail

COMPOSE="docker compose -f infrastructure/docker/docker-compose.dev.yml"
CERT_DIR="infrastructure/mosquitto/certs"
DEVICE_ID="device_dev_001"
SAMPLE_IMAGE="services/ocr/tests/fixtures/sample_prescription.png"

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

# ── Certs ───────────────────────────────────────────────────────────────────
if [ ! -f "$CERT_DIR/ca.crt" ]; then
  echo ">> Dev certs not found — generating..."
  ./scripts/gen-dev-certs.sh
else
  echo ">> Dev certs already exist, skipping generation."
fi

# ── Start stack ─────────────────────────────────────────────────────────────
echo ">> Building and starting all services..."
$COMPOSE up --build -d

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
echo "  Tear down:      ./start.sh --down"
