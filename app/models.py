from pydantic import BaseModel


class UploadResponse(BaseModel):
    filename: str
    url: str
    original_format: str
    width: int
    height: int
    size_bytes: int
    animated: bool


class ErrorResponse(BaseModel):
    detail: str
