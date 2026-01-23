"""
Antigravity Remote - Pydantic Validation Schemas
Per api-builder-SKILL.md patterns for input validation.
"""

from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
import re


# ============ Request Schemas ============

class RelayCommandRequest(BaseModel):
    """Relay text command to AI."""
    text: str = Field(min_length=1, max_length=4000, description="Text to send to AI")


class ScheduleTaskRequest(BaseModel):
    """Schedule a task at specific time."""
    time: str = Field(description="Time in HH:MM format (e.g., 9:00 or 14:30)")
    command: str = Field(min_length=1, max_length=500, description="Command to execute")
    
    @field_validator('time')
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not re.match(r'^\d{1,2}:\d{2}$', v):
            raise ValueError('Time must be in HH:MM format')
        parts = v.split(':')
        hour, minute = int(parts[0]), int(parts[1])
        if hour < 0 or hour > 23:
            raise ValueError('Hour must be 0-23')
        if minute < 0 or minute > 59:
            raise ValueError('Minute must be 0-59')
        return v


class ScreenshotRequest(BaseModel):
    """Screenshot request with optional quality."""
    quality: int = Field(default=85, ge=10, le=100, description="JPEG quality 10-100")


class ScrollRequest(BaseModel):
    """Scroll screen in a direction."""
    direction: str = Field(default="down", description="up, down, top, or bottom")
    
    @field_validator('direction')
    @classmethod
    def validate_direction(cls, v: str) -> str:
        allowed = ['up', 'down', 'top', 'bottom']
        if v.lower() not in allowed:
            raise ValueError(f'Direction must be one of: {allowed}')
        return v.lower()


class StreamRequest(BaseModel):
    """Start streaming with FPS."""
    fps: int = Field(default=2, ge=1, le=10, description="Frames per second 1-10")


class KeyComboRequest(BaseModel):
    """Send key combination."""
    combo: str = Field(min_length=1, max_length=50, description="Key combo like ctrl+c")


class FileUploadRequest(BaseModel):
    """File upload metadata."""
    name: str = Field(min_length=1, max_length=255, description="Filename")
    data: str = Field(description="Base64 encoded file data")


class VoiceRequest(BaseModel):
    """Voice message data."""
    data: str = Field(description="Base64 encoded audio")
    format: str = Field(default="ogg", description="Audio format")


class PhotoRequest(BaseModel):
    """Photo message data."""
    data: str = Field(description="Base64 encoded image")


class TTSRequest(BaseModel):
    """Text-to-speech request."""
    text: str = Field(min_length=1, max_length=1000, description="Text to speak")


class WatchdogRequest(BaseModel):
    """Watchdog toggle."""
    enabled: bool = Field(description="Enable or disable watchdog")


class ModelSwitchRequest(BaseModel):
    """Switch AI model."""
    model: str = Field(min_length=1, max_length=100, description="Model name")


# ============ Response Schemas ============

class BaseResponse(BaseModel):
    """Base response with success status."""
    success: bool = True
    message_id: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response."""
    success: bool = False
    error: str
    code: Optional[str] = None


class ScreenshotResponse(BaseResponse):
    """Screenshot response with image data."""
    image: Optional[str] = None  # Base64 encoded


class DiffResponse(BaseResponse):
    """Git diff response."""
    diff: Optional[str] = None


class StatusResponse(BaseModel):
    """Server status response."""
    status: str = "online"
    version: str
    clients: int = 0
    features: List[str] = []


class QueuedResponse(BaseModel):
    """Command queued response."""
    queued: bool = True
    queue_size: int


class ProgressUpdate(BaseModel):
    """Progress update from agent."""
    task: str
    percent: int = Field(ge=0, le=100)
    status: Optional[str] = None


class AIResponse(BaseModel):
    """AI response for two-way chat."""
    text: str = Field(max_length=10000)


# ============ WebSocket Message Schemas ============

class WebSocketAuthMessage(BaseModel):
    """WebSocket authentication message."""
    auth_token: str = Field(min_length=32, max_length=64)


class WebSocketCommand(BaseModel):
    """Generic WebSocket command."""
    type: str = Field(min_length=1, max_length=50)
    message_id: Optional[str] = None


# ============ Validation Helpers ============

def validate_user_id(user_id: str) -> bool:
    """Validate Telegram user ID format."""
    try:
        int(user_id)
        return len(user_id) <= 20
    except ValueError:
        return False


def sanitize_input(text: str, max_length: int = 4000) -> str:
    """Sanitize user input."""
    if not text:
        return ""
    # Remove control characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text[:max_length]
