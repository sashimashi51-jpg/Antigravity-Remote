"""
Antigravity Remote - Services Layer
Business logic services extracted from main.py for v4.2.0 architecture.
"""

import time
import hashlib
import secrets
from datetime import datetime
from typing import Dict, Optional, List, Any
from collections import defaultdict, deque

# Try to import database layer
try:
    from db import (
        ScheduledTasksRepository,
        CommandQueueRepository,
        AuditLogRepository,
        UserSessionRepository,
    )
    PERSISTENCE_ENABLED = True
except ImportError:
    PERSISTENCE_ENABLED = False


class RateLimiterService:
    """Rate limiting per user."""
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: Dict[str, list] = defaultdict(list)
    
    def is_allowed(self, user_id: str) -> bool:
        now = time.time()
        self.requests[user_id] = [t for t in self.requests[user_id] if now - t < self.window]
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        self.requests[user_id].append(now)
        return True
    
    def get_wait_time(self, user_id: str) -> int:
        if not self.requests[user_id]:
            return 0
        oldest = min(self.requests[user_id])
        return max(0, int(self.window - (time.time() - oldest)))


class CommandQueueService:
    """Command queue with SQLite persistence."""
    def __init__(self, max_size: int = 50, ttl_seconds: int = 300):
        self._memory_queues: Dict[str, deque] = defaultdict(deque)
        self.max_size = max_size
        self.ttl = ttl_seconds
    
    def enqueue(self, user_id: str, command: dict) -> bool:
        if PERSISTENCE_ENABLED:
            return CommandQueueRepository.enqueue(user_id, command, self.ttl)
        else:
            self._cleanup_expired(user_id)
            if len(self._memory_queues[user_id]) >= self.max_size:
                return False
            command["_queued_at"] = time.time()
            self._memory_queues[user_id].append(command)
            return True
    
    def dequeue_all(self, user_id: str) -> List[dict]:
        if PERSISTENCE_ENABLED:
            return CommandQueueRepository.dequeue_all(user_id)
        else:
            self._cleanup_expired(user_id)
            commands = list(self._memory_queues[user_id])
            self._memory_queues[user_id].clear()
            for cmd in commands:
                cmd.pop("_queued_at", None)
            return commands
    
    def _cleanup_expired(self, user_id: str):
        now = time.time()
        self._memory_queues[user_id] = deque(
            cmd for cmd in self._memory_queues[user_id]
            if now - cmd.get("_queued_at", 0) < self.ttl
        )
    
    def get_queue_size(self, user_id: str) -> int:
        if PERSISTENCE_ENABLED:
            return CommandQueueRepository.get_queue_size(user_id)
        else:
            self._cleanup_expired(user_id)
            return len(self._memory_queues[user_id])


class HeartbeatService:
    """Track client heartbeats."""
    def __init__(self, timeout_seconds: int = 60):
        self.last_heartbeat: Dict[str, float] = {}
        self.timeout = timeout_seconds
    
    def record_heartbeat(self, user_id: str):
        self.last_heartbeat[user_id] = time.time()
    
    def is_alive(self, user_id: str) -> bool:
        last = self.last_heartbeat.get(user_id, 0)
        return (time.time() - last) < self.timeout
    
    def remove(self, user_id: str):
        self.last_heartbeat.pop(user_id, None)
    
    def get_dead_clients(self, connected_clients: Dict[str, Any]) -> List[str]:
        now = time.time()
        return [uid for uid in connected_clients if now - self.last_heartbeat.get(uid, 0) > self.timeout]


class SchedulerService:
    """Scheduled tasks with SQLite persistence."""
    def __init__(self):
        self._memory_tasks: Dict[str, List[dict]] = defaultdict(list)
    
    def add_task(self, user_id: str, time_str: str, command: str) -> bool:
        try:
            hour, minute = map(int, time_str.split(':'))
            if PERSISTENCE_ENABLED:
                return ScheduledTasksRepository.add_task(user_id, hour, minute, command)
            else:
                self._memory_tasks[user_id].append({
                    "hour": hour, "minute": minute, "command": command, "last_run": None
                })
                return True
        except:
            return False
    
    def get_due_tasks(self, user_id: str) -> List[str]:
        now = datetime.now()
        if PERSISTENCE_ENABLED:
            tasks = ScheduledTasksRepository.get_due_tasks(user_id, now.hour, now.minute)
            return [t['command'] for t in tasks]
        else:
            due = []
            for task in self._memory_tasks.get(user_id, []):
                if task["hour"] == now.hour and task["minute"] == now.minute:
                    if task["last_run"] != now.strftime("%Y-%m-%d %H:%M"):
                        task["last_run"] = now.strftime("%Y-%m-%d %H:%M")
                        due.append(task["command"])
            return due
    
    def list_tasks(self, user_id: str) -> List[dict]:
        if PERSISTENCE_ENABLED:
            return ScheduledTasksRepository.get_tasks(user_id)
        return self._memory_tasks.get(user_id, [])
    
    def clear_tasks(self, user_id: str):
        if PERSISTENCE_ENABLED:
            ScheduledTasksRepository.clear_tasks(user_id)
        else:
            self._memory_tasks[user_id] = []


class UndoStackService:
    """Undo stack with SQLite persistence and in-memory fallback."""
    def __init__(self, max_size: int = 10):
        # In-memory fallback
        self._memory_stacks: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_size))
        self.max_size = max_size
    
    def push(self, user_id: str, action: str):
        if PERSISTENCE_ENABLED:
            UserSessionRepository.push_undo(user_id, action)
        else:
            self._memory_stacks[user_id].append({"action": action, "time": time.time()})
    
    def get_stack(self, user_id: str) -> List[dict]:
        if PERSISTENCE_ENABLED:
            session = UserSessionRepository.get_or_create(user_id)
            return session['undo_stack']
        return list(self._memory_stacks[user_id])
    
    def clear(self, user_id: str):
        if PERSISTENCE_ENABLED:
            UserSessionRepository.update_undo_stack(user_id, [])
        else:
            self._memory_stacks[user_id].clear()


class LiveStreamService:
    """Live screen streaming."""
    def __init__(self):
        self.frames: Dict[str, bytes] = {}
        self.last_update: Dict[str, float] = {}
        self.streaming: Dict[str, bool] = {}
    
    def update_frame(self, user_id: str, frame_data: bytes):
        self.frames[user_id] = frame_data
        self.last_update[user_id] = time.time()
    
    def get_frame(self, user_id: str) -> Optional[bytes]:
        return self.frames.get(user_id)
    
    def start_stream(self, user_id: str):
        self.streaming[user_id] = True
    
    def stop_stream(self, user_id: str):
        self.streaming[user_id] = False
    
    def is_streaming(self, user_id: str) -> bool:
        return self.streaming.get(user_id, False)


class ProgressService:
    """Track task progress."""
    def __init__(self):
        self.progress: Dict[str, dict] = {}
    
    def update(self, user_id: str, task: str, percent: int, status: str = ""):
        self.progress[user_id] = {
            "task": task,
            "percent": min(100, max(0, percent)),
            "status": status,
            "updated": time.time()
        }
    
    def get(self, user_id: str) -> Optional[dict]:
        return self.progress.get(user_id)
    
    def clear(self, user_id: str):
        self.progress.pop(user_id, None)


class AuditLoggerService:
    """Audit logging with SQLite persistence."""
    def __init__(self, max_entries: int = 1000):
        self._memory_logs: list = []
        self.max_entries = max_entries
    
    def log(self, user_id: str, action: str, details: str = ""):
        if PERSISTENCE_ENABLED:
            AuditLogRepository.log(user_id, action, details)
        else:
            entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "user_id": user_id[-4:] if len(user_id) > 4 else "****",
                "action": action,
                "details": details[:100] if details else ""
            }
            self._memory_logs.append(entry)
            if len(self._memory_logs) > self.max_entries:
                self._memory_logs = self._memory_logs[-self.max_entries:]


class AuthService:
    """Authentication service."""
    def __init__(self, auth_secret: str, token_expiry_days: int = 30):
        self.auth_secret = auth_secret
        self.token_expiry_days = token_expiry_days
    
    def generate_token(self, user_id: str) -> tuple:
        issue_time = int(time.time())
        expires_at = issue_time + (self.token_expiry_days * 86400)
        data = f"{user_id}:{self.auth_secret}:{issue_time}"
        token = hashlib.sha256(data.encode()).hexdigest()[:32]
        return token, expires_at
    
    def validate_token(self, user_id: str, token: str) -> bool:
        current_time = int(time.time())
        for days_ago in range(self.token_expiry_days + 1):
            for hour in range(0, 24, 6):
                test_time = current_time - (days_ago * 86400) - (hour * 3600)
                data = f"{user_id}:{self.auth_secret}:{test_time}"
                expected = hashlib.sha256(data.encode()).hexdigest()[:32]
                if secrets.compare_digest(token, expected):
                    return True
        # Legacy token support
        legacy_data = f"{user_id}:{self.auth_secret}"
        legacy_token = hashlib.sha256(legacy_data.encode()).hexdigest()[:32]
        return secrets.compare_digest(token, legacy_token)
