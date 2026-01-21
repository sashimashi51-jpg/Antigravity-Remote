"""Screenshot utilities for Antigravity Remote."""

import logging
import os
import tempfile
from typing import Optional

import mss
import mss.tools

logger = logging.getLogger(__name__)


def take_screenshot() -> Optional[str]:
    """
    Capture a screenshot of the primary monitor.
    
    Returns:
        Path to the temporary screenshot file, or None on failure.
    """
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            sct_img = sct.grab(monitor)
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=tmp.name)
                logger.debug(f"Screenshot saved to {tmp.name}")
                return tmp.name
                
    except Exception as e:
        logger.error(f"Error taking screenshot: {e}")
        return None


def cleanup_screenshot(path: str) -> None:
    """
    Remove a temporary screenshot file.
    
    Args:
        path: Path to the screenshot file.
    """
    try:
        if path and os.path.exists(path):
            os.remove(path)
            logger.debug(f"Cleaned up screenshot: {path}")
    except Exception as e:
        logger.warning(f"Error cleaning up screenshot: {e}")
