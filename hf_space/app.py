"""
Hugging Face Space — YOLO extract server.

Exposes a single endpoint:
    POST /extract
        Header:  X-API-Key: <HF_API_KEY>
        Body:    multipart/form-data
                   file     — image file (jpg/png)
                   district — integer 0-8, or -1 to skip calibration (optional, default -1)
        Returns: JSON  { buildings, anchor_found, total_detections, conf_used, calibrated, runs }

The Discord bot on Render calls this endpoint instead of running YOLO locally.
All matching and drawing logic stays on Render — only YOLO inference lives here.
"""

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

# ── load model once at startup ────────────────────────────────────────────────
# HF Spaces stores secrets as env vars — set HF_API_KEY in Space secrets.
API_KEY      = os.environ.get("HF_API_KEY", "")
WEIGHTS_PATH = Path(__file__).parent / "model" / "best.pt"

# lazy singleton — loaded on first request to keep startup fast
_extractor = None


def get_extractor():
    global _extractor
    if _extractor is None:
        # import here so the module loads even if ultralytics isn't installed yet
        # during the Space build phase
        from extractor import Extractor
        _extractor = Extractor(weights=str(WEIGHTS_PATH))
    return _extractor


# ── app ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="YOLO Extract API")


def _check_key(x_api_key: str):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server misconfigured: HF_API_KEY not set.")
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@app.get("/health")
def health():
    """Keepalive probe — always returns 200."""
    return {"status": "ok"}


@app.post("/extract")
async def extract(
    file:     UploadFile = File(...),
    district: int        = Form(-1),
    x_api_key: str       = Header(...),
):
    """
    Run YOLO on the uploaded image and return the building layout as JSON.

    district: 0-8 to enable calibration, -1 (or omit) to skip.
    """
    _check_key(x_api_key)

    # validate file type
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

    # write to temp file
    suffix = Path(file.filename or "img.jpg").suffix or ".jpg"
    tmp    = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        contents = await file.read()
        tmp.write(contents)
        tmp.close()

        ext      = get_extractor()
        dist_arg = int(district) if int(district) >= 0 else None
        result   = ext.extract(tmp.name, district=dist_arg)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    return JSONResponse(content={
        "buildings":        result["buildings"],
        "anchor_found":     result["anchor_found"],
        "total_detections": result["total_detections"],
        "conf_used":        result["conf_used"],
        "calibrated":       result["calibrated"],
        "runs":             result["runs"],
    })
