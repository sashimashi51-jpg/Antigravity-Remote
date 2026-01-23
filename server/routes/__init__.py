"""
Antigravity Remote - Routes Package
"""

from .api import router as api_router, init_routes as init_api_routes
from .websocket import router as ws_router, init_websocket

__all__ = [
    "api_router",
    "ws_router", 
    "init_api_routes",
    "init_websocket",
]
