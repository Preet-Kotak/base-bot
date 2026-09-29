import hashlib
import json
import os
import discord
from discord.ext import commands
from config import GUILD_ID
from database import init_db
import commands.base_commands as base_commands
import commands.clan_commands as clan_commands
import commands.timezone_commands as timezone_commands
import commands.birthday_commands as birthday_commands
import commands.match_commands as match_commands

_HASH_FILE = os.path.join(os.path.dirname(__file__), ".cmd_hash")


def _commands_hash(tree: discord.app_commands.CommandTree) -> str:
    """Return a stable hash of all registered command names + descriptions."""
    commands_data = sorted(
        ({"name": c.name, "description": c.description}
         for c in tree.get_commands()),
        key=lambda c: c["name"],
    )
    serialized = json.dumps(commands_data, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        base_commands.register(self)
        clan_commands.register(self)
        timezone_commands.register(self)
        birthday_commands.register(self)
        match_commands.register(self)
        await init_db()

        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)

        # Only sync when the command tree has actually changed.
        current_hash = _commands_hash(self.tree)
        stored_hash = None
        if os.path.exists(_HASH_FILE):
            with open(_HASH_FILE, "r") as f:
                stored_hash = f.read().strip()

        if current_hash != stored_hash:
            await self.tree.sync(guild=guild)
            with open(_HASH_FILE, "w") as f:
                f.write(current_hash)
            print("Slash commands synced (tree changed).")
        else:
            print("Slash commands unchanged — skipping sync.")

        self.loop.create_task(birthday_commands.birthday_loop(self))

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")


bot = DiscordBot()