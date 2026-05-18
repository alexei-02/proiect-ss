# RBAC Role Matrix

This document defines the roles used in the system and their permitted operations. The Auth epic implements enforcement; routes already declare required roles via `Depends(require_role(...))`.

## Roles

| Role | Description | Typical user |
|------|-------------|--------------|
| `admin` | Full system access; user management; system config | IT/operations team |
| `doctor` | Read/write patient data; resolve review queue items | Medical staff |
| `receptionist` | Upload documents; read patient data; no resolution | Front desk |
| `auditor` | Read-only access to anonymized data and metrics | Compliance, research |

## Permission matrix

| Route | admin | doctor | receptionist | auditor |
|-------|:-----:|:------:|:------------:|:-------:|
| `POST /api/v1/auth/login` | — | — | — | — (public) |
| `POST /api/v1/auth/refresh` | — | — | — | — (public) |
| `POST /api/v1/auth/logout` | ✓ | ✓ | ✓ | ✓ |
| `GET /api/v1/auth/me` | ✓ | ✓ | ✓ | ✓ |
| `POST /api/v1/admin/users` | ✓ | ✗ | ✗ | ✗ |
| `GET /api/v1/admin/users` | ✓ | ✗ | ✗ | ✗ |
| `GET /api/v1/admin/users/{id}` | ✓ | ✗ | ✗ | ✗ |
| `PATCH /api/v1/admin/users/{id}` | ✓ | ✗ | ✗ | ✗ |
| `POST /api/v1/documents` | ✓ | ✓ | ✓ | ✗ |
| `GET /api/v1/documents/{id}` | ✓ | ✓ | ✓ | ✓ (PHI masked) |
| `GET /api/v1/review-queue` | ✓ | ✓ | ✗ | ✗ |
| `POST /api/v1/review-queue/{id}/resolve` | ✓ | ✓ | ✗ | ✗ |
| `GET /api/v1/alerts` | ✓ | ✓ | ✗ | ✓ |
| `POST /api/v1/alerts/{id}/acknowledge` | ✓ | ✓ | ✗ | ✗ |
| `POST /api/v1/reports` | ✓ | ✗ | ✗ | ✓ |
| `GET /api/v1/reports/{id}/status` | ✓ | ✗ | ✗ | ✓ |
| `GET /api/v1/reports/{id}/download` | ✓ | ✗ | ✗ | ✓ |
| `GET /api/v1/metrics/ocr` | ✓ | ✗ | ✗ | ✓ |
| `GET /api/v1/audit-log` | ✓ | ✗ | ✗ | ✓ (IP→/24) |
| `GET /health`, `GET /ready` | — | — | — | — (public) |

## Admin user management constraints

- Admin cannot deactivate their own account (self-lockout prevention).
- Admin cannot remove the `admin` role from their own account.
- Deactivating a user (`is_active: false`) immediately revokes all their refresh tokens.
- All mutating operations (`create`, `update`) are written to the audit log with action `admin.user.create` or `admin.user.update`.
- Password minimum length: 12 characters (NIST SP 800-63B). Usernames: 3–64 chars, `[a-zA-Z0-9_\-]` only.
- Valid roles are `admin`, `doctor`, `receptionist`, `auditor`. A user may hold multiple roles.

## Implementation notes

- Use `Depends(require_role("admin"))` for single-role routes and `Depends(require_any_role("admin", "doctor"))` for multi-role routes. Both are defined in `app/core/security.py`.
- An `admin` does NOT automatically inherit lower roles — explicit allowlist per route. This avoids accidental privilege escalation.
- Roles are stored in the JWT `roles` claim (array of strings) and in `User.roles` (PostgreSQL `String[]`).
- Token TTL: 15 minutes for access tokens, 7 days for refresh tokens.
