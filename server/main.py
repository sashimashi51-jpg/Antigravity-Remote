"""
Main entry point for Antigravity Remote Server.

Runs both:
- FastAPI WebSocket server (for local agents)
- Telegram bot (for user commands)
"""

import asyncio
import logging
import os
import threading

import uvicorn
from api import app
from bot import create_bot_app

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def run_telegram_bot():
    """Run the Telegram bot."""
    bot_app = create_bot_app()
    logger.info("🤖 Starting Telegram bot...")
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    
    # Keep running
    while True:
        await asyncio.sleep(1)


def run_api_server():
    """Run the FastAPI server."""
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"🌐 Starting API server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


async def main():
    """Main entry point."""
    logger.info("🚀 Antigravity Remote Server starting...")
    
    # Run API server in background thread
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    
    # Run Telegram bot in main async loop
    await run_telegram_bot()


if __name__ == "__main__":
    asyncio.run(main())
