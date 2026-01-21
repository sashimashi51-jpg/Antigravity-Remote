"""Control command handlers for Antigravity Remote."""

import asyncio
import logging
import time

import pyautogui

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from .base import is_authorized
from ..state import state
from ..utils import focus_antigravity, send_key_combo

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help menu."""
    if not await is_authorized(update):
        return
    
    help_text = """🔗 *Antigravity Remote Control*

*Relay:* Send any message to relay it.

*Commands:*
`/status` - Screenshot now
`/model` - Switch AI model
`/quick` - Quick reply buttons
`/summary` - Ask for task summary
`/watchdog` - Smart auto-alerts
`/pause` / `/resume` - Toggle relay
`/cancel` - Send Escape
`/scroll` - up/down/top/bottom
`/accept` / `/reject` - Click buttons
`/undo` - Ctrl+Z
`/key` - Send key combo
`/schedule` - Schedule command
`/sysinfo` - System stats
`/files` - List files
`/read` - Read file
`/diff` - Git diff
`/log` - Command history
`/lock` / `/unlock` - Security
`/heartbeat` - Auto screenshots
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pause message relay."""
    if not await is_authorized(update):
        return
    
    state.paused = True
    await update.message.reply_text("⏸️ Relay paused. Use /resume to continue.")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resume message relay."""
    if not await is_authorized(update):
        return
    
    state.paused = False
    await update.message.reply_text("▶️ Relay resumed!")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send Escape key."""
    if not await is_authorized(update):
        return
    
    await asyncio.to_thread(lambda: (focus_antigravity(), pyautogui.press('escape')))
    await update.message.reply_text("❌ Sent Escape key")


async def key_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a key combination."""
    if not await is_authorized(update):
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /key ctrl+s or /key alt+shift+tab")
        return
    
    combo = args[0].lower().split('+')
    success = await asyncio.to_thread(send_key_combo, combo)
    
    if success:
        await update.message.reply_text(
            f"⌨️ Sent: `{'+'.join(combo)}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("❌ Failed to send key combo")


async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lock the bot."""
    if not await is_authorized(update):
        return
    
    state.locked = True
    await update.message.reply_text("🔒 Bot locked. Use /unlock <password> to unlock.")


async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unlock the bot."""
    if not await is_authorized(update):
        return
    
    from ..config import config
    
    args = context.args
    if args and args[0] == config.lock_password:
        state.locked = False
        await update.message.reply_text("🔓 Bot unlocked!")
    else:
        await update.message.reply_text("❌ Wrong password.")
