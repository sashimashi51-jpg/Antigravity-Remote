"""Base handler functionality for Antigravity Remote."""

import logging
from functools import wraps
from typing import Callable, TypeVar, ParamSpec

from telegram import Update
from telegram.ext import ContextTypes

from ..config import config

logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


def authorized_only(func: Callable[P, T]) -> Callable[P, T]:
    """Decorator to require authorization for a handler."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = str(update.effective_user.id)
        
        if user_id != config.allowed_user_id:
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            return None
        
        return await func(update, context, *args, **kwargs)
    
    return wrapper


async def is_authorized(update: Update) -> bool:
    """Check if the update is from an authorized user."""
    return str(update.effective_user.id) == config.allowed_user_id
