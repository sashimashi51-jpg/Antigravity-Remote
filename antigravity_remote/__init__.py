"""Antigravity Remote - Secure remote control via Telegram."""

__version__ = "4.5.3"

from .agent import LocalAgent, run_agent
from .secrets import get_user_config, save_user_config

__all__ = [
    "LocalAgent",
    "run_agent",
    "get_user_config",
    "save_user_config",
]
