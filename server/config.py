"""
Antigravity Remote - Configuration
Centralized config following Skill.md unifiedConfig pattern.
"""

import os


class Config:
    """Centralized configuration - never use os.environ directly in other files."""
    BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    PORT: int = int(os.environ.get("PORT", 10000))
    AUTH_SECRET: str = os.environ.get("AUTH_SECRET", "antigravity-remote-2026")
    
    # Timeouts and limits
    HEARTBEAT_INTERVAL: int = 30
    HEARTBEAT_TIMEOUT: int = 60
    COMMAND_QUEUE_TTL: int = 300
    COMMAND_QUEUE_MAX_SIZE: int = 50
    RATE_LIMIT_REQUESTS: int = 60
    RATE_LIMIT_WINDOW: int = 60
    TOKEN_EXPIRY_DAYS: int = 30
    STREAM_FPS: int = 2
    UNDO_STACK_SIZE: int = 10


config = Config()
