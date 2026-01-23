"""CLI entry point for Antigravity Remote (Secure Version)."""

import argparse
import asyncio
import logging
import sys
import os

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.logging import RichHandler
from rich.status import Status
from rich import print as rprint

from .agent import run_agent
from .secrets import (
    get_user_config, save_user_config, clear_user_config, 
    get_user_config_path, get_token_expiry_info, is_token_expired
)

VERSION = "4.5.5"
console = Console()

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)]
    )

def print_banner():
    """Print the killer splash screen."""
    banner_text = r"""
   _____        _   _                                _ _         
  / ____|      | | (_)                              (_) |        
 | |  __   __ _| |_ _  __ _ _ __ __ ___   _____ _ __ _| |_ _   _ 
 | | |_ | / _` | __| |/ _` | '__/ _` \ \ / / _ \ '__| | __| | | |
 | |__| || (_| | |_| | (_| | | | (_| |\ V /  __/ |  | | |_| |_| |
  \_____| \__,_|\__|_|\__, |_|  \__,_| \_/ \___|_|  |_|\__|\__, |
                       __/ |                                 __/ |
                      |___/                                 |___/ 
    """
    console.print(Panel(Text(banner_text, style="cyan"), title=f"v{VERSION}", subtitle="Remote Control for Antigravity AI", border_style="blue"))

def register_user() -> None:
    """Secure user registration."""
    print_banner()
    rprint("[bold blue]🔐 Antigravity Remote - Secure Registration[/bold blue]")
    rprint("\n[yellow]To get your credentials:[/yellow]")
    rprint("1. Open Telegram and message [bold green]@antigravityrcbot[/bold green]")
    rprint("2. Send /start - you'll see your ID and Auth Token\n")
    
    user_id = console.input("[bold blue]Enter your Telegram User ID:[/bold blue] ").strip()
    if not user_id.isdigit():
        rprint("[bold red]❌ Invalid user ID. It should be a number.[/bold red]")
        sys.exit(1)
    
    auth_token = console.input("[bold blue]Enter your Auth Token:[/bold blue] ").strip()
    if len(auth_token) != 32:
        rprint("[bold red]❌ Invalid auth token. Should be 32 characters.[/bold red]")
        sys.exit(1)
    
    save_user_config(user_id, auth_token)
    rprint("\n[bold green]✅ Registered securely![/bold green]")
    rprint(f"   Config saved to: [cyan]{get_user_config_path()}[/cyan]")
    rprint(f"   Token valid for 30 days\n")
    rprint("Now run: [bold white]antigravity-remote[/bold white]")

def show_status() -> None:
    config = get_user_config()
    expiry_info = get_token_expiry_info()
    
    print_banner()
    table = Table(title="Agent Configuration", border_style="cyan")
    table.add_column("Property", style="bold magenta")
    table.add_column("Value", style="white")

    if config:
        table.add_row("User ID", config['user_id'])
        token = config.get('auth_token', '')
        table.add_row("Auth Token", f"{token[:8]}..." if token else "[red]Not Set[/red]")
        
        # Expiry logic
        status_text = expiry_info["message"]
        days = expiry_info.get("days_remaining", -1)
        if expiry_info["valid"]:
            status_style = "green" if days > 7 else "yellow"
            table.add_row("Token Status", f"[{status_style}]{status_text}[/{status_style}]")
        else:
            table.add_row("Token Status", f"[red]{status_text}[/red]")
    else:
        table.add_row("Status", "[red]Not registered[/red]")
    
    table.add_row("Config Path", str(get_user_config_path()))
    table.add_row("Bot", "[dim]@antigravityrcbot[/dim]")
    
    console.print(table)
    if not config:
        rprint("\n[red]Run:[/red] [bold]antigravity-remote --register[/bold]")

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
    parser.add_argument("--version", action="version", version=f"antigravity-remote {VERSION}")
    
    args = parser.parse_args()
    
    if args.register:
        register_user()
        return
    
    if args.status:
        show_status()
        return
    
    if args.unregister:
        clear_user_config()
        rprint("[bold green]✅ Unregistered.[/bold green] Token removed from secure storage.")
        return
    
    if args.refresh:
        rprint("[bold yellow]🔄 Token Refresh[/bold yellow]")
        rprint("Send [bold green]/start[/bold green] to @antigravityrcbot to get a new token,")
        rprint("then run: [bold white]antigravity-remote --register[/bold white]")
        return
    
    print_banner()
    setup_logging(args.verbose)
    
    user_id = args.id
    auth_token = args.token
    
    if not user_id or not auth_token:
        config = get_user_config()
        if not config:
            rprint("[bold red]❌ Error: Not registered![/bold red]")
            rprint("\nUsage:")
            rprint("  [bold]antigravity-remote --id YOUR_ID --token YOUR_TOKEN[/bold]")
            rprint("  [bold]antigravity-remote --register[/bold]")
            sys.exit(1)
        
        user_id = user_id or config.get("user_id")
        auth_token = auth_token or config.get("auth_token")
    
    # If using CLI args, we don't check saved config
    if not args.id and not args.token:
        if is_token_expired():
            rprint("[bold yellow]⚠️ Your token has expired or is expiring soon![/bold yellow]")
            rprint("Send [bold green]/start[/bold green] to @antigravityrcbot for a new token.")
            rprint("Then run: [bold white]antigravity-remote --register[/bold white]\n")
            response = console.input("[bold cyan]Continue anyway? [y/N]: [/bold cyan]").strip().lower()
            if response != 'y':
                sys.exit(0)
    
    config_table = Table(box=None, show_header=False)
    config_table.add_row("[bold cyan]User ID:[/bold cyan]", user_id)
    config_table.add_row("[bold cyan]Auth Mode:[/bold cyan]", "Secure Token")
    config_table.add_row("[bold cyan]Target:[/bold cyan]", "@antigravityrcbot")
    
    console.print(Panel(config_table, title="[bold green]Connection Ready[/bold green]", border_style="green"))
    rprint("[bold white]📱 Control your PC from your phone.[/bold white]")
    rprint("[dim]Press Ctrl+C to stop[/dim]\n")
    
    try:
        with Status("[bold blue]Connecting to bridge server...", console=console, spinner="dots12"):
            asyncio.run(run_agent(user_id, auth_token, args.server))
    except KeyboardInterrupt:
        rprint("\n[bold yellow]👋 Shutting down...[/bold yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
