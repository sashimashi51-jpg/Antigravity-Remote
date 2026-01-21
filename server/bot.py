"""
Telegram Bot Handler for Antigravity Remote Server

Handles incoming Telegram messages and routes them to connected clients.
"""

import asyncio
import base64
import logging
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from api import send_command_to_client, is_user_connected, connected_clients

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot token from environment
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_id = str(update.effective_user.id)
    is_connected = is_user_connected(user_id)
    
    status = "🟢 Connected" if is_connected else "🔴 Not connected"
    
    help_text = f"""🚀 *Antigravity Remote Control*

*Your User ID:* `{user_id}`
*Status:* {status}

*Setup:*
1. Install: `pip install antigravity-remote`
2. Run: `antigravity-remote`
3. Enter your User ID when prompted

*Commands:*
`/status` - Screenshot
`/connect` - Connection status
`/quick` - Quick reply buttons
`/scroll up|down` - Scroll chat
`/accept` / `/reject` - Accept/reject
`/key ctrl+s` - Send key combo
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def connect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check connection status."""
    user_id = str(update.effective_user.id)
    
    if is_user_connected(user_id):
        await update.message.reply_text(
            f"🟢 *Connected!*\n\nYour local agent is online.\nUser ID: `{user_id}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"🔴 *Not connected*\n\n"
            f"Your User ID: `{user_id}`\n\n"
            f"*To connect:*\n"
            f"1. `pip install antigravity-remote`\n"
            f"2. `antigravity-remote`\n"
            f"3. Enter your User ID",
            parse_mode=ParseMode.MARKDOWN
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Take a screenshot."""
    user_id = str(update.effective_user.id)
    
    if not is_user_connected(user_id):
        await update.message.reply_text("🔴 Not connected. Run `antigravity-remote` on your PC first.")
        return
    
    msg = await update.message.reply_text("📸 Capturing...")
    
    response = await send_command_to_client(user_id, {"type": "screenshot"})
    
    if response and response.get("image"):
        # Decode base64 image
        image_data = base64.b64decode(response["image"])
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=image_data,
            caption="🖥️ Current screen"
        )
        await msg.delete()
    else:
        await msg.edit_text("❌ Failed to capture screenshot")


async def scroll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scroll the screen."""
    user_id = str(update.effective_user.id)
    
    if not is_user_connected(user_id):
        await update.message.reply_text("🔴 Not connected.")
        return
    
    args = context.args
    direction = "down" if not args else args[0].lower()
    
    response = await send_command_to_client(user_id, {
        "type": "scroll",
        "direction": direction
    })
    
    if response:
        await update.message.reply_text(f"📜 Scrolled {direction}")
    else:
        await update.message.reply_text("❌ Command failed")


async def key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send key combo."""
    user_id = str(update.effective_user.id)
    
    if not is_user_connected(user_id):
        await update.message.reply_text("🔴 Not connected.")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /key ctrl+s")
        return
    
    combo = args[0]
    response = await send_command_to_client(user_id, {
        "type": "key",
        "combo": combo
    })
    
    if response:
        await update.message.reply_text(f"⌨️ Sent: `{combo}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Command failed")


async def accept_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send accept."""
    user_id = str(update.effective_user.id)
    
    if not is_user_connected(user_id):
        await update.message.reply_text("🔴 Not connected.")
        return
    
    response = await send_command_to_client(user_id, {"type": "accept"})
    await update.message.reply_text("✅ Sent Accept")


async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send reject."""
    user_id = str(update.effective_user.id)
    
    if not is_user_connected(user_id):
        await update.message.reply_text("🔴 Not connected.")
        return
    
    response = await send_command_to_client(user_id, {"type": "reject"})
    await update.message.reply_text("❌ Sent Reject")


async def quick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show quick reply buttons."""
    keyboard = [
        [InlineKeyboardButton("✅ Yes", callback_data="quick_yes"),
         InlineKeyboardButton("❌ No", callback_data="quick_no")],
        [InlineKeyboardButton("▶️ Proceed", callback_data="quick_proceed"),
         InlineKeyboardButton("⏹️ Cancel", callback_data="quick_cancel")],
        [InlineKeyboardButton("📸 Screenshot", callback_data="quick_screenshot")],
    ]
    
    await update.message.reply_text(
        "⚡ *Quick Actions:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()
    
    user_id = str(update.effective_user.id)
    
    if not is_user_connected(user_id):
        await query.message.reply_text("🔴 Not connected.")
        return
    
    data = query.data
    
    if data == "quick_screenshot":
        response = await send_command_to_client(user_id, {"type": "screenshot"})
        if response and response.get("image"):
            image_data = base64.b64decode(response["image"])
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=image_data)
    
    elif data.startswith("quick_"):
        text = data.replace("quick_", "").capitalize()
        response = await send_command_to_client(user_id, {"type": "relay", "text": text})
        await query.message.reply_text(f"📤 Sent: {text}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages - relay to Antigravity."""
    user_id = str(update.effective_user.id)
    
    if not is_user_connected(user_id):
        await update.message.reply_text(
            f"🔴 *Not connected*\n\n"
            f"Your User ID: `{user_id}`\n"
            f"Run `antigravity-remote` on your PC first.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    text = update.message.text
    msg = await update.message.reply_text("📤 Sending...")
    
    response = await send_command_to_client(user_id, {
        "type": "relay",
        "text": text
    })
    
    if response and response.get("success"):
        keyboard = [[InlineKeyboardButton("📸 Screenshot", callback_data="quick_screenshot")]]
        await msg.edit_text(
            "✅ *Sent!*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await msg.edit_text("❌ Failed to send")


def create_bot_app():
    """Create and configure the Telegram bot application."""
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("connect", connect_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("scroll", scroll_command))
    application.add_handler(CommandHandler("key", key_command))
    application.add_handler(CommandHandler("accept", accept_command))
    application.add_handler(CommandHandler("reject", reject_command))
    application.add_handler(CommandHandler("quick", quick_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    return application
