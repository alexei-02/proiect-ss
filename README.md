# Medical OCR Platform

Secure web platform for processing medical documents via MQTT and OCR, with PHI protection, RBAC, and an AI-governed CI/CD pipeline.

## Repository structure

```
medical-ocr-platform/
├── services/
│   ├── api/              # REST API + MQTT consumer (FastAPI)
│   ├── ocr/              # OCR worker, sandboxed (EasyOCR)
│   └── frontend/         # Dashboard UI (Next.js 14)
├── infrastructure/
│   ├── mosquitto/        # MQTT broker config + ACL + certs
│   ├── docker/           # Compose files (dev, prod, security)
│   └── kubernetes/       # K8s manifests (deployments, network policies, HPA)
├── docs/                 # Architecture, TARA, implementation records
└── scripts/              # Dev tooling, cert generation, image builds, scan uploads
```

---

## Quick start (development)

**Prerequisites:** `docker` (with compose plugin), `openssl`, `curl`

```bash
# First run — generates mTLS certs, builds images, runs DB migrations,
# seeds the initial admin user, and waits for the API to be healthy.
# Note: first OCR build takes 10–15 min (downloads ~500 MB EasyOCR models).
./start.sh

# Start + send a sample prescription via MQTT after startup
./start.sh --test-image

# Tear down all containers and volumes
./start.sh --down
```

Services after startup:

| Service | URL |
|---|---|
| API + Swagger UI | `http://localhost:8989/docs` |
| Frontend dashboard | `http://localhost:3000` |
| MQTT broker | `localhost:8883` (mTLS only) |
| PostgreSQL | `localhost:5432` |
| Prisma Studio | `http://localhost:5555` |

---

## Authentication

All API routes (except `/health`, `/ready`, and the auth endpoints) require a **Bearer token**.

### Get a token

```bash
curl -s -X POST http://localhost:8989/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"dev_admin_replace_me"}' | jq .
```

Response:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<opaque>",
  "token_type": "Bearer",
  "expires_in": 900
}
```

Use the `access_token` in subsequent requests:

```bash
export TOKEN="<access_token>"
curl -H "Authorization: Bearer $TOKEN" http://localhost:8989/api/v1/auth/me
```

### Refresh and logout

```bash
# Rotate the refresh token (old token is revoked, new pair issued)
curl -s -X POST http://localhost:8989/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'

# Revoke one token
curl -X POST http://localhost:8989/api/v1/auth/logout \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'

# Revoke all tokens for this user
curl -X POST http://localhost:8989/api/v1/auth/logout \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Dev auth bypass

Set `DEV_AUTH_BYPASS=true` in the `api` service environment (already done in
`docker-compose.dev.yml`) to skip token verification when **no** `Authorization`
header is present. Requests without a header are treated as the built-in
`admin+doctor` dev user. This is **never** allowed when `ENV=production`.

---

## Roles & access

| Role | What they can do |
|---|---|
| `admin` | Full access to all endpoints |
| `doctor` | Upload documents, read documents (with PHI), manage review queue |
| `receptionist` | Upload and read documents |
| `auditor` | Read documents (PHI masked), view metrics, view audit log (IP masked to /24) |

Full matrix: see [docs/RBAC.md](docs/RBAC.md).

---

## API endpoints

### Auth
| Method | Path | Roles | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/login` | public | Exchange credentials for token pair |
| `POST` | `/api/v1/auth/refresh` | public | Rotate refresh token |
| `POST` | `/api/v1/auth/logout` | authenticated | Revoke token(s) |
| `GET` | `/api/v1/auth/me` | authenticated | Current user info |

### Documents
| Method | Path | Roles | Description |
|---|---|---|---|
| `POST` | `/api/v1/documents` | admin, doctor, receptionist | Upload a prescription image |
| `GET` | `/api/v1/documents/{id}` | all | Fetch document + OCR result (PHI masked for auditor) |

### Review queue
| Method | Path | Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/review-queue` | admin, doctor | List items below confidence threshold |
| `POST` | `/api/v1/review-queue/{id}/resolve` | admin, doctor | Mark a review item as resolved |

### Reports & alerts
| Method | Path | Roles | Description |
|---|---|---|---|
| `POST` | `/api/v1/reports` | admin, auditor | Request a new report (async, CSV) |
| `GET` | `/api/v1/reports/{id}/status` | admin, auditor | Poll generation status |
| `GET` | `/api/v1/reports/{id}/download` | admin, auditor | Download completed CSV |
| `GET` | `/api/v1/alerts` | admin, auditor, doctor | List compliance / expiry alerts |
| `POST` | `/api/v1/alerts/{id}/acknowledge` | admin, doctor | Acknowledge an alert |

### Admin — user management
| Method | Path | Roles | Description |
|---|---|---|---|
| `POST` | `/api/v1/admin/users` | admin | Create a new user |
| `GET` | `/api/v1/admin/users` | admin | List all users (paginated) |
| `GET` | `/api/v1/admin/users/{id}` | admin | Get a single user |
| `PATCH` | `/api/v1/admin/users/{id}` | admin | Update roles, active status, or password |

### Metrics & audit
| Method | Path | Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/metrics/ocr` | admin, auditor | OCR latency (p50/p95), queue depth, success rate |
| `GET` | `/metrics/prometheus` | internal | Prometheus text exposition |
| `GET` | `/api/v1/audit-log` | admin, auditor | Paginated PHI-access audit log |

### Health
| Method | Path | Roles | Description |
|---|---|---|---|
| `GET` | `/health` | public | Liveness check |
| `GET` | `/ready` | public | Readiness check |

Full interactive docs: `http://localhost:8989/docs`

---

## Running tests

Tests use a mocked Prisma client — no running database required.

```bash
# API service
cd services/api
pip install -e ".[dev]"
pytest -v --cov=app --cov-branch

# OCR worker
cd services/ocr
pip install -e ".[dev]"
pytest -v --cov=app --cov-branch

# Single file
cd services/api && pytest tests/test_crypto.py -v
```

Coverage thresholds: **≥ 80% branch** overall; `app/core/security.py` and `app/core/crypto.py` target **100%**.

---

## Sending a test image via MQTT

```bash
python scripts/send_test_image.py \
  --device device_dev_001 \
  --file services/ocr/tests/fixtures/sample_prescription_01.png \
  --cert infrastructure/mosquitto/certs/device_dev_001.crt \
  --key  infrastructure/mosquitto/certs/device_dev_001.key \
  --ca   infrastructure/mosquitto/certs/ca.crt
```

---

## Prisma (database)

```bash
# Browse the database (http://localhost:5555)
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

---

## Key environment variables (api service)

| Variable | Dev default | Description |
|---|---|---|
| `JWT_SECRET` | `dev-jwt-secret-…` | HMAC signing secret — **replace before real data** |
| `JWT_SECRET_FILE` | — | Path to file containing `JWT_SECRET` (Docker/K8s secrets) |
| `PHI_MASTER_KEY` | `000…001` (64 hex chars) | AES-256 key for PHI encryption — **replace before real data** |
| `PHI_MASTER_KEY_FILE` | — | Path to file containing `PHI_MASTER_KEY` |
| `DEV_AUTH_BYPASS` | `false` | `true` skips auth when no `Authorization` header is present |
| `INITIAL_ADMIN_USERNAME` | `admin` | Seeded on first container start |
| `INITIAL_ADMIN_PASSWORD` | `dev_admin_replace_me` | Seeded on first container start |
| `DATABASE_URL` | `postgresql://medical:…@postgres:5432/medical_ocr` | Postgres DSN |
| `DATABASE_URL_FILE` | — | Path to file containing `DATABASE_URL` |
| `ENV` | `development` | `development` / `test` / `production` |

> **⚠️ Before handling any real PHI:** rotate `JWT_SECRET` and `PHI_MASTER_KEY` to
> cryptographically random values. See [docs/runbooks/phi_key_rotation.md](docs/runbooks/phi_key_rotation.md).

---

## Individual service rebuild

```bash
docker compose -f infrastructure/docker/docker-compose.dev.yml up --build -d api
docker compose -f infrastructure/docker/docker-compose.dev.yml logs -f api
docker compose -f infrastructure/docker/docker-compose.dev.yml logs -f ocr
```

---

## Linting

```bash
cd services/api && ruff check app/ && ruff format --check app/
cd services/ocr && ruff check app/ && ruff format --check app/
```

---

## Service responsibilities

| Component | Owner | Status |
|---|---|:---:|
| Data Ingestion & APIs | Andrei Alexei | ✅ |
| OCR Processing Engine | Andrei Alexei | ✅ |
| Database & Storage | Saleem Al-Bouri | ✅ |
| Access Control & Auth | Saleem Al-Bouri | ✅ |
| Reporting & Dashboard | Alexandru Vidu | ✅ |
| Embedded / Mobile Client | TBD | ⏳ |
| CI/CD Pipeline & Governance | TBD | ⏳ |
| AI-Assisted CI/CD (optional arch) | TBD | ⏳ |
| Infrastructure & DevOps | Alexandru Vidu | ✅ |

---

## Documentation

- [Architecture overview](docs/ARCHITECTURE.md)
- [Data Ingestion & OCR — implementation guide](docs/DATA_INGESTION_AND_OCR.md)
- [Database & Auth — implementation record](docs/DATABASE_AND_RBAC.md)
- [Reporting & Dashboard — implementation record](docs/REPORTING_AND_DASHBOARD.md)
- [Infrastructure & DevOps — implementation record](docs/INFRASTRUCTURE_AND_DEVOPS.md)
- [RBAC matrix](docs/RBAC.md)
- [PHI fields & encryption](docs/PHI_FIELDS.md)
- [TARA — threat model](docs/TARA.md)

## Branching & contributions

- `main` — protected; requires PR + review + green CI
- `develop` — integration branch
- `feature/<short-name>` — working branches (e.g. `feature/db-schema-design`)

Every PR must pass: unit tests, SAST (no new findings), branch coverage threshold, security gate review.
