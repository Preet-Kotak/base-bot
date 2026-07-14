import re
import aiohttp
import discord
import cloudinary
import cloudinary.uploader
from typing import Optional
from config import DISTRICT_NAMES, DISTRICT_EMOJIS, RENEW_DELAY, CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET

# Configure Cloudinary
if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
    )


def get_district_from_link(link: str) -> Optional[int]:
    parts = re.split(r"%3A", link, flags=re.IGNORECASE)
    if len(parts) >= 3:
        district_str = parts[2].strip()
        if district_str and district_str[0].isdigit():
            n = int(district_str[0])
            if 0 <= n <= 8:
                return n
    return None


async def upload_to_cloudinary(image_url: str, folder: str = "clash_bases") -> Optional[str]:
    """
    Upload an image to Cloudinary from a URL.
    Returns the Cloudinary URL on success, None on failure.
    """
    if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY or not CLOUDINARY_API_SECRET:
        return None
    
    try:
        result = cloudinary.uploader.upload(
            image_url,
            folder=folder,
            resource_type="image",
        )
        return result.get("secure_url")
    except Exception as e:
        print(f"Cloudinary upload failed: {e}")
        return None


def build_renew_embed(
    total: int,
    done: int,
    ok: int,
    failed: int,
    current_link: Optional[str],
    finished: bool,
) -> discord.Embed:
    if finished:
        color = discord.Color.green() if failed == 0 else discord.Color.orange()
        title = "✅  Renew complete" if failed == 0 else "⚠️  Renew complete (with errors)"
    else:
        color = discord.Color.blurple()
        title = "🔄  Renewing bases…"

    bar_filled = int((done / total) * 20) if total else 20
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    pct = int((done / total) * 100) if total else 100

    embed = discord.Embed(title=title, color=color)
    embed.add_field(
        name="Progress",
        value=f"`{bar}` {pct}%  ({done}/{total})",
        inline=False,
    )
    embed.add_field(name="✅ OK",     value=str(ok),     inline=True)
    embed.add_field(name="❌ Failed", value=str(failed), inline=True)

    if not finished and current_link:
        display = current_link if len(current_link) <= 60 else current_link[:57] + "…"
        embed.add_field(name="🔗 Current", value=display, inline=False)

    if finished:
        embed.set_footer(text=f"All {total} links processed  ·  Clan Capital Base Bot")
    else:
        remaining = total - done
        secs = remaining * RENEW_DELAY
        mins, s = divmod(int(secs), 60)
        eta = f"{mins}m {s}s" if mins else f"{s}s"
        embed.set_footer(text=f"~{eta} remaining  ·  Clan Capital Base Bot")

    return embed
