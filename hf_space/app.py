"""
Hugging Face Space — YOLO extract server (Gradio + ZeroGPU).

Mounts a FastAPI app on the Gradio server so the Discord bot can call:
    POST /extract
        Header:  X-API-Key: <HF_API_KEY>
        Body:    multipart/form-data
                   file     — image file (jpg/png)
                   district — integer 0-8, or -1 to skip calibration (default -1)
        Returns: JSON  { buildings, anchor_found, total_detections, conf_used, calibrated, runs }

ZeroGPU allocates a GPU for the duration of the decorated function call.
"""

import os
import tempfile
from pathlib import Path

import gradio as gr
import spaces
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


# ── FastAPI app (mounted onto Gradio) ─────────────────────────────────────────
fastapi_app = FastAPI(title="YOLO Extract API")


def _check_key(x_api_key: str):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server misconfigured: HF_API_KEY not set.")
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@fastapi_app.get("/health")
def health():
    """Keepalive probe."""
    return {"status": "ok"}


@spaces.GPU
def _run_extraction(image_path: str, district: int | None) -> dict:
    """
    Wrapped with @spaces.GPU so ZeroGPU allocates a GPU for this call.
    Must be a plain function (not async) for ZeroGPU compatibility.
    """
    ext = get_extractor()
    return ext.extract(image_path, district=district)


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
        result   = _run_extraction(tmp.name, dist_arg)

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


# ── Gradio UI (minimal — just keeps the Space alive) ──────────────────────────
with gr.Blocks() as gradio_ui:
    gr.Markdown("## YOLO Extract API\nInternal inference server. Use the `/extract` endpoint.")

# mount FastAPI onto Gradio and launch
gradio_ui.mount_gradio_app = None  # not needed
app = gr.mount_gradio_app(fastapi_app, gradio_ui, path="/ui")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
