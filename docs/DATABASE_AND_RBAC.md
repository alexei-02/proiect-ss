# Database & Storage + Access Control & Auth — Implementation Record

## Status: ✅ Implemented

Both epics (t10–t17) are fully implemented on this branch. This document records what was built, the key decisions made, and where each piece lives.

---

## What was built

### Database & Storage (t10–t13)

| Task | Status | Notes |
|---|:---:|---|
| t10 PostgreSQL schema design | ✅ | `User`, `RefreshToken`, `AuditLog` added; `Document` indexes added |
| t11 PHI encryption at rest | ✅ | AES-256-GCM column-level encryption via `PhiCipher` |
| t12 TLS on internal connections | ✅ | Production startup guard; dev stays plain on internal Docker network |
| t13 Database migration tooling | ✅ | Two new Prisma migrations; append-only trigger in SQL |

### Access Control & Auth (t14–t17)

| Task | Status | Notes |
|---|:---:|---|
| t14 RBAC model design | ✅ | Four roles; `require_any_role` + updated route matrix |
| t15 JWT authentication | ✅ | HS256, 15-min access / 7-day refresh, rotation, revocation |
| t16 RBAC enforcement middleware | ✅ | Every route gated; deny by default |
| t17 Audit log for PHI access | ✅ | Append-only table + middleware + phi.decrypt sink events |

---

## New files

| File | Purpose |
|---|---|
| `services/api/app/core/crypto.py` | `PhiCipher`, `KeyProvider`, `EnvKeyProvider` — AES-256-GCM PHI encryption |
| `services/api/app/core/jwt_utils.py` | `encode_access`, `encode_refresh`, `decode_token` |
| `services/api/app/core/passwords.py` | argon2id hashing; constant-time dummy verify for unknown users |
| `services/api/app/core/audit.py` | `AuditEvent`, `PrismaAuditSink`, `AuditMiddleware` |
| `services/api/app/schemas/auth.py` | `LoginRequest`, `TokenResponse`, `RefreshRequest`, `LogoutRequest`, `UserMe` |
| `services/api/app/schemas/audit.py` | `AuditLogEntry`, `AuditLogPage` |
| `services/api/app/services/users.py` | `UserStore` — Prisma wrapper for user CRUD |
| `services/api/app/services/refresh_tokens.py` | `RefreshTokenStore` — issue / rotate / revoke / cleanup |
| `services/api/app/services/masking.py` | `mask_phi()` — redacts PHI for auditor-only callers |
| `services/api/app/api/routes/auth.py` | `/login`, `/refresh`, `/logout`, `/me` |
| `services/api/app/api/routes/audit_log.py` | `GET /api/v1/audit-log` |
| `services/api/scripts/seed_initial_admin.py` | Idempotent admin seeder (called by `entrypoint.sh`) |
| `services/api/prisma/migrations/20260505120000_users_refresh_tokens_audit_logs/` | New tables + append-only trigger |
| `services/api/prisma/migrations/20260505120001_document_indexes/` | `(status, submitted_at)` and `(device_id)` indexes |
| `services/api/tests/test_crypto.py` | Encryption round-trip, tamper detection, key rotation |
| `services/api/tests/test_security.py` | Full branch coverage of `security.py` |
| `services/api/tests/test_auth_routes.py` | Login, refresh, logout, /me integration tests |
| `services/api/tests/test_storage_encryption.py` | PHI encrypt/decrypt, corrupted envelope resilience |
| `services/api/tests/test_audit_log.py` | Middleware, sink, endpoint, IP masking |
| `services/api/tests/test_rbac_matrix.py` | Table-driven RBAC matrix tests |
| `services/api/tests/test_masking.py` | PHI field masking for auditor responses |

---

## Modified files

| File | Change |
|---|---|
| `services/api/app/core/security.py` | Real JWT verification, `require_any_role`, `is_active` kill switch, dev bypass |
| `services/api/app/core/config.py` | Added JWT, PHI key, auth bypass, seed admin settings |
| `services/api/app/services/storage.py` | `__init__(db, cipher=None, audit_sink=None)`; PHI encrypt on write, decrypt on read |
| `services/api/app/main.py` | Wires cipher, audit sink, user/RT stores; mounts `AuditMiddleware`; auth+audit routers; production TLS guard; hourly token cleanup |
| `services/api/app/api/routes/documents.py` | `POST` → `admin/doctor/receptionist`; `GET` → all roles + PHI masked for auditor |
| `services/api/app/api/routes/review.py` | Both routes → `admin/doctor` |
| `services/api/app/api/routes/metrics.py` | `GET /metrics/ocr` → `admin/auditor` |
| `services/api/prisma/schema.prisma` | `User`, `RefreshToken`, `AuditLog` models; `Document` indexes |
| `services/api/pyproject.toml` | Added `pyjwt[crypto]`, `argon2-cffi`, `cryptography` |
| `services/api/entrypoint.sh` | Runs `seed_initial_admin.py` after `prisma migrate deploy` |
| `services/api/Dockerfile.dev` | Copies `scripts/` into the image |
| `infrastructure/docker/docker-compose.dev.yml` | New env vars: `JWT_SECRET`, `PHI_MASTER_KEY`, `DEV_AUTH_BYPASS`, `INITIAL_ADMIN_*` |
| `services/api/tests/conftest.py` | `mock_db` fixture (no real DB in tests), `auth_as`, `phi_cipher`, `in_memory_audit_sink`; `_ACTIVE_CACHE` cleared between tests |

---

## Architectural decisions (locked in)

**Schema shape.** Added `User`, `RefreshToken`, `AuditLog`. Did NOT split `documents` into separate tables — premature normalization that would break the storage interface and OCR pipeline.

**Encryption boundary.** PHI (`patient_name`, `medication`, `raw_text`) encrypted in `storage.py` at write, decrypted at read. Encryption happens at the raw-dict level, before Pydantic validation, so encrypted envelopes (which can exceed `max_length=512`) never pass through `ExtractedField` validators.

Envelope format: `enc:v1:<base64(key_id_byte || nonce_12 || tag_16 || ciphertext)>`  
Leading `key_id` byte enables rotation: old envelopes decrypt with their original key; new writes always use the current key. `expiry_date` is not PHI and stays plain.

**JWT.** PyJWT, HS256 in dev/test. Claims: `sub`, `username`, `roles`, `jti`, `iat`, `exp`, `type`, `iss`, `aud`. TTLs: access 15 min, refresh 7 days. Refresh token rotation on every `/refresh` (old row revoked → new pair issued). Replay of a revoked refresh token revokes the entire user's family and emits `auth.refresh.replay` audit event. No access-token denylist; rely on 15-min TTL + per-user `is_active` kill switch cached 30 s.

**Password hashing.** argon2id, OWASP 2024 params (`time_cost=3`, `memory_cost=64 MiB`, `parallelism=4`). Constant-time dummy verify on unknown-user path so login timing is uniform.

**RBAC enforcement.** `require_any_role(*roles)` in `security.py`; `require_role(role)` is a thin alias (back-compat). Auditor gets `GET /documents/{id}` with PHI masked via `mask_phi()` in the route layer (storage interface stays clean).

**Audit log.** Two writers: `AuditMiddleware` (per PHI-touching request) and `PostgresStore` (`phi.decrypt` events). Append-only enforced by a `BEFORE UPDATE OR DELETE` trigger that raises. `GET /api/v1/audit-log` is admin+auditor only; auditor sees IP masked to `/24`.

**Postgres TLS.** Production only. Startup guard in `main.py` raises if `env=production` and `DATABASE_URL` doesn't contain `sslmode=`. Dev stays plain on the internal Docker network.

**Dev auth bypass.** `DEV_AUTH_BYPASS=true` (with `env != "production"`) returns a fake `admin+doctor` user when no `Authorization` header is present. Hard startup refusal in `config.py` if `env=production` and `dev_auth_bypass=true`.

**Initial admin seed.** `scripts/seed_initial_admin.py` reads `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD`; if set and no admin exists, creates one. Idempotent — safe to run on every container start.

---

## RBAC matrix (implemented)

| Route | admin | doctor | receptionist | auditor |
|---|:---:|:---:|:---:|:---:|
| `POST /api/v1/documents` | ✅ | ✅ | ✅ | ❌ |
| `GET /api/v1/documents/{id}` | ✅ | ✅ | ✅ | ✅ (PHI masked) |
| `GET /api/v1/review-queue` | ✅ | ✅ | ❌ | ❌ |
| `POST /api/v1/review-queue/{id}/resolve` | ✅ | ✅ | ❌ | ❌ |
| `GET /api/v1/metrics/ocr` | ✅ | ❌ | ❌ | ✅ |
| `GET /api/v1/audit-log` | ✅ | ❌ | ❌ | ✅ (IP→/24) |
| `POST /api/v1/auth/login` | — | — | — | — (public) |
| `POST /api/v1/auth/refresh` | — | — | — | — (public) |
| `POST /api/v1/auth/logout` | any authenticated | | | |
| `GET /api/v1/auth/me` | any authenticated | | | |
| `GET /health`, `GET /ready` | — | — | — | — (public) |

---

## New environment variables

| Variable | Required | Default (dev) | Description |
|---|:---:|---|---|
| `JWT_SECRET` | yes | `change-me-…` | HMAC signing secret — replace before any real data |
| `JWT_ALGORITHM` | no | `HS256` | `HS256` for dev; switch to `RS256` for prod with key pair |
| `JWT_ACCESS_TTL_SECONDS` | no | `900` | Access token lifetime (15 min) |
| `JWT_REFRESH_TTL_SECONDS` | no | `604800` | Refresh token lifetime (7 days) |
| `PHI_MASTER_KEY` | yes | `000…001` | 64 hex chars (32 bytes) — replace before any real data |
| `DEV_AUTH_BYPASS` | no | `false` | `true` returns fake admin when no `Authorization` header |
| `INITIAL_ADMIN_USERNAME` | no | `admin` | Seeded on first container start |
| `INITIAL_ADMIN_PASSWORD` | no | `dev_admin_replace_me` | Seeded on first container start |

---

## Out of scope (follow-ups)

- Splitting `documents` into `patients/ocr_results/review_queue` separate tables.
- Image-bytes encryption (API doesn't persist images today).
- mTLS to Postgres (certs are staged; switching `pg_hba.conf` to `cert` auth is a one-PR follow-up).
- HMAC signing of OCR queue files.
- KMS / Vault key provider (only `EnvKeyProvider` ships now).
- User management routes (`POST/GET/PATCH/DELETE /users`).
- `POST /auth/me/change-password` for the seeded admin.
- Audit log partitioning and ship-to-Loki/Splunk.
- Audit log retention enforcement (6-yr policy documented, automation is a follow-up).
