"""Scans completed documents for prescriptions expiring within 30 days."""

import logging
from datetime import UTC, datetime, timedelta

from prisma import Prisma

logger = logging.getLogger(__name__)


async def scan_expiry_alerts(db: Prisma) -> int:
    """Find documents whose expiry_date field falls within the next 30 days.

    Creates Alert rows for each new near-expiry document.
    Skips documents that already have an unacknowledged alert.
    Returns count of new alerts created.

    Raw SQL is used because Prisma Python doesn't support JSONB path operators natively.
    Query parameters are passed positionally — no user input reaches the SQL string.
    """
    rows = await db.query_raw(
        """
        SELECT id,
               ocr_result->'fields'->'expiry_date'->>'value' AS expiry_str
        FROM documents
        WHERE status = 'completed'
          AND ocr_result->'fields'->'expiry_date'->>'value' IS NOT NULL
        """
    )

    now = datetime.now(UTC)
    threshold = now + timedelta(days=30)

    # Collect document IDs that already have an unacknowledged expiry alert
    existing_alerts = await db.alert.find_many(
        where={
            "alertType": "expiry_warning",
            "acknowledged": False,
        }
    )
    already_alerted = {a.documentId for a in existing_alerts if a.documentId}

    created = 0
    for row in rows:
        doc_id: str = row["id"]
        expiry_str: str | None = row.get("expiry_str")

        if not expiry_str:
            continue

        if doc_id in already_alerted:
            continue

        # Parse date — handle common formats
        expiry_date: datetime | None = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                expiry_date = datetime.strptime(expiry_str.strip(), fmt).replace(tzinfo=UTC)
                break
            except ValueError:
                continue

        if expiry_date is None:
            logger.debug("Could not parse expiry date '%s' for doc %s", expiry_str, doc_id)
            continue

        if now <= expiry_date <= threshold:
            days_left = (expiry_date - now).days
            severity = "critical" if days_left <= 7 else "warning"
            await db.alert.create(
                data={
                    "alertType": "expiry_warning",
                    "severity": severity,
                    "documentId": doc_id,
                    "message": (
                        f"Prescription expiring in {days_left} day(s) (expiry: {expiry_str})"
                    ),
                    "expiresOn": expiry_date,
                }
            )
            created += 1
            logger.info(
                "Created expiry alert for document %s (expires %s, %d days)",
                doc_id,
                expiry_str,
                days_left,
            )

    return created
