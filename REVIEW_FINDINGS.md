# Code Review Findings & Potential Solutions

Generated from automated code review. All 14 tests pass; issues below are improvements identified during review.

---

## Critical

### 1. DoS via unbounded multipart buffering
**File:** `app/routes/images.py:30-35`

The `max_file_bytes` check happens after `python-multipart` has already buffered the entire request body in RAM. A large upload exhausts memory before the 413 is returned.

**Potential solution:** Add a size-limiting middleware at the ASGI layer so the connection is dropped before buffering completes.

```python
# app/main.py
from starlette.middleware.base import BaseHTTPMiddleware

class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("content-length"):
            if int(request.headers["content-length"]) > settings.max_file_bytes:
                return JSONResponse(status_code=413, content={"detail": "File too large"})
        return await call_next(request)

app.add_middleware(ContentSizeLimitMiddleware)
```

Alternatively, enforce at the reverse proxy level (`nginx client_max_body_size`).

---

## Warnings

### 2. Blocking event loop during image conversion
**File:** `app/routes/images.py:37`

`service.process_upload(data)` is CPU-bound (Pillow decode + WebP encode) and runs synchronously inside an `async def` route, blocking the entire event loop and starving all other in-flight requests.

**Potential solution:** Offload to a thread pool executor.

```python
import asyncio

result = await asyncio.get_event_loop().run_in_executor(
    None, service.process_upload, data
)
```

Or with `anyio` (already a dev dependency):
```python
import anyio

result = await anyio.to_thread.run_sync(service.process_upload, data)
```

---

### 3. Broken dependency injection for `get_image_service`
**File:** `app/services/image_service.py:107-113`

`settings: Settings = None` is not recognised by FastAPI as a sub-dependency, so `settings` is always `None` and the function falls back to `get_settings()` directly. The DI graph is bypassed, making it impossible to override settings via `app.dependency_overrides` in tests.

**Potential solution:** Declare the dependency properly.

```python
from typing import Annotated
from fastapi import Depends

def get_image_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ImageService:
    return ImageService(settings)
```

---

### 4. Per-frame GIF animation durations collapsed to frame 0
**File:** `app/services/image_service.py:56-67`

`img.info.get("duration", 100)` reads only the first frame's duration. GIFs with variable per-frame timing will have all frames set to the same delay after WebP conversion.

**Potential solution:** Collect per-frame durations during iteration.

```python
durations = []
rgba_frames = []
for frame in ImageSequence.Iterator(img):
    durations.append(frame.info.get("duration", 100))
    rgba_frames.append(frame.copy().convert("RGBA"))

rgba_frames[0].save(
    buf,
    format="WEBP",
    save_all=True,
    append_images=rgba_frames[1:],
    loop=img.info.get("loop", 0),
    duration=durations,   # list accepted by Pillow
    quality=self._settings.webp_quality,
    lossless=self._settings.webp_lossless,
)
```

---

### 5. Decompression bomb exposure (89–178 MP range)
**File:** `app/services/image_service.py:34-46`

Pillow raises `DecompressionBombWarning` at 89 MP and `DecompressionBombError` at 178 MP. The broad `except Exception` catches only the hard error; images in the 89–178 MP window silently decompress (a 90 MP PNG can consume ~270 MB of RAM).

**Potential solution:** Convert the warning to an error and set an explicit pixel budget.

```python
import warnings
from PIL import Image

Image.MAX_IMAGE_PIXELS = 50_000_000  # 50 MP limit

# In validate_and_open():
with warnings.catch_warnings():
    warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ImageValidationError("Image exceeds maximum allowed pixel dimensions") from exc
```

---

### 6. `.tmp` file not cleaned up on write failure
**File:** `app/services/image_service.py:85-87`

If `write_bytes()` raises (e.g. disk full), the `.tmp` file is left on disk permanently.

**Potential solution:** Remove the temp file in a `finally` block.

```python
tmp = dest.with_suffix(".webp.tmp")
try:
    tmp.write_bytes(webp_bytes)
    os.replace(tmp, dest)
except Exception:
    tmp.unlink(missing_ok=True)
    raise
```

---

### 7. Test env var `IMG_UPLOAD_DIR` not restored after fixture teardown
**File:** `tests/conftest.py:87-101`

After each test, `IMG_UPLOAD_DIR` remains set to the deleted `tmp_path`. Tests that run after teardown and read the env var directly will get a stale path.

**Potential solution:** Save and restore the env var around the fixture.

```python
@pytest_asyncio.fixture
async def client(tmp_path):
    old_val = os.environ.get("IMG_UPLOAD_DIR")
    os.environ["IMG_UPLOAD_DIR"] = str(tmp_path / "uploads")
    get_settings.cache_clear()
    test_app = create_app()
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac
    if old_val is not None:
        os.environ["IMG_UPLOAD_DIR"] = old_val
    else:
        os.environ.pop("IMG_UPLOAD_DIR", None)
    get_settings.cache_clear()
```

---

### 8. Fragile EXIF-strip test
**File:** `tests/test_upload.py:70-79`

The test searches for two raw byte patterns (`\x25\x88`, `\x88\x25`) rather than asserting the EXIF blob is fully absent. A GPS tag at an unexpected offset or byte order would pass the test undetected.

**Potential solution:** Assert the EXIF block is empty entirely.

```python
async def test_upload_exif_is_stripped(client, jpeg_exif_bytes):
    r = await _upload(client, jpeg_exif_bytes, "gps.jpg")
    assert r.status_code == 201
    serve_r = await client.get(r.json()["url"])
    img = Image.open(io.BytesIO(serve_r.content))
    assert img.info.get("exif", b"") == b""
```

---

### 9. `piexif` missing from dev requirements
**File:** `tests/conftest.py:45-57`, `requirements-dev.txt`

The EXIF fixture silently degrades to a plain JPEG if `piexif` is not installed, making the EXIF-strip test weaker without any indication.

**Potential solution:** Add `piexif` to dev dependencies and remove the `try/except ImportError`.

```
# requirements-dev.txt
piexif==1.1.3
```

---

## Suggestions

### 10. `innerHTML` with server-sourced data in frontend
**File:** `static/index.html` (metaFormat assignment)

`data.original_format` from Pillow is always a known ASCII constant, so there is no actual XSS risk today. However, mixing `innerHTML` with any server-derived value is a bad habit.

**Potential solution:** Use `textContent` for the format string and build the badge element separately via `createElement`.

---

### 11. Blob URLs never revoked — browser memory leak
**File:** `static/index.html`

`URL.createObjectURL(blob)` is called on every upload but `URL.revokeObjectURL()` is never called, accumulating memory across uploads in a session.

**Potential solution:** Track and revoke the previous object URL before creating a new one.

```javascript
let currentObjectUrl = null;

function revokeCurrentUrl() {
    if (currentObjectUrl) {
        URL.revokeObjectURL(currentObjectUrl);
        currentObjectUrl = null;
    }
}

// Before creating a new object URL:
revokeCurrentUrl();
currentObjectUrl = URL.createObjectURL(blob);
```

---

### 12. Deprecated HTTP 413 status constant
**File:** `app/routes/images.py:33`

`HTTP_413_REQUEST_ENTITY_TOO_LARGE` is deprecated in newer Starlette. The test run emits a `DeprecationWarning`.

**Potential solution:** Use the updated constant name.

```python
status_code=status.HTTP_413_CONTENT_TOO_LARGE,
```

---

### 13. Missing test coverage
The following scenarios have no test:

| Scenario | Why it matters |
|---|---|
| BMP upload | Allowed format, never exercised |
| TIFF upload | Allowed format, never exercised |
| `preserve_animation=False` setting | Static extraction path untested |
| `webp_lossless=True` setting | Lossless encode path untested |
| Zero-byte file upload | Edge case, should return 422 |
| Already-animated WebP upload | Re-encoding animated WebP |
| Decompression bomb (once fix #5 is applied) | Verify pixel budget enforced |

---

### 14. No linter or type checker configured
**File:** `pyproject.toml`

The broken annotation `settings: Settings = None` (should be `Settings | None`) would be caught immediately by mypy. There is no ruff, flake8, or mypy section in `pyproject.toml`.

**Potential solution:**

```toml
# pyproject.toml
[tool.mypy]
strict = true
ignore_missing_imports = true

[tool.ruff]
line-length = 100
select = ["E", "F", "I"]
```
