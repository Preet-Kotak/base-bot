import asyncio
import aiohttp
import http.server
import threading
from config import TOKEN, RENDER_URL, PORT, KEEPALIVE_INTERVAL
from bot import bot


def start_http_server_sync(port: int):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[HTTP] Server started on port {port}")


async def self_ping():
    """Keep the Render dyno alive by pinging /health every KEEPALIVE_INTERVAL seconds.
    Waits for the bot to be fully ready before the first ping, then waits one full
    interval before pinging again — so startup never triggers a Cloudflare hit.
    """
    if not RENDER_URL:
        print("[Keepalive] RENDER_URL not set — self-ping disabled.")
        return

    # Wait until the bot is fully logged in before doing anything.
    await bot.wait_until_ready()
    # Then wait one full interval so the very first ping is spaced well away from
    # the startup burst of Discord API calls (login + optional tree.sync).
    print(f"[Keepalive] Bot ready — first ping in {KEEPALIVE_INTERVAL // 60} min.")
    await asyncio.sleep(KEEPALIVE_INTERVAL)

    async with aiohttp.ClientSession() as session:
        while not bot.is_closed():
            try:
                async with session.get(
                    f"{RENDER_URL}/health",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    print(f"[Keepalive] Ping → {resp.status}")
            except Exception as exc:
                print(f"[Keepalive] Ping failed: {exc}")
            await asyncio.sleep(KEEPALIVE_INTERVAL)


async def main():
    async with bot:
        # Start the keepalive task inside the bot's async context so it is
        # properly cancelled when the bot shuts down.
        bot.loop.create_task(self_ping())
        await bot.start(TOKEN)


if __name__ == "__main__":
    start_http_server_sync(PORT)
    asyncio.run(main())
