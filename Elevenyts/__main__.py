import asyncio
import importlib
import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/health/"):
            body = b"Bot is running"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        pass

def run_http_server():
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"HTTP health server listening on port {port}", flush=True)
    server.serve_forever()

threading.Thread(target=run_http_server, daemon=True).start()

if sys.platform != "win32":
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(65536, hard)
        if soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except Exception:
        pass

async def main():
    from pyrogram import idle
    from Elevenyts import tune, app, config, db, logger, stop, userbot
    from Elevenyts.plugins import all_modules
    try:
        config.check()
        await db.connect()
        await app.boot()
        await userbot.boot()
        await tune.boot()
        for module in all_modules:
            try:
                importlib.import_module(f"Elevenyts.plugins.{module}")
            except Exception as e:
                logger.error(f"Failed to load plugin {module}: {e}", exc_info=True)
        logger.info(f"Loaded {len(all_modules)} plugin modules.")
        sudoers = await db.get_sudoers()
        app.sudoers.update(sudoers)
        app.sudo_filter.update(sudoers)
        app.bl_users.update(await db.get_blacklisted())
        logger.info(f"Loaded {len(app.sudoers)} sudo users.")
        logger.info("Bot started successfully! Ready to play music!")
        await idle()
    except SystemExit as e:
        print(f"Configuration error: {e}", flush=True)
    except Exception as e:
        logging.exception("Critical error in main: %s", e)
        raise
    finally:
        try:
            await stop()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.", flush=True)
