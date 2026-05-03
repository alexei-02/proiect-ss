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

| Operation | admin | doctor | receptionist | auditor |
|-----------|:-----:|:------:|:------------:|:-------:|
| Upload document via API | ✓ | ✓ | ✓ | ✗ |
| Read document by ID | ✓ | ✓ | ✓ | partial† |
| List review queue | ✓ | ✓ | ✗ | ✗ |
| Resolve review item | ✓ | ✓ | ✗ | ✗ |
| Read OCR metrics | ✓ | ✗ | ✗ | ✓ |
| Read anonymized reports | ✓ | ✓ | ✗ | ✓ |
| Manage users / roles | ✓ | ✗ | ✗ | ✗ |
| Generate compliance alerts | ✓ | ✓ | ✗ | ✓ |

† Auditor sees documents with PHI fields auto-masked.

## Implementation notes

- Routes declare a single role via `Depends(require_role("doctor"))`. If a route is accessible by multiple roles, use `Depends(require_any_role("doctor", "admin"))` (the helper is to be added by the Auth epic).
- An `admin` does NOT automatically inherit lower roles — explicit allowlist. This avoids accidental privilege escalation.
- Roles are stored in the JWT claims under `roles` (array of strings).
- Token TTL: 15 minutes for access tokens, 7 days for refresh tokens (proposal — Auth epic to confirm).
