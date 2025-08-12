#!/usr/bin/env python3
"""
Yahoo Fantasy Sports API Authentication Example

This script demonstrates how to use the comprehensive Yahoo authentication system
for accessing Yahoo Fantasy Sports APIs.

Usage:
    python examples/yahoo_auth_example.py [command]

Commands:
    auth        - Perform initial authentication
    status      - Check authentication status
    refresh     - Refresh tokens
    test-api    - Test authenticated API request
    revoke      - Revoke stored tokens

Prerequisites:
    1. Set YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET environment variables
    2. Register your application at https://developer.yahoo.com/apps/
    3. Configure redirect URI as http://localhost:8080/callback
"""

import asyncio
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import Settings
from src.agents.yahoo_auth import YahooAuth, YahooAuthError, YahooTokenExpiredError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn


console = Console()


def print_header():
    """Print application header."""
    console.print(Panel.fit(
        "[bold blue]Yahoo Fantasy Sports API Authentication[/bold blue]\n"
        "[dim]Comprehensive OAuth2 authentication system[/dim]",
        border_style="blue"
    ))


def print_status(auth: YahooAuth):
    """Print detailed authentication status."""
    status = auth.get_status()
    
    # Create status table
    table = Table(title="Authentication Status", border_style="green")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    
    # Add status rows
    table.add_row("State", f"[{'green' if status['authenticated'] else 'red'}]{status['state']}[/]")
    table.add_row("Authenticated", f"[{'green' if status['authenticated'] else 'red'}]{status['authenticated']}[/]")
    table.add_row("Has Tokens", f"[{'green' if status['has_tokens'] else 'yellow'}]{status['has_tokens']}[/]")
    table.add_row("Redirect URI", status['redirect_uri'])
    
    if status['has_tokens']:
        table.add_row("Token Type", status.get('token_type', 'N/A'))
        table.add_row("Scope", status.get('scope', 'N/A'))
        table.add_row("Expires At", status.get('expires_at', 'N/A'))
        table.add_row("Expires In", f"{status.get('expires_in_seconds', 0)} seconds")
        table.add_row("Is Expired", f"[{'red' if status.get('is_expired') else 'green'}]{status.get('is_expired')}[/]")
    
    console.print(table)


async def cmd_authenticate():
    """Perform OAuth2 authentication."""
    console.print("\n[bold yellow]Starting Yahoo OAuth2 Authentication[/bold yellow]")
    
    try:
        settings = Settings()
        auth = YahooAuth(settings)
        
        # Check if already authenticated
        if auth.is_authenticated:
            console.print("[green]✅ Already authenticated with valid tokens![/green]")
            print_status(auth)
            return
        
        # Try token refresh first if we have expired tokens
        if auth.tokens and auth.auth_state.value == "token_expired":
            console.print("[yellow]⏳ Attempting to refresh expired tokens...[/yellow]")
            try:
                await auth.refresh_tokens()
                console.print("[green]✅ Tokens refreshed successfully![/green]")
                print_status(auth)
                return
            except YahooTokenExpiredError:
                console.print("[yellow]⚠️  Token refresh failed, proceeding with new authentication[/yellow]")
        
        # Perform new authentication
        console.print("\n[bold]📋 Authentication Instructions:[/bold]")
        console.print("1. A browser window will open with Yahoo's authorization page")
        console.print("2. Log in to your Yahoo account if required")
        console.print("3. Grant permissions to the application")
        console.print("4. Wait for the success message")
        console.print("\n[dim]Press Enter when ready...[/dim]")
        input()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Waiting for authorization...", total=None)
            
            try:
                tokens = await auth.authenticate(timeout=300, auto_open_browser=True)
                progress.update(task, completed=True)
                
                console.print("\n[green]🎉 Authentication successful![/green]")
                console.print(f"[dim]Access token: {tokens.access_token[:20]}...[/dim]")
                console.print(f"[dim]Expires at: {tokens.expires_at}[/dim]")
                
                print_status(auth)
                
            except YahooAuthError as e:
                progress.stop()
                console.print(f"\n[red]❌ Authentication failed: {e}[/red]")
                sys.exit(1)
    
    except Exception as e:
        console.print(f"[red]❌ Error during authentication: {e}[/red]")
        sys.exit(1)


async def cmd_status():
    """Check authentication status."""
    console.print("\n[bold yellow]Checking Authentication Status[/bold yellow]")
    
    try:
        settings = Settings()
        auth = YahooAuth(settings)
        print_status(auth)
        
        if auth.is_authenticated:
            console.print("\n[green]✅ Ready to make authenticated API requests![/green]")
        elif auth.tokens:
            if auth.tokens.is_expired:
                console.print("\n[yellow]⚠️  Tokens are expired. Run 'refresh' or 'auth' command.[/yellow]")
            else:
                console.print("\n[yellow]⚠️  Authentication state unclear. Try 'auth' command.[/yellow]")
        else:
            console.print("\n[red]❌ Not authenticated. Run 'auth' command first.[/red]")
    
    except Exception as e:
        console.print(f"[red]❌ Error checking status: {e}[/red]")
        sys.exit(1)


async def cmd_refresh():
    """Refresh access tokens."""
    console.print("\n[bold yellow]Refreshing Access Tokens[/bold yellow]")
    
    try:
        settings = Settings()
        auth = YahooAuth(settings)
        
        if not auth.tokens:
            console.print("[red]❌ No tokens found. Run 'auth' command first.[/red]")
            return
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Refreshing tokens...", total=None)
            
            try:
                tokens = await auth.refresh_tokens()
                progress.update(task, completed=True)
                
                console.print("\n[green]✅ Tokens refreshed successfully![/green]")
                console.print(f"[dim]New expires at: {tokens.expires_at}[/dim]")
                print_status(auth)
                
            except YahooTokenExpiredError as e:
                progress.stop()
                console.print(f"\n[red]❌ Refresh failed: {e}[/red]")
                console.print("[yellow]💡 Try running 'auth' command for new authentication[/yellow]")
    
    except Exception as e:
        console.print(f"[red]❌ Error during refresh: {e}[/red]")
        sys.exit(1)


async def cmd_test_api():
    """Test authenticated API request."""
    console.print("\n[bold yellow]Testing Authenticated API Request[/bold yellow]")
    
    try:
        settings = Settings()
        auth = YahooAuth(settings)
        
        # Ensure we're authenticated
        try:
            await auth.ensure_authenticated()
        except YahooTokenExpiredError:
            console.print("[red]❌ Not authenticated. Run 'auth' command first.[/red]")
            return
        
        console.print("[blue]🔍 Making test API request to get user profile...[/blue]")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Making API request...", total=None)
            
            try:
                async with auth.authenticated_session() as session:
                    # Test endpoint: Get user profile
                    url = f"{auth.YAHOO_API_BASE}/users;use_login=1"
                    
                    async with session.get(url) as response:
                        progress.update(task, completed=True)
                        
                        if response.status == 200:
                            data = await response.text()
                            console.print(f"\n[green]✅ API request successful![/green]")
                            console.print(f"[dim]Status: {response.status}[/dim]")
                            console.print(f"[dim]Response size: {len(data)} characters[/dim]")
                            console.print(f"[dim]Content type: {response.headers.get('content-type', 'unknown')}[/dim]")
                            
                            # Show first 200 characters of response
                            if len(data) > 200:
                                preview = data[:200] + "..."
                            else:
                                preview = data
                            
                            console.print(f"\n[bold]Response Preview:[/bold]")
                            console.print(Panel(preview, border_style="green"))
                            
                        else:
                            console.print(f"\n[red]❌ API request failed![/red]")
                            console.print(f"[dim]Status: {response.status}[/dim]")
                            error_text = await response.text()
                            if error_text:
                                console.print(f"[dim]Error: {error_text[:200]}[/dim]")
                            
            except Exception as e:
                progress.stop()
                console.print(f"\n[red]❌ API request failed: {e}[/red]")
    
    except Exception as e:
        console.print(f"[red]❌ Error during API test: {e}[/red]")
        sys.exit(1)


async def cmd_revoke():
    """Revoke stored tokens."""
    console.print("\n[bold yellow]Revoking Stored Tokens[/bold yellow]")
    
    try:
        settings = Settings()
        auth = YahooAuth(settings)
        
        if not auth.tokens:
            console.print("[yellow]⚠️  No tokens found to revoke.[/yellow]")
            return
        
        # Confirm revocation
        console.print("[red]⚠️  This will remove all stored authentication tokens.[/red]")
        confirm = console.input("[bold]Are you sure? (y/N): [/bold]").lower()
        
        if confirm != 'y':
            console.print("[blue]Operation cancelled.[/blue]")
            return
        
        auth.revoke_tokens()
        console.print("[green]✅ Tokens revoked successfully![/green]")
        console.print("[dim]You will need to authenticate again to use the API.[/dim]")
    
    except Exception as e:
        console.print(f"[red]❌ Error during revocation: {e}[/red]")
        sys.exit(1)


async def main(command):
    """Yahoo Fantasy Sports API Authentication Tool."""
    print_header()
    
    if command == 'auth':
        await cmd_authenticate()
    elif command == 'status':
        await cmd_status()
    elif command == 'refresh':
        await cmd_refresh()
    elif command == 'test-api':
        await cmd_test_api()
    elif command == 'revoke':
        await cmd_revoke()
    else:
        console.print(f"[red]Error: Unknown command '{command}'[/red]")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_header()
        console.print("\n[bold red]Error: Command required[/bold red]")
        console.print("\n[bold]Available commands:[/bold]")
        console.print("  [green]auth[/green]     - Perform initial authentication")
        console.print("  [green]status[/green]   - Check authentication status")  
        console.print("  [green]refresh[/green]  - Refresh access tokens")
        console.print("  [green]test-api[/green] - Test authenticated API request")
        console.print("  [green]revoke[/green]   - Revoke stored tokens")
        console.print("\n[dim]Example: python examples/yahoo_auth_example.py auth[/dim]")
        sys.exit(1)
    
    command = sys.argv[1]
    if command not in ['auth', 'status', 'refresh', 'test-api', 'revoke']:
        console.print(f"[red]Error: Unknown command '{command}'[/red]")
        sys.exit(1)
    
    try:
        asyncio.run(main(command))
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {e}[/red]")
        sys.exit(1)