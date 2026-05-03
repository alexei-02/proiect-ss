# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Medical OCR platform that ingests prescription images from edge devices via MQTT, extracts structured PHI fields using OCR, and serves results through a REST API for clinical review. Security is a primary concern — this system processes Protected Health Information (PHI).

## Commands

### Prerequisites

- `docker` with the compose plugin
- `openssl` (for cert generation)
- `curl` (used by `start.sh` health check)
- `python3` + `paho-mqtt` — only needed for `./start.sh --test-image` (`pip install paho-mqtt`)

### Dev Stack (everything in containers)

```bash
# Start the full stack — handles everything on first run:
#   - generates mTLS dev certs
#   - builds all images (first OCR build takes 10–15 min: bakes in ~500 MB of EasyOCR models)
#   - creates and applies the Prisma DB migration
#   - waits for the API to be healthy
./start.sh

# Start + send a sample prescription via MQTT after startup
./start.sh --test-image

# Tear down all containers and volumes
./start.sh --down
```

### Individual service rebuild

```bash
docker compose -f infrastructure/docker/docker-compose.dev.yml up --build -d api
docker compose -f infrastructure/docker/docker-compose.dev.yml logs -f api
docker compose -f infrastructure/docker/docker-compose.dev.yml logs -f ocr
```

### Prisma

```bash
# Browse the database (runs on http://localhost:5555)
cd services/api
DATABASE_URL=postgresql://medical:dev_only_replace_me@localhost:5432/medical_ocr \
  prisma studio --schema prisma/schema.prisma

# Create a new migration after schema changes
docker exec $(docker compose -f infrastructure/docker/docker-compose.dev.yml ps -q api) sh -c \
  "DATABASE_URL=postgresql://medical:dev_only_replace_me@postgres:5432/medical_ocr \
   prisma migrate dev --name <migration_name> --schema /app/prisma/schema.prisma --skip-generate"
# Then copy back to host:
docker cp <container_id>:/app/prisma/migrations ./services/api/prisma/migrations
```

### Tests

```bash
# API (80% branch coverage required)
cd services/api && pip install -e ".[dev]" && pytest -v --cov=app --cov-branch

# OCR worker
cd services/ocr && pip install -e ".[dev]" && pytest -v --cov=app --cov-branch

# Single test file
cd services/api && pytest tests/test_rate_limit.py -v
```

### Lint

```bash
cd services/api && ruff check app/ && ruff format app/
cd services/ocr && ruff check app/ && ruff format app/
```

### Send a test image via MQTT

```bash
python scripts/send_test_image.py \
  --device device_dev_001 \
  --file services/ocr/tests/fixtures/sample_prescription_01.png \
  --cert infrastructure/mosquitto/certs/device_dev_001.crt \
  --key  infrastructure/mosquitto/certs/device_dev_001.key \
  --ca   infrastructure/mosquitto/certs/ca.crt
```

API Swagger UI: `http://localhost:8989/docs`

## Architecture

```
Edge Devices → Mosquitto (mTLS 8883) → API Service → File Queue → OCR Worker
                                            ↓               ↓          ↓
                                       PostgreSQL ← Result Poller ← result.json
                                            ↓
                                       Doctor Review UI
```

Four trust zones (see `docs/ARCHITECTURE.md`):
- **internal** — API, OCR worker, DB (Docker internal network)
- **sandbox** — OCR worker: no network egress, read-only fs, drops all Linux caps
- **edge** — IoT devices authenticated by per-device mTLS certificates
- **untrusted** — Everything outside the platform boundary

### Services

**`services/api/`** — FastAPI REST API + MQTT consumer + result poller (Python 3.11+)
- `app/main.py` — App factory; lifespan connects Prisma, starts MQTT consumer and result poller
- `app/api/routes/` — Endpoints: `documents`, `review`, `metrics`, `health`
- `app/mqtt/consumer.py` — Subscribes to image/result MQTT topics, validates payloads
- `app/core/security.py` — **STUB**: Replace with real JWT verification for the Auth epic
- `app/core/middleware.py` — `BodySizeLimitMiddleware` enforces 10 MB cap (returns 413)
- `app/core/limiter.py` — Rate limiter (slowapi): 3/min on document upload
- `app/services/storage.py` — PostgreSQL via Prisma (`PostgresStore`)
- `app/services/result_poller.py` — Background task: polls `*.result.json` files every 2s, writes to DB
- `app/services/ocr_client.py` — Writes job files to the shared queue volume
- `app/schemas/ocr.py` — **Single source of truth** for the OCR JSON contract
- `prisma/schema.prisma` — Prisma schema (single `Document` model with JSONB `ocr_result`)
- `entrypoint.sh` — Runs `prisma migrate deploy` then starts uvicorn

**`services/ocr/`** — OCR worker (distroless, sandboxed)
- `app/worker.py` — Polling loop; picks up queue jobs, validates image, invokes OCR engine, writes results
- `app/core/engine.py` — Lazy-loads EasyOCR; falls back to mock when `MOCK_OCR=1`
- `app/core/extractor.py` — Field extraction heuristics; confidence gate ≥ 0.95
- `app/core/schemas.py` — `RawBlock`, `FieldName`, `ExtractedField` (mirrors API schema)

**`infrastructure/mosquitto/`** — MQTT broker
- TLS 1.3 only on port 8883, mTLS required, certificate CN → MQTT username for ACL
- `acl.conf` deny-by-default; explicit grants per role

## Data Flow

1. Device publishes image to `medical/images/{device_id}/upload` (mTLS)
2. Mosquitto verifies cert, ACL allows, forwards to API
3. API MQTT consumer creates `Document` row (`status=queued`) in PostgreSQL, writes `*.job.json` to `/queue` volume
4. OCR worker picks up job, validates image (PIL), runs EasyOCR, writes `*.result.json` to `/queue`
5. API result poller (every 2s) reads `*.result.json`, calls `store.attach_ocr_result()`, deletes file
6. `GET /api/v1/documents/{id}` returns:
   - `ocr_result: null` — still queued
   - `ocr_result: "pending_review"` — OCR done, confidence < 0.95 on ≥1 field
   - `ocr_result: { ...json... }` — completed, all fields ≥ 0.95
7. `GET /api/v1/review-queue` — returns full `OCRResult` objects for `pending_review` documents

## Key Constraints

**OCR schema**: `services/api/app/schemas/ocr.py` is the single contract. DB models and frontend types must mirror it exactly.

**Confidence threshold**: Default 0.95 in `services/ocr/app/core/config.py`. Patient-safety critical; do not lower without a TARA review.

**PHI encryption**: `patient_name`, `medication`, `raw_text`, and image bytes must be encrypted at rest (AES-256-GCM). The Prisma `ocrResult` JSONB column stores these unencrypted in dev — the DB epic owns the encryption layer. See `docs/PHI_FIELDS.md`.

**RBAC**: Four roles — `admin`, `doctor`, `receptionist`, `auditor`. Every route must declare its required role. See `docs/RBAC.md`.

**Auth stub**: `security.py` returns a hardcoded user. Do not change function signatures when implementing real JWT — routes depend on them.

**EasyOCR**: The production OCR image (`Dockerfile.ocr`) installs easyocr and uses `MOCK_OCR=0`. Tests and lightweight dev use `Dockerfile.dev` with `MOCK_OCR=1`. Model weights (~500 MB) are stored in the `easyocr_models` Docker volume and downloaded on first container start — never committed to the repo. Never import EasyOCR at module level — lazy-loaded in `engine.py`. Model cache path is controlled by `EASYOCR_MODULE_PATH` env var (mounted at `/models` in the container).

**Prisma migrations**: Migration files live in `services/api/prisma/migrations/` and are baked into the Docker image. After schema changes, generate a new migration inside the container and copy it back to the host (see Prisma commands above). `entrypoint.sh` runs `migrate deploy` on every container start.

**Persistent volumes**: `postgres_data` volume persists across `docker compose down`. Only `./start.sh --down` (which passes `-v`) wipes it.
