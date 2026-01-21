"""Configuration management for Antigravity Remote."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .secrets import get_bot_token, get_user_id


@dataclass
class Config:
    """Configuration for Antigravity Remote bot."""
    
    # Telegram settings - token is embedded, user ID from local config
    bot_token: str = field(default_factory=get_bot_token)
    allowed_user_id: str = field(default_factory=lambda: get_user_id() or "")
    
    # Workspace settings
    workspace_path: Path = field(
        default_factory=lambda: Path(os.getenv("WORKSPACE_PATH", os.getcwd()))
    )
    
    # Security
    lock_password: str = field(default_factory=lambda: os.getenv("LOCK_PASSWORD", "unlock123"))
    
    # OCR settings
    tesseract_path: Optional[str] = field(
        default_factory=lambda: os.getenv(
            "TESSERACT_PATH", 
            r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        )
    )
    
    # Timing settings
    watchdog_interval: int = field(
        default_factory=lambda: int(os.getenv("WATCHDOG_INTERVAL", "5"))
    )
    alert_cooldown: int = field(
        default_factory=lambda: int(os.getenv("ALERT_COOLDOWN", "30"))
    )
    
    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []
        
        if not self.bot_token:
            errors.append("Bot token not available")
        if not self.allowed_user_id:
            errors.append("User not registered. Run: antigravity-remote --register")
        if not self.workspace_path.exists():
            errors.append(f"WORKSPACE_PATH does not exist: {self.workspace_path}")
            
        return errors
    
    def reload_user_id(self) -> None:
        """Reload user ID from local config."""
        self.allowed_user_id = get_user_id() or ""
    
    @classmethod
    def from_env(cls) -> "Config":
        """Create configuration from environment variables."""
        return cls()


# Global config instance
config = Config.from_env()
