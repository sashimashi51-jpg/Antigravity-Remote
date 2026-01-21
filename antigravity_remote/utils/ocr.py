"""OCR utilities for Antigravity Remote."""

import logging
from typing import Optional, Tuple

import mss
from PIL import Image

logger = logging.getLogger(__name__)

# Lazy import pytesseract
_pytesseract = None


def _get_pytesseract():
    """Lazy load pytesseract with path configuration."""
    global _pytesseract
    if _pytesseract is None:
        try:
            import pytesseract
            from ..config import config
            
            if config.tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = config.tesseract_path
            
            _pytesseract = pytesseract
        except ImportError:
            logger.error("pytesseract not installed. Run: pip install pytesseract")
            raise
    return _pytesseract


def scan_screen() -> Tuple[str, int]:
    """
    Capture screenshot and extract text using OCR.
    
    Returns:
        Tuple of (extracted text, image hash for change detection).
    """
    pytesseract = _get_pytesseract()
    
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        img = Image.frombytes('RGB', sct_img.size, sct_img.bgra, 'raw', 'BGRX')
        
        # Extract text
        text = pytesseract.image_to_string(img).lower()
        
        # Simple hash for change detection (first 10KB of image data)
        img_hash = hash(img.tobytes()[:10000])
        
        return text, img_hash


# Keyword lists for detection
APPROVAL_KEYWORDS = [
    "run command", "accept changes", "proceed", "approve",
    "allow", "confirm", "yes or no", "y/n", "always allow",
    "do you want", "permission", "authorize"
]

DONE_KEYWORDS = [
    "anything else", "let me know", "task complete", "done!",
    "successfully", "finished", "completed", "all set",
    "ready for", "is there anything"
]

ERROR_KEYWORDS = [
    "error:", "failed", "exception", "traceback", "cannot",
    "permission denied", "not found", "invalid", "quota exceeded"
]


def detect_keywords(text: str) -> Optional[Tuple[str, str]]:
    """
    Detect important keywords in screen text.
    
    Args:
        text: The OCR-extracted text to search.
        
    Returns:
        Tuple of (category, keyword) if detected, None otherwise.
        Categories: 'approval', 'done', 'error'
    """
    for keyword in APPROVAL_KEYWORDS:
        if keyword in text:
            return ('approval', keyword)
    
    for keyword in DONE_KEYWORDS:
        if keyword in text:
            return ('done', keyword)
    
    for keyword in ERROR_KEYWORDS:
        if keyword in text:
            return ('error', keyword)
    
    return None
