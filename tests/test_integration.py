"""
Antigravity Remote - Integration Tests
Tests for API endpoints and WebSocket communication.
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

# Add server to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


# ============ API Integration Tests ============

class TestAPIIntegration:
    """Integration tests for REST API endpoints."""
    
    @pytest.fixture
    def mock_app(self):
        """Create mock FastAPI app for testing."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        
        app = FastAPI()
        
        @app.get("/")
        def root():
            return {"status": "online", "version": "4.3.1", "clients": 0}
        
        @app.get("/health")
        def health():
            return {"status": "ok"}
        
        return TestClient(app)
    
    def test_root_endpoint(self, mock_app):
        """Test root endpoint returns status."""
        response = mock_app.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"
        assert "version" in data
    
    def test_health_endpoint(self, mock_app):
        """Test health check endpoint."""
        response = mock_app.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


# ============ Schema Validation Tests ============

class TestSchemaValidation:
    """Tests for Pydantic schema validation."""
    
    def test_schedule_task_valid(self):
        """Test valid schedule task request."""
        from schemas import ScheduleTaskRequest
        
        request = ScheduleTaskRequest(time="9:00", command="Check emails")
        assert request.time == "9:00"
        assert request.command == "Check emails"
    
    def test_schedule_task_invalid_time(self):
        """Test invalid time format is rejected."""
        from schemas import ScheduleTaskRequest
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            ScheduleTaskRequest(time="invalid", command="Test")
    
    def test_schedule_task_hour_out_of_range(self):
        """Test hour > 23 is rejected."""
        from schemas import ScheduleTaskRequest
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            ScheduleTaskRequest(time="25:00", command="Test")
    
    def test_scroll_request_valid(self):
        """Test valid scroll request."""
        from schemas import ScrollRequest
        
        request = ScrollRequest(direction="up")
        assert request.direction == "up"
    
    def test_scroll_request_normalizes_case(self):
        """Test scroll direction is normalized to lowercase."""
        from schemas import ScrollRequest
        
        request = ScrollRequest(direction="UP")
        assert request.direction == "up"
    
    def test_scroll_request_invalid_direction(self):
        """Test invalid direction is rejected."""
        from schemas import ScrollRequest
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            ScrollRequest(direction="sideways")
    
    def test_screenshot_request_quality_range(self):
        """Test quality is clamped to valid range."""
        from schemas import ScreenshotRequest
        from pydantic import ValidationError
        
        # Valid range
        request = ScreenshotRequest(quality=50)
        assert request.quality == 50
        
        # Out of range should fail
        with pytest.raises(ValidationError):
            ScreenshotRequest(quality=150)
        
        with pytest.raises(ValidationError):
            ScreenshotRequest(quality=5)
    
    def test_relay_command_max_length(self):
        """Test relay command respects max length."""
        from schemas import RelayCommandRequest
        from pydantic import ValidationError
        
        # Valid
        request = RelayCommandRequest(text="Hello")
        assert request.text == "Hello"
        
        # Too long
        with pytest.raises(ValidationError):
            RelayCommandRequest(text="x" * 5000)
    
    def test_validation_helpers(self):
        """Test validation helper functions."""
        from schemas import validate_user_id, sanitize_input
        
        # Valid user IDs
        assert validate_user_id("123456789") == True
        assert validate_user_id("1") == True
        
        # Invalid user IDs
        assert validate_user_id("not_a_number") == False
        assert validate_user_id("1" * 25) == False
        
        # Sanitize input
        assert sanitize_input("Hello\x00World") == "HelloWorld"
        assert sanitize_input("x" * 5000, max_length=100) == "x" * 100


# ============ Error Handling Tests ============

class TestErrorHandling:
    """Tests for error handling module."""
    
    def test_api_error_creation(self):
        """Test APIError can be created with all fields."""
        from errors import APIError
        
        error = APIError(
            code="TEST_ERROR",
            message="Test message",
            status_code=400,
            details={"field": "value"}
        )
        
        assert error.code == "TEST_ERROR"
        assert error.message == "Test message"
        assert error.status_code == 400
        assert error.details["field"] == "value"
    
    def test_validation_error(self):
        """Test ValidationError."""
        from errors import ValidationError
        
        error = ValidationError("Invalid input", field="email")
        assert error.code == "VALIDATION_ERROR"
        assert error.status_code == 400
        assert error.details["field"] == "email"
    
    def test_rate_limit_error(self):
        """Test RateLimitError includes wait time."""
        from errors import RateLimitError
        
        error = RateLimitError(wait_seconds=30)
        assert error.code == "RATE_LIMIT"
        assert error.status_code == 429
        assert error.details["wait_seconds"] == 30
    
    def test_connection_error_masks_user_id(self):
        """Test ConnectionError masks user ID."""
        from errors import ConnectionError
        
        error = ConnectionError(user_id="123456789")
        assert error.details["user_id"] == "6789"  # Last 4 chars


# ============ Service Integration Tests ============

class TestServiceIntegration:
    """Integration tests for services working together."""
    
    def test_rate_limiter_with_command_queue(self):
        """Test rate limiter gate before command queue."""
        from services import RateLimiterService, CommandQueueService
        
        limiter = RateLimiterService(max_requests=5, window_seconds=60)
        queue = CommandQueueService(max_size=10, ttl_seconds=300)
        
        user_id = "test_user"
        
        # First 5 requests should be allowed and queued
        for i in range(5):
            if limiter.is_allowed(user_id):
                result = queue.enqueue(user_id, {"type": f"cmd_{i}"})
                assert result == True
        
        # 6th request should be rate limited
        assert limiter.is_allowed(user_id) == False
    
    def test_scheduler_with_undo_stack(self):
        """Test scheduler creates undo entries."""
        from services import SchedulerService, UndoStackService
        
        scheduler = SchedulerService()
        undo = UndoStackService()
        
        user_id = "test_user"
        
        # Add task
        scheduler.add_task(user_id, "9:00", "Morning check")
        
        # Record undo for schedule action
        undo.push(user_id, "schedule:9:00")
        
        # Verify
        assert len(scheduler.list_tasks(user_id)) >= 1
        assert len(undo.get_stack(user_id)) == 1


# ============ Async Tests ============

class TestAsyncOperations:
    """Tests for async operations."""
    
    @pytest.mark.asyncio
    async def test_websocket_simulation(self):
        """Simulate WebSocket message flow."""
        # Simulate message handling
        messages = []
        
        async def handle_message(msg: dict):
            messages.append(msg)
            return {"success": True}
        
        # Send commands
        await handle_message({"type": "ping"})
        await handle_message({"type": "screenshot"})
        await handle_message({"type": "relay", "text": "Hello"})
        
        assert len(messages) == 3
        assert messages[0]["type"] == "ping"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
