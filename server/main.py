"""
Antigravity Remote Server - FULL VERSION
All commands implemented
"""

import asyncio
import logging
import os
import sys
import traceback
import base64
import json
from datetime import datetime
from typing import Dict, Optional
from contextlib import asynccontextmanager
import threading

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("Starting Antigravity Remote Server - FULL VERSION")
logger.info("=" * 50)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 10000))

logger.info(f"PORT: {PORT}")
logger.info(f"BOT_TOKEN set: {'Yes' if BOT_TOKEN else 'NO!'}")

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from telegram.constants import ParseMode
    import uvicorn
    logger.info("All imports successful!")
except Exception as e:
    logger.error(f"Import error: {e}")
    sys.exit(1)

# State
connected_clients: Dict[str, WebSocket] = {}
pending_responses: Dict[str, dict] = {}
user_state: Dict[str, dict] = {}  # Per-user state (paused, locked, etc.)
watchdog_tasks: Dict[str, asyncio.Task] = {}
bot_application = None  # Store bot application for alerts

# ============ FastAPI ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI starting...")
    yield

app = FastAPI(title="Antigravity Remote", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "online", "clients": len(connected_clients)}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    connected_clients[user_id] = websocket
    if user_id not in user_state:
        user_state[user_id] = {"paused": False, "locked": False, "lock_pw": "unlock123"}
    logger.info(f"Client connected: {user_id}")
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_id = msg.get("message_id")
            msg_type = msg.get("type")
            
            # Handle alerts from agent (watchdog)
            if msg_type == "alert":
                await handle_agent_alert(user_id, msg)
            elif msg_id and msg_id in pending_responses:
                pending_responses[msg_id]["data"] = msg
                pending_responses[msg_id]["event"].set()
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {user_id}")
    finally:
        connected_clients.pop(user_id, None)
        if user_id in watchdog_tasks:
            watchdog_tasks[user_id].cancel()
            del watchdog_tasks[user_id]

async def handle_agent_alert(user_id: str, msg: dict):
    """Handle alerts from local agent (watchdog detections)."""
    global bot_application
    if not bot_application:
        return
    
    alert_type = msg.get("alert_type", "info")
    text = msg.get("text", "Alert")
    image = msg.get("image")
    
    try:
        if image:
            await bot_application.bot.send_photo(
                chat_id=int(user_id),
                photo=base64.b64decode(image),
                caption=text,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await bot_application.bot.send_message(
                chat_id=int(user_id),
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Alert error: {e}")

async def send_cmd(user_id: str, cmd: dict, timeout: float = 30.0) -> Optional[dict]:
    if user_id not in connected_clients:
        return None
    ws = connected_clients[user_id]
    msg_id = f"{user_id}_{datetime.utcnow().timestamp()}"
    cmd["message_id"] = msg_id
    event = asyncio.Event()
    pending_responses[msg_id] = {"event": event, "data": None}
    try:
        await ws.send_text(json.dumps(cmd))
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return pending_responses[msg_id]["data"]
    except:
        return None
    finally:
        pending_responses.pop(msg_id, None)

# ============ Telegram Handlers ============

def get_user_state(uid: str) -> dict:
    if uid not in user_state:
        user_state[uid] = {"paused": False, "locked": False, "lock_pw": "unlock123"}
    return user_state[uid]

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    st = get_user_state(uid)
    status = "🟢 Connected" if uid in connected_clients else "🔴 Not connected"
    wd = "🐕 Active" if uid in watchdog_tasks else "💤 Off"
    await update.message.reply_text(
        f"🚀 *Antigravity Remote*\n\n"
        f"ID: `{uid}`\nStatus: {status}\nWatchdog: {wd}\n\n"
        f"*Commands:*\n"
        f"/status /scroll /accept /reject\n"
        f"/key /quick /model /summary\n"
        f"/watchdog /pause /resume\n"
        f"/undo /cancel /sysinfo /files",
        parse_mode=ParseMode.MARKDOWN
    )

async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text(f"🔴 Not connected\nID: `{uid}`", parse_mode=ParseMode.MARKDOWN)
        return
    msg = await update.message.reply_text("📸 Capturing...")
    resp = await send_cmd(uid, {"type": "screenshot"})
    if resp and resp.get("image"):
        await ctx.bot.send_photo(chat_id=update.effective_chat.id, photo=base64.b64decode(resp["image"]))
        await msg.delete()
    else:
        await msg.edit_text("❌ Failed")

async def scroll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    direction = ctx.args[0].lower() if ctx.args else "down"
    resp = await send_cmd(uid, {"type": "scroll", "direction": direction})
    await update.message.reply_text(f"📜 Scrolled {direction}" if resp else "❌ Failed")

async def accept_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    resp = await send_cmd(uid, {"type": "accept"})
    await update.message.reply_text("✅ Accept sent" if resp else "❌ Failed")

async def reject_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    resp = await send_cmd(uid, {"type": "reject"})
    await update.message.reply_text("❌ Reject sent" if resp else "❌ Failed")

async def undo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    resp = await send_cmd(uid, {"type": "undo"})
    await update.message.reply_text("↩️ Undo sent" if resp else "❌ Failed")

async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    resp = await send_cmd(uid, {"type": "cancel"})
    await update.message.reply_text("🛑 Cancel sent" if resp else "❌ Failed")

async def key_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /key ctrl+s")
        return
    combo = ctx.args[0]
    resp = await send_cmd(uid, {"type": "key", "combo": combo})
    await update.message.reply_text(f"⌨️ Sent: `{combo}`" if resp else "❌ Failed", parse_mode=ParseMode.MARKDOWN)

async def quick_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ Yes", callback_data="q_yes"), InlineKeyboardButton("❌ No", callback_data="q_no")],
        [InlineKeyboardButton("▶️ Proceed", callback_data="q_proceed"), InlineKeyboardButton("⏹️ Cancel", callback_data="q_cancel")],
        [InlineKeyboardButton("📸 Screenshot", callback_data="q_ss")],
    ]
    await update.message.reply_text("⚡ *Quick:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

MODELS = ["Gemini 3 Pro", "Gemini 3 Flash", "Claude Sonnet 4.5", "Claude Opus 4.5", "GPT-OSS 120B"]

async def model_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(m, callback_data=f"m_{m}")] for m in MODELS]
    await update.message.reply_text("🤖 *Select model:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def summary_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    resp = await send_cmd(uid, {"type": "relay", "text": "Please give me a brief summary of what you just did."})
    keyboard = [[InlineKeyboardButton("📸 Get Result", callback_data="q_ss")]]
    await update.message.reply_text("📝 Summary requested!", reply_markup=InlineKeyboardMarkup(keyboard))

async def watchdog_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    if ctx.args and ctx.args[0].lower() == "off":
        resp = await send_cmd(uid, {"type": "watchdog", "enabled": False})
        if uid in watchdog_tasks:
            watchdog_tasks[uid].cancel()
            del watchdog_tasks[uid]
        await update.message.reply_text("🐕 Watchdog stopped")
        return
    
    resp = await send_cmd(uid, {"type": "watchdog", "enabled": True})
    await update.message.reply_text(
        "🐕 *Watchdog started!*\n\n"
        "Alerts for:\n• 🚨 Approval needed\n• ✅ Task complete\n• ⚠️ Errors\n• 💤 Idle\n\n"
        "`/watchdog off` to stop",
        parse_mode=ParseMode.MARKDOWN
    )

async def pause_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    get_user_state(uid)["paused"] = True
    await update.message.reply_text("⏸️ Paused. /resume to continue.")

async def resume_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    get_user_state(uid)["paused"] = False
    await update.message.reply_text("▶️ Resumed!")

async def sysinfo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    resp = await send_cmd(uid, {"type": "sysinfo"})
    if resp and resp.get("info"):
        await update.message.reply_text(f"⚙️ *System:*\n```\n{resp['info']}\n```", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Failed")

async def files_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    resp = await send_cmd(uid, {"type": "files"})
    if resp and resp.get("files"):
        await update.message.reply_text(f"📂 *Files:*\n{resp['files']}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Failed")

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = str(update.effective_user.id)
    
    if uid not in connected_clients:
        await query.message.reply_text("🔴 Not connected")
        return
    
    data = query.data
    
    if data == "q_ss":
        resp = await send_cmd(uid, {"type": "screenshot"})
        if resp and resp.get("image"):
            await ctx.bot.send_photo(chat_id=update.effective_chat.id, photo=base64.b64decode(resp["image"]))
    elif data.startswith("q_"):
        text = data[2:].capitalize()
        await send_cmd(uid, {"type": "relay", "text": text})
        await query.message.reply_text(f"📤 Sent: {text}")
    elif data.startswith("m_"):
        model = data[2:]
        await send_cmd(uid, {"type": "model", "model": model})
        await query.message.reply_text(f"🔄 Switching to {model}...")

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    st = get_user_state(uid)
    
    if st.get("locked"):
        await update.message.reply_text("🔒 Locked")
        return
    if st.get("paused"):
        await update.message.reply_text("⏸️ Paused. /resume")
        return
    if uid not in connected_clients:
        await update.message.reply_text(f"🔴 Not connected\nID: `{uid}`", parse_mode=ParseMode.MARKDOWN)
        return
    
    msg = await update.message.reply_text("📤 Sending...")
    resp = await send_cmd(uid, {"type": "relay", "text": update.message.text})
    if resp and resp.get("success"):
        keyboard = [[InlineKeyboardButton("📸 Screenshot", callback_data="q_ss")]]
        await msg.edit_text("✅ Sent!", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await msg.edit_text("❌ Failed")

# ============ Main ============

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")

async def run_bot():
    global bot_application
    if not BOT_TOKEN:
        logger.warning("No bot token")
        while True:
            await asyncio.sleep(60)
        return
    
    bot_application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    handlers = [
        ("start", start_cmd), ("status", status_cmd), ("scroll", scroll_cmd),
        ("accept", accept_cmd), ("reject", reject_cmd), ("undo", undo_cmd),
        ("cancel", cancel_cmd), ("key", key_cmd), ("quick", quick_cmd),
        ("model", model_cmd), ("summary", summary_cmd), ("watchdog", watchdog_cmd),
        ("pause", pause_cmd), ("resume", resume_cmd), ("sysinfo", sysinfo_cmd),
        ("files", files_cmd),
    ]
    for cmd, handler in handlers:
        bot_application.add_handler(CommandHandler(cmd, handler))
    
    bot_application.add_handler(CallbackQueryHandler(button_handler))
    bot_application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))
    
    await bot_application.initialize()
    await bot_application.start()
    await bot_application.updater.start_polling()
    logger.info("Bot running - FULL VERSION!")
    
    while True:
        await asyncio.sleep(1)

async def main():
    threading.Thread(target=run_api, daemon=True).start()
    await run_bot()

if __name__ == "__main__":
    asyncio.run(main())
