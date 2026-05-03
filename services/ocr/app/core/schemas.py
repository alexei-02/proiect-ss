"""OCR result schema.

Mirrored from services/api/app/schemas/ocr.py. In a fully productionized
setup this lives in a shared `medical-ocr-schemas` package depended on by
both services. For now the duplication is intentional and small — both
copies are tested for byte-level JSON compatibility (see
test_schema_compat.py).
"""

from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FieldName(str, Enum):
    PATIENT_NAME = "patient_name"
    MEDICATION = "medication"
    EXPIRY_DATE = "expiry_date"


BoundingBox = Annotated[list[int], Field(min_length=4, max_length=4)]


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(..., max_length=512)
    confidence: float = Field(..., ge=0.0, le=1.0)
    bounding_box: BoundingBox | None = None


class OCRResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    processed_at: datetime
    ocr_engine: str
    fields: dict[FieldName, ExtractedField]
    needs_review: bool
    low_confidence_fields: list[FieldName] = Field(default_factory=list)
    raw_text: str = Field(default="", max_length=65536)
    processing_time_ms: int = Field(..., ge=0)
