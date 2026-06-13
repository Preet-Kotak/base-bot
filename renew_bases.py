"""
renew_bases.py — Open every saved CoC base link in an Android emulator via ADB.

Usage:
    python renew_bases.py                  # all districts
    python renew_bases.py --district 3     # Balloon Lagoon only
    python renew_bases.py --debug          # verbose output

Requirements (install once):
    pip install psycopg2-binary opencv-python numpy python-dotenv

Set DATABASE_URL in your .env file.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import psycopg2
import psycopg2.extras

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_SERIAL = "emulator-5554"

REFERENCE_WIDTH  = 1600
REFERENCE_HEIGHT = 900

INITIAL_WAIT_SECONDS      = 5.0    # wait after sending intent before pixel check
DETECTION_TIMEOUT_SECONDS = 10.0   # how long to keep retrying pixel checks
MAX_OPEN_ATTEMPTS         = 3      # attempts per base before giving up
RECOVERY_WAIT_SECONDS     = 20.0   # wait after force-stop when a base fails

FAILED_LOG_PATH = Path(__file__).parent / "failed_bases.log"

DISTRICT_NAMES = {
    0: "Capital Peak",
    1: "Barbarian Camp",
    2: "Wizard Valley",
    3: "Balloon Lagoon",
    4: "Builder's Workshop",
    5: "Dragon Cliffs",
    6: "Golem Quarry",
    7: "Skeleton Park",
    8: "Goblin Mines",
}

# Tap sequence after base popup is confirmed open.
TAP_SEQUENCE = [
    (800,  400),   # button 1
    (800,  550),   # button 2
    (1488, 634),   # button 3
    (950,  550),   # button 4
    (1511,  68),   # red X close
]

# ---------------------------------------------------------------------------
# Pixel checks — confirm base viewer popup is visible
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PixelCheck:
    name:                  str
    x:                     int
    y:                     int
    color_range_start_hex: str
    color_range_end_hex:   str


PIXEL_CHECKS = (
    PixelCheck("point-1", 1511,  68, "#EF6070", "#FF8086"),  # red X button
    PixelCheck("point-2",  800, 800, "#EFB864", "#FFDA84"),  # bottom toolbar
    PixelCheck("point-3",  800, 400, "#ED9600", "#FFB610"),  # orange icon
)

# Button color — tap is considered registered when pixel moves away from this.
BUTTON_HEX       = "#FFAF12"
BUTTON_TOLERANCE = 20

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

DEBUG  = False
SERIAL = DEFAULT_SERIAL

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _out(msg: str) -> None:
    print(msg, flush=True)

def _debug(msg: str) -> None:
    if DEBUG:
        print(f"  [debug] {msg}", flush=True)

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    s = h.strip().lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)

def _pixel_in_range(rgb, a, b) -> bool:
    lo = (min(a[0],b[0]), min(a[1],b[1]), min(a[2],b[2]))
    hi = (max(a[0],b[0]), max(a[1],b[1]), max(a[2],b[2]))
    return lo[0]<=rgb[0]<=hi[0] and lo[1]<=rgb[1]<=hi[1] and lo[2]<=rgb[2]<=hi[2]

def _scale_point(w: int, h: int, rx: int, ry: int) -> tuple[int, int]:
    x = max(0, min(w-1, int(round(w * rx / REFERENCE_WIDTH))))
    y = max(0, min(h-1, int(round(h * ry / REFERENCE_HEIGHT))))
    return x, y

# ---------------------------------------------------------------------------
# ADB
# ---------------------------------------------------------------------------

def _adb(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["adb", *args], capture_output=True, text=True, check=False)

def _adb_bytes(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["adb", *args], capture_output=True, check=False)

def _ensure_connected() -> bool:
    _debug("Starting adb server...")
    _adb("start-server")
    cp = _adb("devices")
    if cp.returncode != 0:
        _out(f"ERROR: 'adb devices' failed: {cp.stderr.strip()}")
        return False
    for line in cp.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == SERIAL and parts[1] == "device":
            _debug(f"Already connected to {SERIAL}.")
            return True
    _debug(f"Connecting to {SERIAL}...")
    _adb("connect", SERIAL)
    cp = _adb("devices")
    for line in cp.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == SERIAL and parts[1] == "device":
            _debug(f"Connected to {SERIAL}.")
            return True
    _out(f"ERROR: Could not connect to emulator at {SERIAL}.")
    return False

def _shell(command: str, description: str) -> bool:
    _debug(f"shell: {description}")
    cp = _adb("-s", SERIAL, "shell", command)
    if cp.returncode != 0:
        _debug(f"  failed: {(cp.stderr or cp.stdout or '').strip()}")
        return False
    return True

def _screencap() -> bytes | None:
    cp = _adb_bytes("-s", SERIAL, "exec-out", "screencap", "-p")
    if cp.returncode != 0 or not cp.stdout:
        return None
    return cp.stdout

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detect_base_screen() -> bool:
    checks = [
        (c, _hex_to_rgb(c.color_range_start_hex), _hex_to_rgb(c.color_range_end_hex))
        for c in PIXEL_CHECKS
    ]
    deadline = time.perf_counter() + DETECTION_TIMEOUT_SECONDS
    attempt  = 0
    while time.perf_counter() < deadline:
        attempt += 1
        png = _screencap()
        if png is None:
            return False
        frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return False
        h, w     = frame.shape[:2]
        all_pass = True
        for check, rgb_a, rgb_b in checks:
            x, y    = _scale_point(w, h, check.x, check.y)
            b, g, r = frame[y, x]
            rgb     = (int(r), int(g), int(b))
            passed  = _pixel_in_range(rgb, rgb_a, rgb_b)
            _debug(f"  {'OK  ' if passed else 'FAIL'} {check.name} @ ({x},{y}) "
                   f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X} "
                   f"expected [{check.color_range_start_hex},{check.color_range_end_hex}]")
            if not passed:
                all_pass = False
        if all_pass:
            _debug(f"All pixels matched on screencap {attempt}.")
            return True
    _debug(f"Detection timed out after {attempt} screencaps.")
    return False

# ---------------------------------------------------------------------------
# Tap sequence
# ---------------------------------------------------------------------------

def _run_tap_sequence() -> tuple[bool, int]:
    """
    Run all 5 taps. Each tap is retried up to 3 times if the pixel doesn't change.
    Returns (all_taps_succeeded, first_failed_tap_number).
    """
    btn_rgb = _hex_to_rgb(BUTTON_HEX)
    tol     = BUTTON_TOLERANCE

    for tap_num, (tx, ty) in enumerate(TAP_SEQUENCE, start=1):
        tapped = False
        for tap_try in range(3):
            _shell(f"input tap {tx} {ty}", f"tap {tap_num} ({tx},{ty}) try {tap_try+1}")
            time.sleep(1.0)
            png = _screencap()
            if png is None:
                break
            frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                break
            h, w   = frame.shape[:2]
            sx, sy = _scale_point(w, h, tx, ty)
            b, g, r = frame[sy, sx]
            rgb = (int(r), int(g), int(b))
            still_btn = _pixel_in_range(
                rgb,
                (max(0,   btn_rgb[0]-tol), max(0,   btn_rgb[1]-tol), max(0,   btn_rgb[2]-tol)),
                (min(255, btn_rgb[0]+tol), min(255, btn_rgb[1]+tol), min(255, btn_rgb[2]+tol)),
            )
            if not still_btn:
                _debug(f"  Tap {tap_num} ({tx},{ty}) registered → #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")
                tapped = True
                break
            _debug(f"  Tap {tap_num} ({tx},{ty}) not registered (#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}), retrying...")

        if not tapped:
            _out(f"  Tap {tap_num} at ({tx},{ty}) failed all 3 tries.")
            return False, tap_num

    return True, 0

# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

def _recover_game() -> None:
    _out(f"  Recovering — force-stopping CoC, waiting {int(RECOVERY_WAIT_SECONDS)}s...")
    _shell("am force-stop com.supercell.clashofclans", "recovery force-stop")
    time.sleep(RECOVERY_WAIT_SECONDS)
    # Relaunch CoC to leave it ready for the next base.
    _shell("monkey -p com.supercell.clashofclans -c android.intent.category.LAUNCHER 1",
           "relaunch CoC")
    _out("  Recovery done — CoC relaunched.")

# ---------------------------------------------------------------------------
# Log failed base
# ---------------------------------------------------------------------------

def _log_failed(base_id: int, district_number: int, link: str, reason: str) -> None:
    district_name = DISTRICT_NAMES.get(district_number, f"District {district_number}")
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = (f"[{ts}] FAILED  id={base_id}  district={district_number} ({district_name})"
            f"  reason={reason}  link={link}\n")
    with FAILED_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)
    _out(f"  → Logged to failed_bases.log")

# ---------------------------------------------------------------------------
# Open a single base link
# ---------------------------------------------------------------------------

def _open_link(base_id: int, district_number: int, https_link: str) -> bool:
    from urllib.parse import urlparse
    parsed = urlparse(https_link)
    if not parsed.query:
        reason = "invalid link — no query string"
        _out(f"  FAIL: {reason}")
        _log_failed(base_id, district_number, https_link, reason)
        return False

    protocol_link = f"clashofclans://{parsed.query}"
    intent_cmd    = f"am start -a android.intent.action.VIEW -d '{protocol_link}'"
    _debug(f"Protocol link: {protocol_link}")

    for attempt in range(1, MAX_OPEN_ATTEMPTS + 1):
        _debug(f"--- Attempt {attempt}/{MAX_OPEN_ATTEMPTS} ---")

        if not _shell(intent_cmd, "launch VIEW intent"):
            _out(f"  Attempt {attempt}  FAIL (launch intent)")
            continue

        _debug(f"Waiting {INITIAL_WAIT_SECONDS}s for base to load...")
        time.sleep(INITIAL_WAIT_SECONDS)

        if not _detect_base_screen():
            _out(f"  Attempt {attempt}  FAIL (pixel check — base not detected)")
            continue

        _out(f"  Attempt {attempt}  detected OK — running taps...")
        taps_ok, failed_tap = _run_tap_sequence()

        if taps_ok:
            time.sleep(2.0)  # let popup fully dismiss before next link
            return True

        _out(f"  Attempt {attempt}  FAIL (tap {failed_tap} did not register)")

    # All attempts exhausted.
    reason = f"failed after {MAX_OPEN_ATTEMPTS} attempts"
    _out(f"  FAIL: {reason}")
    _log_failed(base_id, district_number, https_link, reason)
    _recover_game()
    return False

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _load_links(district: int | None) -> list[dict]:
    from urllib.parse import urlparse, unquote
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        _out("ERROR: DATABASE_URL is not set. Add it to your .env file.")
        sys.exit(1)
    raw    = raw.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(raw)
    conn   = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        dbname=parsed.path.lstrip("/"),
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        sslmode="require",
    )
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if district is not None:
        cur.execute(
            "SELECT id, district_number, link FROM bases WHERE district_number = %s ORDER BY district_number, id",
            (district,),
        )
    else:
        cur.execute("SELECT id, district_number, link FROM bases ORDER BY district_number, id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Renew CoC base links via ADB.")
    p.add_argument("--district", type=int, default=None, metavar="N",
                   help="Only process district N (0–8). Omit for all districts.")
    p.add_argument("--serial", default=DEFAULT_SERIAL,
                   help=f"ADB serial of the emulator (default: {DEFAULT_SERIAL})")
    p.add_argument("--debug", action="store_true", help="Verbose debug output.")
    return p.parse_args()


def main() -> int:
    global DEBUG, SERIAL
    args   = _parse_args()
    DEBUG  = args.debug
    SERIAL = args.serial

    _out("Connecting to database...")
    rows = _load_links(args.district)

    if not rows:
        scope = DISTRICT_NAMES.get(args.district, f"district {args.district}") if args.district is not None else "database"
        _out(f"No bases found in {scope}.")
        return 0

    scope_label = (
        DISTRICT_NAMES.get(args.district, f"district {args.district}")
        if args.district is not None else "all districts"
    )
    _out(f"Found {len(rows)} base(s) in {scope_label}.")
    _out(f"Failed bases will be logged to: {FAILED_LOG_PATH}")
    _out("")

    if not _ensure_connected():
        return 1

    _out("")

    total  = len(rows)
    ok     = 0
    failed = 0

    # Write run header to log.
    with FAILED_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n--- Run started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"({scope_label}, {total} bases) ---\n")

    for i, row in enumerate(rows, start=1):
        district_name = DISTRICT_NAMES.get(row["district_number"], f"District {row['district_number']}")
        _out(f"[{i}/{total}] Base #{row['id']} — {district_name}")
        _out(f"  {row['link']}")

        if _open_link(row["id"], row["district_number"], row["link"]):
            ok += 1
        else:
            failed += 1

        _out("")

    _out("=" * 50)
    _out("Done")
    _out(f"  Total : {total}")
    _out(f"  OK    : {ok}")
    _out(f"  Failed: {failed}")
    if failed:
        _out(f"  See failed_bases.log for details.")
    _out("=" * 50)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
