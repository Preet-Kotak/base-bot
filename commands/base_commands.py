import re
import discord
import asyncio
from discord import app_commands
from typing import Optional

from config import DISTRICT_NAMES, DISTRICT_EMOJIS, DISTRICT_COLORS
from database import get_pool
from utils import get_district_from_link, upload_to_cloudinary
from views.base_views import BaseNavigationView


def register(bot):

    @bot.tree.command(name="add_base", description="Add a Clash of Clans capital base layout")
    @app_commands.describe(
        link="The Clash of Clans layout link (required)",
        screenshot="Upload a screenshot image (optional)",
        builder_name="Name of the builder (optional)",
        description="Short description of the base strategy (optional)",
    )
    async def add_base(
        interaction: discord.Interaction,
        link: str,
        screenshot: Optional[discord.Attachment] = None,
        builder_name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        district_number = get_district_from_link(link)
        if district_number is None:
            await interaction.followup.send(
                "❌ Could not determine the district from that link.\n"
                "Example valid link:\n"
                "`https://link.clashofclans.com/en?action=OpenLayout&id=TH10%3ACC%3A0%3A...`",
                ephemeral=True,
            )
            return

        district_name  = DISTRICT_NAMES.get(district_number, f"District {district_number + 1}")
        emoji          = DISTRICT_EMOJIS.get(district_number, "🏰")
        
        # Upload screenshot to Cloudinary if provided
        screenshot_url = None
        if screenshot:
            cloudinary_url = await upload_to_cloudinary(screenshot.url)
            screenshot_url = cloudinary_url if cloudinary_url else screenshot.url

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO bases (district_number, link, screenshot, builder_name, description)
                   VALUES ($1, $2, $3, $4, $5)""",
                district_number, link, screenshot_url, builder_name, description,
            )

        embed = discord.Embed(
            title="✅  Base added successfully",
            description=f"A new layout has been saved to **{district_name}**.",
            color=discord.Color.green(),
        )
        embed.add_field(name="🔗 Layout Link", value=link, inline=False)
        if description:
            embed.add_field(name="📝 Description", value=description, inline=False)
        embed.add_field(name="🏗️ Builder", value=builder_name or "*Not specified*", inline=True)
        embed.add_field(name="🗺️ District", value=f"{emoji} {district_name} (District {district_number + 1})", inline=True)
        if screenshot_url:
            embed.set_image(url=screenshot_url)
        embed.set_footer(text="Clan Capital Base Bot")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="view_bases", description="View capital base layouts with filters")
    @app_commands.describe(
        district="District name or number (optional)",
        builder_name="Filter by builder name (optional)",
        base_id="Jump directly to a specific base by its ID (optional)",
        search_description="Keyword to search within base descriptions (optional)",
        reverse="Start browsing from the last (newest) base instead of the first",
    )
    @app_commands.choices(district=[
        app_commands.Choice(name="Capital Peak (District 1)",       value="0"),
        app_commands.Choice(name="Barbarian Camp (District 2)",     value="1"),
        app_commands.Choice(name="Wizard Valley (District 3)",      value="2"),
        app_commands.Choice(name="Balloon Lagoon (District 4)",     value="3"),
        app_commands.Choice(name="Builder's Workshop (District 5)", value="4"),
        app_commands.Choice(name="Dragon Cliffs (District 6)",      value="5"),
        app_commands.Choice(name="Golem Quarry (District 7)",       value="6"),
        app_commands.Choice(name="Skeleton Park (District 8)",      value="7"),
        app_commands.Choice(name="Goblin Mines (District 9)",       value="8"),
    ])
    async def view_bases(
        interaction: discord.Interaction,
        district: Optional[str] = None,
        builder_name: Optional[str] = None,
        base_id: Optional[int] = None,
        search_description: Optional[str] = None,
        reverse: Optional[bool] = False,
    ):
        await interaction.response.defer()

        if base_id is not None:
            pool = await get_pool()
            async with pool.acquire() as conn:
                target = await conn.fetchrow("SELECT id FROM bases WHERE id = $1", base_id)
                if not target:
                    await interaction.followup.send(f"❌ No base found with ID **{base_id}**.")
                    return
                bases = await conn.fetch(
                    """SELECT id, district_number, link, screenshot, builder_name, added_at, description
                       FROM bases
                       ORDER BY district_number, added_at"""
                )
            start_index = next((i for i, r in enumerate(bases) if r["id"] == base_id), 0)
            view = BaseNavigationView(bases, current_index=start_index)
            await interaction.followup.send(embed=view.build_embed(), view=view)
            return

        conditions: list[str] = []
        args: list = []

        if district is not None:
            args.append(int(district))
            conditions.append(f"district_number = ${len(args)}")

        if builder_name:
            args.append(f"%{builder_name}%")
            conditions.append(f"LOWER(builder_name) LIKE LOWER(${len(args)})")

        if search_description:
            args.append(f"%{search_description}%")
            conditions.append(f"LOWER(description) LIKE LOWER(${len(args)})")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"""
            SELECT id, district_number, link, screenshot, builder_name, added_at, description
            FROM bases {where}
            ORDER BY district_number, added_at
        """

        pool = await get_pool()
        async with pool.acquire() as conn:
            bases = await conn.fetch(query, *args)

        if not bases:
            filters = []
            if district is not None:
                filters.append(f"district **{DISTRICT_NAMES.get(int(district), district)}**")
            if builder_name:
                filters.append(f"builder **{builder_name}**")
            if search_description:
                filters.append(f"description containing **\"{search_description}\"**")
            filter_text = " and ".join(filters) if filters else "any district or builder"
            await interaction.followup.send(f"No bases found for {filter_text}.")
            return

        start_index = len(bases) - 1 if reverse else 0
        view = BaseNavigationView(bases, current_index=start_index)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @bot.tree.command(name="remove_base", description="Remove a capital base layout by its link")
    @app_commands.describe(link="The Clash of Clans layout link to remove")
    async def remove_base(interaction: discord.Interaction, link: str):
        await interaction.response.defer(ephemeral=True)

        district_number = get_district_from_link(link)
        if district_number is None:
            await interaction.followup.send(
                "❌ Could not determine the district from that link.", ephemeral=True
            )
            return

        district_name = DISTRICT_NAMES.get(district_number, f"District {district_number + 1}")
        emoji         = DISTRICT_EMOJIS.get(district_number, "🏰")

        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, builder_name FROM bases WHERE link = $1 AND district_number = $2",
                link, district_number,
            )
            if not row:
                await interaction.followup.send(
                    f"No base with that link was found in **{district_name}**.", ephemeral=True
                )
                return
            await conn.execute("DELETE FROM bases WHERE id = $1", row["id"])

        embed = discord.Embed(
            title="🗑️  Base removed",
            description=f"The layout has been deleted from **{district_name}**.",
            color=discord.Color.red(),
        )
        embed.add_field(name="🔗 Removed Link", value=link, inline=False)
        embed.add_field(name="🏗️ Builder", value=row["builder_name"] or "*Unknown*", inline=True)
        embed.add_field(name="🗺️ District", value=f"{emoji} {district_name}", inline=True)
        embed.set_footer(text="Clan Capital Base Bot")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="edit_base", description="Edit an existing base by its ID or link")
    @app_commands.describe(
        base_id="The ID of the base (shown in the embed footer)",
        base_link="The existing layout link of the base",
        link="Replace the layout link (optional)",
        screenshot="Replace the screenshot (optional)",
        builder_name="Replace the builder name (optional)",
        description="Replace the description (optional)",
    )
    async def edit_base(
        interaction: discord.Interaction,
        base_id: Optional[int] = None,
        base_link: Optional[str] = None,
        link: Optional[str] = None,
        screenshot: Optional[discord.Attachment] = None,
        builder_name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if not base_id and not base_link:
            await interaction.followup.send(
                "Please provide either `base_id` or `base_link`.", ephemeral=True
            )
            return
        if base_id and base_link:
            await interaction.followup.send(
                "Provide only one identifier — `base_id` **or** `base_link`, not both.", ephemeral=True
            )
            return
        if not any([link, screenshot, builder_name, description]):
            await interaction.followup.send(
                "Provide at least one field to update: `link`, `screenshot`, `builder_name`, or `description`.",
                ephemeral=True,
            )
            return

        pool = await get_pool()
        async with pool.acquire() as conn:
            if base_id:
                row = await conn.fetchrow(
                    "SELECT id, district_number, link, screenshot, builder_name, description FROM bases WHERE id = $1",
                    base_id,
                )
                not_found_msg = f"No base found with ID **{base_id}**."
            else:
                row = await conn.fetchrow(
                    "SELECT id, district_number, link, screenshot, builder_name, description FROM bases WHERE link = $1",
                    base_link,
                )
                not_found_msg = "No base found with that link."

            if not row:
                await interaction.followup.send(not_found_msg, ephemeral=True)
                return

            existing_id      = row["id"]
            district_number  = row["district_number"]
            existing_link    = row["link"]
            existing_ss      = row["screenshot"]
            existing_builder = row["builder_name"]
            existing_desc    = row["description"]

            if link:
                new_district = get_district_from_link(link)
                if new_district is None:
                    await interaction.followup.send(
                        "The new link doesn't appear to be a valid CoC layout link.", ephemeral=True
                    )
                    return
                if new_district != district_number:
                    await interaction.followup.send(
                        f"⚠️ The new link points to **{DISTRICT_NAMES.get(new_district)}** but this base "
                        f"is saved under **{DISTRICT_NAMES.get(district_number)}**.\n"
                        "Remove and re-add the base to change districts.",
                        ephemeral=True,
                    )
                    return

            new_link       = link            if link            else existing_link
            new_screenshot = existing_ss
            if screenshot:
                # Upload new screenshot to Cloudinary
                cloudinary_url = await upload_to_cloudinary(screenshot.url)
                new_screenshot = cloudinary_url if cloudinary_url else screenshot.url
            new_builder    = builder_name    if builder_name is not None else existing_builder
            new_desc       = description     if description  is not None else existing_desc

            await conn.execute(
                """UPDATE bases
                   SET link = $1, screenshot = $2, builder_name = $3, description = $4
                   WHERE id = $5""",
                new_link, new_screenshot, new_builder, new_desc, existing_id,
            )

        district_name = DISTRICT_NAMES.get(district_number, f"District {district_number + 1}")
        emoji         = DISTRICT_EMOJIS.get(district_number, "🏰")

        changes = []
        if link:         changes.append("🔗 Link updated")
        if screenshot:   changes.append("🖼️ Screenshot updated")
        if builder_name: changes.append("🏗️ Builder name updated")
        if description:  changes.append("📝 Description updated")

        embed = discord.Embed(
            title="✏️  Base updated",
            description=f"Base **#{existing_id}** in **{district_name}** has been edited.",
            color=0xF0A500,
        )
        embed.add_field(name="Changes", value="\n".join(changes), inline=False)
        if new_desc:
            embed.add_field(name="📝 Description", value=new_desc, inline=False)
        embed.add_field(name="🏗️ Builder", value=new_builder or "*Unknown*", inline=True)
        embed.add_field(name="🗺️ District", value=f"{emoji} {district_name}", inline=True)
        embed.add_field(name="🔗 Link", value=new_link, inline=False)
        if new_screenshot:
            embed.set_image(url=new_screenshot)
        embed.set_footer(text=f"Base #{existing_id}  ·  Clan Capital Base Bot")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="import_channel", description="Import bases from a channel where each message has a screenshot, link, and optional description")
    @app_commands.describe(
        channel_id="The ID of the channel to import bases from",
        builder_name="Default builder name to assign (optional)",
        limit="Max number of messages to scan (default 100, max 500)",
    )
    async def import_channel(
        interaction: discord.Interaction,
        channel_id: str,
        builder_name: Optional[str] = None,
        limit: Optional[int] = 100,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
        except (ValueError, discord.NotFound, discord.Forbidden):
            await interaction.followup.send("❌ Could not find or access that channel. Check the ID and bot permissions.", ephemeral=True)
            return

        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("❌ That channel is not a text channel.", ephemeral=True)
            return

        limit = max(1, min(limit or 100, 500))

        coc_link_pattern = re.compile(
            r"https://link\.clashofclans\.com/\S+action=OpenLayout\S*",
            re.IGNORECASE,
        )

        imported   = 0
        skipped    = 0
        no_link    = 0
        no_img     = 0
        duplicates = 0

        pool = await get_pool()

        async for message in channel.history(limit=limit, oldest_first=True):
            if message.author.bot:
                skipped += 1
                continue

            content = message.content or ""

            link_match = coc_link_pattern.search(content)
            if not link_match:
                for embed in message.embeds:
                    url = embed.url or ""
                    link_match = coc_link_pattern.search(url)
                    if link_match:
                        break

            if not link_match:
                no_link += 1
                continue

            link = link_match.group(0).strip().strip("<>")

            screenshot_url = None
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    screenshot_url = attachment.url
                    break

            if not screenshot_url:
                for embed in message.embeds:
                    if embed.image and embed.image.url:
                        screenshot_url = embed.image.url
                        break
                    if embed.thumbnail and embed.thumbnail.url:
                        screenshot_url = embed.thumbnail.url
                        break

            if not screenshot_url:
                no_img += 1

            district_number = get_district_from_link(link)
            if district_number is None:
                skipped += 1
                continue

            description_text = coc_link_pattern.sub("", content).strip() or None

            async with pool.acquire() as conn:
                existing = await conn.fetchval("SELECT id FROM bases WHERE link = $1", link)
                if existing:
                    duplicates += 1
                    continue

                await conn.execute(
                    """INSERT INTO bases (district_number, link, screenshot, builder_name, description)
                       VALUES ($1, $2, $3, $4, $5)""",
                    district_number, link, screenshot_url, builder_name or None, description_text,
                )
                imported += 1

        district_summary: dict[int, int] = {}
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT district_number, COUNT(*) as cnt FROM bases GROUP BY district_number")
            for row in rows:
                district_summary[row["district_number"]] = row["cnt"]

        embed = discord.Embed(
            title="📥  Channel Import Complete",
            description=f"Finished scanning **#{channel.name}**.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="✅ Imported",    value=str(imported),   inline=True)
        embed.add_field(name="⏭️ Duplicates", value=str(duplicates), inline=True)
        embed.add_field(name="❌ No link",    value=str(no_link),    inline=True)
        embed.add_field(name="🖼️ No image",  value=str(no_img),     inline=True)
        embed.add_field(name="⏩ Skipped",    value=str(skipped),    inline=True)

        if district_summary:
            lines = [
                f"{DISTRICT_EMOJIS.get(d, '🏰')} {DISTRICT_NAMES.get(d, f'District {d+1}')}: **{cnt}** total"
                for d, cnt in sorted(district_summary.items())
            ]
            embed.add_field(name="📊 District Totals (all time)", value="\n".join(lines), inline=False)

        embed.set_footer(text=f"Scanned up to {limit} messages  ·  Clan Capital Base Bot")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="migrate_images", description="Migrate Discord CDN images to Cloudinary by posting them in a channel")
    @app_commands.describe(
        channel_id="The ID of the channel where images will be posted to fetch new URLs",
    )
    async def migrate_images(
        interaction: discord.Interaction,
        channel_id: str,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
        except (ValueError, discord.NotFound, discord.Forbidden):
            await interaction.followup.send("❌ Could not find or access that channel. Check the ID and bot permissions.", ephemeral=True)
            return

        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("❌ That channel is not a text channel.", ephemeral=True)
            return

        # Fetch all bases with screenshots that contain Discord URLs
        pool = await get_pool()
        async with pool.acquire() as conn:
            bases = await conn.fetch(
                """SELECT id, screenshot 
                   FROM bases 
                   WHERE screenshot IS NOT NULL 
                   AND (screenshot LIKE '%cdn.discordapp.com%' OR screenshot LIKE '%media.discordapp.net%')
                   ORDER BY id"""
            )

        if not bases:
            await interaction.followup.send("✅ No Discord CDN images found to migrate.", ephemeral=True)
            return

        total = len(bases)
        
        success_count = 0
        failed_bases = []

        # Send initial progress message
        try:
            progress_msg = await channel.send(
                f"🔄 **Image Migration Started**\n"
                f"Migrating {total} Discord CDN images to Cloudinary...\n"
                f"Progress: 0/{total}"
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Could not send message to <#{channel.id}>. Check bot permissions.\nError: {e}",
                ephemeral=True
            )
            return
        
        await interaction.followup.send(
            f"🔄 Starting migration of **{total}** Discord CDN images to Cloudinary...\n"
            f"Progress updates will be sent in <#{channel.id}>.",
            ephemeral=True
        )

        for idx, base in enumerate(bases, 1):
            base_id = base["id"]
            old_url = base["screenshot"]
            msg = None

            try:
                # Post the image URL to the channel
                msg = await channel.send(old_url)
                
                # Wait a bit for Discord to process the message
                await asyncio.sleep(2)
                
                # Fetch the message again to get the attachment or embed
                msg = await channel.fetch_message(msg.id)
                
                # Get the new URL from attachment or embed
                new_discord_url = None
                if msg.attachments:
                    new_discord_url = msg.attachments[0].url
                elif msg.embeds and msg.embeds[0].thumbnail:
                    new_discord_url = msg.embeds[0].thumbnail.url
                elif msg.embeds and msg.embeds[0].image:
                    new_discord_url = msg.embeds[0].image.url
                
                if not new_discord_url:
                    failed_bases.append(base_id)
                    if msg:
                        await msg.delete()
                    continue
                
                # Upload to Cloudinary
                cloudinary_url = await upload_to_cloudinary(new_discord_url)
                
                if not cloudinary_url:
                    failed_bases.append(base_id)
                    if msg:
                        await msg.delete()
                    continue
                
                # Update database with Cloudinary URL
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE bases SET screenshot = $1 WHERE id = $2",
                        cloudinary_url, base_id
                    )
                
                success_count += 1
                
                # Delete the message to keep the channel clean
                await asyncio.sleep(1)
                await msg.delete()
                
            except Exception as e:
                failed_bases.append(base_id)
                if msg:
                    try:
                        await msg.delete()
                    except:
                        pass
                print(f"Error processing base {base_id}: {e}")
            
            # Update progress every 10 bases or at the end
            if idx % 10 == 0 or idx == total:
                try:
                    await progress_msg.edit(
                        content=f"🔄 **Image Migration In Progress**\n"
                                f"Progress: {idx}/{total}\n"
                                f"✅ Success: {success_count}\n"
                                f"❌ Failed: {len(failed_bases)}"
                    )
                except:
                    pass
            
            # Small delay between requests
            await asyncio.sleep(1)

        # Send final summary
        embed = discord.Embed(
            title="✅  Image Migration Complete" if not failed_bases else "⚠️  Image Migration Complete (with errors)",
            color=discord.Color.green() if not failed_bases else discord.Color.orange(),
        )
        embed.add_field(name="📊 Total", value=str(total), inline=True)
        embed.add_field(name="✅ Success", value=str(success_count), inline=True)
        embed.add_field(name="❌ Failed", value=str(len(failed_bases)), inline=True)
        
        if failed_bases:
            # Split failed base IDs into chunks if too many
            failed_str = ", ".join(f"#{bid}" for bid in failed_bases)
            if len(failed_str) > 1024:
                failed_str = ", ".join(f"#{bid}" for bid in failed_bases[:50]) + f"\n... and {len(failed_bases) - 50} more"
            embed.add_field(name="❌ Failed Base IDs", value=failed_str, inline=False)
        
        embed.set_footer(text="Clan Capital Base Bot  ·  Images now hosted on Cloudinary")
        
        await progress_msg.edit(content=None, embed=embed)
        await channel.send(f"<@{interaction.user.id}> Migration complete!", embed=embed)
