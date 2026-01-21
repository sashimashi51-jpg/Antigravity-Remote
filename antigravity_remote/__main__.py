"""CLI entry point for Antigravity Remote (Local Agent)."""

import argparse
import asyncio
import logging
import sys

from .agent import run_agent
from .secrets import get_user_id, save_user_id, clear_user_id, get_user_config_path


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - %(message)s',
        level=level
    )


def register_user() -> None:
    """Interactive user registration flow."""
    print("🔑 Antigravity Remote - User Registration")
    print()
    print("To get your Telegram User ID:")
    print("1. Open Telegram and message @userinfobot")
    print("2. It will reply with your user ID")
    print()
    
    user_id = input("Enter your Telegram User ID: ").strip()
    
    if not user_id.isdigit():
        print("❌ Invalid user ID. It should be a number.")
        sys.exit(1)
    
    save_user_id(user_id)
    print(f"✅ Registered! Your user ID: {user_id}")
    print(f"   Config saved to: {get_user_config_path()}")
    print()
    print("Now run: antigravity-remote")


def show_status() -> None:
    """Show current registration status."""
    user_id = get_user_id()
    
    print("📊 Antigravity Remote - Status")
    print()
    
    if user_id:
        print(f"✅ Registered User ID: {user_id}")
    else:
        print("❌ Not registered. Run: antigravity-remote --register")
    
    print(f"📁 Config directory: {get_user_config_path()}")
    print()
    print("📱 Telegram Bot: @antigravityrcbot")
    print("🔗 https://t.me/antigravityrcbot")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Remote control your Antigravity AI assistant via Telegram"
    )
    
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register your Telegram user ID"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show registration status"
    )
    parser.add_argument(
        "--unregister",
        action="store_true",
        help="Remove your registration"
    )
    parser.add_argument(
        "--server",
        help="Custom server URL (default: wss://antigravity-remote.onrender.com/ws)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="antigravity-remote 2.0.0"
    )
    
    args = parser.parse_args()
    
    # Handle registration commands
    if args.register:
        register_user()
        return
    
    if args.status:
        show_status()
        return
    
    if args.unregister:
        clear_user_id()
        print("✅ Unregistered. Your user ID has been removed.")
        return
    
    setup_logging(args.verbose)
    
    # Check registration
    user_id = get_user_id()
    if not user_id:
        print("❌ Not registered!")
        print()
        print("Run: antigravity-remote --register")
        sys.exit(1)
    
    print("🚀 Antigravity Remote Control")
    print(f"   User ID: {user_id}")
    print(f"   Bot: @antigravityrcbot")
    print()
    print("📱 Open Telegram and message @antigravityrcbot to control your PC!")
    print()
    print("Press Ctrl+C to stop")
    print()
    
    try:
        asyncio.run(run_agent(user_id, args.server))
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()
