import io

import pytest
from httpx import AsyncClient
from PIL import Image


async def _upload(client: AsyncClient, data: bytes, filename: str = "test.png") -> dict:
    response = await client.post(
        "/images/",
        files={"file": (filename, io.BytesIO(data), "application/octet-stream")},
    )
    return response


async def test_upload_png_returns_201_and_webp_filename(client: AsyncClient, png_bytes: bytes):
    r = await _upload(client, png_bytes, "photo.png")
    assert r.status_code == 201
    body = r.json()
    assert body["filename"].endswith(".webp")
    assert body["url"].startswith("/images/")
    assert body["url"].endswith(".webp")


async def test_upload_jpeg_converts_to_webp(client: AsyncClient, jpeg_bytes: bytes):
    r = await _upload(client, jpeg_bytes, "photo.jpg")
    assert r.status_code == 201
    url = r.json()["url"]
    serve_r = await client.get(url)
    assert serve_r.status_code == 200
    assert serve_r.headers["content-type"] == "image/webp"


async def test_upload_animated_gif_preserves_animation(client: AsyncClient, gif_animated_bytes: bytes):
    r = await _upload(client, gif_animated_bytes, "anim.gif")
    assert r.status_code == 201
    body = r.json()
    assert body["animated"] is True

    serve_r = await client.get(body["url"])
    assert serve_r.status_code == 200
    img = Image.open(io.BytesIO(serve_r.content))
    assert getattr(img, "n_frames", 1) == 3


async def test_upload_already_webp_accepted(client: AsyncClient):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(0, 0, 128)).save(buf, format="WEBP")
    r = await _upload(client, buf.getvalue(), "image.webp")
    assert r.status_code == 201


async def test_upload_corrupt_file_returns_422(client: AsyncClient, corrupt_bytes: bytes):
    r = await _upload(client, corrupt_bytes, "bad.jpg")
    assert r.status_code == 422
    assert "detail" in r.json()


async def test_upload_non_image_bytes_returns_422(client: AsyncClient):
    r = await _upload(client, b"not an image at all", "text.txt")
    assert r.status_code == 422


async def test_upload_oversized_file_returns_413(client: AsyncClient):
    big = b"\x00" * (10 * 1024 * 1024 + 1)
    r = await _upload(client, big, "big.bin")
    assert r.status_code == 413


async def test_upload_exif_is_stripped(client: AsyncClient, jpeg_exif_bytes: bytes):
    r = await _upload(client, jpeg_exif_bytes, "gps.jpg")
    assert r.status_code == 201
    url = r.json()["url"]
    serve_r = await client.get(url)
    img = Image.open(io.BytesIO(serve_r.content))
    # WebP files should have no EXIF GPS data after conversion
    exif_data = img.info.get("exif", b"")
    # GPS tag 0x8825 = 34853; if present in raw EXIF it would appear as bytes
    assert b"\x25\x88" not in exif_data and b"\x88\x25" not in exif_data


async def test_upload_response_body_schema(client: AsyncClient, png_bytes: bytes):
    r = await _upload(client, png_bytes)
    assert r.status_code == 201
    body = r.json()
    for key in ("filename", "url", "original_format", "width", "height", "size_bytes", "animated"):
        assert key in body, f"Missing key: {key}"
    assert body["original_format"] == "PNG"
    assert body["width"] == 10
    assert body["height"] == 10
    assert body["size_bytes"] > 0
    assert body["animated"] is False
