"""State management for Antigravity Remote bot."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class CommandLogEntry:
    """A single command log entry."""
    timestamp: datetime
    message: str
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.timestamp.strftime("%H:%M:%S"),
            "msg": self.message
        }


@dataclass
class BotState:
    """Mutable state for the Antigravity Remote bot."""
    
    # Control state
    paused: bool = False
    locked: bool = False
    
    # Background tasks
    heartbeat_task: Optional[asyncio.Task] = None
    watchdog_task: Optional[asyncio.Task] = None
    
    # Watchdog state
    watchdog_last_alert: float = 0.0
    watchdog_last_hash: Optional[int] = None
    watchdog_idle_count: int = 0
    
    # Command history
    command_log: list[CommandLogEntry] = field(default_factory=list)
    max_log_entries: int = 100
    
    def log_command(self, message: str) -> None:
        """Add a command to the log."""
        self.command_log.append(
            CommandLogEntry(timestamp=datetime.now(), message=message)
        )
        # Trim log if too long
        if len(self.command_log) > self.max_log_entries:
            self.command_log = self.command_log[-50:]
    
    def get_recent_logs(self, count: int = 10) -> list[CommandLogEntry]:
        """Get the most recent log entries."""
        return self.command_log[-count:]
    
    def cancel_tasks(self) -> None:
        """Cancel all background tasks."""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            self.heartbeat_task = None
        if self.watchdog_task:
            self.watchdog_task.cancel()
            self.watchdog_task = None
    
    def reset(self) -> None:
        """Reset state to defaults."""
        self.paused = False
        self.locked = False
        self.cancel_tasks()
        self.watchdog_last_alert = 0.0
        self.watchdog_last_hash = None
        self.watchdog_idle_count = 0


# Global state instance
state = BotState()
