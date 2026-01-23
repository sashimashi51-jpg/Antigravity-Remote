"""
Antigravity Remote - SQLite Database Layer
Provides persistence for scheduled tasks, command queue, and audit logs.
"""

import sqlite3
import json
import time
import os
import threading
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Database path - use data directory
DB_PATH = os.environ.get("ANTIGRAVITY_DB_PATH", "/tmp/antigravity.db")

# Thread-local storage for connections
_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Get thread-local SQLite connection."""
    if not hasattr(_local, 'connection'):
        _local.connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.connection.row_factory = sqlite3.Row
        _local.connection.execute("PRAGMA journal_mode=WAL")
        _local.connection.execute("PRAGMA foreign_keys=ON")
    return _local.connection


def init_database():
    """Initialize database schema."""
    conn = get_connection()
    
    # Scheduled Tasks Table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            hour INTEGER NOT NULL,
            minute INTEGER NOT NULL,
            command TEXT NOT NULL,
            last_run TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, hour, minute, command)
        )
    """)
    
    # Command Queue Table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            command_data TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
    """)
    
    # Audit Log Table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # User Sessions Table (for undo stack, state, etc.)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id TEXT PRIMARY KEY,
            undo_stack TEXT DEFAULT '[]',
            last_ai_response TEXT,
            is_paused INTEGER DEFAULT 0,
            is_locked INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Indexes for performance
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user ON scheduled_tasks(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_command_queue_user ON command_queue(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_command_queue_expires ON command_queue(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at)")
    
    conn.commit()
    logger.info(f"Database initialized: {DB_PATH}")


# ============ Scheduled Tasks Repository ============

class ScheduledTasksRepository:
    """Repository for scheduled tasks persistence."""
    
    @staticmethod
    def add_task(user_id: str, hour: int, minute: int, command: str) -> bool:
        """Add a scheduled task."""
        try:
            conn = get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO scheduled_tasks (user_id, hour, minute, command, is_active) VALUES (?, ?, ?, ?, 1)",
                (user_id, hour, minute, command)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding task: {e}")
            return False
    
    @staticmethod
    def get_tasks(user_id: str) -> List[Dict]:
        """Get all tasks for a user."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, hour, minute, command, last_run FROM scheduled_tasks WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    
    @staticmethod
    def get_due_tasks(user_id: str, hour: int, minute: int) -> List[Dict]:
        """Get tasks due at the specified time."""
        conn = get_connection()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        rows = conn.execute(
            """SELECT id, command FROM scheduled_tasks 
               WHERE user_id = ? AND hour = ? AND minute = ? AND is_active = 1 
               AND (last_run IS NULL OR last_run != ?)""",
            (user_id, hour, minute, current_time)
        ).fetchall()
        
        # Mark as run
        for row in rows:
            conn.execute(
                "UPDATE scheduled_tasks SET last_run = ? WHERE id = ?",
                (current_time, row['id'])
            )
        conn.commit()
        
        return [dict(row) for row in rows]
    
    @staticmethod
    def clear_tasks(user_id: str):
        """Clear all tasks for a user."""
        conn = get_connection()
        conn.execute("DELETE FROM scheduled_tasks WHERE user_id = ?", (user_id,))
        conn.commit()


# ============ Command Queue Repository ============

class CommandQueueRepository:
    """Repository for command queue persistence."""
    
    @staticmethod
    def enqueue(user_id: str, command: dict, ttl_seconds: int = 300) -> bool:
        """Add command to queue."""
        try:
            conn = get_connection()
            now = time.time()
            expires_at = now + ttl_seconds
            
            conn.execute(
                "INSERT INTO command_queue (user_id, command_data, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (user_id, json.dumps(command), now, expires_at)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error enqueuing command: {e}")
            return False
    
    @staticmethod
    def dequeue_all(user_id: str) -> List[dict]:
        """Get and remove all pending commands for user."""
        conn = get_connection()
        now = time.time()
        
        # Clean expired first
        conn.execute("DELETE FROM command_queue WHERE expires_at < ?", (now,))
        
        # Get valid commands
        rows = conn.execute(
            "SELECT id, command_data FROM command_queue WHERE user_id = ? AND expires_at >= ? ORDER BY created_at",
            (user_id, now)
        ).fetchall()
        
        # Delete retrieved commands
        if rows:
            ids = [row['id'] for row in rows]
            placeholders = ','.join('?' * len(ids))
            conn.execute(f"DELETE FROM command_queue WHERE id IN ({placeholders})", ids)
        
        conn.commit()
        return [json.loads(row['command_data']) for row in rows]
    
    @staticmethod
    def get_queue_size(user_id: str) -> int:
        """Get number of pending commands."""
        conn = get_connection()
        now = time.time()
        
        row = conn.execute(
            "SELECT COUNT(*) as count FROM command_queue WHERE user_id = ? AND expires_at >= ?",
            (user_id, now)
        ).fetchone()
        return row['count'] if row else 0


# ============ Audit Log Repository ============

class AuditLogRepository:
    """Repository for audit log persistence."""
    
    @staticmethod
    def log(user_id: str, action: str, details: str = ""):
        """Add audit log entry."""
        try:
            conn = get_connection()
            # Mask user_id for privacy
            masked_user = user_id[-4:] if len(user_id) > 4 else "****"
            
            conn.execute(
                "INSERT INTO audit_log (user_id, action, details) VALUES (?, ?, ?)",
                (masked_user, action, details[:200] if details else "")
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Audit log error: {e}")
    
    @staticmethod
    def get_recent(limit: int = 100) -> List[Dict]:
        """Get recent audit logs."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT user_id, action, details, created_at FROM audit_log ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


# ============ User Sessions Repository ============

class UserSessionRepository:
    """Repository for user session data (undo stack, state, AI responses)."""
    
    @staticmethod
    def get_or_create(user_id: str) -> Dict:
        """Get or create user session."""
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM user_sessions WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        
        if row:
            return {
                "user_id": row['user_id'],
                "undo_stack": json.loads(row['undo_stack'] or '[]'),
                "last_ai_response": row['last_ai_response'] or "",
                "is_paused": bool(row['is_paused']),
                "is_locked": bool(row['is_locked'])
            }
        
        # Create new session
        conn.execute(
            "INSERT INTO user_sessions (user_id) VALUES (?)",
            (user_id,)
        )
        conn.commit()
        return {
            "user_id": user_id,
            "undo_stack": [],
            "last_ai_response": "",
            "is_paused": False,
            "is_locked": False
        }
    
    @staticmethod
    def update_undo_stack(user_id: str, stack: List):
        """Update undo stack."""
        conn = get_connection()
        conn.execute(
            "UPDATE user_sessions SET undo_stack = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (json.dumps(stack[-10:]), user_id)  # Keep last 10
        )
        conn.commit()
    
    @staticmethod
    def push_undo(user_id: str, action: str):
        """Push action to undo stack."""
        session = UserSessionRepository.get_or_create(user_id)
        stack = session['undo_stack']
        stack.append({"action": action, "time": time.time()})
        UserSessionRepository.update_undo_stack(user_id, stack)
    
    @staticmethod
    def set_ai_response(user_id: str, response: str):
        """Store last AI response."""
        conn = get_connection()
        conn.execute(
            """INSERT INTO user_sessions (user_id, last_ai_response) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET last_ai_response = ?, updated_at = CURRENT_TIMESTAMP""",
            (user_id, response, response)
        )
        conn.commit()
    
    @staticmethod
    def get_ai_response(user_id: str) -> str:
        """Get last AI response."""
        session = UserSessionRepository.get_or_create(user_id)
        return session['last_ai_response']
    
    @staticmethod
    def set_paused(user_id: str, paused: bool):
        """Set paused state."""
        conn = get_connection()
        conn.execute(
            """INSERT INTO user_sessions (user_id, is_paused) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET is_paused = ?, updated_at = CURRENT_TIMESTAMP""",
            (user_id, int(paused), int(paused))
        )
        conn.commit()
    
    @staticmethod
    def is_paused(user_id: str) -> bool:
        """Check if user is paused."""
        session = UserSessionRepository.get_or_create(user_id)
        return session['is_paused']


# Initialize database on import
init_database()
