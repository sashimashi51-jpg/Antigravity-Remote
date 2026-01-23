"""
Antigravity Remote - Telegram Controllers
All Telegram bot command and message handlers.
"""

import asyncio
import base64
import json
import os
import logging
from datetime import datetime
from typing import Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# Shared state - injected
connected_clients = {}
user_state = {}
ai_responses = {}

# Services - injected
rate_limiter = None
command_queue = None
scheduler = None
undo_stack = None
live_stream = None
auth_service = None
config = None

# Helper function - injected
send_cmd = None
sanitize_input = None


def init_telegram_controller(
    clients_ref,
    state_ref,
    ai_resp_ref,
    rate_limiter_svc,
    queue_svc,
    scheduler_svc,
    undo_svc,
    livestream_svc,
    auth_svc,
    cfg,
    send_cmd_func,
    sanitize_func
):
    """Initialize Telegram controller with dependencies."""
    global connected_clients, user_state, ai_responses
    global rate_limiter, command_queue, scheduler, undo_stack, live_stream, auth_service, config
    global send_cmd, sanitize_input
    
    connected_clients = clients_ref
    user_state = state_ref
    ai_responses = ai_resp_ref
    rate_limiter = rate_limiter_svc
    command_queue = queue_svc
    scheduler = scheduler_svc
    undo_stack = undo_svc
    live_stream = livestream_svc
    auth_service = auth_svc
    config = cfg
    send_cmd = send_cmd_func
    sanitize_input = sanitize_func


def get_user_state(uid: str) -> dict:
    """Get or create user state."""
    if uid not in user_state:
        user_state[uid] = {"paused": False, "locked": False}
    return user_state[uid]


async def check_rate_limit(update: Update) -> bool:
    """Check if user is rate limited."""
    uid = str(update.effective_user.id)
    if not rate_limiter.is_allowed(uid):
        await update.message.reply_text(f"⏳ Rate limited. Wait {rate_limiter.get_wait_time(uid)}s")
        return False
    return True


def get_mini_keyboard():
    """Get persistent mini keyboard."""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 Status"), KeyboardButton("✅ Accept"), KeyboardButton("❌ Reject")],
        [KeyboardButton("⬆️ Scroll Up"), KeyboardButton("⬇️ Scroll Down"), KeyboardButton("↩️ Undo")],
    ], resize_keyboard=True, is_persistent=True)


# ============ Command Handlers ============

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    
    if uid in connected_clients:
        status = "🟢 Connected"
    elif command_queue.get_queue_size(uid) > 0:
        status = f"🟡 Offline ({command_queue.get_queue_size(uid)} queued)"
    else:
        status = "🔴 Not connected"
    
    auth_token, expires_at = auth_service.generate_token(uid)
    expiry_date = datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d")
    
    await update.message.reply_text(
        f"🚀 *Antigravity Remote v4.3*\n"
        f"_The Vibecoder's Best Friend_\n\n"
        f"ID: `{uid}`\n"
        f"Status: {status}\n"
        f"Token: `{auth_token}`\n"
        f"Expires: {expiry_date}\n\n"
        f"*Features:*\n"
        f"📺 /stream - Live screen view\n"
        f"💬 Two-way chat with AI\n"
        f"📋 /diff - Preview code changes\n"
        f"⏰ /schedule - Automated tasks\n"
        f"🔄 /undo N - Undo N changes\n\n"
        f"`pip install antigravity-remote`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_mini_keyboard()
    )


async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - take screenshot."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        queued = command_queue.get_queue_size(uid)
        msg = f"🔴 Offline" + (f" ({queued} queued)" if queued > 0 else "")
        await update.message.reply_text(msg, reply_markup=get_mini_keyboard())
        return
    
    msg = await update.message.reply_text("📸 Capturing...")
    resp = await send_cmd(uid, {"type": "screenshot", "quality": 70})
    if resp and resp.get("image"):
        keyboard = [[
            InlineKeyboardButton("✅ Accept", callback_data="q_accept"),
            InlineKeyboardButton("❌ Reject", callback_data="q_reject"),
        ], [
            InlineKeyboardButton("🔄 Refresh", callback_data="q_ss"),
            InlineKeyboardButton("📺 Live", callback_data="q_stream"),
        ]]
        await ctx.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=base64.b64decode(resp["image"]),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await msg.delete()
    else:
        await msg.edit_text("❌ Failed")


async def stream_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /stream command - start live streaming."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    await send_cmd(uid, {"type": "start_stream", "fps": config.STREAM_FPS})
    live_stream.start_stream(uid)
    
    host = os.environ.get("RENDER_EXTERNAL_URL", f"http://localhost:{config.PORT}")
    stream_url = f"{host}/stream/{uid}"
    
    keyboard = [[InlineKeyboardButton("📺 Watch Live", url=stream_url)]]
    await update.message.reply_text(
        f"📺 *Live Stream Started!*\n\nOpen in browser:\n{stream_url}\n\n`/stream stop` to end",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def diff_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /diff command - show pending code changes."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    msg = await update.message.reply_text("📋 Getting diff...")
    resp = await send_cmd(uid, {"type": "get_diff"})
    
    if resp and resp.get("diff"):
        diff_text = sanitize_input(resp["diff"], 3500)
        keyboard = [[
            InlineKeyboardButton("✅ Accept All", callback_data="q_accept"),
            InlineKeyboardButton("❌ Reject All", callback_data="q_reject"),
        ]]
        await msg.edit_text(
            f"📋 *Pending Changes:*\n```diff\n{diff_text}\n```",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await msg.edit_text("📋 No pending changes")


async def schedule_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /schedule command - manage scheduled tasks."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    
    if not ctx.args:
        tasks = scheduler.list_tasks(uid)
        if not tasks:
            await update.message.reply_text(
                "⏰ *Scheduled Tasks*\n\nNo tasks.\n\n"
                "Usage:\n`/schedule 9:00 Check emails`\n`/schedule clear`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            task_list = "\n".join([f"• {t['hour']:02d}:{t['minute']:02d} - {t['command']}" for t in tasks])
            await update.message.reply_text(
                f"⏰ *Scheduled Tasks*\n\n{task_list}\n\n`/schedule clear` to remove all",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    if ctx.args[0] == "clear":
        scheduler.clear_tasks(uid)
        await update.message.reply_text("⏰ All tasks cleared")
        return
    
    time_str = ctx.args[0]
    command = " ".join(ctx.args[1:])
    
    if scheduler.add_task(uid, time_str, command):
        await update.message.reply_text(f"⏰ Scheduled: `{time_str}` → {command}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Invalid time format. Use HH:MM (e.g., 9:00 or 14:30)")


async def undo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /undo command."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    count = 1
    if ctx.args:
        try:
            count = min(10, max(1, int(ctx.args[0])))
        except:
            pass
    
    for i in range(count):
        undo_stack.push(uid, f"undo_{i}")
        await send_cmd(uid, {"type": "undo"})
    
    await update.message.reply_text(f"↩️ Undid {count} change(s)")


async def scroll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /scroll command."""
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    direction = sanitize_input(ctx.args[0] if ctx.args else "down", 10)
    if direction not in ["up", "down", "top", "bottom"]:
        direction = "down"
    await send_cmd(uid, {"type": "scroll", "direction": direction})
    await update.message.reply_text(f"📜 Scrolled {direction}")


async def accept_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /accept command."""
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    undo_stack.push(uid, "accept")
    await send_cmd(uid, {"type": "accept"})
    await update.message.reply_text("✅ Accepted")


async def reject_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /reject command."""
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    await send_cmd(uid, {"type": "reject"})
    await update.message.reply_text("❌ Rejected")


async def tts_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /tts command - text-to-speech."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    text = ai_responses.get(uid, "")
    
    if not text:
        await update.message.reply_text("🗣️ No recent AI response to read")
        return
    
    if uid in connected_clients:
        await send_cmd(uid, {"type": "tts", "text": text[:500]})
        await update.message.reply_text("🗣️ Speaking...")
    else:
        await update.message.reply_text("🔴 Not connected")


async def quick_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /quick command - show quick action buttons."""
    if not await check_rate_limit(update):
        return
    keyboard = [
        [InlineKeyboardButton("✅ Accept", callback_data="q_accept"), 
         InlineKeyboardButton("❌ Reject", callback_data="q_reject")],
        [InlineKeyboardButton("📸 Screenshot", callback_data="q_ss"),
         InlineKeyboardButton("📺 Stream", callback_data="q_stream")],
        [InlineKeyboardButton("📋 Diff", callback_data="q_diff"),
         InlineKeyboardButton("↩️ Undo", callback_data="q_undo")],
    ]
    await update.message.reply_text("⚡ Quick Actions:", reply_markup=InlineKeyboardMarkup(keyboard))


MODELS = ["Gemini 3 Pro", "Gemini 3 Flash", "Claude Sonnet 4.5", "GPT-OSS 120B"]


async def model_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /model command - switch AI model."""
    if not await check_rate_limit(update):
        return
    keyboard = [[InlineKeyboardButton(m, callback_data=f"m_{m}")] for m in MODELS]
    await update.message.reply_text("🤖 Select model:", reply_markup=InlineKeyboardMarkup(keyboard))


async def watchdog_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /watchdog command - toggle watchdog."""
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    if ctx.args and ctx.args[0].lower() == "off":
        await send_cmd(uid, {"type": "watchdog", "enabled": False})
        await update.message.reply_text("🐕 Watchdog stopped")
        return
    
    await send_cmd(uid, {"type": "watchdog", "enabled": True})
    await update.message.reply_text("🐕 Watchdog started! You'll get alerts when AI needs input.")


async def pause_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /pause command."""
    uid = str(update.effective_user.id)
    get_user_state(uid)["paused"] = True
    await update.message.reply_text("⏸️ Paused")


async def resume_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /resume command."""
    uid = str(update.effective_user.id)
    get_user_state(uid)["paused"] = False
    await update.message.reply_text("▶️ Resumed")


# ============ Callback Query Handler ============

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks."""
    query = update.callback_query
    await query.answer()
    uid = str(update.effective_user.id)
    
    if not rate_limiter.is_allowed(uid):
        return
    
    if uid not in connected_clients:
        await query.message.reply_text("🔴 Not connected")
        return
    
    data = query.data
    
    if data == "q_ss":
        resp = await send_cmd(uid, {"type": "screenshot", "quality": 70})
        if resp and resp.get("image"):
            await ctx.bot.send_photo(chat_id=update.effective_chat.id, photo=base64.b64decode(resp["image"]))
    elif data == "q_accept":
        undo_stack.push(uid, "accept")
        await send_cmd(uid, {"type": "accept"})
        await query.message.reply_text("✅ Accepted")
    elif data == "q_reject":
        await send_cmd(uid, {"type": "reject"})
        await query.message.reply_text("❌ Rejected")
    elif data == "q_undo":
        await send_cmd(uid, {"type": "undo"})
        await query.message.reply_text("↩️ Undone")
    elif data == "q_stream":
        host = os.environ.get("RENDER_EXTERNAL_URL", f"http://localhost:{config.PORT}")
        await send_cmd(uid, {"type": "start_stream", "fps": 2})
        live_stream.start_stream(uid)
        await query.message.reply_text(f"📺 Stream: {host}/stream/{uid}")
    elif data == "q_diff":
        resp = await send_cmd(uid, {"type": "get_diff"})
        if resp and resp.get("diff"):
            await query.message.reply_text(f"```diff\n{sanitize_input(resp['diff'], 3500)}\n```", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.message.reply_text("📋 No pending changes")
    elif data == "q_tts":
        text = ai_responses.get(uid, "")
        if text:
            await send_cmd(uid, {"type": "tts", "text": text[:500]})
            await query.message.reply_text("🗣️ Speaking...")
    elif data.startswith("q_"):
        text = data[2:].capitalize()
        await send_cmd(uid, {"type": "relay", "text": text})
    elif data.startswith("m_"):
        model = data[2:]
        await send_cmd(uid, {"type": "model", "model": model})
        await query.message.reply_text(f"🔄 Switching to {model}...")


# ============ Message Handlers ============

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle text messages."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    st = get_user_state(uid)
    text = update.message.text
    
    # Handle mini keyboard buttons
    if text == "📸 Status":
        return await status_cmd(update, ctx)
    elif text == "✅ Accept":
        return await accept_cmd(update, ctx)
    elif text == "❌ Reject":
        return await reject_cmd(update, ctx)
    elif text == "⬆️ Scroll Up":
        ctx.args = ["up"]
        return await scroll_cmd(update, ctx)
    elif text == "⬇️ Scroll Down":
        ctx.args = ["down"]
        return await scroll_cmd(update, ctx)
    elif text == "↩️ Undo":
        return await undo_cmd(update, ctx)
    
    if st.get("paused"):
        await update.message.reply_text("⏸️ Paused. /resume")
        return
    if uid not in connected_clients:
        await update.message.reply_text(f"🔴 Not connected\nID: `{uid}`", parse_mode=ParseMode.MARKDOWN)
        return
    
    text = sanitize_input(text)
    undo_stack.push(uid, f"msg:{text[:20]}")
    
    msg = await update.message.reply_text("📤 Sending...")
    resp = await send_cmd(uid, {"type": "relay", "text": text})
    if resp and resp.get("success"):
        keyboard = [[
            InlineKeyboardButton("📸 Screenshot", callback_data="q_ss"),
            InlineKeyboardButton("✅ Accept", callback_data="q_accept"),
        ]]
        await msg.edit_text("✅ Sent! Waiting for AI response...", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await msg.edit_text("❌ Failed")


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages."""
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    msg = await update.message.reply_text("👁️ Processing...")
    photo_file = await update.message.photo[-1].get_file()
    data = await photo_file.download_as_bytearray()
    b64_data = base64.b64encode(data).decode()
    
    resp = await send_cmd(uid, {"type": "photo", "data": b64_data})
    if resp and resp.get("success"):
        await msg.edit_text("✅ Photo sent to AI")
    else:
        await msg.edit_text("❌ Failed")


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages."""
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return

    msg = await update.message.reply_text("🎙️ Processing...")
    voice_file = await update.message.voice.get_file()
    data = await voice_file.download_as_bytearray()
    b64_data = base64.b64encode(data).decode()
    
    resp = await send_cmd(uid, {"type": "voice", "data": b64_data, "format": "ogg"})
    if resp and resp.get("success"):
        await msg.edit_text(f"✅ Voice: \"{resp.get('text', 'Sent')}\"")
    else:
        await msg.edit_text("❌ Failed")


async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle document messages."""
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return

    doc = update.message.document
    if doc.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("❌ File too large (max 20MB)")
        return

    msg = await update.message.reply_text(f"📂 Sending {doc.file_name}...")
    doc_file = await doc.get_file()
    data = await doc_file.download_as_bytearray()
    b64_data = base64.b64encode(data).decode()
    
    resp = await send_cmd(uid, {"type": "file", "data": b64_data, "name": doc.file_name})
    if resp and resp.get("success"):
        await msg.edit_text(f"✅ Saved: {resp.get('path', 'disk')}")
    else:
        await msg.edit_text("❌ Failed")
