"""
Antigravity Remote - Application Factory
Creates and configures the FastAPI application.
"""

import asyncio
import base64
import json
import logging
import os
import re
import threading
from datetime import datetime
from typing import Dict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket

from config import config
from services import (
    RateLimiterService,
    CommandQueueService,
    HeartbeatService,
    SchedulerService,
    UndoStackService,
    LiveStreamService,
    ProgressService,
    AuditLoggerService,
    AuthService,
)
from routes import api_router, ws_router, init_api_routes, init_websocket
from utils import sanitize_input, make_progress_bar

logger = logging.getLogger(__name__)

# ============ Shared State ============

connected_clients: Dict[str, WebSocket] = {}
pending_responses: Dict[str, dict] = {}
user_state: Dict[str, dict] = {}
ai_responses: Dict[str, str] = {}
bot_application = None

# ============ Services ============

rate_limiter = RateLimiterService(config.RATE_LIMIT_REQUESTS, config.RATE_LIMIT_WINDOW)
command_queue = CommandQueueService(config.COMMAND_QUEUE_MAX_SIZE, config.COMMAND_QUEUE_TTL)
heartbeat_service = HeartbeatService(config.HEARTBEAT_TIMEOUT)
scheduler = SchedulerService()
undo_stack = UndoStackService()
live_stream = LiveStreamService()
progress_service = ProgressService()
audit_logger = AuditLoggerService()
auth_service = AuthService(config.AUTH_SECRET, config.TOKEN_EXPIRY_DAYS)


# ============ Helper Functions ============

async def send_cmd(user_id: str, cmd: dict, timeout: float = 30.0):
    """Send command to connected agent."""
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


async def send_ai_response_to_telegram(user_id: str, text: str):
    """Send AI response to Telegram."""
    global bot_application
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ParseMode
    
    if not bot_application or not text:
        return
    
    try:
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
    from telegram.constants import ParseMode
    
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
    """Handle alert from agent."""
    global bot_application
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ParseMode
    
    if not bot_application:
        return
    
    try:
        text = sanitize_input(msg.get("text", "Alert"))
        image = msg.get("image")
        
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


# ============ Application Factory ============

def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("FastAPI v4.3 starting...")
        
        async def heartbeat_monitor():
            while True:
                await asyncio.sleep(config.HEARTBEAT_INTERVAL)
                try:
                    dead_clients = heartbeat_service.get_dead_clients(connected_clients)
                    for uid in dead_clients:
                        ws = connected_clients.pop(uid, None)
                        heartbeat_service.remove(uid)
                        if ws:
                            try:
                                await ws.close(code=4000)
                            except:
                                pass
                except Exception as e:
                    logger.error(f"Heartbeat error: {e}")
        
        async def scheduler_task():
            while True:
                await asyncio.sleep(60)
                try:
                    for uid in list(connected_clients.keys()):
                        due_tasks = scheduler.get_due_tasks(uid)
                        for task_cmd in due_tasks:
                            await send_cmd(uid, {"type": "relay", "text": task_cmd})
                            if bot_application:
                                from telegram.constants import ParseMode
                                try:
                                    await bot_application.bot.send_message(
                                        chat_id=int(uid),
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
    
    # Create app
    app = FastAPI(title="Antigravity Remote v4.3", lifespan=lifespan)
    
    # Initialize routes with dependencies
    init_api_routes(connected_clients, live_stream, send_cmd)
    init_websocket(
        connected_clients,
        pending_responses,
        user_state,
        ai_responses,
        heartbeat_service,
        command_queue,
        audit_logger,
        auth_service,
        live_stream,
        progress_service,
        send_ai_response_to_telegram,
        send_progress_to_telegram,
        handle_agent_alert
    )
    
    # Include routers
    app.include_router(api_router)
    app.include_router(ws_router)
    
    return app


def get_services():
    """Get all services for external use (e.g., Telegram bot)."""
    return {
        "rate_limiter": rate_limiter,
        "command_queue": command_queue,
        "scheduler": scheduler,
        "undo_stack": undo_stack,
        "live_stream": live_stream,
        "auth_service": auth_service,
        "send_cmd": send_cmd,
        "sanitize_input": sanitize_input,
        "connected_clients": connected_clients,
        "user_state": user_state,
        "ai_responses": ai_responses,
        "config": config,
    }


def set_bot_application(bot_app):
    """Set the Telegram bot application reference."""
    global bot_application
    bot_application = bot_app
