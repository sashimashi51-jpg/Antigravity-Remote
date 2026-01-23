"""
Antigravity Remote - Test Suite
Following testing-architect-SKILL.md patterns.
"""

import pytest
import sys
import os

# Add server to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


# ============ Unit Tests for Services ============

class TestRateLimiterService:
    """Unit tests for RateLimiterService."""
    
    def setup_method(self):
        from services import RateLimiterService
        self.limiter = RateLimiterService(max_requests=5, window_seconds=60)
    
    def test_allows_requests_under_limit(self):
        """Should allow requests under the limit."""
        for i in range(5):
            assert self.limiter.is_allowed("user1") == True
    
    def test_blocks_requests_over_limit(self):
        """Should block requests over the limit."""
        for i in range(5):
            self.limiter.is_allowed("user1")
        assert self.limiter.is_allowed("user1") == False
    
    def test_different_users_have_separate_limits(self):
        """Should track limits per user."""
        for i in range(5):
            self.limiter.is_allowed("user1")
        
        # user2 should still be allowed
        assert self.limiter.is_allowed("user2") == True
    
    def test_get_wait_time_zero_when_no_requests(self):
        """Should return 0 wait time for new user."""
        assert self.limiter.get_wait_time("newuser") == 0


class TestCommandQueueService:
    """Unit tests for CommandQueueService."""
    
    def setup_method(self):
        from services import CommandQueueService
        self.queue = CommandQueueService(max_size=3, ttl_seconds=300)
    
    def test_enqueue_command(self):
        """Should enqueue command successfully."""
        result = self.queue.enqueue("user1", {"type": "test"})
        assert result == True
    
    def test_dequeue_all_returns_queued_commands(self):
        """Should return all queued commands."""
        self.queue.enqueue("user1", {"type": "cmd1"})
        self.queue.enqueue("user1", {"type": "cmd2"})
        
        commands = self.queue.dequeue_all("user1")
        
        assert len(commands) == 2
        assert commands[0]["type"] == "cmd1"
        assert commands[1]["type"] == "cmd2"
    
    def test_dequeue_clears_queue(self):
        """Should clear queue after dequeue."""
        self.queue.enqueue("user1", {"type": "test"})
        self.queue.dequeue_all("user1")
        
        assert self.queue.get_queue_size("user1") == 0
    
    def test_max_size_enforced(self):
        """Should reject commands when queue is full."""
        for i in range(3):
            self.queue.enqueue("user1", {"type": f"cmd{i}"})
        
        result = self.queue.enqueue("user1", {"type": "overflow"})
        assert result == False


class TestSchedulerService:
    """Unit tests for SchedulerService."""
    
    def setup_method(self):
        from services import SchedulerService
        self.scheduler = SchedulerService()
    
    def test_add_task_valid_time(self):
        """Should add task with valid time format."""
        result = self.scheduler.add_task("user1", "9:00", "Check emails")
        assert result == True
    
    def test_add_task_invalid_time(self):
        """Should reject invalid time format."""
        result = self.scheduler.add_task("user1", "invalid", "Bad task")
        assert result == False
    
    def test_list_tasks_returns_added_tasks(self):
        """Should list all added tasks."""
        self.scheduler.add_task("user1", "9:00", "Task 1")
        self.scheduler.add_task("user1", "14:30", "Task 2")
        
        tasks = self.scheduler.list_tasks("user1")
        assert len(tasks) >= 2
    
    def test_clear_tasks(self):
        """Should clear all tasks for user."""
        self.scheduler.add_task("user1", "9:00", "Task")
        self.scheduler.clear_tasks("user1")
        
        tasks = self.scheduler.list_tasks("user1")
        assert len(tasks) == 0


class TestHeartbeatService:
    """Unit tests for HeartbeatService."""
    
    def setup_method(self):
        from services import HeartbeatService
        self.heartbeat = HeartbeatService(timeout_seconds=60)
    
    def test_record_heartbeat(self):
        """Should record heartbeat."""
        self.heartbeat.record_heartbeat("user1")
        assert self.heartbeat.is_alive("user1") == True
    
    def test_is_alive_false_without_heartbeat(self):
        """Should return False for user without heartbeat."""
        assert self.heartbeat.is_alive("unknown") == False
    
    def test_remove_heartbeat(self):
        """Should remove heartbeat."""
        self.heartbeat.record_heartbeat("user1")
        self.heartbeat.remove("user1")
        assert self.heartbeat.is_alive("user1") == False


class TestAuthService:
    """Unit tests for AuthService."""
    
    def setup_method(self):
        from services import AuthService
        self.auth = AuthService(auth_secret="test-secret", token_expiry_days=30)
    
    def test_generate_token_returns_tuple(self):
        """Should return token and expiry."""
        token, expires_at = self.auth.generate_token("user123")
        
        assert isinstance(token, str)
        assert len(token) == 32
        assert isinstance(expires_at, int)
    
    def test_validate_token_success(self):
        """Should validate freshly generated token."""
        token, _ = self.auth.generate_token("user123")
        result = self.auth.validate_token("user123", token)
        
        assert result == True
    
    def test_validate_token_wrong_user(self):
        """Should reject token for wrong user."""
        token, _ = self.auth.generate_token("user123")
        result = self.auth.validate_token("user456", token)
        
        assert result == False
    
    def test_validate_token_invalid(self):
        """Should reject invalid token."""
        result = self.auth.validate_token("user123", "invalid_token_here")
        
        assert result == False


class TestProgressService:
    """Unit tests for ProgressService."""
    
    def setup_method(self):
        from services import ProgressService
        self.progress = ProgressService()
    
    def test_update_progress(self):
        """Should update progress."""
        self.progress.update("user1", "Building", 50, "Step 5/10")
        
        p = self.progress.get("user1")
        assert p["task"] == "Building"
        assert p["percent"] == 50
    
    def test_percent_clamped(self):
        """Should clamp percent between 0-100."""
        self.progress.update("user1", "Task", 150)
        assert self.progress.get("user1")["percent"] == 100
        
        self.progress.update("user1", "Task", -50)
        assert self.progress.get("user1")["percent"] == 0
    
    def test_clear_progress(self):
        """Should clear progress."""
        self.progress.update("user1", "Task", 50)
        self.progress.clear("user1")
        
        assert self.progress.get("user1") is None


# ============ Integration Tests ============

class TestServicesIntegration:
    """Integration tests for services working together."""
    
    def test_command_queue_with_rate_limiter(self):
        """Test command queue respects rate limiting pattern."""
        from services import CommandQueueService, RateLimiterService
        
        rate_limiter = RateLimiterService(max_requests=10, window_seconds=60)
        queue = CommandQueueService()
        
        user_id = "testuser"
        
        # Check rate limit before enqueueing
        if rate_limiter.is_allowed(user_id):
            result = queue.enqueue(user_id, {"type": "test"})
            assert result == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
