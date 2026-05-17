"""OCR result schemas — shared between API and OCR worker.

THIS IS THE SINGLE SOURCE OF TRUTH for the OCR JSON contract.
The DB models (DB epic) and the frontend (Dashboard epic) should both
mirror these field names exactly.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FieldName(StrEnum):
    """OCR fields we extract. Add carefully — DB schema must follow."""

    PATIENT_NAME = "patient_name"
    MEDICATION = "medication"
    EXPIRY_DATE = "expiry_date"


# A bounding box is [x_min, y_min, x_max, y_max] in pixel coordinates.
BoundingBox = Annotated[list[int], Field(min_length=4, max_length=4)]


class ExtractedField(BaseModel):
    """A single extracted field with confidence and location."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(..., max_length=512)
    confidence: float = Field(..., ge=0.0, le=1.0)
    bounding_box: BoundingBox | None = None


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PENDING_REVIEW = "pending_review"
    FAILED = "failed"


class OCRResult(BaseModel):
    """The structured output from the OCR engine."""

    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    processed_at: datetime
    ocr_engine: str = Field(..., examples=["easyocr-1.7.1"])
    fields: dict[FieldName, ExtractedField]
    needs_review: bool
    low_confidence_fields: list[FieldName] = Field(default_factory=list)
    raw_text: str = Field(default="", max_length=65536)
    processing_time_ms: int = Field(..., ge=0)


class DocumentSubmission(BaseModel):
    """Payload accepted by the direct-upload endpoint."""

    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    captured_at: datetime
    notes: str | None = Field(default=None, max_length=1024)


class DocumentResponse(BaseModel):
    """What the API returns to clients about a stored document.

    ocr_result is:
      - null          while queued / processing
      - "pending_review" when OCR completed but confidence is below threshold
      - an OCRResult object when processing completed with sufficient confidence
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: DocumentStatus
    submitted_at: datetime
    device_id: str
    ocr_result: OCRResult | str | None = None
