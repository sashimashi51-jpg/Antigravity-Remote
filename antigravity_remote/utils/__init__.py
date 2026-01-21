"""Utility modules for Antigravity Remote."""

from .automation import focus_antigravity, send_to_antigravity, send_key_combo, scroll_screen
from .screenshot import take_screenshot, cleanup_screenshot
from .ocr import scan_screen, detect_keywords

__all__ = [
    "focus_antigravity",
    "send_to_antigravity", 
    "send_key_combo",
    "scroll_screen",
    "take_screenshot",
    "cleanup_screenshot",
    "scan_screen",
    "detect_keywords",
]
