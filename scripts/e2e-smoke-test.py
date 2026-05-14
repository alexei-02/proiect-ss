#!/usr/bin/env python3
"""End-to-end smoke test for the Reporting & Dashboard epic.

Seeds the test data it needs, drives every sidebar tab in a real browser via
Playwright, and prints a pass/fail line per check.

Usage:
    pip install --user playwright
    python -m playwright install chromium
    python scripts/e2e-smoke-test.py

Requires the dev stack running (./start.sh).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

BASE = "http://localhost:3000"
API = "http://localhost:8989"
ADMIN_USER, ADMIN_PASS = "admin", "dev_admin_replace_me"
DOCTOR_USER, DOCTOR_PASS = "doc1", "test123"

PASS = FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    mark = "\033[32m✓\033[0m" if condition else "\033[31m✗\033[0m"
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {mark} {name}{suffix}")
    if condition:
        PASS += 1
    else:
        FAIL += 1


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def wait_for_stack(timeout_s: int = 30) -> None:
    """Block until API and Frontend respond."""
    deadline = time.time() + timeout_s
    for url in (f"{API}/health", f"{BASE}/login"):
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(1)
        else:
            print(f"\033[31mTimed out waiting for {url}\033[0m")
            sys.exit(2)


def api_container_id() -> str:
    return subprocess.check_output([
        "docker", "compose", "-f",
        "infrastructure/docker/docker-compose.dev.yml", "ps", "-q", "api"
    ]).decode().strip()


def seed_via_api_container(py: str) -> None:
    """Run a one-shot Python snippet inside the API container."""
    subprocess.run(
        ["docker", "exec", "-i", api_container_id(), "python3", "-c", py],
        check=True,
    )


SEED_SCRIPT = """
import asyncio
from prisma import Prisma, Json
from app.core.passwords import hash_password
from app.services.alert_generator import scan_expiry_alerts

async def main():
    db = Prisma()
    await db.connect()

    # Doctor user (idempotent)
    try:
        await db.user.create(data={
            'username': 'doc1',
            'passwordHash': hash_password('test123'),
            'roles': ['doctor'],
        })
    except Exception:
        pass

    # Wipe Epic-5 test state
    await db.alert.delete_many(where={})
    await db.document.delete_many(where={'deviceId': 'smoke-test'})

    # Three completed docs (drive non-zero p50/p95 + completed_last_24h)
    for ms in (1000, 1500, 2500):
        d = await db.document.create(data={'deviceId': 'smoke-test', 'status': 'completed'})
        await db.document.update(where={'id': d.id}, data={'ocrResult': Json({
            'document_id': d.id, 'processed_at': '2026-05-13T10:00:00Z',
            'ocr_engine': 'easyocr',
            'fields': {
                'patient_name': {'value': 'P', 'confidence': 0.99},
                'medication':   {'value': 'M', 'confidence': 0.97},
                'expiry_date':  {'value': '2026-05-20', 'confidence': 0.99},
            },
            'needs_review': False, 'low_confidence_fields': [],
            'raw_text': 'x', 'processing_time_ms': ms,
        })})

    # One pending-review doc (drives queue depth + review queue UI)
    p = await db.document.create(data={'deviceId': 'smoke-test', 'status': 'pending_review'})
    await db.document.update(where={'id': p.id}, data={'ocrResult': Json({
        'document_id': p.id, 'processed_at': '2026-05-13T10:00:00Z',
        'ocr_engine': 'easyocr',
        'fields': {
            'patient_name': {'value': 'Needs Review', 'confidence': 0.50},
            'medication':   {'value': 'Drug',         'confidence': 0.96},
        },
        'needs_review': True, 'low_confidence_fields': ['patient_name'],
        'raw_text': 'x', 'processing_time_ms': 1500,
    })})

    # Generate the critical expiry alert (any doc with expiry <= 7 days)
    n = await scan_expiry_alerts(db)
    print(f'seeded: 3 completed, 1 pending_review, {n} alert(s)')
    await db.disconnect()

asyncio.run(main())
"""


def run() -> int:
    wait_for_stack()
    section("Seeding test data")
    seed_via_api_container(SEED_SCRIPT)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()

        def login(user: str, pw_: str) -> None:
            page.goto(f"{BASE}/login")
            page.wait_for_selector("input#username", timeout=5000)
            page.fill("input#username", user)
            page.fill("input#password", pw_)
            with page.expect_response(
                lambda r: "/api/v1/auth/login" in r.url and r.request.method == "POST",
                timeout=10000,
            ):
                page.click("button[type=submit]")
            page.wait_for_url(lambda u: "/login" not in u, timeout=10000)

        # ── as admin ──────────────────────────────────────────────────
        section("As admin")
        login(ADMIN_USER, ADMIN_PASS)
        page.wait_for_timeout(500)

        nav = [a.text_content().strip() for a in page.locator("aside nav a").all()]
        check(
            "sidebar shows 5 admin links",
            sorted(nav) == sorted(["Dashboard", "Review Queue", "Reports", "Alerts", "Audit Log"]),
            f"got {nav}",
        )

        # ── Dashboard ────────────────────────────────────────────────
        section("Dashboard")
        with page.expect_response(
            lambda r: "/api/v1/metrics/ocr" in r.url, timeout=10000
        ) as info:
            page.goto(f"{BASE}/dashboard")
        page.wait_for_timeout(500)
        metrics = json.loads(info.value.text())
        check(
            "metrics queue_depth ≥ 1",
            int(metrics.get("review_queue_depth", 0)) >= 1,
            f"got {metrics.get('review_queue_depth')}",
        )
        check(
            "metrics completed_last_24h ≥ 3",
            int(metrics.get("completed_last_24h", 0)) >= 3,
            f"got {metrics.get('completed_last_24h')}",
        )
        check(
            "metrics p50_latency_ms > 0",
            float(metrics.get("p50_latency_ms", 0)) > 0,
            f"got {metrics.get('p50_latency_ms')}",
        )
        body = page.content()
        check("dashboard renders metric labels",
              any(s in body for s in ("Queue", "Latency", "Completed")))

        # ── Reports — submit + download every report type ────────────
        section("Reports")
        page.goto(f"{BASE}/reports")
        page.wait_for_timeout(500)
        check("Request Report button rendered",
              page.locator('button:has-text("Request Report")').count() > 0)

        for rt in ("ocr_summary", "audit_export", "compliance", "anonymised_export"):
            page.select_option("select", rt)
            with page.expect_response(
                lambda r: "/api/v1/reports" in r.url and r.request.method == "POST",
                timeout=10000,
            ):
                page.click('button:has-text("Request Report")')
            page.wait_for_timeout(1500)
            refresh = page.locator('button:has-text("Refresh")').first
            if refresh.count() > 0:
                refresh.click()
                page.wait_for_timeout(1000)
            dl_btn = page.locator('button:has-text("Download")').first
            if dl_btn.count() > 0:
                with page.expect_download(timeout=10000) as dl_info:
                    dl_btn.click()
                dl = dl_info.value
                first_line = open(dl.path()).readline().strip()
                check(
                    f"report {rt}: downloaded CSV with header row",
                    "," in first_line and not first_line.startswith("{"),
                    f"first line: {first_line[:80]}",
                )
            else:
                check(f"report {rt}: download button rendered", False)

        # ── Alerts ────────────────────────────────────────────────────
        section("Alerts")
        with page.expect_response(
            lambda r: "/api/v1/alerts" in r.url, timeout=10000
        ):
            page.goto(f"{BASE}/alerts")
        page.wait_for_timeout(500)
        body = page.content()
        check("alerts page shows severity text",
              any(s in body for s in ("critical", "warning", "info")))
        check("alerts page shows expiry message",
              "expir" in body.lower() or "prescription" in body.lower())
        ack_btn = page.locator('button:has-text("Acknowledge")').first
        ack_count_before = page.locator('button:has-text("Acknowledge")').count()
        check("Acknowledge button is rendered", ack_count_before > 0)
        if ack_count_before > 0:
            with page.expect_response(
                lambda r: "/acknowledge" in r.url, timeout=10000
            ) as info:
                ack_btn.click()
            check("Acknowledge POST returned 2xx",
                  200 <= info.value.status < 300, f"status {info.value.status}")
            page.wait_for_timeout(500)
            ack_count_after = page.locator('button:has-text("Acknowledge")').count()
            check("Acknowledge button count decreased by 1",
                  ack_count_after == ack_count_before - 1,
                  f"before={ack_count_before}, after={ack_count_after}")

        # ── Audit Log ────────────────────────────────────────────────
        section("Audit Log")
        with page.expect_response(
            lambda r: "/api/v1/audit-log" in r.url, timeout=10000
        ):
            page.goto(f"{BASE}/audit-log")
        page.wait_for_timeout(500)
        body = page.content()
        check("audit log shows report.* actions",
              "report.create" in body or "report.download" in body)

        # ── Review Queue (admin can also see/approve) ────────────────
        section("Review Queue")
        with page.expect_response(
            lambda r: "/api/v1/review-queue" in r.url, timeout=10000
        ):
            page.goto(f"{BASE}/review-queue")
        page.wait_for_timeout(500)
        approve_btn = page.locator('button:has-text("Approve")').first
        check("Approve button rendered for pending doc", approve_btn.count() > 0)
        if approve_btn.count() > 0:
            with page.expect_response(
                lambda r: "/resolve" in r.url, timeout=10000
            ) as info:
                approve_btn.click()
            check("Approve POST returned 2xx (was 422 before fix)",
                  200 <= info.value.status < 300, f"status {info.value.status}")

        # ── Logout ───────────────────────────────────────────────────
        section("Logout")
        page.click('button:has-text("Log out")')
        page.wait_for_url(lambda u: "/login" in u, timeout=10000)
        check("sidebar hidden on /login",
              page.locator("aside").count() == 0)

        # ── As doctor — RBAC ─────────────────────────────────────────
        section("As doctor — RBAC")
        login(DOCTOR_USER, DOCTOR_PASS)
        page.wait_for_timeout(700)
        nav = [a.text_content().strip() for a in page.locator("aside nav a").all()]
        check(
            "doctor sidebar shows only Review Queue + Alerts",
            sorted(nav) == sorted(["Review Queue", "Alerts"]),
            f"got {nav}",
        )

        for pth in ("/dashboard", "/reports", "/audit-log"):
            page.goto(f"{BASE}{pth}")
            page.wait_for_timeout(800)
            body = page.content()
            check(f"doctor: {pth} shows Access denied",
                  "Access denied" in body or "denied" in body.lower())

        for pth in ("/alerts", "/review-queue"):
            page.goto(f"{BASE}{pth}")
            page.wait_for_timeout(800)
            body = page.content()
            check(f"doctor: {pth} allowed",
                  "Access denied" not in body and "denied" not in body.lower())

        browser.close()

    print(f"\n══════ \033[32m{PASS} passed\033[0m, "
          f"\033[31m{FAIL} failed\033[0m ══════\n")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
