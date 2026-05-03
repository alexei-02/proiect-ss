"""Tests for the field extraction heuristics."""

from app.core.extractor import RawBlock, extract_fields, gate_confidence
from app.core.schemas import FieldName


def _block(text: str, conf: float = 0.97) -> RawBlock:
    return RawBlock(text=text, confidence=conf, bounding_box=[0, 0, 100, 20])


def test_extract_all_fields() -> None:
    blocks = [
        _block("Patient: Ion Popescu"),
        _block("Medication: Atorvastatin 20mg"),
        _block("2026-08-15"),
    ]
    fields = extract_fields(blocks)
    assert FieldName.PATIENT_NAME in fields
    assert fields[FieldName.PATIENT_NAME].value == "Ion Popescu"
    assert fields[FieldName.MEDICATION].value == "Atorvastatin 20mg"
    assert fields[FieldName.EXPIRY_DATE].value == "2026-08-15"


def test_romanian_keywords_recognized() -> None:
    blocks = [
        _block("Pacient: Maria Ionescu"),
        _block("Medicament: Aspirin"),
        _block("Data: 2026-12-01"),
    ]
    fields = extract_fields(blocks)
    assert fields[FieldName.PATIENT_NAME].value == "Maria Ionescu"
    assert fields[FieldName.MEDICATION].value == "Aspirin"


def test_first_match_wins() -> None:
    """If two blocks could match the same field, the first one wins."""
    blocks = [
        _block("Patient: First Name"),
        _block("Patient: Second Name"),
    ]
    fields = extract_fields(blocks)
    assert fields[FieldName.PATIENT_NAME].value == "First Name"


def test_missing_field_omitted_not_zero_confidence() -> None:
    """If a field can't be extracted it's omitted entirely, not faked."""
    blocks = [_block("Random unrelated text")]
    fields = extract_fields(blocks)
    assert FieldName.PATIENT_NAME not in fields
    assert FieldName.MEDICATION not in fields


def test_confidence_carried_through() -> None:
    blocks = [_block("Patient: Test", conf=0.73)]
    fields = extract_fields(blocks)
    assert fields[FieldName.PATIENT_NAME].confidence == 0.73


def test_empty_blocks_handled() -> None:
    blocks = [_block("")]
    fields = extract_fields(blocks)
    assert fields == {}


def test_date_alternative_formats() -> None:
    """Various date formats should all be detected."""
    for date_text in ["2026-08-15", "2026/08/15", "15.08.2026", "15/08/2026"]:
        blocks = [_block(date_text)]
        fields = extract_fields(blocks)
        assert FieldName.EXPIRY_DATE in fields, f"failed for {date_text!r}"


def test_gate_all_above_threshold() -> None:
    fields = {
        FieldName.PATIENT_NAME: _ef(0.99),
        FieldName.MEDICATION: _ef(0.96),
        FieldName.EXPIRY_DATE: _ef(0.97),
    }
    needs_review, low = gate_confidence(fields, threshold=0.95)
    assert needs_review is False
    assert low == []


def test_gate_one_below_threshold() -> None:
    fields = {
        FieldName.PATIENT_NAME: _ef(0.99),
        FieldName.MEDICATION: _ef(0.80),
        FieldName.EXPIRY_DATE: _ef(0.97),
    }
    needs_review, low = gate_confidence(fields, threshold=0.95)
    assert needs_review is True
    assert low == [FieldName.MEDICATION]


def test_gate_missing_required_triggers_review() -> None:
    """A missing required field should also trigger review."""
    fields = {
        FieldName.PATIENT_NAME: _ef(0.99),
        # MEDICATION missing
        FieldName.EXPIRY_DATE: _ef(0.99),
    }
    needs_review, low = gate_confidence(fields, threshold=0.95)
    assert needs_review is True
    assert FieldName.MEDICATION in low


def test_gate_threshold_boundary() -> None:
    """Exactly at threshold passes; just below fails."""
    at = {FieldName.PATIENT_NAME: _ef(0.95), FieldName.MEDICATION: _ef(0.95), FieldName.EXPIRY_DATE: _ef(0.95)}
    just_below = {FieldName.PATIENT_NAME: _ef(0.949), FieldName.MEDICATION: _ef(0.95), FieldName.EXPIRY_DATE: _ef(0.95)}
    assert gate_confidence(at, threshold=0.95)[0] is False
    assert gate_confidence(just_below, threshold=0.95)[0] is True


def _ef(confidence: float):
    from app.core.schemas import ExtractedField
    return ExtractedField(value="x", confidence=confidence)
