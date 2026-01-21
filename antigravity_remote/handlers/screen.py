"""Screen command handlers for Antigravity Remote."""

import asyncio
import logging
import time

import pyautogui

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from .base import is_authorized
from ..utils import focus_antigravity, take_screenshot, cleanup_screenshot, scroll_screen

logger = logging.getLogger(__name__)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Take and send a screenshot."""
    if not await is_authorized(update):
        return
    
    msg = await update.message.reply_text("📸 Capturing...")
    path = await asyncio.to_thread(take_screenshot)
    
    if path:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=open(path, 'rb'),
            caption="🖥️ Current screen"
        )
        cleanup_screenshot(path)
    else:
        await update.message.reply_text("❌ Failed to capture screenshot")
    
    await msg.delete()


async def scroll_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scroll the screen."""
    if not await is_authorized(update):
        return
    
    args = context.args
    direction = "down"
    multiplier = 1
    
    # Parse args: /scroll up x50 or /scroll down 10 or /scroll bottom
    for arg in args:
        if arg == "bottom":
            direction = "down"
            multiplier = 100
        elif arg == "top":
            direction = "up"
            multiplier = 100
        elif arg in ["up", "down"]:
            direction = arg
        elif arg.startswith("x") and arg[1:].isdigit():
            multiplier = int(arg[1:])
        elif arg.isdigit():
            multiplier = int(arg)
    
    # Calculate scroll amount
    base_clicks = 25
    clicks = base_clicks * multiplier
    if direction == "down":
        clicks = -clicks
    
    success = await asyncio.to_thread(scroll_screen, clicks)
    
    if success:
        await update.message.reply_text(f"📜 Scrolled {direction} x{multiplier}")
    else:
        await update.message.reply_text("❌ Failed to scroll")


async def accept_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send Accept (Alt+Enter)."""
    if not await is_authorized(update):
        return
    
    await asyncio.to_thread(
        lambda: (focus_antigravity(), time.sleep(0.2), pyautogui.hotkey('alt', 'enter'))
    )
    await update.message.reply_text("✅ Sent Accept (Alt+Enter)")


async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send Reject (Escape)."""
    if not await is_authorized(update):
        return
    
    await asyncio.to_thread(
        lambda: (focus_antigravity(), time.sleep(0.2), pyautogui.press('escape'))
    )
    await update.message.reply_text("❌ Sent Reject (Escape)")


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send Undo (Ctrl+Z)."""
    if not await is_authorized(update):
        return
    
    await asyncio.to_thread(
        lambda: (focus_antigravity(), pyautogui.hotkey('ctrl', 'z'))
    )
    await update.message.reply_text("↩️ Sent Undo (Ctrl+Z)")
