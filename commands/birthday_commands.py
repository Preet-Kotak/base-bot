import asyncio
import re
import discord
from datetime import datetime, timezone, timedelta
from discord import app_commands
from typing import Optional
from database import get_pool
from config import BIRTHDAY_CHANNEL_ID

DEFAULT_TZ = "+05:30"


def _parse_offset(s: str) -> Optional[timedelta]:
    m = re.fullmatch(r'([+-])(\d{1,2}):(\d{2})', s.strip())
    if not m:
        return None
    sign = 1 if m.group(1) == '+' else -1
    h, mins = int(m.group(2)), int(m.group(3))
    if h > 14 or mins >= 60:
        return None
    return timedelta(hours=sign * h, minutes=sign * mins)


async def birthday_loop(bot: discord.Client):
    """Fires every minute and checks if it's midnight in any user's timezone."""
    await bot.wait_until_ready()
    already_pinged = set()  # track (user_id, date) to avoid double pings

    while not bot.is_closed():
        await asyncio.sleep(60)  # check every minute

        if not BIRTHDAY_CHANNEL_ID:
            continue
        channel = bot.get_channel(BIRTHDAY_CHANNEL_ID)
        if not channel:
            continue

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT discord_user_id, birth_month, birth_day, timezone_offset FROM birthdays"
            )

        now_utc = datetime.now(timezone.utc)

        for row in rows:
            delta = _parse_offset(row["timezone_offset"] or DEFAULT_TZ)
            if delta is None:
                delta = _parse_offset(DEFAULT_TZ)
            tz = timezone(delta)
            local_now = now_utc.astimezone(tz)

            # Only ping at the start of midnight hour (00:00)
            if local_now.hour != 0 or local_now.minute != 0:
                continue
            if local_now.month != row["birth_month"] or local_now.day != row["birth_day"]:
                continue

            key = (row["discord_user_id"], local_now.date().isoformat())
            if key in already_pinged:
                continue

            already_pinged.add(key)
            uid = int(row["discord_user_id"])
            await channel.send(
                f"🎂 HbD <@{uid}>! Wishing you a wonderful day! 🎉"
            )

        # Clean up old ping keys (keep only today's)
        today_str = now_utc.strftime("%Y-%m-%d")
        already_pinged = {k for k in already_pinged if k[1] >= today_str}


def register(bot):

    @bot.tree.command(name="add_birthday", description="Add someone's birthday")
    @app_commands.describe(
        user="The Discord user (mention them)",
        month="Birth month (1–12)",
        day="Birth day (1–31)",
        timezone_offset="Their timezone e.g. +05:30 (default: +05:30)",
    )
    async def add_birthday(
        interaction: discord.Interaction,
        user: discord.Member,
        month: int,
        day: int,
        timezone_offset: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if not (1 <= month <= 12) or not (1 <= day <= 31):
            await interaction.followup.send("❌ Invalid month or day.", ephemeral=True)
            return

        tz_str = timezone_offset or DEFAULT_TZ
        if _parse_offset(tz_str) is None:
            await interaction.followup.send(
                "❌ Invalid timezone format. Use `+05:30` or `-08:00`.", ephemeral=True
            )
            return

        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM birthdays WHERE discord_user_id = $1", str(user.id)
            )
            if existing:
                await conn.execute(
                    """UPDATE birthdays
                       SET birth_month = $1, birth_day = $2, timezone_offset = $3
                       WHERE discord_user_id = $4""",
                    month, day, tz_str, str(user.id),
                )
                await interaction.followup.send(
                    f"✅ Updated birthday for {user.mention} — **{day:02d}/{month:02d}** (UTC{tz_str})",
                    ephemeral=True,
                )
            else:
                await conn.execute(
                    """INSERT INTO birthdays (discord_user_id, birth_month, birth_day, timezone_offset)
                       VALUES ($1, $2, $3, $4)""",
                    str(user.id), month, day, tz_str,
                )
                await interaction.followup.send(
                    f"🎂 Birthday added for {user.mention} — **{day:02d}/{month:02d}** (UTC{tz_str})",
                    ephemeral=True,
                )

    @bot.tree.command(name="remove_birthday", description="Remove someone's birthday")
    @app_commands.describe(user="The Discord user (mention them)")
    async def remove_birthday(interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM birthdays WHERE discord_user_id = $1", str(user.id)
            )
            if not row:
                await interaction.followup.send(
                    f"❌ No birthday found for {user.mention}.", ephemeral=True
                )
                return
            await conn.execute("DELETE FROM birthdays WHERE id = $1", row["id"])
        await interaction.followup.send(
            f"🗑️ Birthday removed for {user.mention}.", ephemeral=True
        )
