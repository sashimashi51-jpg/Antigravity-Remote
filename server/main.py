"""
Antigravity Remote Server - SECURE VERSION
All security measures implemented
"""

import asyncio
import logging
import os
import sys
import traceback
import base64
import json
import hashlib
import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Set
from contextlib import asynccontextmanager
from collections import defaultdict
import threading
import re

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("Antigravity Remote Server - SECURE VERSION")
logger.info("=" * 50)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 10000))
AUTH_SECRET = os.environ.get("AUTH_SECRET", "antigravity-remote-2026")  # Server-side secret

logger.info(f"PORT: {PORT}")
logger.info(f"BOT_TOKEN set: {'Yes' if BOT_TOKEN else 'NO!'}")

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from telegram.constants import ParseMode
    import uvicorn
    logger.info("All imports successful!")
except Exception as e:
    logger.error(f"Import error: {e}")
    sys.exit(1)

# ============ Security Components ============

class RateLimiter:
    """Rate limiting per user."""
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: Dict[str, list] = defaultdict(list)
    
    def is_allowed(self, user_id: str) -> bool:
        now = time.time()
        # Clean old requests
        self.requests[user_id] = [t for t in self.requests[user_id] if now - t < self.window]
        
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        
        self.requests[user_id].append(now)
        return True
    
    def get_wait_time(self, user_id: str) -> int:
        if not self.requests[user_id]:
            return 0
        oldest = min(self.requests[user_id])
        return max(0, int(self.window - (time.time() - oldest)))


class SessionManager:
    """Session management with expiry."""
    def __init__(self, expiry_hours: int = 24):
        self.sessions: Dict[str, dict] = {}
        self.expiry = timedelta(hours=expiry_hours)
    
    def create_session(self, user_id: str, auth_token: str) -> str:
        session_id = secrets.token_urlsafe(32)
        self.sessions[session_id] = {
            "user_id": user_id,
            "auth_token": auth_token,
            "created": datetime.utcnow(),
            "last_active": datetime.utcnow()
        }
        return session_id
    
    def validate_session(self, session_id: str) -> Optional[str]:
        if session_id not in self.sessions:
            return None
        
        session = self.sessions[session_id]
        if datetime.utcnow() - session["created"] > self.expiry:
            del self.sessions[session_id]
            return None
        
        session["last_active"] = datetime.utcnow()
        return session["user_id"]
    
    def cleanup_expired(self):
        now = datetime.utcnow()
        expired = [sid for sid, s in self.sessions.items() if now - s["created"] > self.expiry]
        for sid in expired:
            del self.sessions[sid]


class AuditLogger:
    """Audit logging for commands."""
    def __init__(self, max_entries: int = 1000):
        self.logs: list = []
        self.max_entries = max_entries
    
    def log(self, user_id: str, action: str, details: str = ""):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id[-4:] if len(user_id) > 4 else "****",  # Only last 4 digits
            "action": action,
            "details": details[:100] if details else ""  # Truncate
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_entries:
            self.logs = self.logs[-self.max_entries:]
        logger.info(f"AUDIT: {entry['user_id']} - {action}")


def generate_auth_token(user_id: str) -> str:
    """Generate stable auth token for user (doesn't change)."""
    data = f"{user_id}:{AUTH_SECRET}"
    return hashlib.sha256(data.encode()).hexdigest()[:32]


def validate_auth_token(user_id: str, token: str) -> bool:
    """Validate auth token."""
    expected = generate_auth_token(user_id)
    return secrets.compare_digest(token, expected)


def sanitize_input(text: str, max_length: int = 4000) -> str:
    """Sanitize user input."""
    if not text:
        return ""
    # Remove control characters except newlines/tabs
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Limit length
    return text[:max_length]


def safe_error_message(error: Exception) -> str:
    """Return generic error message."""
    return "An error occurred. Please try again."


# Initialize security components
rate_limiter = RateLimiter(max_requests=30, window_seconds=60)
session_manager = SessionManager(expiry_hours=24)
audit_logger = AuditLogger()

# State
connected_clients: Dict[str, WebSocket] = {}
pending_responses: Dict[str, dict] = {}
user_state: Dict[str, dict] = {}
bot_application = None

# ============ FastAPI ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI starting (SECURE)...")
    # Cleanup task
    async def cleanup_loop():
        while True:
            await asyncio.sleep(3600)
            session_manager.cleanup_expired()
    asyncio.create_task(cleanup_loop())
    yield

app = FastAPI(title="Antigravity Remote (Secure)", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "online", "clients": len(connected_clients), "secure": True}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    
    # Wait for auth message
    try:
        auth_data = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        auth = json.loads(auth_data)
        auth_token = auth.get("auth_token", "")
        
        # Validate
        if not validate_auth_token(user_id, auth_token):
            audit_logger.log(user_id, "AUTH_FAILED", "Invalid token")
            await websocket.send_text(json.dumps({"error": "Authentication failed"}))
            await websocket.close(code=4001)
            return
        
        # Send success response
        await websocket.send_text(json.dumps({"status": "authenticated"}))
        audit_logger.log(user_id, "CONNECTED")
        
    except asyncio.TimeoutError:
        await websocket.close(code=4002)
        return
    except Exception:
        await websocket.close(code=4003)
        return
    
    connected_clients[user_id] = websocket
    if user_id not in user_state:
        user_state[user_id] = {"paused": False, "locked": False}
    
    logger.info(f"Client authenticated: {user_id[-4:]}")
    
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_id = msg.get("message_id")
            msg_type = msg.get("type")
            
            if msg_type == "alert":
                await handle_agent_alert(user_id, msg)
            elif msg_id and msg_id in pending_responses:
                pending_responses[msg_id]["data"] = msg
                pending_responses[msg_id]["event"].set()
                
    except WebSocketDisconnect:
        audit_logger.log(user_id, "DISCONNECTED")
    finally:
        connected_clients.pop(user_id, None)

async def handle_agent_alert(user_id: str, msg: dict):
    global bot_application
    if not bot_application:
        return
    try:
        text = sanitize_input(msg.get("text", "Alert"))
        image = msg.get("image")
        if image:
            await bot_application.bot.send_photo(
                chat_id=int(user_id), photo=base64.b64decode(image),
                caption=text, parse_mode=ParseMode.MARKDOWN
            )
        else:
            await bot_application.bot.send_message(
                chat_id=int(user_id), text=text, parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Alert error: {safe_error_message(e)}")

async def send_cmd(user_id: str, cmd: dict, timeout: float = 30.0) -> Optional[dict]:
    if user_id not in connected_clients:
        return None
    
    # Rate limit check
    if not rate_limiter.is_allowed(user_id):
        return {"error": "rate_limited", "wait": rate_limiter.get_wait_time(user_id)}
    
    ws = connected_clients[user_id]
    msg_id = f"{user_id}_{datetime.utcnow().timestamp()}"
    cmd["message_id"] = msg_id
    event = asyncio.Event()
    pending_responses[msg_id] = {"event": event, "data": None}
    
    try:
        await ws.send_text(json.dumps(cmd))
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return pending_responses[msg_id]["data"]
    except Exception:
        return None
    finally:
        pending_responses.pop(msg_id, None)

# ============ Telegram Handlers ============

def get_user_state(uid: str) -> dict:
    if uid not in user_state:
        user_state[uid] = {"paused": False, "locked": False}
    return user_state[uid]

async def check_rate_limit(update: Update) -> bool:
    uid = str(update.effective_user.id)
    if not rate_limiter.is_allowed(uid):
        wait = rate_limiter.get_wait_time(uid)
        await update.message.reply_text(f"⏳ Rate limited. Wait {wait}s")
        return False
    return True

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    status = "🟢 Connected" if uid in connected_clients else "🔴 Not connected"
    
    # Generate auth token for user
    auth_token = generate_auth_token(uid)
    
    audit_logger.log(uid, "START")
    
    await update.message.reply_text(
        f"🔐 *Antigravity Remote (Secure)*\n\n"
        f"ID: `{uid}`\n"
        f"Status: {status}\n"
        f"Auth Token: `{auth_token}`\n\n"
        f"*Setup:*\n"
        f"`pip install antigravity-remote`\n"
        f"`antigravity-remote --register`\n"
        f"Enter ID + Token when prompted",
        parse_mode=ParseMode.MARKDOWN
    )

async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text(f"🔴 Not connected\nID: `{uid}`", parse_mode=ParseMode.MARKDOWN)
        return
    
    audit_logger.log(uid, "STATUS")
    msg = await update.message.reply_text("📸 Capturing...")
    
    resp = await send_cmd(uid, {"type": "screenshot"})
    if resp and resp.get("error") == "rate_limited":
        await msg.edit_text(f"⏳ Rate limited. Wait {resp.get('wait', 60)}s")
    elif resp and resp.get("image"):
        await ctx.bot.send_photo(chat_id=update.effective_chat.id, photo=base64.b64decode(resp["image"]))
        await msg.delete()
    else:
        await msg.edit_text("❌ Failed")

async def scroll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    direction = sanitize_input(ctx.args[0] if ctx.args else "down", 10)
    if direction not in ["up", "down", "top", "bottom"]:
        direction = "down"
    audit_logger.log(uid, "SCROLL", direction)
    resp = await send_cmd(uid, {"type": "scroll", "direction": direction})
    await update.message.reply_text(f"📜 Scrolled {direction}" if resp else "❌ Failed")

async def accept_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    audit_logger.log(uid, "ACCEPT")
    resp = await send_cmd(uid, {"type": "accept"})
    await update.message.reply_text("✅ Accept sent" if resp else "❌ Failed")

async def reject_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    audit_logger.log(uid, "REJECT")
    resp = await send_cmd(uid, {"type": "reject"})
    await update.message.reply_text("❌ Reject sent" if resp else "❌ Failed")

async def undo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    audit_logger.log(uid, "UNDO")
    resp = await send_cmd(uid, {"type": "undo"})
    await update.message.reply_text("↩️ Undo sent" if resp else "❌ Failed")

async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    audit_logger.log(uid, "CANCEL")
    resp = await send_cmd(uid, {"type": "cancel"})
    await update.message.reply_text("🛑 Cancel sent" if resp else "❌ Failed")

async def key_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /key ctrl+s")
        return
    combo = sanitize_input(ctx.args[0], 50)
    # Validate combo format
    if not re.match(r'^[a-z0-9+]+$', combo.lower()):
        await update.message.reply_text("Invalid key combo")
        return
    audit_logger.log(uid, "KEY", combo)
    resp = await send_cmd(uid, {"type": "key", "combo": combo})
    await update.message.reply_text(f"⌨️ Sent: `{combo}`" if resp else "❌ Failed", parse_mode=ParseMode.MARKDOWN)

async def quick_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    keyboard = [
        [InlineKeyboardButton("✅ Yes", callback_data="q_yes"), InlineKeyboardButton("❌ No", callback_data="q_no")],
        [InlineKeyboardButton("▶️ Proceed", callback_data="q_proceed"), InlineKeyboardButton("⏹️ Cancel", callback_data="q_cancel")],
        [InlineKeyboardButton("📸 Screenshot", callback_data="q_ss")],
    ]
    await update.message.reply_text("⚡ *Quick:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

MODELS = ["Gemini 3 Pro", "Gemini 3 Flash", "Claude Sonnet 4.5", "Claude Opus 4.5", "GPT-OSS 120B"]

async def model_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    keyboard = [[InlineKeyboardButton(m, callback_data=f"m_{m}")] for m in MODELS]
    await update.message.reply_text("🤖 *Select model:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def summary_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    audit_logger.log(uid, "SUMMARY")
    await send_cmd(uid, {"type": "relay", "text": "Please give me a brief summary of what you just did."})
    keyboard = [[InlineKeyboardButton("📸 Get Result", callback_data="q_ss")]]
    await update.message.reply_text("📝 Summary requested!", reply_markup=InlineKeyboardMarkup(keyboard))

async def watchdog_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    if ctx.args and ctx.args[0].lower() == "off":
        audit_logger.log(uid, "WATCHDOG_OFF")
        await send_cmd(uid, {"type": "watchdog", "enabled": False})
        await update.message.reply_text("🐕 Watchdog stopped")
        return
    
    audit_logger.log(uid, "WATCHDOG_ON")
    await send_cmd(uid, {"type": "watchdog", "enabled": True})
    await update.message.reply_text(
        "🐕 *Watchdog started!*\n\n"
        "Alerts for:\n• 🚨 Approval needed\n• ✅ Task complete\n• ⚠️ Errors\n• 💤 Idle\n\n"
        "`/watchdog off` to stop",
        parse_mode=ParseMode.MARKDOWN
    )

async def pause_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    get_user_state(uid)["paused"] = True
    audit_logger.log(uid, "PAUSE")
    await update.message.reply_text("⏸️ Paused. /resume to continue.")

async def resume_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    get_user_state(uid)["paused"] = False
    audit_logger.log(uid, "RESUME")
    await update.message.reply_text("▶️ Resumed!")

async def sysinfo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    audit_logger.log(uid, "SYSINFO")
    resp = await send_cmd(uid, {"type": "sysinfo"})
    if resp and resp.get("info"):
        await update.message.reply_text(f"⚙️ *System:*\n```\n{resp['info']}\n```", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Failed")

async def files_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    audit_logger.log(uid, "FILES")
    resp = await send_cmd(uid, {"type": "files"})
    if resp and resp.get("files"):
        await update.message.reply_text(f"📂 *Files:*\n{sanitize_input(resp['files'])}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Failed")

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = str(update.effective_user.id)
    
    if not rate_limiter.is_allowed(uid):
        return
    
    if uid not in connected_clients:
        await query.message.reply_text("🔴 Not connected")
        return
    
    data = query.data
    audit_logger.log(uid, "BUTTON", data)
    
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
        if model in MODELS:
            await send_cmd(uid, {"type": "model", "model": model})
            await query.message.reply_text(f"🔄 Switching to {model}...")

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    
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
    
    text = sanitize_input(update.message.text)
    audit_logger.log(uid, "MESSAGE", text[:50])
    
    msg = await update.message.reply_text("📤 Sending...")
    resp = await send_cmd(uid, {"type": "relay", "text": text})
    if resp and resp.get("success"):
        keyboard = [[InlineKeyboardButton("📸 Screenshot", callback_data="q_ss")]]
        await msg.edit_text("✅ Sent!", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await msg.edit_text("❌ Failed")

# ============ Main ============

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")

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
    logger.info("Bot running - SECURE VERSION!")
    
    while True:
        await asyncio.sleep(1)

async def main():
    threading.Thread(target=run_api, daemon=True).start()
    await run_bot()

if __name__ == "__main__":
    asyncio.run(main())
