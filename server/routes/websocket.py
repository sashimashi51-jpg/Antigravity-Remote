"""
Antigravity Remote - WebSocket Routes
WebSocket endpoint and message handling.
"""

import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import Dict, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared state - injected by app.py
connected_clients: Dict[str, WebSocket] = {}
pending_responses: Dict[str, dict] = {}
user_state: Dict[str, dict] = {}
ai_responses: Dict[str, str] = {}

# Services - injected by app.py
heartbeat_service = None
command_queue = None
audit_logger = None
auth_service = None
live_stream = None
progress_service = None
send_ai_response_to_telegram = None
send_progress_to_telegram = None
handle_agent_alert = None


def init_websocket(
    clients_ref,
    pending_ref,
    state_ref,
    ai_resp_ref,
    heartbeat_svc,
    queue_svc,
    audit_svc,
    auth_svc,
    livestream_svc,
    progress_svc,
    ai_response_func,
    progress_func,
    alert_func
):
    """Initialize WebSocket routes with shared state and services."""
    global connected_clients, pending_responses, user_state, ai_responses
    global heartbeat_service, command_queue, audit_logger, auth_service
    global live_stream, progress_service
    global send_ai_response_to_telegram, send_progress_to_telegram, handle_agent_alert
    
    connected_clients = clients_ref
    pending_responses = pending_ref
    user_state = state_ref
    ai_responses = ai_resp_ref
    heartbeat_service = heartbeat_svc
    command_queue = queue_svc
    audit_logger = audit_svc
    auth_service = auth_svc
    live_stream = livestream_svc
    progress_service = progress_svc
    send_ai_response_to_telegram = ai_response_func
    send_progress_to_telegram = progress_func
    handle_agent_alert = alert_func


@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """Main WebSocket endpoint for agent connections."""
    await websocket.accept()
    
    # Authentication
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
    
    # Main message loop
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
                if send_ai_response_to_telegram:
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
                if send_progress_to_telegram:
                    await send_progress_to_telegram(user_id)
                continue
            
            # Handle alert
            if msg_type == "alert":
                if handle_agent_alert:
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
