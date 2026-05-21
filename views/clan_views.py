import discord
import asyncpg
from database import get_pool


class EditClanModal(discord.ui.Modal, title="✏️ Edit Clan"):
    """Pre-filled modal for editing a clan from the ClanNavigationView."""

    name_input = discord.ui.TextInput(
        label="Clan Name",
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    link_input = discord.ui.TextInput(
        label="Clan Link",
        style=discord.TextStyle.short,
        placeholder="https://link.clashofclans.com/...",
        required=True,
        max_length=500,
    )
    owner_input = discord.ui.TextInput(
        label="Owner",
        style=discord.TextStyle.short,
        placeholder="Leave blank to clear",
        required=False,
        max_length=100,
    )
    description_input = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        placeholder="Short description (optional)",
        required=False,
        max_length=500,
    )

    def __init__(self, nav_view: "ClanNavigationView"):
        super().__init__()
        self.nav_view = nav_view
        row = nav_view.clans[nav_view.current_index]
        self.name_input.default        = row["clan_name"] or ""
        self.link_input.default        = row["clan_link"] or ""
        self.owner_input.default       = row["owner"] or ""
        self.description_input.default = row["description"] or ""

    async def on_submit(self, interaction: discord.Interaction):
        nav     = self.nav_view
        row     = nav.clans[nav.current_index]
        clan_id = row["id"]

        new_name  = self.name_input.value.strip()
        new_link  = self.link_input.value.strip()
        new_owner = self.owner_input.value.strip() or None
        new_desc  = self.description_input.value.strip() or None

        if not new_name or not new_link:
            await interaction.response.send_message(
                "❌ Clan Name and Clan Link are required.", ephemeral=True
            )
            return

        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE clans
                       SET clan_name = $1, clan_link = $2, owner = $3, description = $4
                       WHERE id = $5""",
                    new_name, new_link, new_owner, new_desc, clan_id,
                )
        except asyncpg.UniqueViolationError:
            await interaction.response.send_message(
                "❌ Another clan already has that link.", ephemeral=True
            )
            return

        updated = dict(row)
        updated["clan_name"]   = new_name
        updated["clan_link"]   = new_link
        updated["owner"]       = new_owner
        updated["description"] = new_desc
        nav.clans[nav.current_index] = updated

        await interaction.response.edit_message(embed=nav.build_embed(), view=nav)


class ClanNavigationView(discord.ui.View):
    def __init__(self, clans: list, current_index: int = 0):
        super().__init__(timeout=300)
        self.clans = clans
        self.current_index = current_index
        self._refresh_buttons()

    def _clamp(self, value: int) -> int:
        return max(0, min(value, len(self.clans) - 1))

    def _refresh_buttons(self):
        idx   = self.current_index
        total = len(self.clans)
        self.prev10_button.disabled = idx < 10
        self.prev_button.disabled   = idx == 0
        self.next_button.disabled   = idx >= total - 1
        self.next10_button.disabled = idx >= total - 10
        self.counter_button.label   = f"{idx + 1} / {total}"

    def build_embed(self) -> discord.Embed:
        row = self.clans[self.current_index]
        embed = discord.Embed(
            title=f"🏰  {row['clan_name']}",
            color=0x3498DB,
        )
        if row["description"]:
            embed.description = row["description"]
        embed.add_field(name="🔗 Clan Link",  value=row["clan_link"],           inline=False)
        embed.add_field(name="👑 Owner",      value=row["owner"] or "*Unknown*", inline=True)
        embed.set_footer(
            text=(
                f"Clan #{row['id']}  ·  {self.current_index + 1} of {len(self.clans)} total"
                f"  ·  Clan Capital Base Bot"
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
        await interaction.response.send_modal(EditClanModal(nav_view=self))
