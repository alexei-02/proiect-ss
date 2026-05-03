# Medical OCR Platform

Secure web platform for processing medical documents via MQTT and OCR, with PHI protection, RBAC, and an AI-governed CI/CD pipeline.

## Repository structure

```
medical-ocr-platform/
├── services/
│   ├── api/              # REST API + MQTT consumer (FastAPI) — Data Ingestion epic
│   ├── ocr/              # OCR worker, sandboxed (EasyOCR)    — OCR Processing epic
│   └── web/              # Frontend dashboard (assigned)
├── infrastructure/
│   ├── mosquitto/        # MQTT broker config + ACL + certs
│   ├── nginx/            # Reverse proxy / TLS termination
│   ├── postgres/         # DB init scripts, schema migrations
│   └── docker/           # Shared base images, compose files
├── ci/
│   ├── policies/         # Security gate policies, RBAC for AI agents
│   └── scanners/         # SAST/DAST configs, SBOM tooling
├── docs/                 # Architecture, TARA, API reference
└── scripts/              # Dev tooling, cert generation, seed data
```

## Quick start (development)

```bash
# 1. Generate dev certs for mTLS
./scripts/gen-dev-certs.sh

# 2. Start the stack
docker compose -f infrastructure/docker/docker-compose.yml up -d

# 3. Run API tests
cd services/api && pytest

# 4. Open the dashboard
open https://localhost:8443
```

## Service responsibilities

| Service | Owner | Status | Description |
|---------|-------|--------|-------------|
| `services/api` | Alexei | ⏳ | REST endpoints + MQTT consumer for image ingestion |
| `services/ocr` | Alexei | ⏳ | Sandboxed OCR worker with confidence thresholding |
| `services/web` | TBD | ⏳ | React/Vue dashboard for review queue + reports |
| `infrastructure/postgres` | TBD | ⏳ | Schema, encryption-at-rest, migrations |
| `ci/*` | TBD | ⏳ | GitHub Actions, scanners, AI agent governance |

## Documentation

- [Data Ingestion & OCR — implementation guide](docs/DATA_INGESTION_AND_OCR.md) — **read this if you're integrating with the API or OCR service**
- [Architecture overview](docs/ARCHITECTURE.md)
- [TARA — threat model](docs/TARA.md)
- [API reference](docs/API.md)

## Branching & contributions

- `main` — protected; requires PR + review + green CI
- `develop` — integration branch
- `feature/<epic>-<short-name>` — your working branches (e.g. `feature/db-schema-design`)

Every PR must pass: unit tests, SAST (no new findings), branch coverage threshold, security gate review.
