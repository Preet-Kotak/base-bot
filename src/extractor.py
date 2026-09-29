"""
Layout extractor — runs YOLO on a screenshot and returns normalized building positions.
Includes confidence auto-calibration to hit the expected building count per district.

On Render (bot server) use remote_extract() which calls the HF Space API.
The local Extractor class is kept for reference / local dev only.

Usage:
    from src.extractor import remote_extract
    result = await remote_extract(image_bytes, district=0)
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# HF Space remote API config
HF_SPACE_URL = os.getenv("HF_SPACE_URL", "").rstrip("/")
HF_API_KEY   = os.getenv("HF_API_KEY", "")

DISTRICT_MAP = {
    0: "capital_peak",
    1: "barbarian_camp",
    2: "wizard_valley",
    3: "balloon_lagoon",
    4: "builders_workshop",
    5: "dragon_cliffs",
    6: "golem_quarry",
    7: "skeleton_park",
    8: "goblin_mines",
}

# valid building counts per district — either count is acceptable
# None means no calibration for that district
DISTRICT_COUNTS: dict[int, list[int]] = {
    0: [50, 48],  # capital_peak
    1: [58, 54],  # barbarian_camp
    2: [49, 47],  # wizard_valley
    3: [56, 54],  # balloon_lagoon
    4: [58, 53],  # builders_workshop
    5: [47],      # dragon_cliffs
    6: [58, 57],  # golem_quarry
    7: [59, 54],  # skeleton_park
    8: [55, 52],  # goblin_mines
}

ANCHOR_CLASSES = {"district_hall", "capital_peak"}
# ─────────────────────────────────────────────


async def remote_extract(
    image_bytes: bytes,
    filename: str = "image.jpg",
    district: int | None = None,
    timeout: float = 60.0,
) -> dict:
    """
    Call the HF Space /extract endpoint and return the result dict.

    Args:
        image_bytes: raw image bytes
        filename:    original filename (used for content-type hint)
        district:    0-8 for calibration, None to skip
        timeout:     httpx timeout in seconds (YOLO can be slow on CPU)

    Returns:
        {
            "buildings":        [{type, x, y, conf}],
            "anchor_found":     bool,
            "total_detections": int,
            "conf_used":        float,
            "calibrated":       bool,
            "runs":             int,
        }

    Raises:
        RuntimeError: if HF_SPACE_URL / HF_API_KEY not set, or request fails.
    """
    if not HF_SPACE_URL:
        raise RuntimeError(
            "HF_SPACE_URL is not set. Add it to your environment variables."
        )
    if not HF_API_KEY:
        raise RuntimeError(
            "HF_API_KEY is not set. Add it to your environment variables."
        )

    district_val = district if district is not None else -1

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{HF_SPACE_URL}/extract",
            headers={"X-API-Key": HF_API_KEY},
            data={"district": str(district_val)},
            files={"file": (filename, image_bytes, "image/jpeg")},
        )

    if response.status_code == 401:
        raise RuntimeError("HF Space rejected the API key — check HF_API_KEY.")
    if response.status_code != 200:
        raise RuntimeError(
            f"HF Space returned {response.status_code}: {response.text[:200]}"
        )

    return response.json()
