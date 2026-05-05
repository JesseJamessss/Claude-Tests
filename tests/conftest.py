import io
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image


def _png_bytes(size: tuple[int, int] = (10, 10), color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(size: tuple[int, int] = (10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(0, 128, 0)).save(buf, format="JPEG")
    return buf.getvalue()


def _gif_animated_bytes(n_frames: int = 3, size: tuple[int, int] = (10, 10)) -> bytes:
    frames = [Image.new("RGB", size, color=(i * 60, 0, 0)) for i in range(n_frames)]
    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=100,
    )
    return buf.getvalue()


def _jpeg_with_exif_bytes() -> bytes:
    import struct

    # Minimal JPEG with a fake GPS EXIF block (sufficient for Pillow to read exif)
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color=(0, 0, 255))
    # Create a minimal EXIF with GPS IFD using piexif if available, else just save plain
    try:
        import piexif

        exif_dict: dict[str, Any] = {
            "GPS": {
                piexif.GPSIFD.GPSLatitudeRef: b"N",
                piexif.GPSIFD.GPSLatitude: ((51, 1), (30, 1), (0, 1)),
            }
        }
        exif_bytes = piexif.dump(exif_dict)
        img.save(buf, format="JPEG", exif=exif_bytes)
    except ImportError:
        img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def png_bytes() -> bytes:
    return _png_bytes()


@pytest.fixture
def jpeg_bytes() -> bytes:
    return _jpeg_bytes()


@pytest.fixture
def gif_animated_bytes() -> bytes:
    return _gif_animated_bytes()


@pytest.fixture
def jpeg_exif_bytes() -> bytes:
    return _jpeg_with_exif_bytes()


@pytest.fixture
def corrupt_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 20  # truncated JPEG header


@pytest_asyncio.fixture
async def client(tmp_path) -> AsyncGenerator[AsyncClient, None]:
    os.environ["IMG_UPLOAD_DIR"] = str(tmp_path / "uploads")
    # Clear the lru_cache so the new env var is picked up
    from app.config import get_settings
    get_settings.cache_clear()

    from app.main import create_app
    test_app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac

    get_settings.cache_clear()
