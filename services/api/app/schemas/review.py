"""Review queue schemas — items requiring manual correction by a doctor."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ocr import ExtractedField, FieldName


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    document_id: UUID
    queued_at: datetime
    fields: dict[FieldName, ExtractedField]
    low_confidence_fields: list[FieldName]
    image_url: str  # presigned URL pointing to the original image


class ReviewResolution(BaseModel):
    """Submitted by the doctor when correcting OCR output."""

    model_config = ConfigDict(extra="forbid")

    corrected_fields: dict[FieldName, str] = Field(..., min_length=1)
    reviewer_notes: str | None = Field(default=None, max_length=2048)
