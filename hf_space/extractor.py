"""
Layout extractor — runs YOLO on a screenshot and returns normalized building positions.
Includes confidence auto-calibration to hit the expected building count per district.

HF Space flat copy — weights resolved relative to this file (./model/best.pt).
"""

import os
from pathlib import Path
from ultralytics import YOLO

# ─────────────────────────────────────────────
_HERE    = Path(__file__).parent
WEIGHTS  = os.getenv("WEIGHTS", str(_HERE / "model" / "best.pt"))

DEFAULT_CONF = 0.25
IOU          = 0.5
MAX_RUNS     = 3
CONF_STEP    = 0.05
CONF_MIN     = 0.10
CONF_MAX     = 0.50

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

DISTRICT_COUNTS: dict[int, list[int]] = {
    0: [50, 48],
    1: [58, 54],
    2: [49, 47],
    3: [56, 54],
    4: [58, 53],
    5: [47],
    6: [58, 57],
    7: [59, 54],
    8: [55, 52],
}

ANCHOR_CLASSES = {"district_hall", "capital_peak"}
# ─────────────────────────────────────────────


def _is_valid_count(count: int, valid_counts: list[int]) -> bool:
    return count in valid_counts


def _closest_count(count: int, valid_counts: list[int]) -> int:
    return min(valid_counts, key=lambda v: abs(count - v))


class Extractor:
    def __init__(self, weights: str = WEIGHTS):
        self.model = YOLO(weights)

    def _run_inference(self, image_path: Path, conf: float) -> dict:
        results = self.model.predict(
            source=str(image_path),
            conf=conf,
            iou=IOU,
            verbose=False,
        )
        result = results[0]
        names  = result.names
        boxes  = result.boxes

        buildings    = []
        anchor_x     = 0.5
        anchor_y     = 0.5
        anchor_found = False

        for box in boxes:
            cls_name = names[int(box.cls[0])]
            if cls_name in ANCHOR_CLASSES:
                anchor_x     = float(box.xywhn[0][0])
                anchor_y     = float(box.xywhn[0][1])
                anchor_found = True
                break

        for box in boxes:
            cls_name = names[int(box.cls[0])]
            conf_val = float(box.conf[0])
            x_center = float(box.xywhn[0][0])
            y_center = float(box.xywhn[0][1])
            buildings.append({
                "type": cls_name,
                "x":    round(x_center - anchor_x, 4),
                "y":    round(y_center - anchor_y, 4),
                "conf": round(conf_val, 3),
            })

        return {
            "buildings":        buildings,
            "anchor_found":     anchor_found,
            "total_detections": len(buildings),
        }

    def extract(self, image_path: str | Path, district: int | None = None) -> dict:
        image_path   = Path(image_path)
        valid_counts = DISTRICT_COUNTS.get(district) if district is not None else None

        if valid_counts is None:
            result = self._run_inference(image_path, DEFAULT_CONF)
            result["conf_used"]  = DEFAULT_CONF
            result["calibrated"] = False
            result["runs"]       = 1
            return result

        conf        = DEFAULT_CONF
        best_result = None
        best_diff   = float("inf")

        for run in range(1, MAX_RUNS + 1):
            result = self._run_inference(image_path, conf)
            count  = result["total_detections"]

            diff = min(abs(count - v) for v in valid_counts)
            if diff < best_diff:
                best_diff              = diff
                best_result            = result
                best_result["conf_used"]  = conf
                best_result["runs"]       = run
                best_result["calibrated"] = True

            if _is_valid_count(count, valid_counts):
                return best_result

            if run == MAX_RUNS:
                break

            closest = _closest_count(count, valid_counts)
            if count < closest:
                conf = max(CONF_MIN, conf - CONF_STEP)
            else:
                conf = min(CONF_MAX, conf + CONF_STEP)

        return best_result
