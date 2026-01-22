"""
Main entry point for Antigravity Remote Server.

Runs both FastAPI WebSocket server and Telegram bot.
"""

import asyncio
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Check for required env vars
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN environment variable is required!")
    logger.error("Set it in Render dashboard under Environment Variables")
    sys.exit(1)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode
import uvicorn
import base64
import json
from datetime import datetime
from typing import Dict, Optional
from contextlib import asynccontextmanager
import threading

# Connected clients: user_id -> WebSocket
connected_clients: Dict[str, WebSocket] = {}
pending_responses: Dict[str, dict] = {}


# ============ FastAPI App ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Server starting...")
    yield
    logger.info("👋 Server shutting down...")


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
    logger.info(f"✅ Client connected: {user_id}")
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_id = message.get("message_id")
            if msg_id and msg_id in pending_responses:
                pending_responses[msg_id]["data"] = message
                pending_responses[msg_id]["event"].set()
    except WebSocketDisconnect:
        logger.info(f"❌ Client disconnected: {user_id}")
    finally:
        if user_id in connected_clients:
            del connected_clients[user_id]


async def send_command(user_id: str, command: dict, timeout: float = 30.0) -> Optional[dict]:
    if user_id not in connected_clients:
        return None
    
    ws = connected_clients[user_id]
    msg_id = f"{user_id}_{datetime.utcnow().timestamp()}"
    command["message_id"] = msg_id
    
    event = asyncio.Event()
    pending_responses[msg_id] = {"event": event, "data": None}
    
    try:
        await ws.send_text(json.dumps(command))
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return pending_responses[msg_id]["data"]
    except asyncio.TimeoutError:
        return None
    finally:
        pending_responses.pop(msg_id, None)


# ============ Telegram Bot ============

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    status = "🟢 Connected" if user_id in connected_clients else "🔴 Not connected"
    await update.message.reply_text(
        f"🚀 *Antigravity Remote*\n\nID: `{user_id}`\nStatus: {status}\n\n"
        f"1. `pip install antigravity-remote`\n"
        f"2. `antigravity-remote --register`\n"
        f"3. `antigravity-remote`",
        parse_mode=ParseMode.MARKDOWN
    )


async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in connected_clients:
        await update.message.reply_text("🔴 Not connected. Run `antigravity-remote` first.")
        return
    
    msg = await update.message.reply_text("📸 Capturing...")
    resp = await send_command(user_id, {"type": "screenshot"})
    
    if resp and resp.get("image"):
        await ctx.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=base64.b64decode(resp["image"])
        )
        await msg.delete()
    else:
        await msg.edit_text("❌ Failed")


async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in connected_clients:
        await update.message.reply_text(f"🔴 Not connected\n\nID: `{user_id}`", parse_mode=ParseMode.MARKDOWN)
        return
    
    msg = await update.message.reply_text("📤 Sending...")
    resp = await send_command(user_id, {"type": "relay", "text": update.message.text})
    
    if resp and resp.get("success"):
        await msg.edit_text("✅ Sent!")
    else:
        await msg.edit_text("❌ Failed")


def run_api():
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🌐 API on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


async def run_bot():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))
    
    logger.info("🤖 Starting Telegram bot...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    while True:
        await asyncio.sleep(1)


async def main():
    # Run API in background thread
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    
    # Run bot in main loop
    await run_bot()


if __name__ == "__main__":
    asyncio.run(main())
