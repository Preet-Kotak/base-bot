import os

TOKEN        = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID     = int(os.environ["DISCORD_GUILD_ID"])
DATABASE_URL = os.environ["DATABASE_URL"]
RENDER_URL   = os.environ.get("RENDER_URL", "")
BIRTHDAY_CHANNEL_ID = int(os.environ.get("BIRTHDAY_CHANNEL_ID", 0))
PORT         = int(os.environ.get("PORT", 8080))

# Cloudinary configuration
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY    = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

KEEPALIVE_INTERVAL = 9 * 60

DISTRICT_NAMES = {
    0: "Capital Peak",
    1: "Barbarian Camp",
    2: "Wizard Valley",
    3: "Balloon Lagoon",
    4: "Builder's Workshop",
    5: "Dragon Cliffs",
    6: "Golem Quarry",
    7: "Skeleton Park",
    8: "Goblin Mines",
}

DISTRICT_EMOJIS = {
    0: "🏔️", 1: "⚔️", 2: "🧙", 3: "🎈",
    4: "🔨", 5: "🐉", 6: "🪨", 7: "💀", 8: "👺",
}

DISTRICT_COLORS = {
    0: 0xE74C3C, 1: 0xE67E22, 2: 0x9B59B6, 3: 0x3498DB,
    4: 0xF1C40F, 5: 0x2ECC71, 6: 0x95A5A6, 7: 0x1ABC9C, 8: 0xE91E63,
}

RENEW_DELAY        = 1.0
RENEW_UPDATE_EVERY = 20
