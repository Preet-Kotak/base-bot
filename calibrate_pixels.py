"""
calibrate_pixels.py — Step-by-step pixel calibration for renew_bases.py.

This tool walks you through all 5 screens that appear during a base renewal,
taking a screenshot at each step so you can find the exact button coordinates.

SCREENS:
  ss1 — Base viewer popup is open           → find button 1 (slot select, ~800,400)
  ss2 — After clicking slot select          → find button 2 (OK, middle of screen)
  ss3 — After clicking OK                   → find button 3 (Cancel)
  ss4 — After clicking Cancel               → find button 4 (OK to confirm cancel)
  ss5 — After clicking OK (base changed)    → find button 5 (red X to close)

HOW TO USE:
  1. Make sure CoC is open in LDPlayer (on your village screen).
  2. Run:
         python calibrate_pixels.py
  3. Follow the prompts — it will tell you what to click in LDPlayer
     and take a screenshot when you press ENTER.
  4. A pixel finder window opens for each screen.
     Hover over the button and note the x, y, HEX from the title bar.
  5. Press Q (or S) to close each window and move to the next screen.
  6. At the end, it prints a summary of all coordinates you found.

Optional flags:
  --serial emulator-5554    ADB serial (default: emulator-5554)
  --link   <https_link>     Base link to open (uses built-in default if omitted)
"""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np

# Default calibration link
CALIBRATION_LINK = (
    "https://link.clashofclans.com/en"
    "?action=OpenLayout&id=TH5%3ACC%3A3%3AAAAAEAAAAALSyGk9Jh2FcsNPq-Jgz2-Q"
)

STEPS = [
    {
        "name": "ss1",
        "label": "Screen 1 — Base viewer popup",
        "instruction": (
            "The base link has been sent to CoC.\n"
            "Wait for the BASE VIEWER POPUP to fully appear on screen.\n"
            "Press ENTER when the popup is fully visible."
        ),
        "find": "Button 1 — Slot select button (the one that starts the renewal flow)",
    },
    {
        "name": "ss2",
        "label": "Screen 2 — Slot select clicked (OK dialog)",
        "instruction": (
            "Click Button 1 (slot select) in LDPlayer now.\n"
            "Wait for the OK confirmation dialog to appear.\n"
            "Press ENTER when the OK dialog is visible."
        ),
        "find": "Button 2 — OK button (confirm slot selection)",
    },
    {
        "name": "ss3",
        "label": "Screen 3 — After OK (Cancel dialog)",
        "instruction": (
            "Click the OK button in LDPlayer now.\n"
            "Wait for the Cancel confirmation screen to appear.\n"
            "Press ENTER when visible."
        ),
        "find": "Button 3 — Cancel button",
    },
    {
        "name": "ss4",
        "label": "Screen 4 — After Cancel (final OK dialog)",
        "instruction": (
            "Click the Cancel button in LDPlayer now.\n"
            "Wait for the final OK dialog to appear.\n"
            "Press ENTER when visible."
        ),
        "find": "Button 4 — OK button (confirm cancel / close base change menu)",
    },
    {
        "name": "ss5",
        "label": "Screen 5 — Base change menu closed (red X)",
        "instruction": (
            "Click the OK button in LDPlayer now.\n"
            "Wait for the base viewer popup to return (with the red X visible).\n"
            "Press ENTER when visible."
        ),
        "find": "Button 5 — Red X close button (top right of popup)",
    },
]


# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------

def _adb(serial: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        capture_output=True, text=True, check=False,
    )

def _adb_bytes(serial: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        capture_output=True, check=False,
    )

def _ensure_connected(serial: str) -> bool:
    subprocess.run(["adb", "start-server"], capture_output=True)
    cp = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    for line in cp.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == serial and parts[1] == "device":
            print(f"Connected to {serial}.")
            return True
    subprocess.run(["adb", "connect", serial], capture_output=True)
    cp = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    for line in cp.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == serial and parts[1] == "device":
            print(f"Connected to {serial}.")
            return True
    print(f"ERROR: Could not connect to {serial}.")
    return False

def _open_link(serial: str, https_link: str) -> None:
    parsed       = urlparse(https_link)
    protocol     = f"clashofclans://{parsed.query}"
    intent_cmd   = f"am start -a android.intent.action.VIEW -d '{protocol}'"
    _adb(serial, "shell", intent_cmd)

def _screencap(serial: str) -> bytes | None:
    cp = _adb_bytes(serial, "exec-out", "screencap", "-p")
    if cp.returncode != 0 or not cp.stdout:
        print("ERROR: screencap failed.")
        return None
    return cp.stdout

# ---------------------------------------------------------------------------
# Pixel finder window
# ---------------------------------------------------------------------------

def _mouse_callback(event, x, y, flags, param) -> None:
    frame = param
    if event == cv2.EVENT_MOUSEMOVE:
        h, w = frame.shape[:2]
        if 0 <= x < w and 0 <= y < h:
            b, g, r   = frame[y, x]
            hex_color = f"#{r:02X}{g:02X}{b:02X}"
            cv2.setWindowTitle(
                "Calibration",
                f"x={x}, y={y}  |  RGB=({r},{g},{b})  HEX={hex_color}  "
                f"|  {w}x{h}  |  S=save  Q=quit"
            )

def _show_pixel_finder(frame: np.ndarray, save_path: Path, step_label: str, find_hint: str) -> None:
    h, w = frame.shape[:2]
    print(f"\n  Resolution: {w}x{h}")
    print(f"  What to find: {find_hint}")
    print("  Hover over the button — title bar shows x, y, HEX in real time.")
    print("  Press S to save screenshot, Q to close this screen.\n")

    cv2.imwrite(str(save_path), frame)
    print(f"  Screenshot saved: {save_path}")

    cv2.namedWindow("Calibration", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Calibration", min(w, 1600), min(h, 900))
    cv2.setWindowTitle("Calibration", step_label)
    cv2.setMouseCallback("Calibration", _mouse_callback, frame)
    cv2.imshow("Calibration", frame)

    while True:
        key = cv2.waitKey(50) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("s"):
            cv2.imwrite(str(save_path), frame)
            print(f"  Saved: {save_path}")
            break
        if cv2.getWindowProperty("Calibration", cv2.WND_PROP_VISIBLE) < 1:
            break

    cv2.destroyAllWindows()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Step-by-step calibration for renew_bases.py")
    parser.add_argument("--serial", default="emulator-5554",
                        help="ADB serial of your emulator (default: emulator-5554)")
    parser.add_argument("--link",   default=CALIBRATION_LINK,
                        help="Base link to open for calibration")
    args = parser.parse_args()

    base_dir = Path(__file__).parent

    print("=" * 60)
    print("CoC Base Renewal — Pixel Calibration")
    print("=" * 60)
    print()
    print("This tool walks you through all 5 button screens.")
    print("For each screen:")
    print("  1. Do what the instruction says in LDPlayer")
    print("  2. Press ENTER here when the correct screen is visible")
    print("  3. A window opens — hover over the button to read coordinates")
    print("  4. Note down x, y, HEX then press Q")
    print()

    if not _ensure_connected(args.serial):
        return 1

    # Send the base link to open the popup.
    print("Opening base link in CoC (no force-stop — game must already be running)...")
    _open_link(args.serial, args.link)
    print("Link sent. Wait for the base viewer popup to appear.\n")

    collected: list[dict] = []

    for step_num, step in enumerate(STEPS, start=1):
        print(f"--- Step {step_num}/5: {step['label']} ---")
        print(f"  {step['instruction']}")
        input("  >>> Press ENTER when ready to take screenshot...")

        print("  Taking screenshot...", end="", flush=True)
        png = _screencap(args.serial)
        if png is None:
            print(" FAILED. Check ADB connection.")
            return 1

        frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            print(" Could not decode image.")
            return 1
        print(" done.")

        save_path = base_dir / f"{step['name']}.png"
        _show_pixel_finder(frame, save_path, step["label"], step["find"])

        x_str   = input("  Enter x coordinate you found (or leave blank to skip): ").strip()
        y_str   = input("  Enter y coordinate you found (or leave blank to skip): ").strip()
        hex_str = input("  Enter HEX color you found   (or leave blank to skip): ").strip()
        collected.append({
            "step":  step_num,
            "label": step["label"],
            "find":  step["find"],
            "x":     x_str,
            "y":     y_str,
            "hex":   hex_str,
        })
        print()

    # Print summary.
    print("=" * 60)
    print("Calibration Summary")
    print("=" * 60)
    print()
    print("Update TAP_SEQUENCE in renew_bases.py with these coordinates:\n")
    print("TAP_SEQUENCE = [")
    for item in collected:
        x   = item["x"]   or "???"
        y   = item["y"]   or "???"
        print(f"    ({x:>4}, {y:>4}),   # {item['find']}")
    print("]")
    print()
    print("Full details:")
    for item in collected:
        print(f"  Step {item['step']}: {item['find']}")
        print(f"    x={item['x']}  y={item['y']}  hex={item['hex']}")
    print()
    print("Done. Update renew_bases.py TAP_SEQUENCE with the above values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
