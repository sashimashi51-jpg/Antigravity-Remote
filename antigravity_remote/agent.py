"""
Antigravity Remote Agent - v4.0.0 VIBECODER EDITION
Features: Live Stream, AI Response Capture, TTS, Diff, Better Screenshots
"""

import asyncio
import base64
import json
import logging
import os
import time
import hashlib
import re
import subprocess
from pathlib import Path
from typing import Optional

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

# Keywords for watchdog
APPROVAL_KEYWORDS = ["run command", "accept changes", "proceed", "approve", "allow", "confirm", "y/n"]
DONE_KEYWORDS = ["anything else", "let me know", "task complete", "done!", "successfully", "finished"]
ERROR_KEYWORDS = ["error:", "failed", "exception", "traceback", "cannot", "permission denied"]


def sanitize_input(text: str, max_length: int = 4000) -> str:
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text[:max_length]


class LocalAgent:
    """v4.0 Agent with all vibecoder features."""
    
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
        self.streaming = False
        self.stream_task = None
        self.last_ai_response = ""
        
        self.downloads_dir = Path.home() / "Downloads" / "AntigravityRemote"
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
    
    async def connect(self):
        url = f"{self.server_url}/{self.user_id}"
        logger.info("🔌 Connecting to server...")
        
        try:
            self.websocket = await websockets.connect(url)
            
            auth_msg = json.dumps({"auth_token": self.auth_token})
            await self.websocket.send(auth_msg)
            
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
                resp = json.loads(response)
                if "error" in resp:
                    logger.error(f"❌ Auth failed: {resp['error']}")
                    return False
            except asyncio.TimeoutError:
                logger.warning("⚠️ No auth response, assuming connected")
            
            logger.info("✅ Connected!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False
    
    async def send_alert(self, alert_type: str, text: str, include_screenshot: bool = False):
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
        except:
            pass
    
    async def send_ai_response(self, text: str):
        """Send AI response to Telegram (Two-Way Chat)."""
        if not self.websocket or not text:
            return
        
        try:
            await self.websocket.send(json.dumps({
                "type": "ai_response",
                "text": text
            }))
            self.last_ai_response = text
            logger.info(f"📤 Sent AI response: {text[:50]}...")
        except Exception as e:
            logger.error(f"Failed to send AI response: {e}")
    
    async def send_progress(self, task: str, percent: int, status: str = ""):
        """Send progress update to Telegram."""
        if not self.websocket:
            return
        
        try:
            await self.websocket.send(json.dumps({
                "type": "progress",
                "task": task,
                "percent": percent,
                "status": status
            }))
        except:
            pass
    
    async def stream_screen(self, fps: int = 2):
        """Stream screen to server."""
        logger.info(f"📺 Starting stream at {fps} FPS")
        delay = 1.0 / fps
        
        while self.streaming and self.websocket:
            try:
                path = take_screenshot(quality=50, max_width=1280)
                if path:
                    with open(path, "rb") as f:
                        frame_data = base64.b64encode(f.read()).decode()
                    cleanup_screenshot(path)
                    
                    await self.websocket.send(json.dumps({
                        "type": "stream_frame",
                        "data": frame_data
                    }))
                
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"Stream error: {e}")
                break
        
        logger.info("📺 Stream stopped")
    
    async def run_watchdog(self):
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
                
                # Try OCR for smart notifications
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
        """Transcribe voice using local Whisper."""
        # Try faster-whisper first
        try:
            from faster_whisper import WhisperModel
            
            if not hasattr(self, '_whisper_model'):
                logger.info("Loading Whisper model...")
                self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            
            wav_path = audio_path
            if audio_path.suffix.lower() == '.ogg':
                try:
                    from pydub import AudioSegment
                    wav_path = audio_path.with_suffix('.wav')
                    sound = AudioSegment.from_ogg(str(audio_path))
                    sound.export(str(wav_path), format="wav")
                except:
                    pass
            
            segments, _ = self._whisper_model.transcribe(str(wav_path), beam_size=5)
            text = " ".join([s.text for s in segments]).strip()
            
            if text:
                logger.info(f"Transcribed: {text[:50]}...")
                return text
                
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Whisper error: {e}")
        
        # Fallback to Google STT
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
                return text
        except:
            pass
        
        return ""
    
    def speak_text(self, text: str):
        """Text-to-speech using system TTS."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text[:500])
            engine.runAndWait()
            logger.info("🗣️ Spoke text")
        except ImportError:
            # Fallback to Windows built-in
            try:
                subprocess.run([
                    "powershell", "-Command",
                    f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak('{text[:200]}')"
                ], capture_output=True)
            except:
                logger.warning("TTS not available")
    
    def get_git_diff(self) -> str:
        """Get pending git diff."""
        try:
            result = subprocess.run(
                ["git", "diff", "--staged"],
                capture_output=True, text=True, timeout=10
            )
            if result.stdout:
                return result.stdout[:3500]
            
            # Try unstaged diff too
            result = subprocess.run(
                ["git", "diff"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout[:3500] if result.stdout else ""
        except:
            return ""

    async def handle_command(self, command: dict) -> dict:
        cmd_type = command.get("type")
        message_id = command.get("message_id")
        result = {"message_id": message_id, "success": False}
        
        try:
            if cmd_type == "screenshot":
                quality = command.get("quality", 85)
                path = take_screenshot(quality=quality)
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
                    
                    text = self.process_voice(path)
                    if text:
                        send_to_antigravity(f"(Voice): {text}")
                        result["text"] = text
                    else:
                        send_to_antigravity(f"Voice note: {path}")
                        result["text"] = "Audio saved"
                    
                    result["success"] = True
                except Exception as e:
                    result["error"] = str(e)
            
            elif cmd_type == "file":
                try:
                    data = base64.b64decode(command.get("data", ""))
                    name = sanitize_input(command.get("name", "file"), 100)
                    path = Path.cwd() / name
                    path.write_bytes(data)
                    send_to_antigravity(f"File saved: {path.absolute()}")
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
                pyautogui.hotkey('ctrl', '/')
                time.sleep(0.5)
                pyautogui.write(model, interval=0.05)
                time.sleep(0.5)
                pyautogui.press('enter')
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
            
            elif cmd_type == "start_stream":
                fps = command.get("fps", 2)
                self.streaming = True
                if self.stream_task:
                    self.stream_task.cancel()
                self.stream_task = asyncio.create_task(self.stream_screen(fps))
                result["success"] = True
            
            elif cmd_type == "stop_stream":
                self.streaming = False
                if self.stream_task:
                    self.stream_task.cancel()
                    self.stream_task = None
                result["success"] = True
            
            elif cmd_type == "get_diff":
                diff = self.get_git_diff()
                result["diff"] = diff
                result["success"] = True
            
            elif cmd_type == "tts":
                text = command.get("text", "")
                if text:
                    self.speak_text(text)
                result["success"] = True
            
            elif cmd_type == "sysinfo":
                import psutil
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                result["info"] = f"CPU: {cpu}%\nRAM: {mem.percent}%"
                result["success"] = True
            
            elif cmd_type == "files":
                items = os.listdir(os.getcwd())[:20]
                result["files"] = "\n".join(f"📄 {i}" for i in items)
                result["success"] = True
            
            else:
                logger.warning(f"Unknown command: {cmd_type}")
                
        except Exception as e:
            logger.error(f"Command error: {e}")
            result["error"] = "Command failed"
        
        return result
    
    async def send_heartbeat(self):
        while self.running and self.websocket:
            try:
                await asyncio.sleep(30)
                if self.websocket:
                    await self.websocket.send(json.dumps({"type": "ping"}))
            except:
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
                heartbeat_task = asyncio.create_task(self.send_heartbeat())
                
                try:
                    async for message in self.websocket:
                        command = json.loads(message)
                        cmd_type = command.get('type')
                        
                        if cmd_type == "pong":
                            continue
                        
                        logger.info(f"📥 {cmd_type}")
                        result = await self.handle_command(command)
                        await self.websocket.send(json.dumps(result))
                finally:
                    heartbeat_task.cancel()
                    self.streaming = False
                    
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
        self.streaming = False
        if self.websocket:
            asyncio.create_task(self.websocket.close())


async def run_agent(user_id: str, auth_token: str, server_url: str = None):
    agent = LocalAgent(user_id, auth_token, server_url)
    await agent.run()
