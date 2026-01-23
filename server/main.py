"""
Antigravity Remote Server - v4.3.0 VIBECODER EDITION
Thin entry point - all logic moved to modular components.

Architecture:
├── main.py           # This file - entry point
├── app.py            # FastAPI app factory
├── config.py         # Configuration
├── utils.py          # Utilities
├── routes/           # API endpoints
│   ├── api.py        # REST routes  
│   └── websocket.py  # WebSocket routes
├── controllers/      # Request handlers
│   └── telegram.py   # Telegram bot handlers
├── services/         # Business logic
│   └── __init__.py   # All services
└── db/               # Database layer
    └── __init__.py   # SQLite repositories
"""

import asyncio
import logging
import sys
import threading

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("Antigravity Remote Server - v4.3.0 VIBECODER EDITION")
logger.info("Architecture: Modular (routes/controllers/services)")
logger.info("=" * 50)

try:
    import uvicorn
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    
    from config import config
    from app import create_app, get_services, set_bot_application
    from controllers import telegram as tg_controller
    
    logger.info("All imports successful!")
except Exception as e:
    logger.error(f"Import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


def setup_telegram_bot():
    """Setup and return Telegram bot application."""
    if not config.BOT_TOKEN:
        logger.warning("No TELEGRAM_BOT_TOKEN set - bot disabled")
        return None
    
    # Get services for injection
    services = get_services()
    
    # Initialize Telegram controller with dependencies
    tg_controller.init_telegram_controller(
        services["connected_clients"],
        services["user_state"],
        services["ai_responses"],
        services["rate_limiter"],
        services["command_queue"],
        services["scheduler"],
        services["undo_stack"],
        services["live_stream"],
        services["auth_service"],
        services["config"],
        services["send_cmd"],
        services["sanitize_input"]
    )
    
    # Build application
    bot_app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    
    # Register handlers
    bot_app.add_handler(CommandHandler("start", tg_controller.start_cmd))
    bot_app.add_handler(CommandHandler("status", tg_controller.status_cmd))
    bot_app.add_handler(CommandHandler("ss", tg_controller.status_cmd))
    bot_app.add_handler(CommandHandler("stream", tg_controller.stream_cmd))
    bot_app.add_handler(CommandHandler("diff", tg_controller.diff_cmd))
    bot_app.add_handler(CommandHandler("schedule", tg_controller.schedule_cmd))
    bot_app.add_handler(CommandHandler("undo", tg_controller.undo_cmd))
    bot_app.add_handler(CommandHandler("scroll", tg_controller.scroll_cmd))
    bot_app.add_handler(CommandHandler("accept", tg_controller.accept_cmd))
    bot_app.add_handler(CommandHandler("y", tg_controller.accept_cmd))
    bot_app.add_handler(CommandHandler("reject", tg_controller.reject_cmd))
    bot_app.add_handler(CommandHandler("n", tg_controller.reject_cmd))
    bot_app.add_handler(CommandHandler("tts", tg_controller.tts_cmd))
    bot_app.add_handler(CommandHandler("quick", tg_controller.quick_cmd))
    bot_app.add_handler(CommandHandler("model", tg_controller.model_cmd))
    bot_app.add_handler(CommandHandler("watchdog", tg_controller.watchdog_cmd))
    bot_app.add_handler(CommandHandler("pause", tg_controller.pause_cmd))
    bot_app.add_handler(CommandHandler("resume", tg_controller.resume_cmd))
    bot_app.add_handler(CallbackQueryHandler(tg_controller.button_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tg_controller.handle_msg))
    bot_app.add_handler(MessageHandler(filters.PHOTO, tg_controller.handle_photo))
    bot_app.add_handler(MessageHandler(filters.VOICE, tg_controller.handle_voice))
    bot_app.add_handler(MessageHandler(filters.Document.ALL, tg_controller.handle_document))
    
    logger.info("Telegram bot configured with all handlers")
    return bot_app


def run_telegram_bot(bot_app):
    """Run Telegram bot in a separate thread."""
    if bot_app:
        # Set the global reference for the app factory
        set_bot_application(bot_app)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def start_bot():
            await bot_app.initialize()
            await bot_app.start()
            await bot_app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot started!")
            
            # Keep running
            while True:
                await asyncio.sleep(3600)
        
        try:
            loop.run_until_complete(start_bot())
        except Exception as e:
            logger.error(f"Bot error: {e}")


def main():
    """Main entry point."""
    logger.info(f"PORT: {config.PORT}")
    logger.info(f"BOT_TOKEN: {'SET' if config.BOT_TOKEN else 'MISSING!'}")
    
    # Create FastAPI app
    app = create_app()
    
    # Setup Telegram bot
    bot_app = setup_telegram_bot()
    
    # Run bot in background thread
    if bot_app:
        bot_thread = threading.Thread(target=run_telegram_bot, args=(bot_app,), daemon=True)
        bot_thread.start()
        logger.info("Telegram bot thread started")
    
    # Run FastAPI with uvicorn
    logger.info(f"Starting server on port {config.PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
