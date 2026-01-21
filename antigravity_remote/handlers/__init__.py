"""Handler modules for Antigravity Remote."""

from .control import (
    start_command,
    pause_command,
    resume_command,
    cancel_command,
    key_command,
    lock_command,
    unlock_command,
)
from .screen import (
    status_command,
    scroll_command,
    accept_command,
    reject_command,
    undo_command,
)
from .files import (
    sysinfo_command,
    files_command,
    read_command,
    diff_command,
    log_command,
)
from .monitoring import (
    heartbeat_command,
    watchdog_command,
    schedule_command,
)
from .ai import (
    model_command,
    summary_command,
    handle_message,
    handle_model_callback,
)
from .quick import (
    quick_replies_command,
    handle_quick_callback,
    handle_voice,
)

__all__ = [
    # Control
    "start_command",
    "pause_command",
    "resume_command",
    "cancel_command",
    "key_command",
    "lock_command",
    "unlock_command",
    # Screen
    "status_command",
    "scroll_command",
    "accept_command",
    "reject_command",
    "undo_command",
    # Files
    "sysinfo_command",
    "files_command",
    "read_command",
    "diff_command",
    "log_command",
    # Monitoring
    "heartbeat_command",
    "watchdog_command",
    "schedule_command",
    # AI
    "model_command",
    "summary_command",
    "handle_message",
    "handle_model_callback",
    # Quick
    "quick_replies_command",
    "handle_quick_callback",
    "handle_voice",
]
