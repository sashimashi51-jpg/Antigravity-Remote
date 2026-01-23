"""
Antigravity Remote - Two-Way Chat Clipboard Monitor
Monitors clipboard for AI responses and sends them to Telegram.
"""

import time
import threading
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ClipboardMonitor:
    """
    Monitors clipboard for changes to detect AI responses.
    When AI copies text to clipboard or when text changes in IDE,
    this captures it and sends to the callback.
    """
    
    def __init__(self, callback: Callable[[str], None], interval: float = 1.0):
        """
        Args:
            callback: Function to call with new clipboard content
            interval: How often to check clipboard (seconds)
        """
        self.callback = callback
        self.interval = interval
        self.running = False
        self.last_content = ""
        self.thread: Optional[threading.Thread] = None
        
        # Keywords that indicate an AI response (not user-typed)
        self.ai_indicators = [
            "```",  # Code blocks
            "I'll ",
            "I've ",
            "I will ",
            "I can ",
            "Here's ",
            "Let me ",
            "Sure,",
            "Certainly",
            "Here is",
            "The following",
        ]
        
        # Minimum length for AI response
        self.min_length = 50
    
    def start(self):
        """Start monitoring clipboard."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("📋 Clipboard monitor started")
    
    def stop(self):
        """Stop monitoring clipboard."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        logger.info("📋 Clipboard monitor stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        try:
            import pyperclip
        except ImportError:
            logger.warning("pyperclip not installed, clipboard monitoring disabled")
            return
        
        while self.running:
            try:
                current = pyperclip.paste()
                
                # Check if content changed and looks like AI response
                if current != self.last_content and self._is_ai_response(current):
                    logger.info(f"📋 Detected AI response: {current[:50]}...")
                    self.callback(current)
                
                self.last_content = current
                
            except Exception as e:
                logger.error(f"Clipboard error: {e}")
            
            time.sleep(self.interval)
    
    def _is_ai_response(self, text: str) -> bool:
        """Check if text looks like an AI response."""
        if not text or len(text) < self.min_length:
            return False
        
        # Check for AI indicators
        text_lower = text.lower()
        for indicator in self.ai_indicators:
            if indicator.lower() in text_lower:
                return True
        
        # Check for code blocks (strong indicator)
        if "```" in text:
            return True
        
        # Check for bullet points / numbered lists
        if "\n- " in text or "\n1. " in text or "\n* " in text:
            return True
        
        return False


class AIResponseDetector:
    """
    Detects AI responses by monitoring the IDE window.
    Uses OCR or accessibility APIs to read the screen.
    """
    
    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback
        self.running = False
        self.last_response_hash = ""
    
    def start(self):
        """Start detecting AI responses."""
        self.running = True
        # Start in background thread
        threading.Thread(target=self._detection_loop, daemon=True).start()
    
    def stop(self):
        """Stop detection."""
        self.running = False
    
    def _detection_loop(self):
        """Main detection loop using screen reading."""
        try:
            import pytesseract
            from PIL import Image
            import mss
        except ImportError:
            logger.warning("OCR dependencies not installed, using clipboard-only mode")
            return
        
        while self.running:
            try:
                # Take screenshot of active window
                with mss.mss() as sct:
                    monitor = sct.monitors[1]
                    screenshot = sct.grab(monitor)
                    
                    # Convert to PIL Image
                    img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')
                    
                    # OCR the image
                    text = pytesseract.image_to_string(img)
                    
                    # Look for AI response patterns
                    response = self._extract_ai_response(text)
                    if response:
                        # Check if this is new
                        import hashlib
                        response_hash = hashlib.md5(response.encode()).hexdigest()
                        
                        if response_hash != self.last_response_hash:
                            self.last_response_hash = response_hash
                            self.callback(response)
                
            except Exception as e:
                logger.error(f"OCR error: {e}")
            
            time.sleep(5.0)  # Check every 5 seconds
    
    def _extract_ai_response(self, text: str) -> Optional[str]:
        """Extract AI response from screen text."""
        lines = text.split('\n')
        
        # Look for response markers
        for i, line in enumerate(lines):
            # Common AI response starters
            if any(marker in line for marker in ["🤖", "AI:", "Claude:", "Gemini:", "GPT:"]):
                # Return everything after the marker
                response_lines = lines[i:]
                return '\n'.join(response_lines[:50])  # Limit to 50 lines
        
        return None
