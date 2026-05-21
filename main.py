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
    if not RENDER_URL:
        print("[Keepalive] RENDER_URL not set — self-ping disabled.")
        return
    await asyncio.sleep(30)
    async with aiohttp.ClientSession() as session:
        while True:
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
    asyncio.create_task(self_ping())
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    start_http_server_sync(PORT)
    asyncio.run(main())
