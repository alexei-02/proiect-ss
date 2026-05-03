"""Document endpoints — direct upload (HTTP alternative to MQTT) and fetch."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.core.limiter import limiter
from app.core.security import User, require_role
from app.schemas.ocr import DocumentResponse

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role("doctor"))],
)
@limiter.limit("3/minute")
async def upload_document(
    request: Request,
    device_id: str = Form(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$"),
    file: UploadFile = File(...),
) -> DocumentResponse:
    """Direct HTTP upload — alternative to MQTT for clients without a broker."""
    settings = request.app.state.settings

    # Stream into memory while enforcing the byte cap (Content-Length is
    # advisory; this is the authoritative check).
    content = b""
    while chunk := await file.read(64 * 1024):
        content += chunk
        if len(content) > settings.max_upload_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds {settings.max_upload_size_bytes} bytes",
            )

    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    store = request.app.state.store
    doc = await store.create_document(device_id=device_id)

    ocr_client = request.app.state.ocr_client
    await ocr_client.submit(
        document_id=doc.id,
        image_bytes=content,
        source_device=device_id,
    )
    return doc


@router.get(
    "/{doc_id}",
    response_model=DocumentResponse,
    dependencies=[Depends(require_role("doctor"))],
)
@limiter.limit("100/minute")
async def get_document(
    request: Request,
    doc_id: UUID,
    _user: User = Depends(require_role("doctor")),
) -> DocumentResponse:
    store = request.app.state.store
    doc = await store.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
