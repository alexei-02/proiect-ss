"""Pluggable async report generation service.

Generators write CSV files to {queue_dir}/reports/{report_id}.csv using an
atomic temp-file-then-rename pattern so the downloader never sees a partial file.
"""

import asyncio
import csv
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.schemas.reports import ReportType
from app.services.masking import mask_phi
from app.services.storage import _to_response
from prisma import Prisma

logger = logging.getLogger(__name__)


# ─── Individual generators ─────────────────────────────────────────────────────


async def generate_ocr_summary(params: dict, db: Prisma):
    """Yield one row per document: id, device_id, status, submitted_at, p50_latency_ms."""
    skip = 0
    batch = 500
    while True:
        docs = await db.document.find_many(skip=skip, take=batch)
        if not docs:
            break
        for doc in docs:
            latency = None
            if doc.ocrResult and isinstance(doc.ocrResult, dict):
                latency = doc.ocrResult.get("processing_time_ms")
            yield {
                "id": doc.id,
                "device_id": doc.deviceId,
                "status": doc.status,
                "submitted_at": doc.submittedAt.isoformat() if doc.submittedAt else "",
                "p50_latency_ms": latency if latency is not None else "",
            }
        if len(docs) < batch:
            break
        skip += batch


async def generate_audit_export(params: dict, db: Prisma):
    """Yield AuditLog rows, filtered by optional date_from/date_to in params."""
    date_from = params.get("date_from")
    date_to = params.get("date_to")

    where: dict = {}
    if date_from or date_to:
        occurred_at_filter: dict = {}
        if date_from:
            occurred_at_filter["gte"] = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
        if date_to:
            occurred_at_filter["lte"] = datetime.fromisoformat(date_to).replace(tzinfo=UTC)
        where["occurredAt"] = occurred_at_filter

    skip = 0
    batch = 500
    while True:
        rows = await db.auditlog.find_many(where=where, skip=skip, take=batch)
        if not rows:
            break
        for row in rows:
            yield {
                "id": row.id,
                "occurred_at": row.occurredAt.isoformat() if row.occurredAt else "",
                "user_id": row.userId or "",
                "username": row.username or "",
                "action": row.action,
                "resource_type": row.resourceType or "",
                "resource_id": row.resourceId or "",
                "ip_address": row.ipAddress or "",
                "outcome": row.outcome,
            }
        if len(rows) < batch:
            break
        skip += batch


async def generate_compliance_report(params: dict, db: Prisma):
    """Yield documents where expiry_date field is present in the JSONB."""
    rows = await db.query_raw(
        """
        SELECT id,
               ocr_result->'fields'->'expiry_date'->>'value' AS expiry_value
        FROM documents
        WHERE status = 'completed'
          AND ocr_result->'fields'->'expiry_date'->>'value' IS NOT NULL
        """
    )
    for row in rows:
        yield {
            "document_id": row["id"],
            "expiry_date_value": row["expiry_value"],
        }


async def generate_anonymised_export(params: dict, db: Prisma, cipher):
    """Yield flattened dicts with PHI masked, cursor-based pagination (batch 500)."""
    skip = 0
    batch = 500
    while True:
        docs = await db.document.find_many(skip=skip, take=batch)
        if not docs:
            break
        for doc in docs:
            try:
                resp = _to_response(doc, cipher, None)
                masked = mask_phi(resp)
                ocr = masked.ocr_result
                row: dict = {
                    "id": str(masked.id),
                    "status": masked.status.value,
                    "submitted_at": masked.submitted_at.isoformat(),
                    "device_id": masked.device_id,
                }
                if hasattr(ocr, "fields"):
                    for field_name, ef in ocr.fields.items():
                        key = field_name.value if hasattr(field_name, "value") else str(field_name)
                        row[f"field_{key}_value"] = ef.value
                        row[f"field_{key}_confidence"] = ef.confidence
                    row["processing_time_ms"] = getattr(ocr, "processing_time_ms", "")
                    row["needs_review"] = getattr(ocr, "needs_review", "")
                yield row
            except Exception as exc:
                logger.warning("Skipping document %s in anonymised export: %s", doc.id, exc)
        if len(docs) < batch:
            break
        skip += batch


# ─── Runner ───────────────────────────────────────────────────────────────────


async def run_report(
    report_id: UUID,
    report_type: ReportType,
    params: dict,
    db: Prisma,
    cipher,
    queue_dir: Path,
) -> Path:
    """Generate a CSV report and return its path.

    Sets DB status to 'running', writes CSV atomically, then sets 'ready'.
    On exception: sets 'failed' + error_msg and re-raises.
    """
    reports_dir = queue_dir / "reports"

    def _make_reports_dir() -> None:
        reports_dir.mkdir(parents=True, exist_ok=True)

    await asyncio.to_thread(_make_reports_dir)

    final_path = reports_dir / f"{report_id}.csv"

    # Mark running
    await db.report.update(
        where={"id": str(report_id)},
        data={"status": "running"},
    )

    try:
        rows = []
        if report_type == ReportType.OCR_SUMMARY:
            async for row in generate_ocr_summary(params, db):
                rows.append(row)
        elif report_type == ReportType.AUDIT_EXPORT:
            async for row in generate_audit_export(params, db):
                rows.append(row)
        elif report_type == ReportType.COMPLIANCE:
            async for row in generate_compliance_report(params, db):
                rows.append(row)
        elif report_type == ReportType.ANONYMISED_EXPORT:
            async for row in generate_anonymised_export(params, db, cipher):
                rows.append(row)
        else:
            raise ValueError(f"Unknown report type: {report_type}")

        # Write CSV atomically. Build a union of keys across all rows so
        # documents that have extra OCR fields (e.g. expiry_date) don't trip
        # csv.DictWriter, which locks the fieldname set from the header.
        def _write_csv() -> None:
            if rows:
                seen: dict[str, None] = {}
                for r in rows:
                    for k in r:
                        seen.setdefault(k, None)
                fieldnames = list(seen)
            else:
                fieldnames = ["(no data)"]
            fd, tmp_path = tempfile.mkstemp(dir=reports_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                os.rename(tmp_path, final_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        await asyncio.to_thread(_write_csv)

        await db.report.update(
            where={"id": str(report_id)},
            data={
                "status": "ready",
                "resultPath": str(final_path),
                "completedAt": datetime.now(UTC),
            },
        )
        logger.info("Report %s completed: %s", report_id, final_path)
        return final_path

    except Exception as exc:
        error_msg = str(exc)
        logger.exception("Report %s failed", report_id)
        try:
            await db.report.update(
                where={"id": str(report_id)},
                data={
                    "status": "failed",
                    "errorMsg": error_msg,
                    "completedAt": datetime.now(UTC),
                },
            )
        except Exception:
            logger.exception("Could not mark report %s as failed", report_id)
        raise
