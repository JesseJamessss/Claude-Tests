import io
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageSequence, UnidentifiedImageError

from app.config import Settings

ALLOWED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "GIF", "WEBP", "BMP", "TIFF"})


class ImageValidationError(ValueError):
    pass


@dataclass
class ProcessedImage:
    filename: str
    path: Path
    original_format: str
    width: int
    height: int
    size_bytes: int
    animated: bool


class ImageService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def validate_and_open(self, data: bytes) -> Image.Image:
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except UnidentifiedImageError as exc:
            raise ImageValidationError("Cannot decode image: unrecognized format") from exc
        except Exception as exc:
            raise ImageValidationError(f"Cannot decode image: {exc}") from exc

        if img.format not in ALLOWED_FORMATS:
            raise ImageValidationError(
                f"Format {img.format!r} is not supported. "
                f"Allowed: {', '.join(sorted(ALLOWED_FORMATS))}"
            )
        return img

    def convert_to_webp(self, img: Image.Image) -> tuple[bytes, bool]:
        is_animated = getattr(img, "n_frames", 1) > 1

        buf = io.BytesIO()

        if is_animated and self._settings.preserve_animation:
            rgba_frames = [f.copy().convert("RGBA") for f in ImageSequence.Iterator(img)]
            duration = img.info.get("duration", 100)
            loop = img.info.get("loop", 0)
            rgba_frames[0].save(
                buf,
                format="WEBP",
                save_all=True,
                append_images=rgba_frames[1:],
                loop=loop,
                duration=duration,
                quality=self._settings.webp_quality,
                lossless=self._settings.webp_lossless,
            )
        else:
            mode = "RGBA" if img.mode in ("RGBA", "LA", "PA") else "RGB"
            static = img.convert(mode)
            static.save(
                buf,
                format="WEBP",
                quality=self._settings.webp_quality,
                lossless=self._settings.webp_lossless,
                method=4,
            )

        return buf.getvalue(), is_animated

    def save(self, webp_bytes: bytes) -> tuple[str, Path]:
        self._settings.upload_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4()}.webp"
        dest = self._settings.upload_dir / filename
        tmp = dest.with_suffix(".webp.tmp")
        tmp.write_bytes(webp_bytes)
        os.replace(tmp, dest)
        return filename, dest

    def process_upload(self, data: bytes) -> ProcessedImage:
        img = self.validate_and_open(data)
        original_format = img.format or "UNKNOWN"
        width, height = img.size
        webp_bytes, is_animated = self.convert_to_webp(img)
        filename, path = self.save(webp_bytes)
        return ProcessedImage(
            filename=filename,
            path=path,
            original_format=original_format,
            width=width,
            height=height,
            size_bytes=len(webp_bytes),
            animated=is_animated,
        )


def get_image_service(
    settings: Settings = None,
) -> ImageService:
    if settings is None:
        from app.config import get_settings
        settings = get_settings()
    return ImageService(settings)
