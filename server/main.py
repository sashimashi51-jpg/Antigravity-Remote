"""
Antigravity Remote Server - v4.0.0 VIBECODER EDITION
Features: Live Stream, Two-Way Chat, Code Preview, Scheduled Tasks, 
          Smart Notifs, Mini Keyboard, Voice Response, Better Screenshots,
          Progress Bar, Undo Stack
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
import io
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
logger.info("Antigravity Remote Server - v4.0.0 VIBECODER EDITION")
logger.info("=" * 50)

# ============ Configuration ============

class Config:
    BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    PORT: int = int(os.environ.get("PORT", 10000))
    AUTH_SECRET: str = os.environ.get("AUTH_SECRET", "antigravity-remote-2026")
    
    HEARTBEAT_INTERVAL: int = 30
    HEARTBEAT_TIMEOUT: int = 60
    COMMAND_QUEUE_TTL: int = 300
    COMMAND_QUEUE_MAX_SIZE: int = 50
    RATE_LIMIT_REQUESTS: int = 60
    RATE_LIMIT_WINDOW: int = 60
    TOKEN_EXPIRY_DAYS: int = 30
    STREAM_FPS: int = 2
    UNDO_STACK_SIZE: int = 10

config = Config()

logger.info(f"PORT: {config.PORT}")
logger.info(f"BOT_TOKEN: {'SET' if config.BOT_TOKEN else 'MISSING!'}")

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from telegram.constants import ParseMode
    import uvicorn
    import httpx
    logger.info("All imports successful!")
except Exception as e:
    logger.error(f"Import error: {e}")
    sys.exit(1)

# ============ Services ============

class RateLimiterService:
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
    def __init__(self, max_size: int = 50, ttl_seconds: int = 300):
        self.queues: Dict[str, deque] = defaultdict(deque)
        self.max_size = max_size
        self.ttl = ttl_seconds
    
    def enqueue(self, user_id: str, command: dict) -> bool:
        self._cleanup_expired(user_id)
        if len(self.queues[user_id]) >= self.max_size:
            return False
        command["_queued_at"] = time.time()
        self.queues[user_id].append(command)
        return True
    
    def dequeue_all(self, user_id: str) -> List[dict]:
        self._cleanup_expired(user_id)
        commands = list(self.queues[user_id])
        self.queues[user_id].clear()
        for cmd in commands:
            cmd.pop("_queued_at", None)
        return commands
    
    def _cleanup_expired(self, user_id: str):
        now = time.time()
        self.queues[user_id] = deque(
            cmd for cmd in self.queues[user_id]
            if now - cmd.get("_queued_at", 0) < self.ttl
        )
    
    def get_queue_size(self, user_id: str) -> int:
        self._cleanup_expired(user_id)
        return len(self.queues[user_id])


class HeartbeatService:
    def __init__(self, timeout_seconds: int = 60):
        self.last_heartbeat: Dict[str, float] = {}
        self.timeout = timeout_seconds
    
    def record_heartbeat(self, user_id: str):
        self.last_heartbeat[user_id] = time.time()
    
    def is_alive(self, user_id: str) -> bool:
        last = self.last_heartbeat.get(user_id, 0)
        return (time.time() - last) < self.timeout
    
    def remove(self, user_id: str):
        self.last_heartbeat.pop(user_id, None)
    
    def get_dead_clients(self, connected_clients: Dict[str, Any]) -> List[str]:
        now = time.time()
        return [uid for uid in connected_clients if now - self.last_heartbeat.get(uid, 0) > self.timeout]


class SchedulerService:
    """Scheduled tasks service."""
    def __init__(self):
        self.tasks: Dict[str, List[dict]] = defaultdict(list)
    
    def add_task(self, user_id: str, time_str: str, command: str) -> bool:
        """Add scheduled task. time_str format: '9:00' or '14:30'"""
        try:
            hour, minute = map(int, time_str.split(':'))
            self.tasks[user_id].append({
                "hour": hour,
                "minute": minute,
                "command": command,
                "last_run": None
            })
            return True
        except:
            return False
    
    def get_due_tasks(self, user_id: str) -> List[str]:
        """Get tasks that are due now."""
        now = datetime.now()
        due = []
        for task in self.tasks.get(user_id, []):
            if task["hour"] == now.hour and task["minute"] == now.minute:
                if task["last_run"] != now.strftime("%Y-%m-%d %H:%M"):
                    task["last_run"] = now.strftime("%Y-%m-%d %H:%M")
                    due.append(task["command"])
        return due
    
    def list_tasks(self, user_id: str) -> List[dict]:
        return self.tasks.get(user_id, [])
    
    def clear_tasks(self, user_id: str):
        self.tasks[user_id] = []


class UndoStackService:
    """Undo stack for multiple undos."""
    def __init__(self, max_size: int = 10):
        self.stacks: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_size))
    
    def push(self, user_id: str, action: str):
        self.stacks[user_id].append({"action": action, "time": time.time()})
    
    def get_stack(self, user_id: str) -> List[dict]:
        return list(self.stacks[user_id])
    
    def clear(self, user_id: str):
        self.stacks[user_id].clear()


class LiveStreamService:
    """Live screen streaming service."""
    def __init__(self):
        self.frames: Dict[str, bytes] = {}
        self.last_update: Dict[str, float] = {}
        self.streaming: Dict[str, bool] = {}
    
    def update_frame(self, user_id: str, frame_data: bytes):
        self.frames[user_id] = frame_data
        self.last_update[user_id] = time.time()
    
    def get_frame(self, user_id: str) -> Optional[bytes]:
        return self.frames.get(user_id)
    
    def start_stream(self, user_id: str):
        self.streaming[user_id] = True
    
    def stop_stream(self, user_id: str):
        self.streaming[user_id] = False
    
    def is_streaming(self, user_id: str) -> bool:
        return self.streaming.get(user_id, False)


class ProgressService:
    """Track task progress."""
    def __init__(self):
        self.progress: Dict[str, dict] = {}
    
    def update(self, user_id: str, task: str, percent: int, status: str = ""):
        self.progress[user_id] = {
            "task": task,
            "percent": min(100, max(0, percent)),
            "status": status,
            "updated": time.time()
        }
    
    def get(self, user_id: str) -> Optional[dict]:
        return self.progress.get(user_id)
    
    def clear(self, user_id: str):
        self.progress.pop(user_id, None)


class AuditLoggerService:
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


class AuthService:
    @staticmethod
    def generate_token(user_id: str) -> tuple[str, int]:
        issue_time = int(time.time())
        expires_at = issue_time + (config.TOKEN_EXPIRY_DAYS * 86400)
        data = f"{user_id}:{config.AUTH_SECRET}:{issue_time}"
        token = hashlib.sha256(data.encode()).hexdigest()[:32]
        return token, expires_at
    
    @staticmethod
    def validate_token(user_id: str, token: str) -> bool:
        current_time = int(time.time())
        for days_ago in range(config.TOKEN_EXPIRY_DAYS + 1):
            for hour in range(0, 24, 6):
                test_time = current_time - (days_ago * 86400) - (hour * 3600)
                data = f"{user_id}:{config.AUTH_SECRET}:{test_time}"
                expected = hashlib.sha256(data.encode()).hexdigest()[:32]
                if secrets.compare_digest(token, expected):
                    return True
        legacy_data = f"{user_id}:{config.AUTH_SECRET}"
        legacy_token = hashlib.sha256(legacy_data.encode()).hexdigest()[:32]
        return secrets.compare_digest(token, legacy_token)


# ============ Utilities ============

def sanitize_input(text: str, max_length: int = 4000) -> str:
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text[:max_length]


def make_progress_bar(percent: int, width: int = 10) -> str:
    filled = int(width * percent / 100)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}] {percent}%"


# ============ Initialize Services ============

rate_limiter = RateLimiterService(config.RATE_LIMIT_REQUESTS, config.RATE_LIMIT_WINDOW)
command_queue = CommandQueueService(config.COMMAND_QUEUE_MAX_SIZE, config.COMMAND_QUEUE_TTL)
heartbeat_service = HeartbeatService(config.HEARTBEAT_TIMEOUT)
scheduler = SchedulerService()
undo_stack = UndoStackService(config.UNDO_STACK_SIZE)
live_stream = LiveStreamService()
progress_service = ProgressService()
audit_logger = AuditLoggerService()
auth_service = AuthService()

# State
connected_clients: Dict[str, WebSocket] = {}
pending_responses: Dict[str, dict] = {}
user_state: Dict[str, dict] = {}
ai_responses: Dict[str, str] = {}  # Store last AI response per user
bot_application = None

# ============ FastAPI ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI v4.0 starting...")
    
    async def heartbeat_monitor():
        while True:
            await asyncio.sleep(config.HEARTBEAT_INTERVAL)
            try:
                dead_clients = heartbeat_service.get_dead_clients(connected_clients)
                for user_id in dead_clients:
                    ws = connected_clients.pop(user_id, None)
                    heartbeat_service.remove(user_id)
                    if ws:
                        try:
                            await ws.close(code=4000)
                        except:
                            pass
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
    
    async def scheduler_task():
        while True:
            await asyncio.sleep(60)  # Check every minute
            try:
                for user_id in list(connected_clients.keys()):
                    due_tasks = scheduler.get_due_tasks(user_id)
                    for task_cmd in due_tasks:
                        await send_cmd(user_id, {"type": "relay", "text": task_cmd})
                        if bot_application:
                            try:
                                await bot_application.bot.send_message(
                                    chat_id=int(user_id),
                                    text=f"⏰ Scheduled task running:\n`{task_cmd}`",
                                    parse_mode=ParseMode.MARKDOWN
                                )
                            except:
                                pass
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
    
    async def keep_alive():
        while True:
            await asyncio.sleep(600)
            try:
                async with httpx.AsyncClient() as client:
                    await client.get(f"http://localhost:{config.PORT}/health", timeout=5.0)
            except:
                pass
    
    asyncio.create_task(heartbeat_monitor())
    asyncio.create_task(scheduler_task())
    asyncio.create_task(keep_alive())
    
    yield
    logger.info("FastAPI shutting down...")

app = FastAPI(title="Antigravity Remote v4.0", lifespan=lifespan)

@app.get("/")
async def root():
    return {
        "status": "online",
        "version": "4.0.0",
        "clients": len(connected_clients),
        "features": ["live_stream", "two_way_chat", "scheduled_tasks", "undo_stack", "progress_bar"]
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/stream/{user_id}")
async def stream_page(user_id: str):
    """HTML page for live streaming."""
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Antigravity Live Stream</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ margin: 0; padding: 20px; background: #1a1a2e; color: white; font-family: system-ui; }}
            h1 {{ color: #00d4ff; margin: 0 0 20px 0; }}
            #stream {{ max-width: 100%; border: 2px solid #00d4ff; border-radius: 10px; }}
            .info {{ color: #888; margin-top: 10px; }}
            .status {{ color: #00ff88; }}
        </style>
    </head>
    <body>
        <h1>🔴 Antigravity Live</h1>
        <img id="stream" src="/stream/{user_id}/frame" alt="Loading...">
        <p class="info">Refreshing every 500ms | <span class="status" id="status">Connecting...</span></p>
        <script>
            const img = document.getElementById('stream');
            const status = document.getElementById('status');
            let errors = 0;
            setInterval(() => {{
                const newImg = new Image();
                newImg.onload = () => {{
                    img.src = newImg.src;
                    status.textContent = 'Connected';
                    errors = 0;
                }};
                newImg.onerror = () => {{
                    errors++;
                    status.textContent = errors > 3 ? 'Disconnected' : 'Buffering...';
                }};
                newImg.src = '/stream/{user_id}/frame?' + Date.now();
            }}, 500);
        </script>
    </body>
    </html>
    """)

@app.get("/stream/{user_id}/frame")
async def stream_frame(user_id: str):
    """Get latest frame for streaming."""
    frame = live_stream.get_frame(user_id)
    if frame:
        return StreamingResponse(io.BytesIO(frame), media_type="image/jpeg")
    # Return placeholder image
    return JSONResponse({"error": "No stream"}, status_code=404)

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    
    try:
        auth_data = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        auth = json.loads(auth_data)
        auth_token = auth.get("auth_token", "")
        
        if not auth_service.validate_token(user_id, auth_token):
            await websocket.send_text(json.dumps({"error": "Authentication failed"}))
            await websocket.close(code=4001)
            return
        
        await websocket.send_text(json.dumps({"status": "authenticated"}))
        audit_logger.log(user_id, "CONNECTED")
        
    except asyncio.TimeoutError:
        await websocket.close(code=4002)
        return
    except Exception:
        await websocket.close(code=4003)
        return
    
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
    
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")
            msg_id = msg.get("message_id")
            
            if msg_type == "ping":
                heartbeat_service.record_heartbeat(user_id)
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            
            # Handle AI response (Two-Way Chat)
            if msg_type == "ai_response":
                ai_responses[user_id] = msg.get("text", "")
                await send_ai_response_to_telegram(user_id, msg.get("text", ""))
                continue
            
            # Handle stream frame
            if msg_type == "stream_frame":
                frame_data = base64.b64decode(msg.get("data", ""))
                live_stream.update_frame(user_id, frame_data)
                continue
            
            # Handle progress update
            if msg_type == "progress":
                progress_service.update(
                    user_id,
                    msg.get("task", "Working..."),
                    msg.get("percent", 0),
                    msg.get("status", "")
                )
                await send_progress_to_telegram(user_id)
                continue
            
            # Handle alert
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
        logger.error(f"WebSocket error: {e}")
    finally:
        connected_clients.pop(user_id, None)
        heartbeat_service.remove(user_id)
        live_stream.stop_stream(user_id)


async def send_ai_response_to_telegram(user_id: str, text: str):
    """Send AI response back to Telegram (Two-Way Chat)."""
    global bot_application
    if not bot_application or not text:
        return
    
    try:
        # Truncate long responses
        if len(text) > 4000:
            text = text[:4000] + "... (truncated)"
        
        keyboard = [[
            InlineKeyboardButton("✅ Accept", callback_data="q_accept"),
            InlineKeyboardButton("❌ Reject", callback_data="q_reject"),
        ], [
            InlineKeyboardButton("📸 Screenshot", callback_data="q_ss"),
            InlineKeyboardButton("🗣️ Listen", callback_data="q_tts"),
        ]]
        
        await bot_application.bot.send_message(
            chat_id=int(user_id),
            text=f"🤖 *AI Response:*\n\n{sanitize_input(text)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error sending AI response: {e}")


async def send_progress_to_telegram(user_id: str):
    """Send progress update to Telegram."""
    global bot_application
    if not bot_application:
        return
    
    progress = progress_service.get(user_id)
    if not progress:
        return
    
    try:
        bar = make_progress_bar(progress["percent"])
        await bot_application.bot.send_message(
            chat_id=int(user_id),
            text=f"📊 *{progress['task']}*\n{bar}\n{progress.get('status', '')}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Progress send error: {e}")


async def handle_agent_alert(user_id: str, msg: dict):
    global bot_application
    if not bot_application:
        return
    
    try:
        text = sanitize_input(msg.get("text", "Alert"))
        image = msg.get("image")
        
        # Smart notification with action buttons
        keyboard = [[
            InlineKeyboardButton("✅ Accept", callback_data="q_accept"),
            InlineKeyboardButton("❌ Reject", callback_data="q_reject"),
        ]]
        
        if image:
            await bot_application.bot.send_photo(
                chat_id=int(user_id), 
                photo=base64.b64decode(image),
                caption=text, 
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await bot_application.bot.send_message(
                chat_id=int(user_id), 
                text=text, 
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Alert error: {e}")


async def send_cmd(user_id: str, cmd: dict, timeout: float = 30.0) -> Optional[dict]:
    if not rate_limiter.is_allowed(user_id):
        return {"error": "rate_limited", "wait": rate_limiter.get_wait_time(user_id)}
    
    if user_id not in connected_clients:
        if command_queue.enqueue(user_id, cmd):
            return {"queued": True, "queue_size": command_queue.get_queue_size(user_id)}
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
        await update.message.reply_text(f"⏳ Rate limited. Wait {rate_limiter.get_wait_time(uid)}s")
        return False
    return True


# Mini Keyboard (persistent reply keyboard)
def get_mini_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 Status"), KeyboardButton("✅ Accept"), KeyboardButton("❌ Reject")],
        [KeyboardButton("⬆️ Scroll Up"), KeyboardButton("⬇️ Scroll Down"), KeyboardButton("↩️ Undo")],
    ], resize_keyboard=True, is_persistent=True)


async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
        f"🚀 *Antigravity Remote v4.0*\n"
        f"_The Vibecoder's Best Friend_\n\n"
        f"ID: `{uid}`\n"
        f"Status: {status}\n"
        f"Token: `{auth_token}`\n"
        f"Expires: {expiry_date}\n\n"
        f"*NEW in v4.0:*\n"
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
        # Better screenshot with inline buttons
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
    """Start live streaming."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    
    # Start streaming on agent
    await send_cmd(uid, {"type": "start_stream", "fps": config.STREAM_FPS})
    live_stream.start_stream(uid)
    
    # Get the URL
    # Note: Render URL format
    host = os.environ.get("RENDER_EXTERNAL_URL", f"http://localhost:{config.PORT}")
    stream_url = f"{host}/stream/{uid}"
    
    keyboard = [[InlineKeyboardButton("📺 Watch Live", url=stream_url)]]
    await update.message.reply_text(
        f"📺 *Live Stream Started!*\n\nOpen in browser:\n{stream_url}\n\n`/stream stop` to end",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def diff_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Preview pending code changes."""
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
    """Manage scheduled tasks."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    
    if not ctx.args:
        # List tasks
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
    
    # Add task: /schedule 9:00 Check emails and summarize
    time_str = ctx.args[0]
    command = " ".join(ctx.args[1:])
    
    if scheduler.add_task(uid, time_str, command):
        await update.message.reply_text(f"⏰ Scheduled: `{time_str}` → {command}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Invalid time format. Use HH:MM (e.g., 9:00 or 14:30)")


async def undo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Undo multiple changes."""
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
    
    # Record in undo stack and send
    for i in range(count):
        undo_stack.push(uid, f"undo_{i}")
        await send_cmd(uid, {"type": "undo"})
    
    await update.message.reply_text(f"↩️ Undid {count} change(s)")


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
    await send_cmd(uid, {"type": "scroll", "direction": direction})
    await update.message.reply_text(f"📜 Scrolled {direction}")


async def accept_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    if not await check_rate_limit(update):
        return
    uid = str(update.effective_user.id)
    if uid not in connected_clients:
        await update.message.reply_text("🔴 Not connected")
        return
    await send_cmd(uid, {"type": "reject"})
    await update.message.reply_text("❌ Rejected")


async def tts_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Text-to-speech: read last AI response."""
    if not await check_rate_limit(update):
        return
    
    uid = str(update.effective_user.id)
    text = ai_responses.get(uid, "")
    
    if not text:
        await update.message.reply_text("🗣️ No recent AI response to read")
        return
    
    # Use agent for TTS (it has local TTS capability)
    if uid in connected_clients:
        await send_cmd(uid, {"type": "tts", "text": text[:500]})
        await update.message.reply_text("🗣️ Speaking...")
    else:
        await update.message.reply_text("🔴 Not connected")


async def quick_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    if not await check_rate_limit(update):
        return
    keyboard = [[InlineKeyboardButton(m, callback_data=f"m_{m}")] for m in MODELS]
    await update.message.reply_text("🤖 Select model:", reply_markup=InlineKeyboardMarkup(keyboard))


async def watchdog_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    uid = str(update.effective_user.id)
    get_user_state(uid)["paused"] = True
    await update.message.reply_text("⏸️ Paused")


async def resume_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    get_user_state(uid)["paused"] = False
    await update.message.reply_text("▶️ Resumed")


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


async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
        ("start", start_cmd), ("status", status_cmd), ("stream", stream_cmd),
        ("diff", diff_cmd), ("schedule", schedule_cmd), ("undo", undo_cmd),
        ("scroll", scroll_cmd), ("accept", accept_cmd), ("reject", reject_cmd),
        ("tts", tts_cmd), ("quick", quick_cmd), ("model", model_cmd),
        ("watchdog", watchdog_cmd), ("pause", pause_cmd), ("resume", resume_cmd),
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
    logger.info("Bot v4.0 running - VIBECODER EDITION!")
    
    while True:
        await asyncio.sleep(1)


async def main():
    threading.Thread(target=run_api, daemon=True).start()
    await run_bot()


if __name__ == "__main__":
    asyncio.run(main())
