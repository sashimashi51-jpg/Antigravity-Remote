"""
Local Agent for Antigravity Remote - SECURE VERSION
Handles authentication and all commands including MEDIA (Voice, Photo, Files)
"""

import asyncio
import base64
import json
import logging
import os
import time
import hashlib
import re
from pathlib import Path

import websockets

from .utils import (
    send_to_antigravity,
    send_key_combo,
    scroll_screen,
    take_screenshot,
    cleanup_screenshot,
    focus_antigravity,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_SERVER_URL = os.environ.get("ANTIGRAVITY_SERVER", "wss://antigravity-remote.onrender.com/ws")

# OCR keywords
APPROVAL_KEYWORDS = ["run command", "accept changes", "proceed", "approve", "allow", "confirm", "y/n"]
DONE_KEYWORDS = ["anything else", "let me know", "task complete", "done!", "successfully", "finished"]
ERROR_KEYWORDS = ["error:", "failed", "exception", "traceback", "cannot", "permission denied"]


def sanitize_input(text: str, max_length: int = 4000) -> str:
    """Sanitize input."""
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text[:max_length]


class LocalAgent:
    """Secure local agent with authentication and media support."""
    
    def __init__(self, user_id: str, auth_token: str, server_url: str = None):
        self.user_id = user_id
        self.auth_token = auth_token
        self.server_url = server_url or DEFAULT_SERVER_URL
        self.websocket = None
        self.running = False
        self.watchdog_enabled = False
        self.watchdog_task = None
        self.last_screen_hash = None
        self.idle_count = 0
        
        # Setup download dirs
        self.downloads_dir = Path.home() / "Downloads" / "AntigravityRemote"
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
    
    async def connect(self):
        url = f"{self.server_url}/{self.user_id}"
        logger.info(f"🔌 Connecting to server...")
        
        try:
            self.websocket = await websockets.connect(url)
            
            # Send authentication
            auth_msg = json.dumps({"auth_token": self.auth_token})
            await self.websocket.send(auth_msg)
            
            # Wait for strict auth response
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
                resp = json.loads(response)
                if "error" in resp:
                    logger.error(f"❌ Authentication failed: {resp['error']}")
                    return False
            except asyncio.TimeoutError:
                 # Legacy server might not send response immediately, assume ok but warn
                 logger.warning("⚠️ No auth response (legacy server?), assuming connected")
            
            logger.info("✅ Authenticated and connected!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False
    
    async def send_alert(self, alert_type: str, text: str, include_screenshot: bool = False):
        """Send alert to server."""
        if not self.websocket:
            return
        
        alert = {"type": "alert", "alert_type": alert_type, "text": text}
        
        if include_screenshot:
            path = take_screenshot()
            if path:
                with open(path, "rb") as f:
                    alert["image"] = base64.b64encode(f.read()).decode()
                cleanup_screenshot(path)
        
        try:
            await self.websocket.send(json.dumps(alert))
        except Exception:
            pass
    
    async def run_watchdog(self):
        """Background watchdog loop."""
        logger.info("🐕 Watchdog started")
        last_alert_time = 0
        
        while self.watchdog_enabled:
            await asyncio.sleep(5)
            
            try:
                path = take_screenshot()
                if not path:
                    continue
                
                with open(path, "rb") as f:
                    data = f.read()
                    current_hash = hashlib.md5(data[:10000]).hexdigest()
                
                if current_hash == self.last_screen_hash:
                    self.idle_count += 1
                else:
                    self.idle_count = 0
                self.last_screen_hash = current_hash
                
                # Try OCR
                try:
                    import pytesseract
                    from PIL import Image
                    img = Image.open(path)
                    text = pytesseract.image_to_string(img).lower()
                    
                    current_time = time.time()
                    if current_time - last_alert_time > 30:
                        for kw in APPROVAL_KEYWORDS:
                            if kw in text:
                                await self.send_alert("approval", f"🚨 *Approval needed!*\nDetected: `{kw}`", True)
                                last_alert_time = current_time
                                break
                        
                        for kw in DONE_KEYWORDS:
                            if kw in text:
                                await self.send_alert("done", f"✅ *Task complete!*\nDetected: `{kw}`", True)
                                last_alert_time = current_time
                                break
                        
                        for kw in ERROR_KEYWORDS:
                            if kw in text:
                                await self.send_alert("error", f"⚠️ *Error detected!*\nDetected: `{kw}`", True)
                                last_alert_time = current_time
                                break
                except ImportError:
                    pass
                
                cleanup_screenshot(path)
                
                if self.idle_count >= 3 and time.time() - last_alert_time > 60:
                    await self.send_alert("idle", "💤 *Screen idle*", True)
                    last_alert_time = time.time()
                    self.idle_count = 0
                    
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
        
        logger.info("🐕 Watchdog stopped")
    
    def process_voice(self, audio_path: Path) -> str:
        """
        Transcribe voice file using local Whisper (FREE, no API).
        Falls back to Google Speech Recognition if Whisper not available.
        """
        # Try faster-whisper first (best quality, runs locally)
        try:
            from faster_whisper import WhisperModel
            
            # Use tiny model for speed (can upgrade to base/small for accuracy)
            if not hasattr(self, '_whisper_model'):
                logger.info("Loading Whisper model (first time, may take a moment)...")
                self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            
            # Convert OGG to WAV if needed
            wav_path = audio_path
            if audio_path.suffix.lower() == '.ogg':
                try:
                    from pydub import AudioSegment
                    wav_path = audio_path.with_suffix('.wav')
                    sound = AudioSegment.from_ogg(str(audio_path))
                    sound.export(str(wav_path), format="wav")
                except Exception:
                    pass  # Try with OGG directly
            
            segments, info = self._whisper_model.transcribe(str(wav_path), beam_size=5)
            text = " ".join([segment.text for segment in segments]).strip()
            
            if text:
                logger.info(f"Whisper transcribed: {text[:50]}...")
                return text
                
        except ImportError:
            logger.debug("faster-whisper not installed, trying fallback...")
        except Exception as e:
            logger.warning(f"Whisper error: {e}, trying fallback...")
        
        # Fallback to Google Speech Recognition (also free, but less reliable)
        try:
            import speech_recognition as sr
            from pydub import AudioSegment
            
            wav_path = audio_path.with_suffix('.wav')
            if audio_path.suffix.lower() == '.ogg':
                sound = AudioSegment.from_ogg(str(audio_path))
                sound.export(str(wav_path), format="wav")
            
            r = sr.Recognizer()
            with sr.AudioFile(str(wav_path)) as source:
                audio = r.record(source)
                text = r.recognize_google(audio)
                logger.info(f"Google STT transcribed: {text[:50]}...")
                return text
                
        except ImportError:
            logger.warning("Neither faster-whisper nor speech_recognition installed")
        except Exception as e:
            logger.error(f"All transcription methods failed: {e}")
        
        return ""

    async def handle_command(self, command: dict) -> dict:
        cmd_type = command.get("type")
        message_id = command.get("message_id")
        result = {"message_id": message_id, "success": False}
        
        try:
            if cmd_type == "screenshot":
                path = take_screenshot()
                if path:
                    with open(path, "rb") as f:
                        result["image"] = base64.b64encode(f.read()).decode()
                    cleanup_screenshot(path)
                    result["success"] = True
            
            elif cmd_type == "relay":
                text = sanitize_input(command.get("text", ""))
                result["success"] = send_to_antigravity(text)
            
            elif cmd_type == "photo":
                try:
                    data = base64.b64decode(command.get("data", ""))
                    filename = f"photo_{int(time.time())}.jpg"
                    path = self.downloads_dir / filename
                    path.write_bytes(data)
                    
                    # Tell Agent
                    send_to_antigravity(f"I uploaded a photo here: {path}")
                    result["success"] = True
                except Exception as e:
                    result["error"] = str(e)
            
            elif cmd_type == "voice":
                try:
                    data = base64.b64decode(command.get("data", ""))
                    filename = f"voice_{int(time.time())}.ogg"
                    path = self.downloads_dir / filename
                    path.write_bytes(data)
                    
                    # Try transcribe
                    text = self.process_voice(path)
                    if text:
                        send_to_antigravity(f"(Voice Command): {text}")
                        result["text"] = text
                    else:
                        send_to_antigravity(f"I sent a voice note here: {path}")
                        result["text"] = "Audio saved (transcription failed)"
                    
                    result["success"] = True
                except Exception as e:
                    result["error"] = str(e)
            
            elif cmd_type == "file":
                try:
                    data = base64.b64decode(command.get("data", ""))
                    name = sanitize_input(command.get("name", "file"), 100)
                    path = Path.cwd() / name  # Save to CWD
                    path.write_bytes(data)
                    
                    send_to_antigravity(f"I saved a file: {path.absolute()}")
                    result["path"] = str(path.absolute())
                    result["success"] = True
                except Exception as e:
                    result["error"] = str(e)

            elif cmd_type == "scroll":
                direction = command.get("direction", "down")
                clicks = {"up": 25, "down": -25, "top": 500, "bottom": -500}.get(direction, -25)
                result["success"] = scroll_screen(clicks)
            
            elif cmd_type == "key":
                combo = sanitize_input(command.get("combo", ""), 50).split("+")
                result["success"] = send_key_combo(combo)
            
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
            
            elif cmd_type == "undo":
                import pyautogui
                focus_antigravity()
                pyautogui.hotkey('ctrl', 'z')
                result["success"] = True
            
            elif cmd_type == "cancel":
                import pyautogui
                focus_antigravity()
                pyautogui.press('escape')
                result["success"] = True
            
            elif cmd_type == "model":
                import pyautogui
                model = sanitize_input(command.get("model", ""), 100)
                focus_antigravity()
                time.sleep(0.5)
                
                # Strategy 1: Ctrl + / (Common Cursor shortcut)
                pyautogui.hotkey('ctrl', '/')
                time.sleep(0.5)
                pyautogui.write(model, interval=0.05)
                time.sleep(0.5)
                pyautogui.press('enter')
                
                # Strategy 2: Just tell the Agent!
                time.sleep(0.5)
                send_to_antigravity(f"Please switch model to {model}")
                result["success"] = True
            
            elif cmd_type == "watchdog":
                enabled = command.get("enabled", False)
                self.watchdog_enabled = enabled
                if enabled and not self.watchdog_task:
                    self.watchdog_task = asyncio.create_task(self.run_watchdog())
                elif not enabled and self.watchdog_task:
                    self.watchdog_task.cancel()
                    self.watchdog_task = None
                result["success"] = True
            
            elif cmd_type == "sysinfo":
                import psutil
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                result["info"] = f"CPU: {cpu}%\nRAM: {mem.percent}%"
                result["success"] = True
            
            elif cmd_type == "files":
                workspace = os.getcwd()
                items = os.listdir(workspace)[:20]
                result["files"] = "\n".join(f"📄 {i}" for i in items)
                result["success"] = True
            
            else:
                logger.warning(f"Unknown command: {cmd_type}")
                
        except Exception as e:
            logger.error(f"Command error: {e}")
            result["error"] = "Command failed"
        
        return result
    
    async def send_heartbeat(self):
        """Send periodic heartbeat pings to server."""
        while self.running and self.websocket:
            try:
                await asyncio.sleep(30)  # Every 30 seconds
                if self.websocket:
                    await self.websocket.send(json.dumps({"type": "ping"}))
                    logger.debug("💓 Heartbeat sent")
            except Exception as e:
                logger.debug(f"Heartbeat error (will reconnect): {e}")
                break
    
    async def run(self):
        self.running = True
        reconnect_delay = 5
        
        while self.running:
            try:
                if not await self.connect():
                    logger.info(f"Retrying in {reconnect_delay}s...")
                    await asyncio.sleep(reconnect_delay)
                    continue
                
                reconnect_delay = 5
                
                # Start heartbeat task
                heartbeat_task = asyncio.create_task(self.send_heartbeat())
                
                try:
                    async for message in self.websocket:
                        command = json.loads(message)
                        cmd_type = command.get('type')
                        
                        # Handle pong (response to our ping)
                        if cmd_type == "pong":
                            logger.debug("💓 Heartbeat acknowledged")
                            continue
                        
                        logger.info(f"📥 Received: {cmd_type}")
                        result = await self.handle_command(command)
                        await self.websocket.send(json.dumps(result))
                finally:
                    heartbeat_task.cancel()
                    
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed. Reconnecting...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(reconnect_delay)
    
    def stop(self):
        self.running = False
        self.watchdog_enabled = False
        if self.websocket:
            asyncio.create_task(self.websocket.close())


async def run_agent(user_id: str, auth_token: str, server_url: str = None):
    """Run the secure local agent."""
    agent = LocalAgent(user_id, auth_token, server_url)
    await agent.run()
