"""RBAC matrix integration tests.

Each (role, route) pair is table-driven against the matrix in docs/RBAC.md.
This test fails if the code drifts from the documented matrix.
"""

from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


# ─── matrix ─────────────────────────────────────────────────────────────────
# (roles, method, path_template, expected_status, kwargs)
# 404 counts as "authorised" (got past auth); 403 means "denied".

_MATRIX = [
    # POST /documents — admin, doctor, receptionist allowed; auditor denied
    (["admin"],        "POST", "/api/v1/documents", 202, {}),
    (["doctor"],       "POST", "/api/v1/documents", 202, {}),
    (["receptionist"], "POST", "/api/v1/documents", 202, {}),
    (["auditor"],      "POST", "/api/v1/documents", 403, {}),

    # GET /documents/{id} — all roles allowed (auditor sees masked PHI)
    (["admin"],        "GET", "/api/v1/documents/{id}", 404, {}),
    (["doctor"],       "GET", "/api/v1/documents/{id}", 404, {}),
    (["receptionist"], "GET", "/api/v1/documents/{id}", 404, {}),
    (["auditor"],      "GET", "/api/v1/documents/{id}", 404, {}),

    # GET /review-queue — admin and doctor only
    (["admin"],        "GET", "/api/v1/review-queue", 200, {}),
    (["doctor"],       "GET", "/api/v1/review-queue", 200, {}),
    (["receptionist"], "GET", "/api/v1/review-queue", 403, {}),
    (["auditor"],      "GET", "/api/v1/review-queue", 403, {}),

    # POST /review-queue/{id}/resolve — admin and doctor only
    (["admin"],        "POST", "/api/v1/review-queue/{id}/resolve", 404, {}),
    (["doctor"],       "POST", "/api/v1/review-queue/{id}/resolve", 404, {}),
    (["receptionist"], "POST", "/api/v1/review-queue/{id}/resolve", 403, {}),
    (["auditor"],      "POST", "/api/v1/review-queue/{id}/resolve", 403, {}),

    # GET /metrics/ocr — admin and auditor only
    (["admin"],        "GET", "/api/v1/metrics/ocr", 200, {}),
    (["auditor"],      "GET", "/api/v1/metrics/ocr", 200, {}),
    (["doctor"],       "GET", "/api/v1/metrics/ocr", 403, {}),
    (["receptionist"], "GET", "/api/v1/metrics/ocr", 403, {}),

    # GET /audit-log — admin and auditor only
    (["admin"],        "GET", "/api/v1/audit-log", 200, {}),
    (["auditor"],      "GET", "/api/v1/audit-log", 200, {}),
    (["doctor"],       "GET", "/api/v1/audit-log", 403, {}),
    (["receptionist"], "GET", "/api/v1/audit-log", 403, {}),
]


def _ids(entry):
    roles, method, path, expected, _ = entry
    return f"{method}:{path}:{'+'.join(roles)}→{expected}"


@pytest.mark.parametrize("roles,method,path_tpl,expected_status,kwargs", _MATRIX, ids=_ids)
def test_rbac(
    client: TestClient,
    auth_as,
    roles: list[str],
    method: str,
    path_tpl: str,
    expected_status: int,
    kwargs: dict,
) -> None:
    random_id = str(uuid4())
    path = path_tpl.replace("{id}", random_id)
    headers = auth_as(roles)

    if method == "POST" and "/documents" in path and not path.endswith("/resolve"):
        resp = client.post(
            path,
            headers=headers,
            data={"device_id": "dev-001"},
            files={"file": ("img.png", BytesIO(b"\x89PNG\r\n"), "image/png")},
        )
    elif method == "POST" and path.endswith("/resolve"):
        resp = client.post(
            path,
            headers=headers,
            json={"corrected_fields": {"patient_name": "Jane"}},
        )
    else:
        resp = client.request(method, path, headers=headers)

    assert resp.status_code == expected_status, (
        f"{method} {path} with roles={roles}: "
        f"expected {expected_status}, got {resp.status_code} — {resp.text[:200]}"
    )
