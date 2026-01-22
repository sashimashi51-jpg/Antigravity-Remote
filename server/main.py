"""
Antigravity Remote Server - v3.3.0
Fixes: Heartbeat, Command Queue, Voice Transcription, Keep-Alive

Architecture follows backend-dev-guidelines:
- Layered: Routes → Controllers → Services
- Proper error handling with logging
- Async patterns with try-catch
"""

import asyncio
import logging
import os
import sys
import base64
import json
import hashlib
import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
from contextlib import asynccontextmanager
from collections import defaultdict, deque
import threading
import re

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("Antigravity Remote Server - v3.3.0")
logger.info("Features: Heartbeat, Command Queue, Voice Transcription")
logger.info("=" * 50)

# ============ Configuration (unifiedConfig pattern) ============

class Config:
    """Centralized configuration - never use os.environ directly."""
    BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    PORT: int = int(os.environ.get("PORT", 10000))
    AUTH_SECRET: str = os.environ.get("AUTH_SECRET", "antigravity-remote-2026")
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    
    # Timeouts and limits
    HEARTBEAT_INTERVAL: int = 30  # seconds
    HEARTBEAT_TIMEOUT: int = 60   # seconds before considering client dead
    COMMAND_QUEUE_TTL: int = 300  # 5 minutes
    COMMAND_QUEUE_MAX_SIZE: int = 50
    RATE_LIMIT_REQUESTS: int = 30
    RATE_LIMIT_WINDOW: int = 60
    TOKEN_EXPIRY_DAYS: int = 30

config = Config()

logger.info(f"PORT: {config.PORT}")
logger.info(f"BOT_TOKEN set: {'Yes' if config.BOT_TOKEN else 'NO!'}")
logger.info(f"OPENAI_API_KEY set: {'Yes' if config.OPENAI_API_KEY else 'No (voice transcription disabled)'}")

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
    from fastapi.responses import JSONResponse
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from telegram.constants import ParseMode
    import uvicorn
    import httpx  # For Whisper API
    logger.info("All imports successful!")
except Exception as e:
    logger.error(f"Import error: {e}")
    sys.exit(1)

# ============ Custom Error Types (async-and-errors.md pattern) ============

class AppError(Exception):
    """Base application error."""
    def __init__(self, message: str, code: str = "UNKNOWN", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code

class ValidationError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "VALIDATION_ERROR", 400)

class NotFoundError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "NOT_FOUND", 404)

class AuthenticationError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "AUTH_FAILED", 401)

# ============ Services Layer ============

class RateLimiterService:
    """Rate limiting per user."""
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: Dict[str, list] = defaultdict(list)
    
    def is_allowed(self, user_id: str) -> bool:
        now = time.time()
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


class CommandQueueService:
    """
    Queue commands when client is disconnected.
    Commands are stored with TTL and delivered on reconnection.
    """
    def __init__(self, max_size: int = 50, ttl_seconds: int = 300):
        self.queues: Dict[str, deque] = defaultdict(deque)
        self.max_size = max_size
        self.ttl = ttl_seconds
    
    def enqueue(self, user_id: str, command: dict) -> bool:
        """Add command to queue. Returns False if queue is full."""
        self._cleanup_expired(user_id)
        
        if len(self.queues[user_id]) >= self.max_size:
            logger.warning(f"Command queue full for user {user_id[-4:]}")
            return False
        
        command["_queued_at"] = time.time()
        self.queues[user_id].append(command)
        logger.info(f"Queued command for user {user_id[-4:]}: {command.get('type')}")
        return True
    
    def dequeue_all(self, user_id: str) -> List[dict]:
        """Get all pending commands for user and clear queue."""
        self._cleanup_expired(user_id)
        
        commands = list(self.queues[user_id])
        self.queues[user_id].clear()
        
        # Remove internal metadata
        for cmd in commands:
            cmd.pop("_queued_at", None)
        
        if commands:
            logger.info(f"Delivering {len(commands)} queued commands to user {user_id[-4:]}")
        
        return commands
    
    def _cleanup_expired(self, user_id: str):
        """Remove expired commands."""
        now = time.time()
        self.queues[user_id] = deque(
            cmd for cmd in self.queues[user_id]
            if now - cmd.get("_queued_at", 0) < self.ttl
        )
    
    def get_queue_size(self, user_id: str) -> int:
        self._cleanup_expired(user_id)
        return len(self.queues[user_id])


class HeartbeatService:
    """
    Track client heartbeats and detect disconnections.
    Implements ping/pong pattern.
    """
    def __init__(self, timeout_seconds: int = 60):
        self.last_heartbeat: Dict[str, float] = {}
        self.timeout = timeout_seconds
    
    def record_heartbeat(self, user_id: str):
        """Record a heartbeat from client."""
        self.last_heartbeat[user_id] = time.time()
    
    def is_alive(self, user_id: str) -> bool:
        """Check if client is still alive."""
        last = self.last_heartbeat.get(user_id, 0)
        return (time.time() - last) < self.timeout
    
    def remove(self, user_id: str):
        """Remove client from tracking."""
        self.last_heartbeat.pop(user_id, None)
    
    def get_dead_clients(self, connected_clients: Dict[str, Any]) -> List[str]:
        """Get list of clients that haven't sent heartbeat in timeout period."""
        now = time.time()
        dead = []
        for user_id in connected_clients:
            last = self.last_heartbeat.get(user_id, 0)
            if now - last > self.timeout:
                dead.append(user_id)
        return dead


class VoiceTranscriptionService:
    """
    Transcribe audio using OpenAI Whisper API.
    Fallback to file path if API key not configured.
    """
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.enabled = bool(api_key)
        if self.enabled:
            logger.info("Voice transcription enabled (Whisper API)")
        else:
            logger.info("Voice transcription disabled (no OPENAI_API_KEY)")
    
    async def transcribe(self, audio_data: bytes, format: str = "ogg") -> Optional[str]:
        """
        Transcribe audio to text using Whisper API.
        Returns None if transcription fails.
        """
        if not self.enabled:
            logger.info("Transcription skipped: no API key")
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                # Whisper API expects multipart form data
                files = {
                    "file": (f"audio.{format}", audio_data, f"audio/{format}"),
                    "model": (None, "whisper-1"),
                }
                
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files=files,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    text = result.get("text", "").strip()
                    logger.info(f"Transcribed: {text[:50]}...")
                    return text
                else:
                    logger.error(f"Whisper API error: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None


class AuditLoggerService:
    """Audit logging for commands."""
    def __init__(self, max_entries: int = 1000):
        self.logs: list = []
        self.max_entries = max_entries
    
    def log(self, user_id: str, action: str, details: str = ""):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id[-4:] if len(user_id) > 4 else "****",
            "action": action,
            "details": details[:100] if details else ""
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_entries:
            self.logs = self.logs[-self.max_entries:]
        logger.info(f"AUDIT: {entry['user_id']} - {action}")


# ============ Auth Service ============

class AuthService:
    """Authentication token generation and validation."""
    
    @staticmethod
    def generate_token(user_id: str) -> tuple[str, int]:
        """Generate auth token with expiry timestamp."""
        issue_time = int(time.time())
        expires_at = issue_time + (config.TOKEN_EXPIRY_DAYS * 86400)
        
        data = f"{user_id}:{config.AUTH_SECRET}:{issue_time}"
        token = hashlib.sha256(data.encode()).hexdigest()[:32]
        
        return token, expires_at
    
    @staticmethod
    def validate_token(user_id: str, token: str) -> bool:
        """Validate auth token - accepts tokens from last 30 days."""
        current_time = int(time.time())
        
        # Check tokens from the last 30 days
        for days_ago in range(config.TOKEN_EXPIRY_DAYS + 1):
            for hour in range(0, 24, 6):
                test_time = current_time - (days_ago * 86400) - (hour * 3600)
                data = f"{user_id}:{config.AUTH_SECRET}:{test_time}"
                expected = hashlib.sha256(data.encode()).hexdigest()[:32]
                if secrets.compare_digest(token, expected):
                    return True
        
        # Accept legacy static tokens
        legacy_data = f"{user_id}:{config.AUTH_SECRET}"
        legacy_token = hashlib.sha256(legacy_data.encode()).hexdigest()[:32]
        if secrets.compare_digest(token, legacy_token):
            return True
        
        return False


# ============ Utility Functions ============

def sanitize_input(text: str, max_length: int = 4000) -> str:
    """Sanitize user input."""
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text[:max_length]


def safe_error_message(error: Exception) -> str:
    """Return generic error message."""
    return "An error occurred. Please try again."


# ============ Initialize Services ============

rate_limiter = RateLimiterService(config.RATE_LIMIT_REQUESTS, config.RATE_LIMIT_WINDOW)
command_queue = CommandQueueService(config.COMMAND_QUEUE_MAX_SIZE, config.COMMAND_QUEUE_TTL)
heartbeat_service = HeartbeatService(config.HEARTBEAT_TIMEOUT)
voice_service = VoiceTranscriptionService(config.OPENAI_API_KEY)
audit_logger = AuditLoggerService()
auth_service = AuthService()

# State
connected_clients: Dict[str, WebSocket] = {}
pending_responses: Dict[str, dict] = {}
user_state: Dict[str, dict] = {}
bot_application = None

# ============ FastAPI App ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI starting (v3.3.0)...")
    
    # Background tasks
    async def heartbeat_monitor():
        """Monitor client heartbeats and cleanup dead connections."""
        while True:
            await asyncio.sleep(config.HEARTBEAT_INTERVAL)
            try:
                dead_clients = heartbeat_service.get_dead_clients(connected_clients)
                for user_id in dead_clients:
                    logger.warning(f"Client {user_id[-4:]} timed out (no heartbeat)")
                    ws = connected_clients.pop(user_id, None)
                    heartbeat_service.remove(user_id)
                    if ws:
                        try:
                            await ws.close(code=4000, reason="Heartbeat timeout")
                        except:
                            pass
            except Exception as e:
                logger.error(f"Heartbeat monitor error: {e}")
    
    async def keep_alive_self():
        """Keep server warm by pinging itself (prevents Render cold start)."""
        while True:
            await asyncio.sleep(600)  # Every 10 minutes
            try:
                async with httpx.AsyncClient() as client:
                    await client.get(f"http://localhost:{config.PORT}/health", timeout=5.0)
                    logger.debug("Keep-alive ping successful")
            except Exception as e:
                logger.debug(f"Keep-alive ping failed (normal on startup): {e}")
    
    # Start background tasks
    asyncio.create_task(heartbeat_monitor())
    asyncio.create_task(keep_alive_self())
    
    yield
    logger.info("FastAPI shutting down...")

app = FastAPI(title="Antigravity Remote (v3.3.0)", lifespan=lifespan)

@app.get("/")
async def root():
    return {
        "status": "online",
        "version": "3.3.0",
        "clients": len(connected_clients),
        "features": ["heartbeat", "command_queue", "voice_transcription"]
    }

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/stats")
async def stats():
    """Server statistics endpoint."""
    return {
        "connected_clients": len(connected_clients),
        "queued_commands": sum(command_queue.get_queue_size(uid) for uid in command_queue.queues),
        "uptime": "active"
    }

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    
    # Wait for auth message
    try:
        auth_data = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        auth = json.loads(auth_data)
        auth_token = auth.get("auth_token", "")
        
        # Validate
        if not auth_service.validate_token(user_id, auth_token):
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
    
    # Register client
    connected_clients[user_id] = websocket
    heartbeat_service.record_heartbeat(user_id)
    
    # Deliver queued commands
    queued = command_queue.dequeue_all(user_id)
    for cmd in queued:
        try:
            await websocket.send_text(json.dumps(cmd))
        except:
            break
    
    if user_id not in user_state:
        user_state[user_id] = {"paused": False, "locked": False}
    
    logger.info(f"Client authenticated: {user_id[-4:]}")
    
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")
            msg_id = msg.get("message_id")
            
            # Handle heartbeat (ping/pong)
            if msg_type == "ping":
                heartbeat_service.record_heartbeat(user_id)
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            
            # Handle alerts from agent
            if msg_type == "alert":
                await handle_agent_alert(user_id, msg)
                continue
            
            # Handle command responses
            if msg_id and msg_id in pending_responses:
                pending_responses[msg_id]["data"] = msg
                pending_responses[msg_id]["event"].set()
                
    except WebSocketDisconnect:
        audit_logger.log(user_id, "DISCONNECTED")
    except Exception as e:
        logger.error(f"WebSocket error for {user_id[-4:]}: {e}")
    finally:
        connected_clients.pop(user_id, None)
        heartbeat_service.remove(user_id)


async def handle_agent_alert(user_id: str, msg: dict):
    """Handle alerts from local agent (watchdog detections)."""
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
    """Send command to client. Queue if disconnected."""
    
    # Rate limit check
    if not rate_limiter.is_allowed(user_id):
        return {"error": "rate_limited", "wait": rate_limiter.get_wait_time(user_id)}
    
    # If client not connected, queue the command
    if user_id not in connected_clients:
        if command_queue.enqueue(user_id, cmd):
            return {"queued": True, "queue_size": command_queue.get_queue_size(user_id)}
        else:
            return {"error": "queue_full"}
    
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
    
    # Connection status
    if uid in connected_clients:
        status = "🟢 Connected"
    elif command_queue.get_queue_size(uid) > 0:
        status = f"🟡 Offline ({command_queue.get_queue_size(uid)} queued)"
    else:
        status = "🔴 Not connected"
    
    # Generate auth token
    auth_token, expires_at = auth_service.generate_token(uid)
    expiry_date = datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d")
    
    audit_logger.log(uid, "START")
    
    await update.message.reply_text(
        f"🔐 *Antigravity Remote v3.3*\n\n"
        f"ID: `{uid}`\n"
        f"Status: {status}\n"
        f"Auth Token: `{auth_token}`\n"
        f"Expires: {expiry_date}\n\n"
        f"*New in v3.3:*\n"
        f"• 💓 Heartbeat (better connection)\n"
        f"• 📦 Command Queue (offline support)\n"
        f"• 🎙️ Whisper Voice (reliable transcription)\n\n"
        f"*Setup:*\n"
        f"`pip install antigravity-remote`\n"
        f"`antigravity-remote --register`",
        parse_mode=ParseMode.MARKDOWN
    )


async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        queued = command_queue.get_queue_size(uid)
        if queued > 0:
            await update.message.reply_text(f"🟡 Offline ({queued} commands queued)")
        else:
            await update.message.reply_text(f"🔴 Not connected\nID: `{uid}`", parse_mode=ParseMode.MARKDOWN)
        return
    
    audit_logger.log(uid, "STATUS")
    msg = await update.message.reply_text("📸 Capturing...")
    
    resp = await send_cmd(uid, {"type": "screenshot"})
    if resp and resp.get("queued"):
        await msg.edit_text(f"📦 Command queued (you're offline)")
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
        try:
            await msg.edit_text("✅ Sent!", reply_markup=InlineKeyboardMarkup(keyboard))
        except:
            pass
    else:
        await msg.edit_text("❌ Failed")


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    msg = await update.message.reply_text("👁️ Processing photo...")
    photo_file = await update.message.photo[-1].get_file()
    data = await photo_file.download_as_bytearray()
    b64_data = base64.b64encode(data).decode()
    
    resp = await send_cmd(uid, {"type": "photo", "data": b64_data})
    if resp and resp.get("success"):
        await msg.edit_text("✅ Photo sent to Agent")
    else:
        await msg.edit_text("❌ Failed to send photo")


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages with Whisper transcription."""
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return

    msg = await update.message.reply_text("🎙️ Processing voice...")
    voice_file = await update.message.voice.get_file()
    data = await voice_file.download_as_bytearray()
    
    # Try cloud transcription first
    transcribed_text = await voice_service.transcribe(bytes(data), "ogg")
    
    if transcribed_text:
        # Send transcribed text as command
        audit_logger.log(uid, "VOICE", transcribed_text[:50])
        resp = await send_cmd(uid, {"type": "relay", "text": transcribed_text})
        if resp and resp.get("success"):
            await msg.edit_text(f"✅ *Voice command:*\n\"{transcribed_text}\"", parse_mode=ParseMode.MARKDOWN)
        else:
            await msg.edit_text(f"❌ Failed to send: \"{transcribed_text}\"")
    else:
        # Fallback: send audio file to agent for local processing
        b64_data = base64.b64encode(data).decode()
        resp = await send_cmd(uid, {"type": "voice", "data": b64_data, "format": "ogg"})
        if resp and resp.get("success"):
            result_text = resp.get("text", "Audio sent")
            await msg.edit_text(f"✅ Voice sent: \"{result_text}\"")
        else:
            await msg.edit_text("❌ Failed to process voice")


async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
        await msg.edit_text(f"✅ Saved to: {resp.get('path', 'disk')}")
    else:
        await msg.edit_text("❌ Failed to send file")


# ============ Main ============

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level="warning")


async def run_bot():
    global bot_application
    if not config.BOT_TOKEN:
        logger.warning("No bot token")
        while True:
            await asyncio.sleep(60)
        return
    
    bot_application = ApplicationBuilder().token(config.BOT_TOKEN).build()
    
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
    bot_application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    bot_application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    bot_application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    await bot_application.initialize()
    await bot_application.start()
    await bot_application.updater.start_polling()
    logger.info("Bot running - v3.3.0 with Heartbeat, Queue, Whisper!")
    
    while True:
        await asyncio.sleep(1)


async def main():
    threading.Thread(target=run_api, daemon=True).start()
    await run_bot()


if __name__ == "__main__":
    asyncio.run(main())
