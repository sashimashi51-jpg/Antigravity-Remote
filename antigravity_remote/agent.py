"""
Local Agent for Antigravity Remote.

Connects to the server via WebSocket and executes commands locally.
"""

import asyncio
import base64
import json
import logging
import os
import time

import websockets

from .utils import (
    send_to_antigravity,
    send_key_combo,
    scroll_screen,
    take_screenshot,
    cleanup_screenshot,
    focus_antigravity,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default server URL (will be updated when deployed to Render)
DEFAULT_SERVER_URL = os.environ.get(
    "ANTIGRAVITY_SERVER",
    "wss://antigravity-remote.onrender.com/ws"
)


class LocalAgent:
    """Local agent that connects to the server and executes commands."""
    
    def __init__(self, user_id: str, server_url: str = None):
        self.user_id = user_id
        self.server_url = server_url or DEFAULT_SERVER_URL
        self.websocket = None
        self.running = False
    
    async def connect(self):
        """Connect to the server."""
        url = f"{self.server_url}/{self.user_id}"
        logger.info(f"🔌 Connecting to {url}...")
        
        try:
            self.websocket = await websockets.connect(url)
            logger.info("✅ Connected to server!")
            return True
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False
    
    async def handle_command(self, command: dict) -> dict:
        """Handle a command from the server."""
        cmd_type = command.get("type")
        message_id = command.get("message_id")
        
        result = {"message_id": message_id, "success": False}
        
        try:
            if cmd_type == "screenshot":
                path = take_screenshot()
                if path:
                    with open(path, "rb") as f:
                        image_data = base64.b64encode(f.read()).decode()
                    cleanup_screenshot(path)
                    result["success"] = True
                    result["image"] = image_data
            
            elif cmd_type == "relay":
                text = command.get("text", "")
                success = send_to_antigravity(text)
                result["success"] = success
            
            elif cmd_type == "scroll":
                direction = command.get("direction", "down")
                clicks = 25 if direction == "up" else -25
                success = scroll_screen(clicks)
                result["success"] = success
            
            elif cmd_type == "key":
                combo = command.get("combo", "").split("+")
                success = send_key_combo(combo)
                result["success"] = success
            
            elif cmd_type == "accept":
                import pyautogui
                focus_antigravity()
                time.sleep(0.2)
                pyautogui.hotkey('alt', 'enter')
                result["success"] = True
            
            elif cmd_type == "reject":
                import pyautogui
                focus_antigravity()
                time.sleep(0.2)
                pyautogui.press('escape')
                result["success"] = True
            
            else:
                logger.warning(f"Unknown command type: {cmd_type}")
                
        except Exception as e:
            logger.error(f"Command error: {e}")
            result["error"] = str(e)
        
        return result
    
    async def run(self):
        """Main loop - receive and execute commands."""
        self.running = True
        reconnect_delay = 5
        
        while self.running:
            try:
                if not await self.connect():
                    logger.info(f"Retrying in {reconnect_delay}s...")
                    await asyncio.sleep(reconnect_delay)
                    continue
                
                # Reset reconnect delay on successful connection
                reconnect_delay = 5
                
                async for message in self.websocket:
                    command = json.loads(message)
                    logger.info(f"📥 Received: {command.get('type')}")
                    
                    result = await self.handle_command(command)
                    await self.websocket.send(json.dumps(result))
                    
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed. Reconnecting...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)
                
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(reconnect_delay)
    
    def stop(self):
        """Stop the agent."""
        self.running = False
        if self.websocket:
            asyncio.create_task(self.websocket.close())


async def run_agent(user_id: str, server_url: str = None):
    """Run the local agent."""
    agent = LocalAgent(user_id, server_url)
    await agent.run()
