"""
Antigravity Remote Server - FastAPI WebSocket + Telegram Bot

This server:
1. Receives commands from Telegram
2. Pushes them to connected local agents via WebSocket
3. Returns screenshots/results to Telegram
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Connected clients: user_id -> WebSocket
connected_clients: Dict[str, WebSocket] = {}

# Pending responses: message_id -> asyncio.Event + data
pending_responses: Dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("🚀 Server starting...")
    yield
    logger.info("👋 Server shutting down...")


app = FastAPI(
    title="Antigravity Remote Server",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "online",
        "connected_clients": len(connected_clients),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health")
async def health():
    """Health check for Render."""
    return {"status": "ok"}


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket endpoint for local agents."""
    await websocket.accept()
    
    # Register client
    connected_clients[user_id] = websocket
    logger.info(f"✅ Client connected: {user_id}")
    
    try:
        while True:
            # Receive messages from client (screenshots, results, etc.)
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


async def send_command_to_client(user_id: str, command: dict, timeout: float = 30.0) -> Optional[dict]:
    """Send a command to a connected client and wait for response."""
    if user_id not in connected_clients:
        return None
    
    websocket = connected_clients[user_id]
    msg_id = f"{user_id}_{datetime.utcnow().timestamp()}"
    command["message_id"] = msg_id
    
    # Setup response handler
    event = asyncio.Event()
    pending_responses[msg_id] = {"event": event, "data": None}
    
    try:
        # Send command
        await websocket.send_text(json.dumps(command))
        
        # Wait for response
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return pending_responses[msg_id]["data"]
        
    except asyncio.TimeoutError:
        logger.warning(f"Timeout waiting for response from {user_id}")
        return None
    finally:
        if msg_id in pending_responses:
            del pending_responses[msg_id]


def is_user_connected(user_id: str) -> bool:
    """Check if a user's local agent is connected."""
    return user_id in connected_clients


# This will be imported by bot.py
def get_app():
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
