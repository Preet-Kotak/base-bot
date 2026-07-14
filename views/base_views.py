import discord
from database import get_pool
from utils import get_district_from_link, upload_to_cloudinary
from config import DISTRICT_NAMES, DISTRICT_EMOJIS, DISTRICT_COLORS


class EditBaseModal(discord.ui.Modal, title="✏️ Edit Base"):
    """
    A Discord Modal with four text inputs pre-filled from the current base.
    On submit it performs the same DB update as /edit_base and refreshes
    the navigation embed in place.
    """

    link_input = discord.ui.TextInput(
        label="Layout Link",
        style=discord.TextStyle.short,
        placeholder="https://link.clashofclans.com/...",
        required=True,
        max_length=500,
    )
    builder_input = discord.ui.TextInput(
        label="Builder Name",
        style=discord.TextStyle.short,
        placeholder="Leave blank to clear",
        required=False,
        max_length=100,
    )
    description_input = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        placeholder="Short strategy description (optional)",
        required=False,
        max_length=500,
    )
    screenshot_input = discord.ui.TextInput(
        label="Screenshot URL",
        style=discord.TextStyle.short,
        placeholder="https://cdn.discordapp.com/... (leave blank to keep)",
        required=False,
        max_length=500,
    )

    def __init__(self, nav_view: "BaseNavigationView"):
        super().__init__()
        self.nav_view = nav_view

        row = nav_view.bases[nav_view.current_index]
        self.link_input.default        = row["link"] or ""
        self.builder_input.default     = row["builder_name"] or ""
        self.description_input.default = row["description"] or ""
        self.screenshot_input.default  = row["screenshot"] or ""

    async def on_submit(self, interaction: discord.Interaction):
        nav   = self.nav_view
        row   = nav.bases[nav.current_index]
        base_id         = row["id"]
        district_number = row["district_number"]

        new_link       = self.link_input.value.strip()
        new_builder    = self.builder_input.value.strip() or None
        new_desc       = self.description_input.value.strip() or None
        new_screenshot_input = self.screenshot_input.value.strip()
        
        # If user provided a new screenshot URL, upload to Cloudinary
        if new_screenshot_input and new_screenshot_input != row["screenshot"]:
            cloudinary_url = await upload_to_cloudinary(new_screenshot_input)
            new_screenshot = cloudinary_url if cloudinary_url else new_screenshot_input
        else:
            new_screenshot = row["screenshot"]

        new_district = get_district_from_link(new_link)
        if new_district is None:
            await interaction.response.send_message(
                "❌ The link doesn't look like a valid CoC layout link — no changes saved.",
                ephemeral=True,
            )
            return
        if new_district != district_number:
            await interaction.response.send_message(
                f"⚠️ The new link points to **{DISTRICT_NAMES.get(new_district)}** but this base "
                f"is saved under **{DISTRICT_NAMES.get(district_number)}**.\n"
                "Remove and re-add the base to change districts.",
                ephemeral=True,
            )
            return

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE bases
                   SET link = $1, screenshot = $2, builder_name = $3, description = $4
                   WHERE id = $5""",
                new_link, new_screenshot, new_builder, new_desc, base_id,
            )

        updated = dict(row)
        updated["link"]         = new_link
        updated["screenshot"]   = new_screenshot
        updated["builder_name"] = new_builder
        updated["description"]  = new_desc
        nav.bases[nav.current_index] = updated

        await interaction.response.edit_message(embed=nav.build_embed(), view=nav)


class BaseNavigationView(discord.ui.View):
    def __init__(self, bases: list, current_index: int = 0):
        super().__init__(timeout=300)
        self.bases = bases
        self.current_index = current_index
        self._refresh_buttons()

    def _clamp(self, value: int) -> int:
        return max(0, min(value, len(self.bases) - 1))

    def _refresh_buttons(self):
        idx   = self.current_index
        total = len(self.bases)

        self.prev10_button.disabled = idx < 10
        self.prev_button.disabled   = idx == 0
        self.next_button.disabled   = idx >= total - 1
        self.next10_button.disabled = idx >= total - 10

        self.counter_button.label = f"{idx + 1} / {total}"

    def build_embed(self) -> discord.Embed:
        row             = self.bases[self.current_index]
        base_id         = row["id"]
        district_number = row["district_number"]
        link            = row["link"]
        screenshot      = row["screenshot"]
        builder_name    = row["builder_name"]
        description     = row["description"]

        district_name = DISTRICT_NAMES.get(district_number, f"District {district_number + 1}")
        emoji         = DISTRICT_EMOJIS.get(district_number, "🏰")
        color         = DISTRICT_COLORS.get(district_number, 0x5865F2)

        embed = discord.Embed(title=f"{emoji}  {district_name}", color=color)
        embed.description = description or None
        if screenshot:
            embed.set_image(url=screenshot)
        embed.add_field(name="🔗 Layout Link", value=link, inline=False)
        embed.add_field(name="🏗️ Builder", value=builder_name or "*Unknown*", inline=True)
        embed.set_footer(
            text=(
                f"Base #{base_id}  ·  {self.current_index + 1} of {len(self.bases)} total"
                f"  ·  Use ◀◀ / ▶▶ to jump 10  ·  Clan Capital Base Bot"
            )
        )
        return embed

    @discord.ui.button(label="◀◀ -10", style=discord.ButtonStyle.primary, row=0)
    async def prev10_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index = self._clamp(self.current_index - 10)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

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

    @discord.ui.button(label="+10 ▶▶", style=discord.ButtonStyle.primary, row=0)
    async def next10_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index = self._clamp(self.current_index + 10)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="✏️ Edit", style=discord.ButtonStyle.success, row=1)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditBaseModal(nav_view=self)
        await interaction.response.send_modal(modal)
