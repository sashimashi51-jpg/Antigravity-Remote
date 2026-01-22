"""
Antigravity Remote Server - Main Entry Point
"""

import asyncio
import logging
import os
import sys
import traceback

# Setup logging FIRST
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("Starting Antigravity Remote Server...")
logger.info("=" * 50)

# Check env var
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 10000))

logger.info(f"PORT: {PORT}")
logger.info(f"BOT_TOKEN set: {'Yes' if BOT_TOKEN else 'NO - MISSING!'}")

if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN is NOT SET!")
    logger.error("Set it in Render Environment Variables")

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from telegram.constants import ParseMode
    import uvicorn
    import base64
    import json
    from datetime import datetime
    from typing import Dict, Optional
    from contextlib import asynccontextmanager
    import threading
    logger.info("All imports successful!")
except Exception as e:
    logger.error(f"Import error: {e}")
    traceback.print_exc()
    sys.exit(1)

# Connected clients
connected_clients: Dict[str, WebSocket] = {}
pending_responses: Dict[str, dict] = {}

# ============ FastAPI ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI lifespan starting...")
    yield
    logger.info("FastAPI lifespan ending...")

app = FastAPI(title="Antigravity Remote", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "online", "clients": len(connected_clients), "bot": bool(BOT_TOKEN)}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    connected_clients[user_id] = websocket
    logger.info(f"Client connected: {user_id}")
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_id = msg.get("message_id")
            if msg_id and msg_id in pending_responses:
                pending_responses[msg_id]["data"] = msg
                pending_responses[msg_id]["event"].set()
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {user_id}")
    finally:
        connected_clients.pop(user_id, None)

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

# ============ Telegram Bot ============

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    status = "🟢 Connected" if uid in connected_clients else "🔴 Not connected"
    await update.message.reply_text(
        f"🚀 *Antigravity Remote*\n\n"
        f"ID: `{uid}`\nStatus: {status}\n\n"
        f"*Commands:*\n"
        f"/status - Screenshot\n"
        f"/scroll up|down - Scroll\n"
        f"/accept - Accept (Alt+Enter)\n"
        f"/reject - Reject (Escape)\n"
        f"/key ctrl+s - Key combo\n"
        f"/quick - Quick buttons\n"
        f"Or just type a message!",
        parse_mode=ParseMode.MARKDOWN
    )

async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text(f"🔴 Not connected\n\nID: `{uid}`", parse_mode=ParseMode.MARKDOWN)
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
    
    args = ctx.args
    direction = "down"
    if args and args[0].lower() in ["up", "down", "top", "bottom"]:
        direction = args[0].lower()
    
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

async def key_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: /key ctrl+s")
        return
    
    combo = args[0]
    resp = await send_cmd(uid, {"type": "key", "combo": combo})
    await update.message.reply_text(f"⌨️ Sent: `{combo}`" if resp else "❌ Failed", parse_mode=ParseMode.MARKDOWN)

async def quick_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await query.message.reply_text("🔴 Not connected")
        return
    
    data = query.data
    
    if data == "quick_screenshot":
        resp = await send_cmd(uid, {"type": "screenshot"})
        if resp and resp.get("image"):
            await ctx.bot.send_photo(chat_id=update.effective_chat.id, photo=base64.b64decode(resp["image"]))
    else:
        text = data.replace("quick_", "").capitalize()
        resp = await send_cmd(uid, {"type": "relay", "text": text})
        await query.message.reply_text(f"📤 Sent: {text}" if resp else "❌ Failed")

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text(f"🔴 Not connected\n\nID: `{uid}`", parse_mode=ParseMode.MARKDOWN)
        return
    msg = await update.message.reply_text("📤 Sending...")
    resp = await send_cmd(uid, {"type": "relay", "text": update.message.text})
    if resp and resp.get("success"):
        keyboard = [[InlineKeyboardButton("📸 Screenshot", callback_data="quick_screenshot")]]
        await msg.edit_text("✅ Sent!", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await msg.edit_text("❌ Failed")

def run_api():
    logger.info(f"Starting API on port {PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")

async def run_bot():
    if not BOT_TOKEN:
        logger.warning("No bot token - bot disabled")
        while True:
            await asyncio.sleep(60)
        return
    
    logger.info("Starting Telegram bot...")
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add all handlers
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("scroll", scroll_cmd))
    application.add_handler(CommandHandler("accept", accept_cmd))
    application.add_handler(CommandHandler("reject", reject_cmd))
    application.add_handler(CommandHandler("key", key_cmd))
    application.add_handler(CommandHandler("quick", quick_cmd))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("Bot running!")
    
    while True:
        await asyncio.sleep(1)

async def main():
    logger.info("Starting main...")
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    logger.info("API thread started")
    await run_bot()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)
