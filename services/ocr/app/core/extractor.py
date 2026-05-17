"""Field extractor.

Takes raw OCR output (a list of recognized text blocks with confidence
scores and bounding boxes) and maps it to the structured FieldName enum.

Heuristics here are intentionally minimal and well-tested — bigger NLP
pipelines belong in a separate service. The goal is to be deterministic
and auditable: any extraction failure produces an explicit
low-confidence record, never a silent guess.
"""

import logging
import re
from dataclasses import dataclass

from app.core.schemas import ExtractedField, FieldName

logger = logging.getLogger(__name__)


# A "raw block" from the OCR engine.
@dataclass
class RawBlock:
    text: str
    confidence: float
    bounding_box: list[int]  # [x_min, y_min, x_max, y_max]


# ── Patterns for field detection ─────────────────────────────────────
# These are deliberately strict — false positives are worse than misses
# because of the 95% confidence gate downstream.

_DATE_RE = re.compile(
    r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"  # 2026-08-15 or 2026/08/15
    r"|\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"  # 15-08-2026
)

# Romanian and English keywords that hint at a patient-name line.
_NAME_KEYWORDS = (
    "patient",
    "pacient",
    "name",
    "nume",
    "pacientului",
)
_MED_KEYWORDS = (
    "medication",
    "medicamentul",
    "drug",
    "medicament",
    "rx",
    "prescription",
    "reteta",
)


def _is_name_line(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in _NAME_KEYWORDS)


def _is_med_line(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in _MED_KEYWORDS)


def _strip_keyword(text: str, keywords: tuple[str, ...]) -> str:
    """Remove a leading 'Patient: ' style prefix from a value."""
    for k in keywords:
        m = re.match(rf"^\s*{re.escape(k)}\s*[:\-]\s*", text, flags=re.IGNORECASE)
        if m:
            return text[m.end() :].strip()
    return text.strip()


def extract_fields(blocks: list[RawBlock]) -> dict[FieldName, ExtractedField]:
    """Map raw OCR blocks to a dict of structured fields.

    Strategy:
      - First block matching each pattern wins.
      - Confidence carried through unchanged from OCR.
      - If a field isn't found, it's omitted (NOT inserted with conf=0).
        The caller decides what missing-field policy to apply — typically
        treating absence as needs_review.
    """
    out: dict[FieldName, ExtractedField] = {}

    for b in blocks:
        text = b.text.strip()
        if not text:
            continue

        # Date — picks the first chronologically plausible match.
        if FieldName.EXPIRY_DATE not in out:
            if _DATE_RE.search(text):
                out[FieldName.EXPIRY_DATE] = ExtractedField(
                    value=text,
                    confidence=b.confidence,
                    bounding_box=b.bounding_box,
                )
                continue

        # Patient name — line containing a name keyword.
        if FieldName.PATIENT_NAME not in out and _is_name_line(text):
            value = _strip_keyword(text, _NAME_KEYWORDS)
            if value:
                out[FieldName.PATIENT_NAME] = ExtractedField(
                    value=value,
                    confidence=b.confidence,
                    bounding_box=b.bounding_box,
                )
                continue

        # Medication.
        if FieldName.MEDICATION not in out and _is_med_line(text):
            value = _strip_keyword(text, _MED_KEYWORDS)
            if value:
                out[FieldName.MEDICATION] = ExtractedField(
                    value=value,
                    confidence=b.confidence,
                    bounding_box=b.bounding_box,
                )

    return out


def gate_confidence(
    fields: dict[FieldName, ExtractedField],
    *,
    threshold: float,
    required: tuple[FieldName, ...] = (
        FieldName.PATIENT_NAME,
        FieldName.MEDICATION,
        FieldName.EXPIRY_DATE,
    ),
) -> tuple[bool, list[FieldName]]:
    """Return (needs_review, low_confidence_field_list).

    A field triggers review if either:
      - It's required and missing entirely.
      - Its confidence is strictly below the threshold.
    """
    low: list[FieldName] = []

    for name in required:
        if name not in fields:
            # Missing-required is logically below threshold.
            low.append(name)
            continue
        if fields[name].confidence < threshold:
            low.append(name)

    return bool(low), low
