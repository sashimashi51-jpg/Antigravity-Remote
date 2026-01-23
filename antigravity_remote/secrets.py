"""
Secure secrets management for Antigravity Remote.
Implements encrypted storage and token lifecycle management.
"""

import os
import json
import time
import hashlib
import base64
from pathlib import Path
from typing import Optional

# Try to use keyring for secure storage, fallback to obfuscated file
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

# Constants
SERVICE_NAME = "AntigravityRemote"
TOKEN_EXPIRY_DAYS = 30
TOKEN_EXPIRY_SECONDS = TOKEN_EXPIRY_DAYS * 24 * 60 * 60


def get_user_config_path() -> Path:
    """Get the user config directory path."""
    if os.name == 'nt':
        config_dir = Path(os.environ.get('APPDATA', '')) / 'AntigravityRemote'
    else:
        config_dir = Path.home() / '.config' / 'antigravity-remote'
    
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def _get_machine_key() -> bytes:
    """Get a machine-specific key for obfuscation (fallback when keyring unavailable)."""
    # Use username + machine name as seed (not cryptographically secure, but better than plaintext)
    seed = f"{os.getlogin()}:{os.environ.get('COMPUTERNAME', 'local')}"
    return hashlib.sha256(seed.encode()).digest()


def _obfuscate(data: str) -> str:
    """Simple XOR obfuscation for fallback storage."""
    key = _get_machine_key()
    data_bytes = data.encode()
    obfuscated = bytes(b ^ key[i % len(key)] for i, b in enumerate(data_bytes))
    return base64.b64encode(obfuscated).decode()


def _deobfuscate(data: str) -> str:
    """Reverse XOR obfuscation."""
    try:
        key = _get_machine_key()
        obfuscated = base64.b64decode(data.encode())
        original = bytes(b ^ key[i % len(key)] for i, b in enumerate(obfuscated))
        return original.decode()
    except Exception:
        return ""


def get_user_config() -> dict | None:
    """
    Get the registered user config (ID + auth token).
    Retrieves token from secure storage if available.
    """
    config_file = get_user_config_path() / 'config.json'
    
    if not config_file.exists():
        # Migration: check for old format
        old_file = get_user_config_path() / 'user.txt'
        if old_file.exists():
            user_id = old_file.read_text().strip()
            return {"user_id": user_id, "auth_token": "", "expires_at": 0}
        return None
    
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        user_id = config.get("user_id", "")
        expires_at = config.get("expires_at", 0)
        
        # Try to get token from keyring first
        if KEYRING_AVAILABLE:
            auth_token = keyring.get_password(SERVICE_NAME, user_id)
            if auth_token:
                return {"user_id": user_id, "auth_token": auth_token, "expires_at": expires_at}
        
        # Fallback to obfuscated storage
        obfuscated_token = config.get("auth_token_enc", "")
        if obfuscated_token:
            auth_token = _deobfuscate(obfuscated_token)
            return {"user_id": user_id, "auth_token": auth_token, "expires_at": expires_at}
        
        # Legacy plain token (migrate on next save)
        auth_token = config.get("auth_token", "")
        return {"user_id": user_id, "auth_token": auth_token, "expires_at": expires_at}
        
    except Exception:
        return None


def save_user_config(user_id: str, auth_token: str, expires_at: int = 0) -> None:
    """
    Save the user config with secure token storage.
    Uses keyring if available, otherwise obfuscated file storage.
    """
    config_file = get_user_config_path() / 'config.json'
    
    # Set expiry if not provided
    if expires_at == 0:
        expires_at = int(time.time()) + TOKEN_EXPIRY_SECONDS
    
    # Try to store token in keyring
    if KEYRING_AVAILABLE:
        try:
            keyring.set_password(SERVICE_NAME, user_id, auth_token)
            # Store only non-sensitive data in file
            config = {
                "user_id": user_id,
                "expires_at": expires_at,
                "storage": "keyring"
            }
            with open(config_file, 'w') as f:
                json.dump(config, f)
            return
        except Exception:
            pass  # Fall through to obfuscated storage
    
    # Fallback: obfuscated file storage
    config = {
        "user_id": user_id,
        "auth_token_enc": _obfuscate(auth_token),
        "expires_at": expires_at,
        "storage": "obfuscated"
    }
    
    with open(config_file, 'w') as f:
        json.dump(config, f)


def clear_user_config() -> None:
    """Clear the user config and remove token from secure storage."""
    config = get_user_config()
    
    # Remove from keyring if available
    if config and KEYRING_AVAILABLE:
        try:
            keyring.delete_password(SERVICE_NAME, config["user_id"])
        except Exception:
            pass
    
    # Remove config file
    config_file = get_user_config_path() / 'config.json'
    if config_file.exists():
        config_file.unlink()
    
    # Remove old format too
    old_file = get_user_config_path() / 'user.txt'
    if old_file.exists():
        old_file.unlink()


def is_token_expired() -> bool:
    """Check if the current token is expired or near expiry."""
    config = get_user_config()
    if not config:
        return True
    
    expires_at = config.get("expires_at", 0)
    if expires_at == 0:
        return False  # Legacy token, don't force expiry
    
    # Consider expired if less than 1 day remaining
    return time.time() > (expires_at - 86400)


def get_token_expiry_info() -> dict:
    """Get information about token expiry."""
    config = get_user_config()
    if not config:
        return {"valid": False, "message": "No token configured"}
    
    expires_at = config.get("expires_at", 0)
    if expires_at == 0:
        return {"valid": True, "message": "Legacy token (no expiry)", "days_remaining": -1}
    
    remaining = expires_at - time.time()
    days = int(remaining / 86400)
    
    if remaining <= 0:
        return {"valid": False, "message": "Token expired", "days_remaining": 0}
    elif days <= 7:
        return {"valid": True, "message": f"Token expires in {days} days", "days_remaining": days}
    else:
        return {"valid": True, "message": f"Token valid for {days} days", "days_remaining": days}


# Legacy compatibility
def get_user_id() -> str | None:
    config = get_user_config()
    return config["user_id"] if config else None


def save_user_id(user_id: str) -> None:
    save_user_config(user_id, "")
