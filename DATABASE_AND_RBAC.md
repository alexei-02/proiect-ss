# Database & Storage + Access Control & Auth — Implementation Plan

## Context

The medical OCR platform currently has a working ingestion + OCR pipeline backed by a single `Document` Prisma model and a stub `security.py`. PHI (`patient_name`, `medication`, `raw_text`) is stored as plaintext JSONB and every route trusts a hardcoded dev user. This plan implements two epics from the project task board so the system can hold real PHI safely and enforce the RBAC matrix in [docs/RBAC.md](docs/RBAC.md):

- **Database & Storage** (t10–t13): expand the schema for users/auth/audit, add column-level AES-256-GCM encryption for PHI fields, stage Postgres TLS for production.
- **Access Control & Auth** (t14–t17): implement JWT auth (login/refresh/logout/me) with refresh-token rotation, real `get_current_user`, `require_any_role` helper, RBAC matrix wiring, and an immutable audit log of PHI access.

User decisions (locked in):
- Auditor gets `GET /documents/{id}` with PHI masked (matches RBAC matrix).
- Postgres TLS configured for prod only; dev stays on the internal Docker network without TLS (production startup guard refuses non-TLS DSN).
- One bundled PR for both epics.

Hard constraints from [CLAUDE.md](CLAUDE.md):
- Public interface of [security.py](services/api/app/core/security.py) (`User`, `get_current_user`, `require_role`) must not change — only function bodies.
- The 5-method interface of `PostgresStore` in [storage.py](services/api/app/services/storage.py) must not change. `__init__` may take additional optional params.
- OCR JSON contract in [services/api/app/schemas/ocr.py](services/api/app/schemas/ocr.py) is the single source of truth.
- DB tooling stays Prisma — no Alembic.

---

## Architectural decisions

**Schema shape.** Add `User`, `RefreshToken`, `AuditLog` models. Do NOT split `documents` into `patients/ocr_results/review_queue` — premature normalization that would break the storage contract and the OCR pipeline for no query we actually run today. Roles stored as `String[]` on `User` (closed enum of 4 values, no metadata needed yet). Document this trade-off in [docs/RBAC.md](docs/RBAC.md).

**Encryption boundary.** PHI is encrypted in [storage.py](services/api/app/services/storage.py) at write, decrypted at read. The `OCRResult` Pydantic model stays plaintext-in-app. Algorithm: AES-256-GCM via `cryptography`. Envelope format stored as a string `enc:v1:base64(key_id||nonce(12)||tag(16)||ct)` replacing each PHI value inside the existing JSONB shape. `expiry_date` stays plaintext (not PHI). Keys come from a `KeyProvider` abstraction (`EnvKeyProvider` for dev, KMS/Vault later); leading byte = `key_id` enables rotation without breaking old envelopes. Image bytes are not currently persisted by the API → out of scope.

**JWT.** PyJWT, HS256 in dev / RS256 in prod. Claims: `sub`, `username`, `roles`, `jti`, `iat`, `exp`, `type` (access|refresh), `iss`, `aud`. TTLs: access 15 min, refresh 7 d. Refresh-token rotation on every `/refresh` (old row revoked, new pair issued — replay of revoked refresh logs an `auth.refresh.replay` audit event). No access-token jti denylist; rely on 15-min TTL plus a per-user `is_active` kill switch checked in `get_current_user` with a 30 s in-memory cache.

**Password hashing.** `argon2-cffi`, argon2id, OWASP 2024 params (`time_cost=3`, `memory_cost=64 MiB`, `parallelism=4`).

**RBAC enforcement.** Add `require_any_role(*roles)` in [security.py](services/api/app/core/security.py); make `require_role(role)` a thin alias (back-compat). Update existing routes to use `require_any_role` per the matrix in [docs/RBAC.md](docs/RBAC.md). For auditor on `GET /documents/{id}`: mask PHI in a route-layer helper `app/services/masking.py` (storage interface stays clean).

**Audit log.** Two writers: (a) `AuditMiddleware` logs every PHI-touching request after the auth dep populates `request.state.user`; (b) `PostgresStore` emits `phi.decrypt` events via an optional `audit_sink` callable. Storage in same Postgres DB but append-only enforced by a `BEFORE UPDATE OR DELETE` trigger that raises (defense-in-depth even if the app DB role gets compromised). Exposed via `GET /api/v1/audit-log` (admin/auditor only, cursor-paginated on `id`, IP masked to /24 for auditor).

**Postgres TLS.** Production only. Config additions to docker-compose.dev.yml gated by env var so the dev stack stays simple. Production `DATABASE_URL` requires `sslmode=verify-full` — startup guard in `app/main.py` lifespan raises if `env=production` and DSN doesn't include it. API↔OCR uses a shared volume (no network) so no TLS needed; add HMAC signing of `*.job.json` / `*.result.json` files as a follow-up.

**Initial admin seed.** Idempotent `scripts/seed_initial_admin.py` reads `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` env vars; if set and no admin exists, creates one. Hooked into [entrypoint.sh](services/api/entrypoint.sh) after `prisma migrate deploy`. Dev compose passes `admin` / `dev_admin_replace_me`.

**Dev ergonomics.** New setting `dev_auth_bypass: bool = False`. When `env=development` AND `dev_auth_bypass=true` AND no `Authorization` header is present, `get_current_user` returns the existing fake `dev-user` (admin + doctor). Default OFF — devs exercise the real path locally. Hard refusal at startup if `env=production` with bypass on.

**Pre-prod data.** No real PHI in dev DB → truncate `documents` as part of rollout. Documented in the new runbook, not in a migration.

---

## Files to create

- [services/api/app/core/crypto.py](services/api/app/core/crypto.py) — `PhiCipher`, `KeyProvider`, `EnvKeyProvider`. Pure unit-testable.
- [services/api/app/core/jwt_utils.py](services/api/app/core/jwt_utils.py) — `encode_access`, `encode_refresh`, `decode_token`, `verify_key`, `signing_key`.
- [services/api/app/core/passwords.py](services/api/app/core/passwords.py) — `hash_password`, `verify_password` (with constant-time dummy-verify on unknown-user path so login timing is uniform).
- [services/api/app/core/audit.py](services/api/app/core/audit.py) — `AuditEvent` model, `AuditSink` protocol, `AuditMiddleware`, `PHI_TOUCHING_PATHS` whitelist.
- [services/api/app/api/routes/auth.py](services/api/app/api/routes/auth.py) — `/login`, `/refresh`, `/logout`, `/me`. Per-route slowapi limits (5/min login, 10/min refresh).
- [services/api/app/api/routes/audit_log.py](services/api/app/api/routes/audit_log.py) — `GET /api/v1/audit-log`, paginated, filter by user_id/action/from/to, admin+auditor only.
- [services/api/app/schemas/auth.py](services/api/app/schemas/auth.py) — `LoginRequest`, `TokenResponse`, `RefreshRequest`, `LogoutRequest`, `UserMe`.
- [services/api/app/schemas/audit.py](services/api/app/schemas/audit.py) — `AuditLogEntry`, `AuditLogPage`.
- [services/api/app/services/masking.py](services/api/app/services/masking.py) — `mask_phi(doc: DocumentResponse) -> DocumentResponse`. Used in `documents.py` for auditor-only callers.
- [services/api/app/services/users.py](services/api/app/services/users.py) — `UserStore` over Prisma: `get_by_username`, `create_user`, `set_active`, `record_login`. Keeps `PostgresStore` focused on Documents.
- [services/api/app/services/refresh_tokens.py](services/api/app/services/refresh_tokens.py) — `RefreshTokenStore`: issue, lookup-by-hash, revoke, rotate, cleanup-expired.
- [services/api/prisma/migrations/<ts>_users_refresh_tokens_audit_logs/migration.sql](services/api/prisma/migrations) — new tables, indexes, audit-log trigger.
- [services/api/prisma/migrations/<ts>_document_indexes/migration.sql](services/api/prisma/migrations) — `(status, submittedAt)` and `(deviceId)` indexes on `documents`.
- [scripts/seed_initial_admin.py](scripts/seed_initial_admin.py) — idempotent admin seeding.
- [docs/runbooks/db_migrations.md](docs/runbooks/db_migrations.md) — migration creation + reversibility policy.
- [docs/runbooks/phi_key_rotation.md](docs/runbooks/phi_key_rotation.md) — key rotation operational steps.
- [docs/runbooks/postgres_tls_prod.md](docs/runbooks/postgres_tls_prod.md) — production TLS setup.
- New tests: [tests/test_crypto.py](services/api/tests/test_crypto.py), [tests/test_security.py](services/api/tests/test_security.py), [tests/test_auth_routes.py](services/api/tests/test_auth_routes.py), [tests/test_storage_encryption.py](services/api/tests/test_storage_encryption.py), [tests/test_audit_log.py](services/api/tests/test_audit_log.py), [tests/test_rbac_matrix.py](services/api/tests/test_rbac_matrix.py), [tests/test_masking.py](services/api/tests/test_masking.py).

## Files to modify

- [services/api/prisma/schema.prisma](services/api/prisma/schema.prisma) — add `User`, `RefreshToken`, `AuditLog`; add indexes to `Document`.
- [services/api/app/core/security.py](services/api/app/core/security.py) — replace stub bodies (signatures unchanged); add `require_any_role`; alias `require_role`; per-user `is_active` kill switch with 30 s cache.
- [services/api/app/core/config.py](services/api/app/core/config.py) — add `jwt_secret`, `jwt_algorithm`, `jwt_audience`, `jwt_issuer`, `jwt_access_ttl_seconds`, `jwt_refresh_ttl_seconds`, `phi_master_key`, `phi_key_provider`, `dev_auth_bypass`, `initial_admin_username`, `initial_admin_password`.
- [services/api/app/services/storage.py](services/api/app/services/storage.py) — `__init__(db, cipher, audit_sink=None)`; encrypt PHI in `attach_ocr_result`; decrypt in `_to_response` and `list_review_queue`; emit `phi.decrypt` audit events; resilient per-row decrypt with fallback (log + skip).
- [services/api/app/main.py](services/api/app/main.py) — instantiate `PhiCipher` and `KeyProvider` in lifespan; pass to `PostgresStore`; mount `AuditMiddleware`; mount auth + audit-log routers; production TLS startup guard; refresh-token cleanup task (hourly).
- [services/api/app/api/routes/documents.py](services/api/app/api/routes/documents.py) — `POST` → `require_any_role("admin","doctor","receptionist")`; `GET` → `require_any_role("admin","doctor","receptionist","auditor")`, mask PHI when caller is auditor-only; remove the duplicate `_user` parameter on the GET handler.
- [services/api/app/api/routes/review.py](services/api/app/api/routes/review.py) — both routes → `require_any_role("admin","doctor")`.
- [services/api/app/api/routes/metrics.py](services/api/app/api/routes/metrics.py) → `require_any_role("admin","auditor")`.
- [services/api/entrypoint.sh](services/api/entrypoint.sh) — run `seed_initial_admin.py` after `prisma migrate deploy`.
- [services/api/pyproject.toml](services/api/pyproject.toml) — add deps: `pyjwt[crypto]`, `argon2-cffi`, `cryptography`. Add per-module 100% branch coverage gate for `app/core/security.py` and `app/core/crypto.py`.
- [infrastructure/docker/docker-compose.dev.yml](infrastructure/docker/docker-compose.dev.yml) — pass new env vars to `api` (`JWT_SECRET`, `PHI_MASTER_KEY`, `INITIAL_ADMIN_*`, `DEV_AUTH_BYPASS=false`).
- [services/api/tests/conftest.py](services/api/tests/conftest.py) — `auth_as(roles, user_id=...)` fixture that mints a signed Bearer token using the test JWT secret; in-memory `PhiCipher` with a fixed test key; in-memory `AuditSink` that records events.
- [docs/RBAC.md](docs/RBAC.md) — note that `require_any_role` exists; document role-array choice.
- [docs/PHI_FIELDS.md](docs/PHI_FIELDS.md) — document the `enc:v1:` envelope and decrypt resilience policy.
- [CLAUDE.md](CLAUDE.md) — add a short "Auth & encryption" subsection covering env vars, dev bypass, seed admin command, and key rotation pointer.

## Files NOT to modify

- [services/api/app/schemas/ocr.py](services/api/app/schemas/ocr.py) — contract is fixed.
- [services/api/app/mqtt/consumer.py](services/api/app/mqtt/consumer.py), [services/api/app/services/result_poller.py](services/api/app/services/result_poller.py), [services/api/app/services/ocr_client.py](services/api/app/services/ocr_client.py) — call sites already use the unchanged `PostgresStore` interface.
- [services/ocr/](services/ocr/) — OCR worker is upstream of encryption.

---

## Schema additions (Prisma DSL)

```prisma
model User {
  id            String         @id @default(uuid()) @db.Uuid
  username      String         @unique
  passwordHash  String         @map("password_hash")
  roles         String[]       // {"admin","doctor","receptionist","auditor"} validated in code
  isActive      Boolean        @default(true) @map("is_active")
  createdAt     DateTime       @default(now()) @map("created_at")
  lastLoginAt   DateTime?      @map("last_login_at")
  refreshTokens RefreshToken[]
  auditLogs     AuditLog[]
  @@map("users")
}

model RefreshToken {
  id         String    @id @default(uuid()) @db.Uuid
  userId     String    @map("user_id") @db.Uuid
  tokenHash  String    @unique @map("token_hash")
  jti        String    @unique
  expiresAt  DateTime  @map("expires_at")
  revokedAt  DateTime? @map("revoked_at")
  createdAt  DateTime  @default(now()) @map("created_at")
  userAgent  String?   @map("user_agent")
  ipAddress  String?   @map("ip_address")
  user       User      @relation(fields: [userId], references: [id], onDelete: Cascade)
  @@index([userId])
  @@index([expiresAt])
  @@map("refresh_tokens")
}

model AuditLog {
  id           BigInt   @id @default(autoincrement())
  occurredAt   DateTime @default(now()) @map("occurred_at")
  userId       String?  @map("user_id") @db.Uuid
  username     String?
  action       String
  resourceType String?  @map("resource_type")
  resourceId   String?  @map("resource_id")
  ipAddress    String?  @map("ip_address")
  userAgent    String?  @map("user_agent")
  outcome      String   // success | denied | error
  metadata     Json?    // never plaintext PHI
  user         User?    @relation(fields: [userId], references: [id], onDelete: SetNull)
  @@index([occurredAt])
  @@index([userId, occurredAt])
  @@index([action, occurredAt])
  @@index([resourceType, resourceId])
  @@map("audit_logs")
}
```

Plus a raw-SQL block in the migration for the append-only trigger:

```sql
CREATE OR REPLACE FUNCTION audit_logs_no_change() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_logs is append-only'; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_no_update_or_delete
  BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_logs_no_change();
```

And `Document` indexes (separate migration):

```sql
CREATE INDEX documents_status_submitted_at_idx ON documents (status, submitted_at);
CREATE INDEX documents_device_id_idx           ON documents (device_id);
```

---

## Auth route shapes

```
POST /api/v1/auth/login        body {username,password}        → {access_token, refresh_token, token_type:"Bearer", expires_in}
POST /api/v1/auth/refresh      body {refresh_token}            → same shape (rotation)
POST /api/v1/auth/logout       Bearer + body {refresh_token?}  → 204
GET  /api/v1/auth/me           Bearer                          → {id, username, roles}
GET  /api/v1/audit-log         Bearer (admin|auditor)          → {entries[], next_cursor}
```

Login returns identical 401 message and identical timing whether the username is unknown or the password is wrong (constant-time argon2 verify against a dummy hash on unknown user).

---

## RBAC matrix wiring (concrete)

| File | Route | Before | After |
|---|---|---|---|
| documents.py | `POST /documents` | `require_role("doctor")` | `require_any_role("admin","doctor","receptionist")` |
| documents.py | `GET /documents/{id}` | `require_role("doctor")` (duplicate dep) | `require_any_role("admin","doctor","receptionist","auditor")`; route masks PHI when caller is auditor-only |
| review.py | `GET /review-queue` | `require_role("doctor")` | `require_any_role("admin","doctor")` |
| review.py | `POST /review-queue/{id}/resolve` | `require_role("doctor")` | `require_any_role("admin","doctor")` |
| metrics.py | `GET /metrics/ocr` | `require_role("auditor")` | `require_any_role("admin","auditor")` |

`/health` and `/ready` stay unauthenticated.

---

## Test plan

- **test_crypto.py** — round-trip; tampered ciphertext, nonce, tag rejected; rotation (encrypt with key 0, rotate to 1, old envelope still decrypts, new encrypts use key 1); unknown key id rejected.
- **test_security.py** — every branch in `get_current_user`, `require_role`, `require_any_role`: missing header, malformed header, bad sig, expired, wrong audience, wrong issuer, refresh-as-access, disabled user, dev bypass on/off, role hit/miss for any-of/single-of. Target: 100% branch coverage on this file.
- **test_auth_routes.py** — login success / wrong password / unknown user (assert response body and timing are within tolerance); refresh success / expired / revoked-replay (asserts an `auth.refresh.replay` audit row is written); logout single-token vs all-tokens; `/me`.
- **test_storage_encryption.py** — `attach_ocr_result` then read raw JSONB column directly; assert each PHI field starts with `enc:v1:` and plaintext does not appear; `get_document` returns plaintext; `list_review_queue` decrypts; corrupted envelope on one row degrades gracefully (others still returned, error audit row written).
- **test_audit_log.py** — middleware writes a row on PHI-touching paths, no row on `/health`; `outcome=denied` on 403; decrypt sink writes `phi.decrypt` rows; the trigger blocks UPDATE/DELETE (raw SQL test); `GET /audit-log` is admin/auditor only; auditor sees IP masked to /24.
- **test_rbac_matrix.py** — table-driven `(route, role) → allowed?` pairs straight from the matrix; this test fails if [docs/RBAC.md](docs/RBAC.md) drifts from the code.
- **test_masking.py** — `mask_phi` zeros patient_name, medication, raw_text; leaves expiry_date, confidence, status untouched.

`conftest.py` gains an `auth_as` fixture that mints a Bearer header for arbitrary `(user_id, roles)`. Existing tests that don't care about auth keep working because the test client sets `dev_auth_bypass=True` in the `_test_env` fixture.

Coverage gate: `pytest --cov=app --cov-branch` with `pyproject.toml` `[tool.coverage.report] fail_under = 80` AND a CI command `coverage report --include='app/core/security.py,app/core/crypto.py' --fail-under=100`.

---

## Risks and mitigations

1. **Encryption mis-wire breaks the result poller.** Mitigation: API startup fails fast if `PHI_MASTER_KEY` missing (Settings validator). End-to-end test asserts MQTT-image → DB row → API read returns plaintext.
2. **Decrypt failure on one row breaks `list_review_queue`.** Mitigation: per-row try/except; log to audit with `outcome=error`; skip row from response; surface a degraded count in metrics.
3. **JWT clock skew.** Mitigation: `leeway=10` on decode.
4. **Refresh tokens accumulate.** Mitigation: hourly background task in lifespan deletes rows where `expires_at < now() - 7 days`.
5. **Audit log table grows fast.** Mitigation: documented retention is 6 yr (compliance floor); follow-up ticket for partitioning by month.
6. **Rotation/destruction script accidentally double-encrypts.** Mitigation: rotation script asserts plaintext doesn't already start with `enc:v1:` before encrypting.
7. **Dev auth bypass leaks to prod.** Mitigation: hard startup refusal in `app/main.py` if `env=production` and `dev_auth_bypass=true`.

---

## Verification

After implementation:

1. **Stack boots.** `./start.sh --down && ./start.sh` — all containers healthy, `/health` and `/ready` return 200.
2. **Initial admin seeded.** `docker compose ... exec api python -c "from prisma import Prisma; ..."` shows one `users` row with role `admin`. Idempotency: re-run `seed_initial_admin.py`, assert no second admin created.
3. **Login flow.** `curl -X POST /api/v1/auth/login -d '{"username":"admin","password":"dev_admin_replace_me"}'` returns `{access_token, refresh_token, ...}`. Decode the JWT (jwt.io) and verify claims.
4. **Auth enforcement.** `curl /api/v1/documents/<id>` without Bearer → 401. With doctor's Bearer → 200. With auditor's Bearer → 200 with PHI masked. With receptionist's Bearer on `/review-queue` → 403.
5. **End-to-end OCR with encryption.** `./start.sh --test-image` and verify:
   - DB shell (`prisma studio`) shows `documents.ocr_result.fields.patient_name.value` starts with `enc:v1:`.
   - `GET /api/v1/documents/<id>` (with auth) returns the plaintext OCR result.
6. **Audit log.** Hit `GET /api/v1/documents/<id>` then `GET /api/v1/audit-log` as admin → at least one row with `action=document.read` matching the doc id, plus a `phi.decrypt` row from the storage sink. As auditor, IP is `xxx.xxx.xxx.0/24`.
7. **Refresh rotation replay-detection.** Take a refresh token, exchange for new pair, then try to refresh with the OLD token → 401 and an `auth.refresh.replay` audit row.
8. **Append-only trigger.** `docker compose exec postgres psql ... -c "DELETE FROM audit_logs LIMIT 1;"` → error `audit_logs is append-only`.
9. **Dev bypass off.** Set `DEV_AUTH_BYPASS=false`, restart api, verify `curl /api/v1/documents/<id>` (no Bearer) returns 401.
10. **Production guard.** Locally set `ENV=production` and `DATABASE_URL=postgresql://...` (no sslmode) → app fails to start with a clear error.
11. **Tests.** `cd services/api && pytest -v --cov=app --cov-branch` — all green, ≥80% branch overall, 100% on `security.py` and `crypto.py`.
12. **Lint.** `ruff check app/ && ruff format --check app/` clean.

---

## Out of scope (track as follow-ups)

- Splitting `documents` into `patients/ocr_results/review_queue` separate tables.
- Image-bytes encryption (API doesn't persist images today).
- mTLS to Postgres (certs are staged by the cert-gen script; switching `pg_hba.conf` to `cert` auth is a one-PR follow-up).
- HMAC signing of OCR queue files.
- KMS / Vault key provider implementations (only `EnvKeyProvider` lands now).
- User management routes (`POST/GET/PATCH/DELETE /users`) — admin can be seeded; further user CRUD is a separate epic.
- Audit log partitioning, ship-to-Loki/Splunk.
- `POST /auth/me/change-password` for the seeded admin to rotate their password post-deploy.
- Audit log retention enforcement (6-yr policy is documented, automation is a follow-up).