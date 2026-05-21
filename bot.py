import discord
from discord.ext import commands
from config import GUILD_ID
from database import init_db
import commands.base_commands as base_commands
import commands.clan_commands as clan_commands


class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        base_commands.register(self)
        clan_commands.register(self)
        await init_db()
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("Slash commands synced.")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")


bot = DiscordBot()
