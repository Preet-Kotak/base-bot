import discord
from datetime import datetime, timezone, timedelta
from discord import app_commands
from typing import Optional
from database import get_pool


def _parse_offset(offset_str: str) -> Optional[timedelta]:
    """Parse '+05:30' or '-08:00' into a timedelta."""
    import re
    m = re.fullmatch(r'([+-])(\d{1,2}):(\d{2})', offset_str.strip())
    if not m:
        return None
    sign = 1 if m.group(1) == '+' else -1
    hours, minutes = int(m.group(2)), int(m.group(3))
    if hours > 14 or minutes >= 60:
        return None
    return timedelta(hours=sign * hours, minutes=sign * minutes)


def register(bot):

    @bot.tree.command(name="add_timezone", description="Add a timezone to the clock list")
    @app_commands.describe(
        offset="UTC offset e.g. +05:30 or -08:00",
        label="Friendly name e.g. India, New York (optional)",
    )
    async def add_timezone(interaction: discord.Interaction, offset: str, label: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if _parse_offset(offset) is None:
            await interaction.followup.send("❌ Invalid offset. Use format like `+05:30` or `-08:00`.", ephemeral=True)
            return
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchval("SELECT id FROM timezones WHERE offset_str = $1", offset)
            if existing:
                await interaction.followup.send(f"⚠️ Timezone `{offset}` is already added.", ephemeral=True)
                return
            await conn.execute(
                "INSERT INTO timezones (offset_str, label) VALUES ($1, $2)",
                offset, label
            )
        name = f" ({label})" if label else ""
        await interaction.followup.send(f"✅ Timezone `{offset}`{name} added.", ephemeral=True)

    @bot.tree.command(name="remove_timezone", description="Remove a timezone from the clock list")
    @app_commands.describe(offset="UTC offset to remove e.g. +05:30")
    async def remove_timezone(interaction: discord.Interaction, offset: str):
        await interaction.response.defer(ephemeral=True)
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id, label FROM timezones WHERE offset_str = $1", offset)
            if not row:
                await interaction.followup.send(f"❌ Timezone `{offset}` not found.", ephemeral=True)
                return
            await conn.execute("DELETE FROM timezones WHERE id = $1", row["id"])
        await interaction.followup.send(f"🗑️ Timezone `{offset}` removed.", ephemeral=True)

    @bot.tree.command(name="show_time", description="Show current time in all saved timezones")
    async def show_time(interaction: discord.Interaction):
        await interaction.response.defer()
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT offset_str, label FROM timezones ORDER BY added_at")
        if not rows:
            await interaction.followup.send("No timezones added yet. Use `/add_timezone` first.")
            return
        now_utc = datetime.now(timezone.utc)
        embed = discord.Embed(title="🕐 Current Times", color=0x3498DB)
        for row in rows:
            delta = _parse_offset(row["offset_str"])
            local_time = now_utc + delta
            label = row["label"] or row["offset_str"]
            embed.add_field(
                name=f"🌐 {label} (UTC{row['offset_str']})",
                value=local_time.strftime("**%I:%M %p** — %A, %d %b %Y"),
                inline=False,
            )
        embed.set_footer(text="Times update each time you run /show_time")
        await interaction.followup.send(embed=embed)