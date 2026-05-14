# Reporting & Dashboard — Implementation Record

## Status: ✅ Implemented

Tasks t18–t22 are fully implemented across the API service and the new `services/frontend/` Next.js app.

---

## What was built

| Task | Status | Notes |
|---|:---:|---|
| t18 Dynamic report generator | ✅ | Pluggable async CSV generator; four report types |
| t19 Compliance / expiry alerts | ✅ | Daily cron at 02:00 UTC; JSONB expiry scan via raw SQL |
| t20 Anonymised dataset export | ✅ | Reuses `mask_phi()`; cursor-based streaming; audit logged |
| t21 System performance metrics | ✅ | Real `percentile_cont` aggregations; Prometheus endpoint |
| t22 Frontend dashboard UI | ✅ | Next.js 14, Tailwind, role-based views, API proxy |

---

## New files

### API service

| File | Purpose |
|---|---|
| `services/api/app/schemas/reports.py` | `ReportType`, `ReportRequest`, `ReportStatusResponse`, `AlertResponse` |
| `services/api/app/services/report_runner.py` | Async CSV generator registry; `run_report()` writes atomically via temp-file rename |
| `services/api/app/services/alert_generator.py` | `scan_expiry_alerts()` — raw SQL JSONB scan, creates `Alert` rows |
| `services/api/app/services/scheduler.py` | Daily asyncio loop; calls `scan_expiry_alerts` at 02:00 UTC |
| `services/api/app/api/routes/reports.py` | `POST /api/v1/reports`, `GET /{id}/status`, `GET /{id}/download` |
| `services/api/app/api/routes/alerts.py` | `GET /api/v1/alerts`, `POST /{id}/acknowledge` |
| `services/api/tests/test_reports.py` | Report lifecycle, RBAC, streaming download |
| `services/api/tests/test_alerts.py` | Alert generation, acknowledge, RBAC |
| `services/api/tests/test_metrics_real.py` | Real aggregation coverage |
| `services/api/tests/test_anonymised_export.py` | PHI masking verification |

### Frontend

| File | Purpose |
|---|---|
| `services/frontend/lib/auth.ts` | JWT decode + `hasRole()` — no library dependency |
| `services/frontend/lib/api.ts` | Typed `apiFetch<T>()` wrapper using Next.js API proxy |
| `services/frontend/middleware.ts` | Redirects unauthenticated requests to `/login` |
| `services/frontend/components/RoleGuard.tsx` | Client-side gate; renders "Access denied" for wrong roles |
| `services/frontend/components/Sidebar.tsx` | Role-filtered nav; logout clears cookie |
| `services/frontend/components/MetricCard.tsx` | Metric display tile |
| `services/frontend/app/login/page.tsx` | Credential form → Bearer token cookie |
| `services/frontend/app/dashboard/page.tsx` | OCR metrics (admin, auditor) |
| `services/frontend/app/review-queue/page.tsx` | Pending docs; approve action; 15 s auto-refresh |
| `services/frontend/app/reports/page.tsx` | Report request form + status polling + CSV download |
| `services/frontend/app/alerts/page.tsx` | Alert list; severity badges; acknowledge action |
| `services/frontend/app/audit-log/page.tsx` | Paginated audit entries |

---

## Modified files

| File | Change |
|---|---|
| `services/api/app/api/routes/metrics.py` | Replaced zero-stub with real `COUNT` + `percentile_cont` raw queries |
| `services/api/app/main.py` | Registers `reports` + `alerts` routers; starts scheduler task in lifespan |
| `services/api/prisma/schema.prisma` | Added `Report` and `Alert` models; added `reports[]` relation on `User` |
| `services/api/pyproject.toml` | Added `prometheus-fastapi-instrumentator` |
| `infrastructure/docker/docker-compose.dev.yml` | Added `frontend` service on port 3000 |

---

## API surface added

### Reports

| Method | Path | Roles | Description |
|---|---|---|---|
| `POST` | `/api/v1/reports` | admin, auditor | Request a new report (async generation) |
| `GET` | `/api/v1/reports/{id}/status` | admin, auditor | Poll generation status |
| `GET` | `/api/v1/reports/{id}/download` | admin, auditor | Stream completed CSV |

### Alerts

| Method | Path | Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/alerts` | admin, auditor, doctor | List alerts; filter by `acknowledged`, `severity` |
| `POST` | `/api/v1/alerts/{id}/acknowledge` | admin, doctor | Mark alert as acknowledged |

### Metrics

| Method | Path | Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/metrics/ocr` | admin, auditor | `queue_depth`, `completed_last_24h`, `p50_latency_ms`, `p95_latency_ms` |
| `GET` | `/metrics/prometheus` | internal only | Prometheus text exposition |

---

## Report types

| Type | Content |
|---|---|
| `ocr_summary` | One row per document — `id`, `device_id`, `status`, `submitted_at`, `p50_latency_ms` |
| `audit_export` | `AuditLog` rows; optional `date_from` / `date_to` params filter by `occurred_at` |
| `compliance` | Two columns — `document_id`, `expiry_date_value` — for every completed doc with an `expiry_date` OCR field |
| `anonymised_export` | All documents with PHI fields masked to `***`; cursor-batched in groups of 500 |

Every report submission and download emits an `AuditEvent` (`report.create` and `report.download` respectively) so any data export is traceable from the audit log.

---

## Role → view matrix (frontend)

| View | admin | doctor | receptionist | auditor |
|---|:---:|:---:|:---:|:---:|
| Dashboard (metrics) | ✓ | — | — | ✓ |
| Review queue | ✓ | ✓ | ✓ | — |
| Reports | ✓ | — | — | ✓ |
| Alerts | ✓ | ✓ | — | ✓ |
| Audit log | ✓ | — | — | ✓ |

---

## Prisma schema additions

Two new models added to `prisma/schema.prisma`. Run a migration to apply:

```bash
docker exec $(docker compose -f infrastructure/docker/docker-compose.dev.yml ps -q api) sh -c \
  "DATABASE_URL=postgresql://medical:dev_only_replace_me@postgres:5432/medical_ocr \
   prisma migrate dev --name add_reports_alerts --schema /app/prisma/schema.prisma --skip-generate"
docker cp <container_id>:/app/prisma/migrations ./services/api/prisma/migrations
```

---

## Frontend quick start

The frontend is included in the dev Compose stack and requires no separate setup:

```bash
./start.sh   # frontend available at http://localhost:3000
```

Log in with the seeded admin credentials (`admin` / `dev_admin_replace_me`). The Next.js dev server proxies all `/api/*` requests to `http://api:8989`, so no CORS configuration is needed.
