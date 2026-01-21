"""Main bot class for Antigravity Remote."""

import asyncio
import logging
import sys

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from .config import config
from .state import state
from .handlers import (
    # Control
    start_command,
    pause_command,
    resume_command,
    cancel_command,
    key_command,
    lock_command,
    unlock_command,
    # Screen
    status_command,
    scroll_command,
    accept_command,
    reject_command,
    undo_command,
    # Files
    sysinfo_command,
    files_command,
    read_command,
    diff_command,
    log_command,
    # Monitoring
    heartbeat_command,
    watchdog_command,
    schedule_command,
    # AI
    model_command,
    summary_command,
    handle_message,
    handle_model_callback,
    # Quick
    quick_replies_command,
    handle_quick_callback,
    handle_voice,
)
from .utils import take_screenshot, cleanup_screenshot
from .handlers.base import is_authorized

logger = logging.getLogger(__name__)


class AntigravityBot:
    """Main Antigravity Remote Control bot."""
    
    def __init__(self):
        """Initialize the bot using embedded token and registered user."""
        self.token = config.bot_token
        self.user_id = config.allowed_user_id
        self.application = None
    
    def validate(self) -> bool:
        """Validate configuration before starting."""
        errors = config.validate()
        
        if errors:
            for error in errors:
                logger.error(f"Configuration error: {error}")
            return False
        
        return True
    
    async def button_handler(self, update: Update, context) -> None:
        """Handle all callback button presses."""
        query = update.callback_query
        await query.answer()
        
        if not await is_authorized(update):
            return
        
        data = query.data
        
        if data == "screenshot":
            await query.message.reply_text("📸 Capturing...")
            path = await asyncio.to_thread(take_screenshot)
            if path:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=open(path, 'rb')
                )
                cleanup_screenshot(path)
        
        elif data.startswith("model_"):
            model_id = data.replace("model_", "")
            await handle_model_callback(query, context, model_id)
        
        elif data.startswith("quick_"):
            action = data.replace("quick_", "")
            await handle_quick_callback(query, context, action)
    
    def setup_handlers(self) -> None:
        """Register all command and message handlers."""
        app = self.application
        
        # Command handlers
        handlers = [
            ("start", start_command),
            ("status", status_command),
            ("pause", pause_command),
            ("resume", resume_command),
            ("cancel", cancel_command),
            ("scroll", scroll_command),
            ("accept", accept_command),
            ("reject", reject_command),
            ("undo", undo_command),
            ("sysinfo", sysinfo_command),
            ("files", files_command),
            ("read", read_command),
            ("diff", diff_command),
            ("log", log_command),
            ("lock", lock_command),
            ("unlock", unlock_command),
            ("heartbeat", heartbeat_command),
            ("key", key_command),
            ("schedule", schedule_command),
            ("watchdog", watchdog_command),
            ("model", model_command),
            ("quick", quick_replies_command),
            ("summary", summary_command),
        ]
        
        for command, handler in handlers:
            app.add_handler(CommandHandler(command, handler))
        
        # Callback handlers
        app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Message handlers
        app.add_handler(MessageHandler(filters.VOICE, handle_voice))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    def run(self) -> None:
        """Start the bot."""
        if not self.validate():
            logger.error("Configuration validation failed")
            sys.exit(1)
        
        self.application = ApplicationBuilder().token(self.token).build()
        self.setup_handlers()
        
        print("🚀 Antigravity Remote Control")
        print(f"   User: {self.user_id}")
        print(f"   Workspace: {config.workspace_path}")
        print()
        
        self.application.run_polling()
    
    def stop(self) -> None:
        """Stop the bot and cleanup."""
        state.cancel_tasks()
        if self.application:
            self.application.stop()
