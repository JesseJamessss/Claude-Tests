import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from app.config import Settings, get_settings
from app.models import ErrorResponse, UploadResponse
from app.services.image_service import ImageService, ImageValidationError, get_image_service

router = APIRouter(prefix="/images", tags=["images"])

_FILENAME_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.webp$")


@router.post(
    "/",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def upload_image(
    file: UploadFile,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[ImageService, Depends(get_image_service)],
) -> UploadResponse:
    data = await file.read(settings.max_file_bytes + 1)
    if len(data) > settings.max_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.max_file_bytes} bytes",
        )

    result = service.process_upload(data)

    return UploadResponse(
        filename=result.filename,
        url=f"{settings.url_prefix}/{result.filename}",
        original_format=result.original_format,
        width=result.width,
        height=result.height,
        size_bytes=result.size_bytes,
        animated=result.animated,
    )


@router.get(
    "/{filename}",
    response_class=FileResponse,
    responses={404: {"model": ErrorResponse}},
)
async def serve_image(
    filename: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    if not _FILENAME_RE.match(filename):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    path = settings.upload_dir / filename
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return FileResponse(
        path=path,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
