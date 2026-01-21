"""
Antigravity Remote - Control your Antigravity AI assistant via Telegram.

Usage:
    pip install antigravity-remote
    antigravity-remote --token YOUR_TOKEN --user-id YOUR_ID
    
Or use environment variables:
    export TELEGRAM_BOT_TOKEN=your_token
    export TELEGRAM_USER_ID=your_id
    antigravity-remote
"""

from .bot import AntigravityBot
from .config import Config, config
from .state import BotState, state

__version__ = "1.0.0"
__all__ = ["AntigravityBot", "Config", "config", "BotState", "state"]
