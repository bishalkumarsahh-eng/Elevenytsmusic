# ==========================================================
# Copyright (c) 2026 VelocityBots 
# All Rights Reserved.
#
# Project      : VelocityBots API Telegram Music Bot
# Powered By   : VelocityBots 
# Type         : API Based Telegram Music Bot
#
# Bot          : @JunoXmusic_Robot
# Channel      : https://t.me/junoxmusic_updates
# GitHub       : https://github.com/bishalkumarsahh-eng
#
# Unauthorized copying, modification, or redistribution
# of this source code without permission is prohibited.
# ==========================================================

import asyncio
import importlib
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from pyrogram import idle

# Raise the file descriptor limit on Linux to avoid "[Errno 24] Too many open files"
# when serving many groups concurrently (each audio stream + ffmpeg probe opens FDs).
if sys.platform != "win32":
    try:
        import resource
        _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        _target = min(65536, _hard)
        if _soft < _target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (_target, _hard))
    except Exception:
        pass

from Elevenyts import (tune, app, config, db,
                   logger, stop, userbot, yt)
from Elevenyts.plugins import all_modules


# HTTP Server for Render health checks
class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for Render health checks"""
    
    def do_GET(self):
        """Handle GET requests"""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running')
    
    def log_message(self, format, *args):
        """Suppress log messages to keep console clean"""
        pass


def run_http_server():
    """Run a simple HTTP server for Render health checks"""
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"🌐 HTTP health check server started on port {port}")
    server.serve_forever()


async def main():
    try:
        # Step 1: Validate required environment variables
        try:
            config.check()
        except SystemExit as e:
            logger.error(str(e))
            return

        # Step 2: Start HTTP server in a separate thread (for Render)
        http_thread = threading.Thread(target=run_http_server, daemon=True)
        http_thread.start()
        logger.info("🌐 HTTP server thread started for Render health checks")

        # Step 3: Connect to MongoDB database
        await db.connect()
        
        # Step 4: Start the main bot client
        await app.boot()
        
        # Step 5: Start assistant/userbot clients (for joining voice chats)
        await userbot.boot()
        
        # Step 6: Initialize voice call handler
        await tune.boot()

        # Step 7: Load all plugin modules (commands like /play, /pause, etc.)
        for module in all_modules:
            try:
                importlib.import_module(f"Elevenyts.plugins.{module}")
            except Exception as e:
                logger.error(f"Failed to load plugin {module}: {e}", exc_info=True)
        logger.info(f"🔌 Loaded {len(all_modules)} plugin modules.")

        # Step 8: Load sudo users and blacklisted users from database
        sudoers = await db.get_sudoers()
        app.sudoers.update(sudoers)  # Add sudo users to set
        app.sudo_filter.update(sudoers)  # Add sudo users to filter
        app.bl_users.update(await db.get_blacklisted())  # Add blacklisted users to filter
        logger.info(f"👑 Loaded {len(app.sudoers)} sudo users.")
        logger.info("\n🎉 Bot started successfully! Ready to play music! 🎵\n")

        # Step 9: Keep the bot running (press Ctrl+C to stop)
        try:
            await idle()
        except KeyboardInterrupt:
            logger.info("Received stop signal...")
        except Exception as e:
            logger.error(f"Error during idle: {e}", exc_info=True)
        
        # Step 10: Cleanup and shutdown when bot is stopped
        await stop()
    except Exception as e:
        logger.error(f"Critical error in main: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
    except SystemExit as e:
        logger.error(f"Bot exited with system error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error caused bot to stop: {e}", exc_info=True)
        # Don't raise - allow clean shutdown
    finally:
        # Ensure cleanup happens
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.stop()
        except:
            pass
