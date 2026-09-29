"""
Match commands — base comparison commands using remote YOLO inference (HF Space).

/find_similar   — find top 10 bases ≥75% match for a given image or base_id
/compare_bases  — compare two bases (images or base_ids) and get a visual diff
/visualize_base — highlight a specific building class on a base image
"""

import io
import json
from typing import Optional

import cv2
import discord
import httpx
import numpy as np
from discord import app_commands

from config import DISTRICT_NAMES, DISTRICT_EMOJIS, DISTRICT_COLORS
from database import get_pool
from src.extractor import remote_extract
from src.matcher import match_layouts

# ─── constants ────────────────────────────────────────────────────────────────
MATCH_THRESHOLD = 75.0
MAX_RESULTS     = 10
GRAY_FACTOR     = 0.50
DOT_RADIUS      = 10
DOT_COLOR       = (0, 0, 255)   # red  — unmatched
DOT_OUTLINE     = (255, 255, 255)
DOT_VIS_COLOR   = (0, 200, 0)   # green — visualise

PRETTY_NAMES = {
    "air_bomb":        "Air Bomb",
    "air_defence":     "Air Defence",
    "blast_bow":       "Blast Bow",
    "bomb_tower":      "Bomb Tower",
    "cannon":          "Cannon",
    "capital_peak":    "Capital Peak",
    "crusher":         "Crusher",
    "district_hall":   "District Hall",
    "gaint_cannon":    "Giant Cannon",
    "hive":            "Hive",
    "inferno_tower":   "Inferno Tower",
    "motor":           "Mortar",
    "multi_cannon":    "Multi Cannon",
    "post_cannon":     "Post Cannon",
    "post_dragon":     "Post Dragon",
    "post_gaint":      "Post Giant",
    "post_goblin":     "Post Goblin",
    "rapid_rocket":    "Rapid Rocket",
    "reflector":       "Reflector",
    "rocket_artilery": "Rocket Artillery",
    "spear":           "Spear",
    "tesla":           "Tesla",
    "wizard_tower":    "Wizard Tower",
}


# ─── helpers ──────────────────────────────────────────────────────────────────

async def _download_bytes(url: str, timeout: float = 30.0) -> bytes:
    """Download a URL and return raw bytes."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url)
        r.raise_for_status()
    return r.content


async def _extract_from_bytes(
    image_bytes: bytes,
    filename: str,
    district: Optional[int],
) -> dict:
    """Call HF Space remote_extract. Raises ValueError with user-friendly message on failure."""
    try:
        return await remote_extract(image_bytes, filename=filename, district=district)
    except RuntimeError as e:
        raise ValueError(str(e))
    except httpx.TimeoutException:
        raise ValueError(
            "The YOLO server took too long to respond. Try again in a moment."
        )
    except Exception as e:
        raise ValueError(f"YOLO extraction failed: `{e}`")


async def _get_layout_for_base(
    base_id: int,
    district: Optional[int] = None,
) -> tuple[list[dict], dict]:
    """
    Fetch layout for a DB base.
    Returns (buildings, base_row_dict).
    Falls back to remote YOLO on screenshot URL if layout_json is NULL.
    Raises ValueError with a user-friendly message on failure.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, district_number, link, screenshot, builder_name,
                      description, layout_json
               FROM bases WHERE id = $1""",
            base_id,
        )

    if not row:
        raise ValueError(f"No base found with ID **{base_id}**.")

    row = dict(row)

    # fast path — layout already in DB
    if row["layout_json"] is not None:
        buildings = row["layout_json"]
        if isinstance(buildings, str):
            buildings = json.loads(buildings)
        return buildings, row

    # fallback — try remote YOLO on screenshot
    if not row["screenshot"]:
        raise ValueError(
            f"Base **#{base_id}** has no stored layout and no screenshot. "
            "Please re-upload the screenshot using `/edit_base`."
        )

    try:
        img_bytes = await _download_bytes(row["screenshot"])
    except Exception:
        raise ValueError(
            f"Base **#{base_id}** has no stored layout and its screenshot could not "
            "be downloaded. Please re-upload it using `/edit_base`."
        )

    dist = district if district is not None else row["district_number"]
    buildings_data = await _extract_from_bytes(img_bytes, "screenshot.jpg", dist)
    return buildings_data["buildings"], row


async def _get_layout_for_attachment(
    attachment: discord.Attachment,
    district: Optional[int],
) -> tuple[list[dict], bytes, float]:
    """
    Download a Discord attachment and run remote extraction.
    Returns (buildings, image_bytes, conf_used).
    image_bytes kept so we can pass it to pixel-box extraction later without re-downloading.
    """
    try:
        img_bytes = await _download_bytes(attachment.url)
    except Exception as e:
        raise ValueError(f"Could not download the uploaded image: `{e}`")

    result = await _extract_from_bytes(img_bytes, attachment.filename or "image.jpg", district)
    return result["buildings"], img_bytes, result.get("conf_used", 0.25)


async def _get_pixel_boxes_remote(
    image_bytes: bytes,
    filename: str,
) -> list[dict]:
    """
    Re-run remote extraction without district calibration to get pixel coords.
    The HF Space /extract endpoint already returns x/y relative to anchor,
    but NOT pixel coords. We re-run with conf fixed (no calibration, district=-1)
    purely to get the layout again — then combine with a fresh cv2 decode
    to get pixel coords from the normalised values.

    Since the HF endpoint only returns normalised coords, we reconstruct pixel
    positions from the downloaded image dimensions + normalised values.
    Note: xywhn coords are relative to image size, but our x/y are relative to
    the anchor. We need absolute normalised positions, which means we re-run
    extract with district=None so we get anchor-relative coords, then convert.

    Simpler approach: use the returned buildings from /extract and infer pixel
    positions from the normalised absolute positions stored before anchor subtraction.
    We can't do this exactly without the raw xywhn. Instead we use a simpler heuristic:
    decode the image, scale the (x, y) normalised-relative-to-anchor positions back
    to pixels using the image dimensions (approximate center region).
    """
    result   = await remote_extract(image_bytes, filename=filename, district=None)
    buildings = result["buildings"]

    # decode image to get dimensions
    nparr = np.frombuffer(image_bytes, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return []
    h, w = img.shape[:2]

    # x, y in buildings are relative to anchor (centre ≈ 0.5, 0.5 of image).
    # Add 0.5 back to get approximate absolute normalised position.
    pixel_boxes = []
    for b in buildings:
        abs_x = b["x"] + 0.5
        abs_y = b["y"] + 0.5
        # estimate a small bounding box (40x40 px) centred on the building
        cx = int(abs_x * w)
        cy = int(abs_y * h)
        half = 20
        pixel_boxes.append({
            "type": b["type"],
            "x":    b["x"],
            "y":    b["y"],
            "x1":   max(0, cx - half),
            "y1":   max(0, cy - half),
            "x2":   min(w, cx + half),
            "y2":   min(h, cy + half),
            "cx":   cx,
            "cy":   cy,
        })
    return pixel_boxes


def _find_unmatched_pixels(
    pixel_boxes: list[dict],
    unmatched_layout: list[dict],
    tolerance: float = 0.05,
) -> list[dict]:
    """Map normalised unmatched buildings back to pixel boxes."""
    unmatched_pixels = []
    used = set()
    for um in unmatched_layout:
        best_idx, best_dist = None, float("inf")
        for i, pb in enumerate(pixel_boxes):
            if i in used or pb["type"] != um["type"]:
                continue
            dist = ((pb["x"] - um["x"]) ** 2 + (pb["y"] - um["y"]) ** 2) ** 0.5
            if dist < best_dist:
                best_dist, best_idx = dist, i
        if best_idx is not None and best_dist < tolerance:
            unmatched_pixels.append(pixel_boxes[best_idx])
            used.add(best_idx)
    return unmatched_pixels


def _draw_comparison(
    img: np.ndarray,
    pixel_boxes: list[dict],
    unmatched_pixels: list[dict],
    label: str,
) -> np.ndarray:
    unmatched_coords = {(pb["cx"], pb["cy"]) for pb in unmatched_pixels}
    result = (img.astype(np.float32) * GRAY_FACTOR).astype(np.uint8)

    for pb in pixel_boxes:
        x1, y1, x2, y2 = pb["x1"], pb["y1"], pb["x2"], pb["y2"]
        cx, cy          = pb["cx"], pb["cy"]

        if (cx, cy) in unmatched_coords:
            result[y1:y2, x1:x2] = img[y1:y2, x1:x2]
            cv2.circle(result, (cx, cy), DOT_RADIUS + 2, DOT_OUTLINE, -1)
            cv2.circle(result, (cx, cy), DOT_RADIUS, DOT_COLOR, -1)
            text        = pb["type"]
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.3, 1)
            cv2.putText(
                result, text,
                (cx - tw // 2, cy + DOT_RADIUS + th + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1, cv2.LINE_AA,
            )

    cv2.putText(result, label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(result, label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2, cv2.LINE_AA)
    return result


def _draw_visualize(
    img: np.ndarray,
    pixel_boxes: list[dict],
    target_class: str,
) -> np.ndarray:
    result = (img.astype(np.float32) * GRAY_FACTOR).astype(np.uint8)
    for pb in pixel_boxes:
        if pb["type"] == target_class:
            x1, y1, x2, y2 = pb["x1"], pb["y1"], pb["x2"], pb["y2"]
            cx, cy          = pb["cx"], pb["cy"]
            result[y1:y2, x1:x2] = img[y1:y2, x1:x2]
            cv2.circle(result, (cx, cy), DOT_RADIUS + 2, DOT_OUTLINE, -1)
            cv2.circle(result, (cx, cy), DOT_RADIUS, DOT_VIS_COLOR, -1)

    label = f"Showing: {PRETTY_NAMES.get(target_class, target_class)}"
    cv2.putText(result, label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(result, label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2, cv2.LINE_AA)
    return result


def _bytes_to_cv2(image_bytes: bytes) -> Optional[np.ndarray]:
    nparr = np.frombuffer(image_bytes, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)


def _cv2_to_discord_file(img: np.ndarray, filename: str) -> discord.File:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("Failed to encode image.")
    return discord.File(io.BytesIO(buf.tobytes()), filename=filename)


def _stack_images(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    """Vertically stack two images, padding the narrower one."""
    h1, w1 = top.shape[:2]
    h2, w2 = bottom.shape[:2]
    max_w  = max(w1, w2)

    def _pad(img: np.ndarray) -> np.ndarray:
        diff = max_w - img.shape[1]
        if diff == 0:
            return img
        return cv2.copyMakeBorder(img, 0, 0, 0, diff, cv2.BORDER_CONSTANT, value=(30, 30, 30))

    sep = np.full((4, max_w, 3), 80, dtype=np.uint8)
    return np.vstack([_pad(top), sep, _pad(bottom)])


# ─── navigation view for /find_similar ────────────────────────────────────────

class MatchNavigationView(discord.ui.View):
    def __init__(self, matches: list[dict], current_index: int = 0):
        super().__init__(timeout=300)
        self.matches       = matches
        self.current_index = current_index
        self._refresh_buttons()

    def _clamp(self, v: int) -> int:
        return max(0, min(v, len(self.matches) - 1))

    def _refresh_buttons(self):
        idx   = self.current_index
        total = len(self.matches)
        self.prev_button.disabled  = idx == 0
        self.next_button.disabled  = idx >= total - 1
        self.counter_button.label  = f"{idx + 1} / {total}"

    def build_embed(self) -> discord.Embed:
        row             = self.matches[self.current_index]
        district_number = row["district_number"]
        match_pct       = row["match_pct"]

        district_name = DISTRICT_NAMES.get(district_number, f"District {district_number + 1}")
        emoji         = DISTRICT_EMOJIS.get(district_number, "🏰")
        color         = DISTRICT_COLORS.get(district_number, 0x5865F2)
        match_bar     = "🟢" if match_pct >= 90 else ("🟡" if match_pct >= 75 else "🔴")

        embed = discord.Embed(title=f"{emoji}  {district_name}", color=color)
        embed.description = row.get("description") or None
        if row.get("screenshot"):
            embed.set_image(url=row["screenshot"])

        embed.add_field(name="🎯 Match",       value=f"{match_bar} **{match_pct}%**",       inline=True)
        embed.add_field(name="🏗️ Builder",    value=row.get("builder_name") or "*Unknown*", inline=True)
        embed.add_field(name="🔗 Layout Link", value=row["link"],                            inline=False)
        embed.set_footer(
            text=(
                f"Base #{row['id']}  ·  Match {self.current_index + 1} of {len(self.matches)}"
                f"  ·  Clan Capital Base Bot"
            )
        )
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index = self._clamp(self.current_index - 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.grey, disabled=True, row=0)
    async def counter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index = self._clamp(self.current_index + 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ─── command registration ──────────────────────────────────────────────────────

def register(bot):

    # ── /find_similar ──────────────────────────────────────────────────────────
    @bot.tree.command(
        name="find_similar",
        description="Find bases similar to an image or a stored base",
    )
    @app_commands.describe(
        image="Upload a screenshot to match against (optional if base_id given)",
        base_id="ID of a stored base to match against (optional if image given)",
        district="District to search in (required)",
        match_mode="strict = exact type  |  fuzzy = cannon & spear count as same (default: strict)",
    )
    @app_commands.choices(
        district=[
            app_commands.Choice(name="Capital Peak (District 1)",       value="0"),
            app_commands.Choice(name="Barbarian Camp (District 2)",     value="1"),
            app_commands.Choice(name="Wizard Valley (District 3)",      value="2"),
            app_commands.Choice(name="Balloon Lagoon (District 4)",     value="3"),
            app_commands.Choice(name="Builder's Workshop (District 5)", value="4"),
            app_commands.Choice(name="Dragon Cliffs (District 6)",      value="5"),
            app_commands.Choice(name="Golem Quarry (District 7)",       value="6"),
            app_commands.Choice(name="Skeleton Park (District 8)",      value="7"),
            app_commands.Choice(name="Goblin Mines (District 9)",       value="8"),
        ],
        match_mode=[
            app_commands.Choice(name="Strict", value="strict"),
            app_commands.Choice(name="Fuzzy",  value="fuzzy"),
        ],
    )
    async def find_similar(
        interaction: discord.Interaction,
        district: str,
        image: Optional[discord.Attachment] = None,
        base_id: Optional[int] = None,
        match_mode: Optional[str] = "strict",
    ):
        await interaction.response.defer()

        if not image and base_id is None:
            await interaction.followup.send("❌ Provide either an `image` or a `base_id`.", ephemeral=True)
            return

        district_int  = int(district)
        fuzzy         = match_mode == "fuzzy"
        district_name = DISTRICT_NAMES.get(district_int, f"District {district_int + 1}")

        # --- get input layout ---
        if image:
            try:
                input_buildings, _, _ = await _get_layout_for_attachment(image, district_int)
            except ValueError as e:
                await interaction.followup.send(f"❌ {e}")
                return
        else:
            try:
                input_buildings, _ = await _get_layout_for_base(base_id, district_int)
            except ValueError as e:
                await interaction.followup.send(f"❌ {e}")
                return

        # --- load all DB bases for this district ---
        pool = await get_pool()
        async with pool.acquire() as conn:
            db_rows = await conn.fetch(
                """SELECT id, district_number, link, screenshot, builder_name,
                          description, layout_json
                   FROM bases
                   WHERE district_number = $1
                   ORDER BY id""",
                district_int,
            )

        if not db_rows:
            await interaction.followup.send(f"❌ No bases found in **{district_name}**.")
            return

        # --- match against each base ---
        results = []
        for row in db_rows:
            row = dict(row)
            db_buildings = row.get("layout_json")

            # fallback — try remote YOLO if layout_json missing
            if not db_buildings:
                if not row.get("screenshot"):
                    continue
                try:
                    img_bytes    = await _download_bytes(row["screenshot"])
                    fb           = await _extract_from_bytes(img_bytes, "screenshot.jpg", district_int)
                    db_buildings = fb["buildings"]
                except Exception:
                    continue  # skip silently — can't get layout

            if isinstance(db_buildings, str):
                db_buildings = json.loads(db_buildings)

            match_result = match_layouts(input_buildings, db_buildings, fuzzy=fuzzy)
            if match_result["match_pct"] >= MATCH_THRESHOLD:
                row["match_pct"] = match_result["match_pct"]
                results.append(row)

        results.sort(key=lambda x: x["match_pct"], reverse=True)
        results = results[:MAX_RESULTS]

        if not results:
            await interaction.followup.send(
                f"No bases found in **{district_name}** with ≥{MATCH_THRESHOLD}% match."
            )
            return

        mode_label = "fuzzy" if fuzzy else "strict"
        view       = MatchNavigationView(results)
        embed      = view.build_embed()
        header     = (
            f"Found **{len(results)}** match{'es' if len(results) != 1 else ''} "
            f"≥{MATCH_THRESHOLD}% in **{district_name}** ({mode_label} mode)\n\n"
        )
        embed.description = (header + (embed.description or "")).strip()
        await interaction.followup.send(embed=embed, view=view)


    # ── /compare_bases ─────────────────────────────────────────────────────────
    @bot.tree.command(
        name="compare_bases",
        description="Compare two bases and see a visual diff of unmatched buildings",
    )
    @app_commands.describe(
        image1="Screenshot of base 1 (optional if base_id_1 given)",
        image2="Screenshot of base 2 (optional if base_id_2 given)",
        base_id_1="ID of stored base 1 (optional if image1 given)",
        base_id_2="ID of stored base 2 (optional if image2 given)",
        match_mode="strict = exact type  |  fuzzy = cannon & spear count as same (default: strict)",
    )
    @app_commands.choices(
        match_mode=[
            app_commands.Choice(name="Strict", value="strict"),
            app_commands.Choice(name="Fuzzy",  value="fuzzy"),
        ],
    )
    async def compare_bases(
        interaction: discord.Interaction,
        image1: Optional[discord.Attachment] = None,
        image2: Optional[discord.Attachment] = None,
        base_id_1: Optional[int] = None,
        base_id_2: Optional[int] = None,
        match_mode: Optional[str] = "strict",
    ):
        await interaction.response.defer()

        if not image1 and base_id_1 is None:
            await interaction.followup.send("❌ Provide `image1` or `base_id_1` for the first base.", ephemeral=True)
            return
        if not image2 and base_id_2 is None:
            await interaction.followup.send("❌ Provide `image2` or `base_id_2` for the second base.", ephemeral=True)
            return

        fuzzy = match_mode == "fuzzy"

        # --- base 1 ---
        if image1:
            try:
                buildings1, img_bytes1, _ = await _get_layout_for_attachment(image1, None)
                label1 = "Image 1"
            except ValueError as e:
                await interaction.followup.send(f"❌ Base 1: {e}")
                return
        else:
            try:
                buildings1, row1 = await _get_layout_for_base(base_id_1)
                label1 = f"Base #{base_id_1}"
            except ValueError as e:
                await interaction.followup.send(f"❌ Base 1: {e}")
                return
            if not row1.get("screenshot"):
                await interaction.followup.send(
                    f"❌ Base **#{base_id_1}** has no screenshot stored. Add one using `/edit_base`."
                )
                return
            try:
                img_bytes1 = await _download_bytes(row1["screenshot"])
            except Exception:
                await interaction.followup.send(
                    f"❌ Base **#{base_id_1}** screenshot could not be downloaded. "
                    "Please re-upload it using `/edit_base`."
                )
                return

        # --- base 2 ---
        if image2:
            try:
                buildings2, img_bytes2, _ = await _get_layout_for_attachment(image2, None)
                label2 = "Image 2"
            except ValueError as e:
                await interaction.followup.send(f"❌ Base 2: {e}")
                return
        else:
            try:
                buildings2, row2 = await _get_layout_for_base(base_id_2)
                label2 = f"Base #{base_id_2}"
            except ValueError as e:
                await interaction.followup.send(f"❌ Base 2: {e}")
                return
            if not row2.get("screenshot"):
                await interaction.followup.send(
                    f"❌ Base **#{base_id_2}** has no screenshot stored. Add one using `/edit_base`."
                )
                return
            try:
                img_bytes2 = await _download_bytes(row2["screenshot"])
            except Exception:
                await interaction.followup.send(
                    f"❌ Base **#{base_id_2}** screenshot could not be downloaded. "
                    "Please re-upload it using `/edit_base`."
                )
                return

        # --- match ---
        match_result = match_layouts(buildings1, buildings2, fuzzy=fuzzy)
        match_pct   = match_result["match_pct"]
        matched     = match_result["matched"]
        total       = match_result["total"]
        unmatched_a = match_result["unmatched_a"]
        unmatched_b = match_result["unmatched_b"]

        # --- pixel boxes for visualisation (re-run extract for pixel coords) ---
        try:
            px1 = await _get_pixel_boxes_remote(img_bytes1, "base1.jpg")
            px2 = await _get_pixel_boxes_remote(img_bytes2, "base2.jpg")
        except Exception as e:
            await interaction.followup.send(f"❌ Could not get pixel positions for visualisation: `{e}`")
            return

        unmatched_px1 = _find_unmatched_pixels(px1, unmatched_a)
        unmatched_px2 = _find_unmatched_pixels(px2, unmatched_b)

        # --- render ---
        img1 = _bytes_to_cv2(img_bytes1)
        img2 = _bytes_to_cv2(img_bytes2)
        if img1 is None or img2 is None:
            await interaction.followup.send("❌ Could not decode one or both images.")
            return

        vis1     = _draw_comparison(img1, px1, unmatched_px1, f"{label1} — {match_pct}% match")
        vis2     = _draw_comparison(img2, px2, unmatched_px2, f"{label2} — {match_pct}% match")
        combined = _stack_images(vis1, vis2)
        file     = _cv2_to_discord_file(combined, "compare.png")

        match_bar  = "🟢" if match_pct >= 90 else ("🟡" if match_pct >= 75 else "🔴")
        mode_label = "fuzzy" if fuzzy else "strict"

        embed = discord.Embed(title="🔍  Base Comparison", color=0x3498DB)
        embed.add_field(name="🎯 Match",    value=f"{match_bar} **{match_pct}%**",      inline=True)
        embed.add_field(name="✅ Matched",  value=f"**{matched}** / {total} buildings", inline=True)
        embed.add_field(name="⚙️ Mode",     value=mode_label.capitalize(),              inline=True)
        embed.add_field(name=f"❌ Unmatched — {label1}", value=str(len(unmatched_a)),   inline=True)
        embed.add_field(name=f"❌ Unmatched — {label2}", value=str(len(unmatched_b)),   inline=True)
        embed.set_image(url="attachment://compare.png")
        embed.set_footer(
            text="Matched = grayed  ·  Unmatched = full colour + red dot  ·  Clan Capital Base Bot"
        )
        await interaction.followup.send(embed=embed, file=file)


    # ── /visualize_base ────────────────────────────────────────────────────────
    @bot.tree.command(
        name="visualize_base",
        description="Highlight a specific building class on a base, gray out everything else",
    )
    @app_commands.describe(
        building_class="Building type to highlight",
        image="Upload a screenshot (optional if base_id given)",
        base_id="ID of a stored base (optional if image given)",
    )
    @app_commands.choices(
        building_class=[
            app_commands.Choice(name="Air Bomb",         value="air_bomb"),
            app_commands.Choice(name="Air Defence",      value="air_defence"),
            app_commands.Choice(name="Blast Bow",        value="blast_bow"),
            app_commands.Choice(name="Bomb Tower",       value="bomb_tower"),
            app_commands.Choice(name="Cannon",           value="cannon"),
            app_commands.Choice(name="Capital Peak",     value="capital_peak"),
            app_commands.Choice(name="Crusher",          value="crusher"),
            app_commands.Choice(name="District Hall",    value="district_hall"),
            app_commands.Choice(name="Giant Cannon",     value="gaint_cannon"),
            app_commands.Choice(name="Hive",             value="hive"),
            app_commands.Choice(name="Inferno Tower",    value="inferno_tower"),
            app_commands.Choice(name="Mortar",           value="motor"),
            app_commands.Choice(name="Multi Cannon",     value="multi_cannon"),
            app_commands.Choice(name="Post Cannon",      value="post_cannon"),
            app_commands.Choice(name="Post Dragon",      value="post_dragon"),
            app_commands.Choice(name="Post Giant",       value="post_gaint"),
            app_commands.Choice(name="Post Goblin",      value="post_goblin"),
            app_commands.Choice(name="Rapid Rocket",     value="rapid_rocket"),
            app_commands.Choice(name="Reflector",        value="reflector"),
            app_commands.Choice(name="Rocket Artillery", value="rocket_artilery"),
            app_commands.Choice(name="Spear",            value="spear"),
            app_commands.Choice(name="Tesla",            value="tesla"),
            app_commands.Choice(name="Wizard Tower",     value="wizard_tower"),
        ],
    )
    async def visualize_base(
        interaction: discord.Interaction,
        building_class: str,
        image: Optional[discord.Attachment] = None,
        base_id: Optional[int] = None,
    ):
        await interaction.response.defer()

        if not image and base_id is None:
            await interaction.followup.send("❌ Provide either an `image` or a `base_id`.", ephemeral=True)
            return

        # --- get image bytes ---
        if image:
            try:
                img_bytes = await _download_bytes(image.url)
            except Exception as e:
                await interaction.followup.send(f"❌ Could not download the image: `{e}`")
                return
        else:
            pool = await get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, screenshot FROM bases WHERE id = $1", base_id
                )
            if not row:
                await interaction.followup.send(f"❌ No base found with ID **{base_id}**.")
                return
            if not row["screenshot"]:
                await interaction.followup.send(
                    f"❌ Base **#{base_id}** has no screenshot. Add one using `/edit_base`."
                )
                return
            try:
                img_bytes = await _download_bytes(row["screenshot"])
            except Exception:
                await interaction.followup.send(
                    f"❌ Base **#{base_id}** screenshot could not be downloaded. "
                    "Please re-upload it using `/edit_base`."
                )
                return

        # --- remote extract for pixel boxes ---
        try:
            pixel_boxes = await _get_pixel_boxes_remote(img_bytes, "base.jpg")
        except Exception as e:
            await interaction.followup.send(f"❌ YOLO failed on this image: `{e}`")
            return

        # --- render ---
        img = _bytes_to_cv2(img_bytes)
        if img is None:
            await interaction.followup.send("❌ Could not decode the image.")
            return

        vis         = _draw_visualize(img, pixel_boxes, building_class)
        file        = _cv2_to_discord_file(vis, f"visualize_{building_class}.png")
        found_count = sum(1 for pb in pixel_boxes if pb["type"] == building_class)
        pretty      = PRETTY_NAMES.get(building_class, building_class)

        embed = discord.Embed(title=f"🔬  Visualising: {pretty}", color=0x2ECC71)
        embed.add_field(
            name="🏗️ Found",
            value=f"**{found_count}** × {pretty}" if found_count else "⚠️ None detected",
            inline=True,
        )
        embed.set_image(url=f"attachment://visualize_{building_class}.png")
        embed.set_footer(
            text="Highlighted = green dot  ·  Everything else grayed  ·  Clan Capital Base Bot"
        )
        await interaction.followup.send(embed=embed, file=file)
