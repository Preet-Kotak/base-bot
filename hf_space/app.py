"""
Hugging Face Space — YOLO extract server (Gradio SDK, CPU).

Mounts a FastAPI app alongside Gradio so the Discord bot can call:
    POST /extract
        Header:  X-API-Key: <HF_API_KEY>
        Body:    multipart/form-data
                   file     — image file (jpg/png)
                   district — integer 0-8, or -1 to skip calibration (default -1)
        Returns: JSON  { buildings, anchor_found, total_detections, conf_used, calibrated, runs }
"""

import os
import tempfile
from pathlib import Path

import gradio as gr
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

# ── config ────────────────────────────────────────────────────────────────────
API_KEY      = os.environ.get("HF_API_KEY", "")
WEIGHTS_PATH = Path(__file__).parent / "model" / "best.pt"

# ── lazy model singleton ───────────────────────────────────────────────────────
_extractor = None


def get_extractor():
    global _extractor
    if _extractor is None:
        from extractor import Extractor
        _extractor = Extractor(weights=str(WEIGHTS_PATH))
    return _extractor


# ── FastAPI app ────────────────────────────────────────────────────────────────
fastapi_app = FastAPI(title="YOLO Extract API")


def _check_key(x_api_key: str):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server misconfigured: HF_API_KEY not set.")
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@fastapi_app.get("/health")
def health():
    return {"status": "ok"}


@fastapi_app.post("/extract")
async def extract(
    file:      UploadFile = File(...),
    district:  int        = Form(-1),
    x_api_key: str        = Header(...),
):
    _check_key(x_api_key)

    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

    suffix = Path(file.filename or "img.jpg").suffix or ".jpg"
    tmp    = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        contents = await file.read()
        tmp.write(contents)
        tmp.close()

        dist_arg = int(district) if int(district) >= 0 else None
        result   = get_extractor().extract(tmp.name, district=dist_arg)

    except HTTPException:
        raise
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


# ── Gradio UI — required by Gradio SDK to keep the Space running ───────────────
with gr.Blocks() as gradio_ui:
    gr.Markdown("## YOLO Extract API\nInternal inference server. Use the `/extract` endpoint.")

app = gr.mount_gradio_app(fastapi_app, gradio_ui, path="/ui")
