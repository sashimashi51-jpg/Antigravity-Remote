"""Quick command handlers for Antigravity Remote."""

import asyncio
import logging
import os
import tempfile

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from .base import is_authorized
from ..utils import send_to_antigravity, take_screenshot, cleanup_screenshot

logger = logging.getLogger(__name__)

# Quick reply options
QUICK_REPLIES = [
    ("✅ Yes", "quick_yes"),
    ("❌ No", "quick_no"),
    ("▶️ Proceed", "quick_proceed"),
    ("⏹️ Cancel", "quick_cancel"),
    ("👍 Approve", "quick_approve"),
    ("⏭️ Skip", "quick_skip"),
]

QUICK_TEXTS = {
    "quick_yes": "Yes",
    "quick_no": "No",
    "quick_proceed": "Proceed",
    "quick_cancel": "Cancel",
    "quick_approve": "Approve",
    "quick_skip": "Skip",
}


async def quick_replies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show quick reply buttons."""
    if not await is_authorized(update):
        return
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes", callback_data="quick_yes"),
         InlineKeyboardButton("❌ No", callback_data="quick_no")],
        [InlineKeyboardButton("▶️ Proceed", callback_data="quick_proceed"),
         InlineKeyboardButton("⏹️ Cancel", callback_data="quick_cancel")],
        [InlineKeyboardButton("👍 Approve", callback_data="quick_approve"),
         InlineKeyboardButton("⏭️ Skip", callback_data="quick_skip")],
    ]
    
    await update.message.reply_text(
        "⚡ *Quick Replies* - Tap to send:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_quick_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    action: str
) -> None:
    """Handle quick reply callback."""
    text = QUICK_TEXTS.get(action, action.capitalize())
    success = await asyncio.to_thread(send_to_antigravity, text)
    
    if success:
        await query.message.reply_text(f"📤 Sent: *{text}*", parse_mode=ParseMode.MARKDOWN)
    else:
        await query.message.reply_text("❌ Failed to send")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages - download, transcribe, and relay."""
    if not await is_authorized(update):
        return
    
    voice = update.message.voice
    status_msg = await update.message.reply_text("🎤 Processing voice message...")
    
    try:
        # Download voice file
        file = await context.bot.get_file(voice.file_id)
        voice_path = os.path.join(tempfile.gettempdir(), f"voice_{voice.file_id}.ogg")
        await file.download_to_drive(voice_path)
        
        # Try to transcribe with speech recognition
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            
            # Convert ogg to wav
            wav_path = voice_path.replace('.ogg', '.wav')
            os.system(f'ffmpeg -i "{voice_path}" -y "{wav_path}" 2>nul')
            
            with sr.AudioFile(wav_path) as source:
                audio = recognizer.record(source)
                text = recognizer.recognize_google(audio)
            
            # Cleanup
            if os.path.exists(wav_path):
                os.remove(wav_path)
            if os.path.exists(voice_path):
                os.remove(voice_path)
            
            # Relay transcribed text
            await status_msg.edit_text(
                f"🎤 Transcribed: *{text}*\n\nSending...",
                parse_mode=ParseMode.MARKDOWN
            )
            success = await asyncio.to_thread(send_to_antigravity, text)
            
            if success:
                keyboard = [[InlineKeyboardButton("📸 Get Result", callback_data="screenshot")]]
                await status_msg.edit_text(
                    f"✅ *Voice relayed:*\n`{text}`",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await status_msg.edit_text("❌ Failed to relay voice message")
                
        except ImportError:
            await status_msg.edit_text(
                "⚠️ Voice transcription not available.\n"
                "Install: `pip install SpeechRecognition`",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Transcription failed: {e}")
            if os.path.exists(voice_path):
                os.remove(voice_path)
                
    except Exception as e:
        await status_msg.edit_text(f"❌ Error processing voice: {e}")
