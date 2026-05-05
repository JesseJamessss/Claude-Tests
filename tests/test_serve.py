import io

from httpx import AsyncClient
from PIL import Image


async def _upload_png(client: AsyncClient) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(255, 0, 0)).save(buf, format="PNG")
    r = await client.post(
        "/images/",
        files={"file": ("test.png", io.BytesIO(buf.getvalue()), "image/png")},
    )
    return r.json()["url"]


async def test_serve_existing_file_returns_200_webp(client: AsyncClient):
    url = await _upload_png(client)
    r = await client.get(url)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"


async def test_serve_nonexistent_file_returns_404(client: AsyncClient):
    r = await client.get("/images/00000000-0000-0000-0000-000000000000.webp")
    assert r.status_code == 404


async def test_serve_path_traversal_rejected(client: AsyncClient):
    r = await client.get("/images/../config.py")
    assert r.status_code == 404


async def test_serve_cache_control_header_immutable(client: AsyncClient):
    url = await _upload_png(client)
    r = await client.get(url)
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "immutable" in cc


async def test_serve_invalid_filename_pattern_rejected(client: AsyncClient):
    r = await client.get("/images/../../etc/passwd.webp")
    assert r.status_code == 404
