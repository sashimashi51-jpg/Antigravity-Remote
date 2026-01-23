"""Screenshot utilities for Antigravity Remote v4.0."""

import logging
import os
import tempfile
from typing import Optional

import mss
import mss.tools

logger = logging.getLogger(__name__)


def take_screenshot(quality: int = 85, max_width: int = None) -> Optional[str]:
    """
    Capture a screenshot with optional compression.
    
    Args:
        quality: JPEG quality (1-100). Lower = smaller file. Default 85.
        max_width: Max width in pixels. If screen is wider, resize. None = no resize.
    
    Returns:
        Path to the temporary screenshot file, or None on failure.
    """
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            sct_img = sct.grab(monitor)
            
            # Convert to PIL for processing
            try:
                from PIL import Image
                import io
                
                # Create PIL Image from raw data
                img = Image.frombytes('RGB', sct_img.size, sct_img.bgra, 'raw', 'BGRX')
                
                # Resize if needed
                if max_width and img.width > max_width:
                    ratio = max_width / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((max_width, new_height), Image.LANCZOS)
                
                # Save as JPEG with compression
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    img.save(tmp.name, 'JPEG', quality=quality, optimize=True)
                    logger.debug(f"Screenshot: {tmp.name} (quality={quality}, width={img.width})")
                    return tmp.name
                    
            except ImportError:
                # Fallback to PNG if Pillow not available
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    mss.tools.to_png(sct_img.rgb, sct_img.size, output=tmp.name)
                    logger.debug(f"Screenshot (PNG): {tmp.name}")
                    return tmp.name
                
    except Exception as e:
        logger.error(f"Error taking screenshot: {e}")
        return None


def cleanup_screenshot(path: str) -> None:
    """Remove a temporary screenshot file."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
            logger.debug(f"Cleaned up: {path}")
    except Exception as e:
        logger.warning(f"Error cleaning up screenshot: {e}")
