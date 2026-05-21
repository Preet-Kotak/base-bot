import discord
import asyncpg
from discord import app_commands
from typing import Optional

from database import get_pool
from views.clan_views import ClanNavigationView


def register(bot):

    @bot.tree.command(name="add_clan", description="Add a Clash of Clans clan to the registry")
    @app_commands.describe(
        clan_name="Name of the clan (required)",
        clan_link="Clan link from Clash of Clans (required)",
        owner="Leader / owner name (optional)",
        description="Short description of the clan (optional)",
    )
    async def add_clan(
        interaction: discord.Interaction,
        clan_name: str,
        clan_link: str,
        owner: Optional[str] = None,
        description: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO clans (clan_name, clan_link, owner, description)
                       VALUES ($1, $2, $3, $4)""",
                    clan_name, clan_link, owner, description,
                )
        except asyncpg.UniqueViolationError:
            await interaction.followup.send(
                "❌ A clan with that link is already registered.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="✅  Clan added successfully",
            description=f"**{clan_name}** has been saved to the registry.",
            color=discord.Color.green(),
        )
        embed.add_field(name="🔗 Clan Link",  value=clan_link,                inline=False)
        embed.add_field(name="👑 Owner",      value=owner or "*Not specified*", inline=True)
        if description:
            embed.add_field(name="📝 Description", value=description, inline=False)
        embed.set_footer(text="Clan Capital Base Bot")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="edit_clan", description="Edit an existing clan by its ID or link")
    @app_commands.describe(
        clan_id="The ID of the clan (shown in the embed footer)",
        clan_link_lookup="The existing clan link to look up the clan",
        clan_name="Replace the clan name (optional)",
        clan_link="Replace the clan link (optional)",
        owner="Replace the owner name (optional)",
        description="Replace the description (optional)",
    )
    async def edit_clan(
        interaction: discord.Interaction,
        clan_id: Optional[int] = None,
        clan_link_lookup: Optional[str] = None,
        clan_name: Optional[str] = None,
        clan_link: Optional[str] = None,
        owner: Optional[str] = None,
        description: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if not clan_id and not clan_link_lookup:
            await interaction.followup.send(
                "Please provide either `clan_id` or `clan_link_lookup`.", ephemeral=True
            )
            return
        if clan_id and clan_link_lookup:
            await interaction.followup.send(
                "Provide only one identifier — `clan_id` **or** `clan_link_lookup`, not both.",
                ephemeral=True,
            )
            return
        if not any([clan_name, clan_link, owner, description]):
            await interaction.followup.send(
                "Provide at least one field to update: `clan_name`, `clan_link`, `owner`, or `description`.",
                ephemeral=True,
            )
            return

        pool = await get_pool()
        async with pool.acquire() as conn:
            if clan_id:
                row = await conn.fetchrow(
                    "SELECT id, clan_name, clan_link, owner, description FROM clans WHERE id = $1",
                    clan_id,
                )
                not_found_msg = f"No clan found with ID **{clan_id}**."
            else:
                row = await conn.fetchrow(
                    "SELECT id, clan_name, clan_link, owner, description FROM clans WHERE clan_link = $1",
                    clan_link_lookup,
                )
                not_found_msg = "No clan found with that link."

            if not row:
                await interaction.followup.send(not_found_msg, ephemeral=True)
                return

            new_name  = clan_name   if clan_name   is not None else row["clan_name"]
            new_link  = clan_link   if clan_link   is not None else row["clan_link"]
            new_owner = owner       if owner       is not None else row["owner"]
            new_desc  = description if description is not None else row["description"]

            try:
                await conn.execute(
                    """UPDATE clans
                       SET clan_name = $1, clan_link = $2, owner = $3, description = $4
                       WHERE id = $5""",
                    new_name, new_link, new_owner, new_desc, row["id"],
                )
            except asyncpg.UniqueViolationError:
                await interaction.followup.send(
                    "❌ Another clan already has that link.", ephemeral=True
                )
                return

        changes = []
        if clan_name:   changes.append("🏰 Name updated")
        if clan_link:   changes.append("🔗 Link updated")
        if owner:       changes.append("👑 Owner updated")
        if description: changes.append("📝 Description updated")

        embed = discord.Embed(
            title="✏️  Clan updated",
            description=f"Clan **#{row['id']}** — **{new_name}** has been edited.",
            color=0xF0A500,
        )
        embed.add_field(name="Changes",      value="\n".join(changes),       inline=False)
        embed.add_field(name="🔗 Clan Link", value=new_link,                 inline=False)
        embed.add_field(name="👑 Owner",     value=new_owner or "*Unknown*",  inline=True)
        if new_desc:
            embed.add_field(name="📝 Description", value=new_desc, inline=False)
        embed.set_footer(text=f"Clan #{row['id']}  ·  Clan Capital Base Bot")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="view_clans", description="Browse registered clans with optional filters")
    @app_commands.describe(
        clan_name="Search by clan name (optional)",
        owner="Filter by owner name (optional)",
        search_description="Keyword to search within clan descriptions (optional)",
        clan_id="Jump directly to a specific clan by its ID (optional)",
    )
    async def view_clans(
        interaction: discord.Interaction,
        clan_name: Optional[str] = None,
        owner: Optional[str] = None,
        search_description: Optional[str] = None,
        clan_id: Optional[int] = None,
    ):
        await interaction.response.defer()

        pool = await get_pool()

        if clan_id is not None:
            async with pool.acquire() as conn:
                target = await conn.fetchrow("SELECT id FROM clans WHERE id = $1", clan_id)
                if not target:
                    await interaction.followup.send(f"❌ No clan found with ID **{clan_id}**.")
                    return
                clans = await conn.fetch(
                    "SELECT id, clan_name, clan_link, owner, description, added_at FROM clans ORDER BY added_at"
                )
            start_index = next((i for i, r in enumerate(clans) if r["id"] == clan_id), 0)
            view = ClanNavigationView(clans, current_index=start_index)
            await interaction.followup.send(embed=view.build_embed(), view=view)
            return

        conditions: list[str] = []
        args: list = []

        if clan_name:
            args.append(f"%{clan_name}%")
            conditions.append(f"LOWER(clan_name) LIKE LOWER(${len(args)})")

        if owner:
            args.append(f"%{owner}%")
            conditions.append(f"LOWER(owner) LIKE LOWER(${len(args)})")

        if search_description:
            args.append(f"%{search_description}%")
            conditions.append(f"LOWER(description) LIKE LOWER(${len(args)})")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"""
            SELECT id, clan_name, clan_link, owner, description, added_at
            FROM clans {where}
            ORDER BY added_at
        """

        async with pool.acquire() as conn:
            clans = await conn.fetch(query, *args)

        if not clans:
            filters = []
            if clan_name:          filters.append(f"name **{clan_name}**")
            if owner:              filters.append(f"owner **{owner}**")
            if search_description: filters.append(f"description containing **\"{search_description}\"**")
            filter_text = " and ".join(filters) if filters else "any filter"
            await interaction.followup.send(f"No clans found for {filter_text}.")
            return

        view = ClanNavigationView(list(clans), current_index=0)
        await interaction.followup.send(embed=view.build_embed(), view=view)
