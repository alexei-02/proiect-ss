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

### Summary

| Component | Owner | Status |
|---------|-------|--------|
| Data Ingestion & APIs | Andrei Alexei | ⏳ |
| OCR Processing Engine | Andrei Alexei | ⏳ |
| Database & Storage | Saleem Al-Bouri | ⏳ |
| Access Control & Auth | Saleem Al-Bouri | ⏳
| Reporting & Dashboard | TBD | ⏳ |
| Embedded / Mobile Client | TBD | ⏳ |
| CI/CD Pipeline & Governance | TBD | ⏳ |
| AI-Assisted CI/CD (optional arch) | TBD | ⏳ |
| Infrastructure & DevOps | TBD | ⏳ |

### Data Ingestion & APIs

| # | Task | Description | Tags | Effort |
|---|------|-------------|------|:------:|
| t1 | Set up MQTT broker (Mosquitto) | TLS/mTLS, rate limiting, payload size limits for DoS prevention | backend, security | M |
| t2 | Implement REST/GraphQL API layer | Authenticated endpoints for frontend; input validation on all routes | backend | M |
| t3 | API rate limiting & DoS protection middleware | Token bucket or sliding window; configurable per route | backend, security | S |
| t4 | MQTT topic ACL configuration | Per-role topic permissions, client certificate validation | backend, security | S |

### OCR Processing Engine

| # | Task | Description | Tags | Effort |
|---|------|-------------|------|:------:|
| t5 | Integrate OCR engine (EasyOCR or DeepSeek) | Dockerized, distroless or gVisor sandbox; no root privileges | ml, security | L |
| t6 | Define structured JSON output schema | Fields: PatientName, Medication, ExpiryDate, confidence scores per field | ml, backend | S |
| t7 | Confidence thresholding logic | Flag any field below 95% confidence for manual review queue | ml, backend | S |
| t8 | OCR sandbox isolation | Distroless container or gVisor runtime; block network egress from OCR process | security, infra | M |
| t9 | Malicious image handling & fuzzing | Reject corrupt/oversized inputs; integrate API fuzzer in pipeline | security, ml | M |

### Database & Storage

| # | Task | Description | Tags | Effort |
|---|------|-------------|------|:------:|
| t10 | PostgreSQL schema design | Tables: patients, documents, ocr_results, review_queue, users, roles | backend | M |
| t11 | PHI encryption at rest | Column-level encryption for sensitive fields; key management (e.g. Vault, KMS) | security, backend | L |
| t12 | TLS on all internal service connections | DB ↔ API, API ↔ OCR; mTLS preferred; certificate rotation plan | security, infra | M |
| t13 | Database migration tooling | Alembic or Flyway; versioned, reversible migrations | backend, infra | S |

### Access Control & Auth

| # | Task | Description | Tags | Effort |
|---|------|-------------|------|:------:|
| t14 | RBAC model design | Roles: admin, doctor, receptionist, auditor; permissions matrix document | security, backend | M |
| t15 | JWT or session-based authentication | Short-lived tokens, refresh flow, revocation list | security, backend | M |
| t16 | RBAC enforcement middleware | Every API route checks role; deny by default | security, backend | M |
| t17 | Audit log for all PHI access | Immutable append-only log: who, what, when, from where | security, backend | M |

### Reporting & Dashboard

| # | Task | Description | Tags | Effort |
|---|------|-------------|------|:------:|
| t18 | Dynamic report generator | Pluggable report types; async generation for large datasets | backend | L |
| t19 | Compliance / expiry alerts | Daily cron: workers expiring next 30 days, overdue renewals | backend | M |
| t20 | Anonymised dataset export | Auto-mask PHI fields; only available to auditor/research roles | backend, security | M |
| t21 | System performance metrics | OCR latency p50/p95, success rate, queue depth; expose via API | backend, infra | S |
| t22 | Frontend dashboard UI | Review queue, report viewer, alert list, role-based views | frontend | L |

### Embedded / Mobile Client

| # | Task | Description | Tags | Effort |
|---|------|-------------|------|:------:|
| t23 | Mobile camera capture flow | iOS/Android or PWA; document framing UX, image pre-validation | embedded, frontend | M |
| t24 | MQTT client with mTLS | paho-mqtt or equiv; device certificate provisioning flow | embedded, security | M |
| t25 | Offline mode & local storage | SD/flash queue when server unreachable; auto-retry on reconnect | embedded | M |
| t26 | OTA firmware update mechanism (bonus) | Triggered via MQTT message or HTTP endpoint; signed firmware bundles | embedded, security | L |

### CI/CD Pipeline & Governance

| # | Task | Description | Tags | Effort |
|---|------|-------------|------|:------:|
| t27 | SCM setup & branch protection | GitHub/GitLab; main branch requires PR + review + green pipeline | cicd | S |
| t28 | Unit test suite (100% branch coverage on security boundaries) | Auth, RBAC, OCR confidence gating, encryption paths | cicd, security | L |
| t29 | SAST integration (static analysis) | Bandit/Semgrep; SARIF export; pipeline fails on new findings | cicd, security | M |
| t30 | DAST & API fuzzer integration | OWASP ZAP or Nuclei; run against staging; results to central dashboard | cicd, security | M |
| t31 | Security gateway (no-merge policy enforcement) | Pipeline gate: all scans green + human approval before merge to main | cicd, security | M |
| t32 | SBOM generation at build time | CycloneDX or SPDX; auto-attached to every release artifact | cicd, infra | S |
| t33 | Immutable audit archive | All AI prompts, decisions, tool calls, test evidence stored append-only | cicd, security | M |

### AI-Assisted CI/CD (optional arch)

| # | Task | Description | Tags | Effort |
|---|------|-------------|------|:------:|
| t34 | AI orchestrator & agent swarm setup | Agents propose code/PRs only; no autonomous deployment permission | cicd, infra | L |
| t35 | MCP capability gateway & allowlist | Restrict which CI tools agents can invoke; RBAC for agent actions | cicd, security | L |
| t36 | Outbound quarantine sandbox for AI-generated code | Run & test AI patches in isolation before human sees the PR | cicd, security | L |
| t37 | RAG knowledge store for agents | Vector DB with project metadata, approved schemas, security guidelines | cicd, ml | M |
| t38 | Human-in-the-loop approval gate (deterministic proof) | Approval service logs every decision with timestamp + approver identity | cicd, security | M |

### Infrastructure & DevOps

| # | Task | Description | Tags | Effort |
|---|------|-------------|------|:------:|
| t39 | Docker Compose / Kubernetes manifests | Service mesh with TLS; separate namespaces for OCR sandbox | infra | L |
| t40 | Secret management | Vault or cloud KMS; no secrets in env files or repos | infra, security | M |
| t41 | Centralised security findings dashboard | Aggregate SARIF from SAST/DAST; single pane of glass | infra, security | M |
| t42 | TARA (Threat Analysis & Risk Assessment) document | Required deliverable; identify threats per component, rate residual risk | security | L |

---

## Documentation

- [Data Ingestion & OCR — implementation guide](docs/DATA_INGESTION_AND_OCR.md) — **read this if you're integrating with the API or OCR service**
- [Architecture overview](docs/ARCHITECTURE.md)
- [TARA — threat model](docs/TARA.md)
- [API reference](docs/API.md)

## Branching & contributions

- `main` — protected; requires PR + review + green CI
- `develop` — integration branch
- `feature/<short-name>` — your working branches (e.g. `feature/db-schema-design`)

Every PR must pass: unit tests, SAST (no new findings), branch coverage threshold, security gate review.
