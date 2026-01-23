"""CLI entry point for Antigravity Remote (Secure Version)."""

import argparse
import asyncio
import logging
import sys

from .agent import run_agent
from .secrets import (
    get_user_config, save_user_config, clear_user_config, 
    get_user_config_path, get_token_expiry_info, is_token_expired
)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=level)


def register_user() -> None:
    """Secure user registration."""
    print("🔐 Antigravity Remote - Secure Registration")
    print()
    print("To get your credentials:")
    print("1. Open Telegram and message @antigravityrcbot")
    print("2. Send /start - you'll see your ID and Auth Token")
    print()
    
    user_id = input("Enter your Telegram User ID: ").strip()
    if not user_id.isdigit():
        print("❌ Invalid user ID. It should be a number.")
        sys.exit(1)
    
    auth_token = input("Enter your Auth Token: ").strip()
    if len(auth_token) != 32:
        print("❌ Invalid auth token. Should be 32 characters.")
        sys.exit(1)
    
    save_user_config(user_id, auth_token)
    print("✅ Registered securely!")
    print(f"   Config saved to: {get_user_config_path()}")
    print(f"   Token valid for 30 days")
    print()
    print("Now run: antigravity-remote")


def show_status() -> None:
    config = get_user_config()
    expiry_info = get_token_expiry_info()
    
    print("📊 Antigravity Remote - Status")
    print()
    if config:
        print(f"✅ User ID: {config['user_id']}")
        token = config.get('auth_token', '')
        if token:
            print(f"🔑 Auth Token: {token[:8]}...")
        else:
            print("🔑 Auth Token: (not set)")
        
        # Show expiry
        if expiry_info["valid"]:
            days = expiry_info.get("days_remaining", -1)
            if days > 7:
                print(f"⏰ {expiry_info['message']}")
            elif days > 0:
                print(f"⚠️ {expiry_info['message']} - Consider refreshing!")
            else:
                print(f"ℹ️ {expiry_info['message']}")
        else:
            print(f"❌ {expiry_info['message']} - Run /start in Telegram to get a new token")
    else:
        print("❌ Not registered. Run: antigravity-remote --register")
    
    print(f"📁 Config: {get_user_config_path()}")
    print()
    print("📱 Bot: @antigravityrcbot")


def main() -> None:
    parser = argparse.ArgumentParser(description="Secure remote control for Antigravity AI")
    
    parser.add_argument("--register", action="store_true", help="Register your credentials")
    parser.add_argument("--status", action="store_true", help="Show registration status")
    parser.add_argument("--unregister", action="store_true", help="Remove your registration")
    parser.add_argument("--refresh", action="store_true", help="Refresh expired token")
    parser.add_argument("--id", help="Telegram User ID (overrides saved config)")
    parser.add_argument("--token", help="Auth Token (overrides saved config)")
    parser.add_argument("--server", help="Custom server URL")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--version", action="version", version="antigravity-remote 4.5.2")
    
    args = parser.parse_args()
    
    if args.register:
        register_user()
        return
    
    if args.status:
        show_status()
        return
    
    if args.unregister:
        clear_user_config()
        print("✅ Unregistered. Token removed from secure storage.")
        return
    
    if args.refresh:
        print("🔄 Token Refresh")
        print("Send /start to @antigravityrcbot to get a new token,")
        print("then run: antigravity-remote --register")
        return
    
    setup_logging(args.verbose)
    
    user_id = args.id
    auth_token = args.token
    
    if not user_id or not auth_token:
        config = get_user_config()
        if not config:
            if not user_id or not auth_token:
                print("❌ Not registered!")
                print()
                print("Usage:")
                print("  antigravity-remote --id YOUR_ID --token YOUR_TOKEN")
                print("  antigravity-remote --register")
                sys.exit(1)
        
        user_id = user_id or config.get("user_id")
        auth_token = auth_token or config.get("auth_token")
    
    # Check token expiry (only for saved config)
    if not args.id and not args.token and is_token_expired():
        print("⚠️ Your token has expired or is expiring soon!")
        print("Send /start to @antigravityrcbot for a new token.")
        print("Then run: antigravity-remote --register")
        print()
        response = input("Continue anyway? [y/N]: ").strip().lower()
        if response != 'y':
            sys.exit(0)
    
    user_id = config["user_id"]
    auth_token = config["auth_token"]
    
    if not auth_token:
        print("❌ No auth token configured!")
        print("Run: antigravity-remote --register")
        sys.exit(1)
    
    print("🔐 Antigravity Remote Control (Secure)")
    print(f"   User ID: {user_id}")
    print(f"   Auth: {auth_token[:8]}...")
    print(f"   Bot: @antigravityrcbot")
    
    expiry_info = get_token_expiry_info()
    if expiry_info.get("days_remaining", -1) > 0:
        print(f"   ⏰ {expiry_info['message']}")
    
    print()
    print("📱 Open Telegram and message @antigravityrcbot to control your PC!")
    print()
    print("Press Ctrl+C to stop")
    print()
    
    try:
        asyncio.run(run_agent(user_id, auth_token, args.server))
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()
