"""
Antigravity Remote - Utility Functions
"""

import re


def sanitize_input(text: str, max_length: int = 4000) -> str:
    """Sanitize user input."""
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text[:max_length]


def make_progress_bar(percent: int, width: int = 10) -> str:
    """Create ASCII progress bar."""
    filled = int(width * percent / 100)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}] {percent}%"
