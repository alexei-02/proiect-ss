"""PHI masking for auditor-role document responses.

mask_phi() returns a new DocumentResponse with patient_name, medication,
and raw_text replaced by "***".  expiry_date, confidence scores, and all
other non-PHI fields are preserved unchanged.
"""

from app.schemas.ocr import DocumentResponse, ExtractedField, FieldName, OCRResult

_REDACTED = "***"
_PHI_FIELD_NAMES = frozenset({FieldName.PATIENT_NAME, FieldName.MEDICATION})


def mask_phi(doc: DocumentResponse) -> DocumentResponse:
    """Return a copy of *doc* with PHI values replaced by '***'.

    If ocr_result is None or the string sentinel "pending_review",
    the document is returned unchanged (nothing to mask).
    """
    if not isinstance(doc.ocr_result, OCRResult):
        return doc

    result = doc.ocr_result
    masked_fields: dict[FieldName, ExtractedField] = {}
    for fname, ef in result.fields.items():
        if fname in _PHI_FIELD_NAMES:
            masked_fields[fname] = ExtractedField(
                value=_REDACTED,
                confidence=ef.confidence,
                bounding_box=ef.bounding_box,
            )
        else:
            masked_fields[fname] = ef

    masked_result = OCRResult(
        document_id=result.document_id,
        processed_at=result.processed_at,
        ocr_engine=result.ocr_engine,
        fields=masked_fields,
        needs_review=result.needs_review,
        low_confidence_fields=result.low_confidence_fields,
        raw_text=_REDACTED,
        processing_time_ms=result.processing_time_ms,
    )

    return DocumentResponse(
        id=doc.id,
        status=doc.status,
        submitted_at=doc.submitted_at,
        device_id=doc.device_id,
        ocr_result=masked_result,
    )
