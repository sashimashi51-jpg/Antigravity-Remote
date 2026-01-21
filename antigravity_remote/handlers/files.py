"""File command handlers for Antigravity Remote."""

import logging
import os
import subprocess

import psutil
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from .base import is_authorized
from ..config import config

logger = logging.getLogger(__name__)


async def sysinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show system information."""
    if not await is_authorized(update):
        return
    
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('C:/')
    
    msg = f"""⚙️ *System Info*
CPU: `{cpu}%`
RAM: `{mem.percent}%` ({mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB)
Disk C: `{disk.percent}%` ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)
"""
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List files in workspace."""
    if not await is_authorized(update):
        return
    
    try:
        items = os.listdir(config.workspace_path)
        files = []
        for item in items[:30]:
            path = config.workspace_path / item
            icon = "📄" if path.is_file() else "📁"
            files.append(f"{icon} {item}")
        
        await update.message.reply_text(
            f"📂 *Files in workspace:*\n" + "\n".join(files),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def read_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Read a file's contents."""
    if not await is_authorized(update):
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /read filename.txt")
        return
    
    filepath = config.workspace_path / args[0]
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()[:3000]
        
        await update.message.reply_text(
            f"📄 *{args[0]}*:\n```\n{content}\n```",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"Error reading file: {e}")


async def diff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show git diff."""
    if not await is_authorized(update):
        return
    
    try:
        result = subprocess.run(
            ['git', 'diff', '--stat'],
            cwd=config.workspace_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        output = result.stdout[:3000] or "No changes"
        
        await update.message.reply_text(
            f"📊 *Git Diff:*\n```\n{output}\n```",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show command history."""
    if not await is_authorized(update):
        return
    
    from ..state import state
    
    logs = state.get_recent_logs(10)
    
    if not logs:
        await update.message.reply_text("📋 No commands logged yet.")
        return
    
    log_text = "\n".join([
        f"`{entry.to_dict()['time']}`: {entry.message[:50]}"
        for entry in logs
    ])
    
    await update.message.reply_text(
        f"📋 *Recent Commands:*\n{log_text}",
        parse_mode=ParseMode.MARKDOWN
    )
