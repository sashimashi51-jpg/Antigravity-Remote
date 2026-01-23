"""
Antigravity Remote - Error Handling
Per api-builder-SKILL.md patterns for consistent error responses.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Base API error with code and message."""
    
    def __init__(self, code: str, message: str, status_code: int = 400, details: dict = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ValidationError(APIError):
    """Input validation failed."""
    
    def __init__(self, message: str, field: str = None):
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=400,
            details={"field": field} if field else {}
        )


class AuthenticationError(APIError):
    """Authentication failed."""
    
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            code="AUTH_ERROR",
            message=message,
            status_code=401
        )


class NotFoundError(APIError):
    """Resource not found."""
    
    def __init__(self, resource: str = "Resource"):
        super().__init__(
            code="NOT_FOUND",
            message=f"{resource} not found",
            status_code=404
        )


class RateLimitError(APIError):
    """Rate limit exceeded."""
    
    def __init__(self, wait_seconds: int):
        super().__init__(
            code="RATE_LIMIT",
            message=f"Rate limit exceeded. Wait {wait_seconds}s",
            status_code=429,
            details={"wait_seconds": wait_seconds}
        )


class ConnectionError(APIError):
    """Client not connected."""
    
    def __init__(self, user_id: str):
        super().__init__(
            code="NOT_CONNECTED",
            message="Client not connected",
            status_code=503,
            details={"user_id": user_id[-4:]}  # Masked
        )


class QueueFullError(APIError):
    """Command queue is full."""
    
    def __init__(self):
        super().__init__(
            code="QUEUE_FULL",
            message="Command queue is full",
            status_code=503
        )


# ============ Error Handler ============

async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Global handler for APIError exceptions."""
    logger.warning(f"API Error: {exc.code} - {exc.message}")
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.message,
            "code": exc.code,
            **exc.details
        }
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler for unexpected exceptions."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "code": "INTERNAL_ERROR"
        }
    )


def register_error_handlers(app):
    """Register error handlers with FastAPI app."""
    app.add_exception_handler(APIError, api_error_handler)
    # Don't add generic handler in dev - let errors propagate for debugging
