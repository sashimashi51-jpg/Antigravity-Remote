"""Monitoring command handlers for Antigravity Remote."""

import asyncio
import logging
import time
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from .base import is_authorized
from ..config import config
from ..state import state
from ..utils import take_screenshot, cleanup_screenshot, scan_screen, detect_keywords

logger = logging.getLogger(__name__)


async def heartbeat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start/stop heartbeat screenshots."""
    if not await is_authorized(update):
        return
    
    args = context.args
    
    # Cancel existing heartbeat
    if state.heartbeat_task:
        state.heartbeat_task.cancel()
        state.heartbeat_task = None
    
    if not args or args[0] == "off":
        await update.message.reply_text("💓 Heartbeat stopped.")
        return
    
    try:
        minutes = int(args[0])
    except ValueError:
        await update.message.reply_text("Usage: /heartbeat <minutes> or /heartbeat off")
        return
    
    async def heartbeat_loop():
        while True:
            await asyncio.sleep(minutes * 60)
            path = await asyncio.to_thread(take_screenshot)
            if path:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=open(path, 'rb'),
                    caption=f"💓 Heartbeat - {datetime.now().strftime('%H:%M')}"
                )
                cleanup_screenshot(path)
    
    state.heartbeat_task = asyncio.create_task(heartbeat_loop())
    await update.message.reply_text(f"💓 Heartbeat started! Screenshot every {minutes} minutes.")


async def watchdog_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start/stop smart watchdog monitoring."""
    if not await is_authorized(update):
        return
    
    args = context.args
    
    # Cancel existing watchdog
    if state.watchdog_task:
        state.watchdog_task.cancel()
        state.watchdog_task = None
    
    if args and args[0] == "off":
        await update.message.reply_text("🐕 Watchdog stopped.")
        return
    
    check_interval = config.watchdog_interval
    alert_cooldown = config.alert_cooldown
    
    async def watchdog_loop():
        while True:
            await asyncio.sleep(check_interval)
            
            try:
                screen_text, current_hash = await asyncio.to_thread(scan_screen)
                current_time = time.time()
                
                # Activity monitoring
                if current_hash == state.watchdog_last_hash:
                    state.watchdog_idle_count += 1
                else:
                    state.watchdog_idle_count = 0
                state.watchdog_last_hash = current_hash
                
                # Check for keywords
                detection = detect_keywords(screen_text)
                
                if detection and current_time - state.watchdog_last_alert > alert_cooldown:
                    category, keyword = detection
                    state.watchdog_last_alert = current_time
                    
                    path = await asyncio.to_thread(take_screenshot)
                    if path:
                        captions = {
                            'approval': f"🚨 *Approval needed!*\nDetected: `{keyword}`",
                            'done': f"✅ *Task appears complete!*\nDetected: `{keyword}`",
                            'error': f"⚠️ *Error detected!*\nDetected: `{keyword}`",
                        }
                        
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=open(path, 'rb'),
                            caption=captions.get(category, f"Detected: `{keyword}`"),
                            parse_mode=ParseMode.MARKDOWN
                        )
                        cleanup_screenshot(path)
                
                # Idle detection (2+ cycles with no change)
                if (state.watchdog_idle_count >= 2 and 
                    current_time - state.watchdog_last_alert > 60):
                    
                    state.watchdog_last_alert = current_time
                    state.watchdog_idle_count = 0
                    
                    path = await asyncio.to_thread(take_screenshot)
                    if path:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=open(path, 'rb'),
                            caption="💤 *Screen idle* - No activity detected",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        cleanup_screenshot(path)
                        
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
    
    state.watchdog_task = asyncio.create_task(watchdog_loop())
    
    await update.message.reply_text(
        "🐕 *Watchdog started!*\n\n"
        "I'll alert you when:\n"
        "• 🚨 Approval is needed\n"
        "• ✅ Task appears complete\n"
        "• ⚠️ Errors are detected\n"
        "• 💤 Screen goes idle\n\n"
        "Use `/watchdog off` to stop.",
        parse_mode=ParseMode.MARKDOWN
    )


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Schedule a command for later."""
    if not await is_authorized(update):
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /schedule 5m /status\nTime: 30s, 5m, 1h")
        return
    
    time_str = args[0].lower()
    scheduled_cmd = ' '.join(args[1:])
    
    # Parse time
    try:
        if time_str.endswith('s'):
            seconds = int(time_str[:-1])
        elif time_str.endswith('m'):
            seconds = int(time_str[:-1]) * 60
        elif time_str.endswith('h'):
            seconds = int(time_str[:-1]) * 3600
        else:
            seconds = int(time_str)
    except ValueError:
        await update.message.reply_text("Invalid time format. Use: 30s, 5m, 1h")
        return
    
    await update.message.reply_text(
        f"⏰ Scheduled `{scheduled_cmd}` in {time_str}",
        parse_mode=ParseMode.MARKDOWN
    )
    
    async def run_scheduled():
        await asyncio.sleep(seconds)
        
        if 'status' in scheduled_cmd.lower() or 'screenshot' in scheduled_cmd.lower():
            path = await asyncio.to_thread(take_screenshot)
            if path:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=open(path, 'rb'),
                    caption="⏰ Scheduled screenshot"
                )
                cleanup_screenshot(path)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⏰ Timer complete for: {scheduled_cmd}"
            )
    
    asyncio.create_task(run_scheduled())
