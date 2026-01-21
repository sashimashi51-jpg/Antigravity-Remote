"""AI command handlers for Antigravity Remote."""

import asyncio
import logging
import time

import pyautogui
import pyperclip

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from .base import is_authorized
from ..state import state
from ..utils import focus_antigravity, send_to_antigravity, take_screenshot, cleanup_screenshot

logger = logging.getLogger(__name__)

# Available models in Antigravity
MODELS = [
    ("Gemini 3 Pro (High)", "gemini_3_pro_high"),
    ("Gemini 3 Pro (Low)", "gemini_3_pro_low"),
    ("Gemini 3 Flash", "gemini_3_flash"),
    ("Claude Sonnet 4.5", "claude_sonnet_45"),
    ("Claude Sonnet 4.5 (Thinking)", "claude_sonnet_45_thinking"),
    ("Claude Opus 4.5 (Thinking)", "claude_opus_45_thinking"),
    ("GPT-OSS 120B (Medium)", "gpt_oss_120b"),
]

MODEL_NAMES = {model_id: name for name, model_id in MODELS}


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show model selection menu."""
    if not await is_authorized(update):
        return
    
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"model_{model_id}")]
        for name, model_id in MODELS
    ]
    
    await update.message.reply_text(
        "🤖 *Select a model:*\n\n_Note: Model availability depends on your subscription_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask Antigravity for a task summary."""
    if not await is_authorized(update):
        return
    
    summary_prompt = "Please give me a brief summary of what you just did in the last task."
    
    status_msg = await update.message.reply_text("📝 Asking for summary...")
    success = await asyncio.to_thread(send_to_antigravity, summary_prompt)
    
    if success:
        keyboard = [[InlineKeyboardButton("📸 Get Summary", callback_data="screenshot")]]
        await status_msg.edit_text(
            "📝 *Summary requested!*\nWait a moment for the response, then tap:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await status_msg.edit_text("❌ Failed to send summary request")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages - relay to Antigravity."""
    if not await is_authorized(update):
        return
    
    if state.locked:
        await update.message.reply_text("🔒 Bot is locked. Use /unlock <password>")
        return
    
    if state.paused:
        await update.message.reply_text("⏸️ Relay is paused. Use /resume")
        return
    
    user_msg = update.message.text
    
    # Log command
    state.log_command(user_msg)
    
    status_msg = await update.message.reply_text("📤 Sending to Antigravity...")
    success = await asyncio.to_thread(send_to_antigravity, user_msg)
    
    if not success:
        await status_msg.edit_text("❌ Failed to send. Is Antigravity app open?")
        return
    
    keyboard = [[InlineKeyboardButton("📸 Get Result", callback_data="screenshot")]]
    await status_msg.edit_text(
        "✅ *Sent!* Tap when ready:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_model_callback(
    query, 
    context: ContextTypes.DEFAULT_TYPE,
    model_id: str
) -> None:
    """Handle model selection callback."""
    model_name = MODEL_NAMES.get(model_id, model_id)
    
    def switch_model():
        focus_antigravity()
        time.sleep(0.2)
        # Open command palette
        pyautogui.hotkey('ctrl', 'shift', 'p')
        time.sleep(0.5)
        # Type model switch command
        pyperclip.copy("Switch Model")
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.3)
        pyautogui.press('enter')
        time.sleep(0.3)
        # Type model name
        pyperclip.copy(model_name)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)
        pyautogui.press('enter')
    
    await asyncio.to_thread(switch_model)
    await query.message.reply_text(
        f"🔄 Switching to *{model_name}*...",
        parse_mode=ParseMode.MARKDOWN
    )
