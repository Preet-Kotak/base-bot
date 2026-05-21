import asyncio
import discord
from datetime import datetime, timezone
from discord import app_commands
from typing import Optional
from database import get_pool
from config import BIRTHDAY_CHANNEL_ID


async def birthday_loop(bot: discord.Client):
    """Runs daily — pings anyone whose birthday is today."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now(timezone.utc)
        # Wait until next midnight UTC
        next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        next_midnight += timedelta(days=1)
        wait_secs = (next_midnight - now).total_seconds()
        await asyncio.sleep(wait_secs)

        if not BIRTHDAY_CHANNEL_ID:
            continue

        channel = bot.get_channel(BIRTHDAY_CHANNEL_ID)
        if not channel:
            continue

        today = datetime.now(timezone.utc)
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT discord_user_id FROM birthdays WHERE birth_month = $1 AND birth_day = $2",
                today.month, today.day,
            )

        for row in rows:
            uid = int(row["discord_user_id"])
            await channel.send(
                f"🎂 Happy Birthday <@{uid}>! Wishing you a wonderful day! 🎉"
            )


def register(bot):

    @bot.tree.command(name="add_birthday", description="Add someone's birthday")
    @app_commands.describe(
        user="The Discord user (mention them)",
        month="Birth month (1–12)",
        day="Birth day (1–31)",
    )
    async def add_birthday(
        interaction: discord.Interaction,
        user: discord.Member,
        month: int,
        day: int,
    ):
        await interaction.response.defer(ephemeral=True)
        if not (1 <= month <= 12) or not (1 <= day <= 31):
            await interaction.followup.send("❌ Invalid month or day.", ephemeral=True)
            return
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM birthdays WHERE discord_user_id = $1", str(user.id)
            )
            if existing:
                await conn.execute(
                    "UPDATE birthdays SET birth_month = $1, birth_day = $2 WHERE discord_user_id = $3",
                    month, day, str(user.id),
                )
                await interaction.followup.send(
                    f"✅ Updated birthday for {user.mention} to **{day:02d}/{month:02d}**.", ephemeral=True
                )
            else:
                await conn.execute(
                    "INSERT INTO birthdays (discord_user_id, birth_month, birth_day) VALUES ($1, $2, $3)",
                    str(user.id), month, day,
                )
                await interaction.followup.send(
                    f"🎂 Birthday added for {user.mention} — **{day:02d}/{month:02d}**.", ephemeral=True
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
                await interaction.followup.send(f"❌ No birthday found for {user.mention}.", ephemeral=True)
                return
            await conn.execute("DELETE FROM birthdays WHERE id = $1", row["id"])
        await interaction.followup.send(f"🗑️ Birthday removed for {user.mention}.", ephemeral=True)