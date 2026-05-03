"""Confidence gate — if any field is below threshold, route to review."""

from app.schemas.ocr import ExtractedField, FieldName


THRESHOLD = 0.95


def _gate(fields: dict[FieldName, ExtractedField]) -> tuple[bool, list[FieldName]]:
    """The actual gating logic. Mirrors what the OCR worker does."""
    low = [name for name, f in fields.items() if f.confidence < THRESHOLD]
    return bool(low), low


def test_all_high_confidence_skips_review() -> None:
    fields = {
        FieldName.PATIENT_NAME: ExtractedField(value="A", confidence=0.99),
        FieldName.MEDICATION: ExtractedField(value="B", confidence=0.96),
        FieldName.EXPIRY_DATE: ExtractedField(value="C", confidence=0.97),
    }
    needs_review, low = _gate(fields)
    assert needs_review is False
    assert low == []


def test_one_low_confidence_triggers_review() -> None:
    fields = {
        FieldName.PATIENT_NAME: ExtractedField(value="A", confidence=0.99),
        FieldName.MEDICATION: ExtractedField(value="B", confidence=0.80),
        FieldName.EXPIRY_DATE: ExtractedField(value="C", confidence=0.97),
    }
    needs_review, low = _gate(fields)
    assert needs_review is True
    assert low == [FieldName.MEDICATION]


def test_threshold_boundary_is_strict() -> None:
    """Exactly 0.95 should NOT trigger review (>= threshold passes)."""
    fields = {
        FieldName.PATIENT_NAME: ExtractedField(value="A", confidence=0.95),
    }
    needs_review, _ = _gate(fields)
    assert needs_review is False


def test_just_below_threshold_triggers_review() -> None:
    fields = {
        FieldName.PATIENT_NAME: ExtractedField(value="A", confidence=0.949),
    }
    needs_review, _ = _gate(fields)
    assert needs_review is True


def test_all_low_confidence() -> None:
    fields = {
        FieldName.PATIENT_NAME: ExtractedField(value="A", confidence=0.50),
        FieldName.MEDICATION: ExtractedField(value="B", confidence=0.30),
    }
    needs_review, low = _gate(fields)
    assert needs_review is True
    assert set(low) == {FieldName.PATIENT_NAME, FieldName.MEDICATION}
