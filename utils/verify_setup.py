#!/usr/bin/env python3
"""Credential-safe readiness check for the Yahoo Fantasy Football MCP."""

import asyncio
import importlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
SERVER_SCRIPT = PROJECT_ROOT / "fantasy_football_multi_league.py"
SERVER_NAME = "yahoo-fantasy-football"

EXPECTED_TOOLS = {
    "ff_get_leagues",
    "ff_get_league_info",
    "ff_get_standings",
    "ff_get_teams",
    "ff_get_roster",
    "ff_get_matchup",
    "ff_get_players",
    "ff_compare_teams",
    "ff_build_lineup",
    "ff_refresh_token",
    "ff_get_draft_results",
    "ff_get_waiver_wire",
    "ff_get_api_status",
    "ff_clear_cache",
    "ff_get_draft_rankings",
    "ff_get_draft_recommendation",
    "ff_analyze_draft_state",
    "ff_analyze_reddit_sentiment",
    "ff_get_player_news",
}

REQUIRED_IMPORTS = {
    "aiohttp": "aiohttp",
    "dotenv": "python-dotenv",
    "mcp": "mcp",
    "numpy": "numpy",
    "pandas": "pandas",
    "praw": "praw",
    "pydantic": "pydantic",
    "requests": "requests",
    "yfpy": "yfpy",
}


def is_configured(value) -> bool:
    """Return whether an environment value is real rather than blank/placeholder."""
    if value is None:
        return False
    normalized = str(value).strip()
    return bool(normalized) and not normalized.lower().startswith(("your_", "replace_"))


def check_env_file() -> tuple[bool, dict[str, str | None]]:
    """Check local credential-file presence and permissions without showing values."""
    print("1. Local credential file")
    try:
        from dotenv import dotenv_values
    except ImportError:
        print("   FAIL: python-dotenv is not installed")
        return False, {}

    if not ENV_FILE.is_file():
        print("   FAIL: .env is missing")
        print("   Create it from .env.example and keep it untracked.")
        return False, {}

    permissions_ok = True
    if sys.platform != "win32":
        mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
        permissions_ok = mode & 0o077 == 0
        if not permissions_ok:
            print("   FAIL: .env is readable by other users; run chmod 600 .env")

    values = dotenv_values(ENV_FILE)
    client_ready = all(
        is_configured(values.get(name))
        for name in ("YAHOO_CLIENT_ID", "YAHOO_CLIENT_SECRET")
    )
    oauth_ready = all(
        is_configured(values.get(name))
        for name in ("YAHOO_ACCESS_TOKEN", "YAHOO_REFRESH_TOKEN")
    )

    print(f"   Yahoo app credentials: {'CONFIGURED' if client_ready else 'PENDING'}")
    print(f"   Yahoo OAuth tokens: {'CONFIGURED' if oauth_ready else 'PENDING'}")
    if client_ready and not oauth_ready:
        print("   Next: run .venv/bin/python utils/setup_yahoo_auth.py")
    elif not client_ready:
        print("   Waiting for Yahoo to provide the Client ID and Client Secret.")

    if permissions_ok:
        print("   PASS: .env exists and is private")
    return permissions_ok, values


def check_dependencies() -> bool:
    """Import the core runtime dependencies."""
    print("2. Python dependencies")
    missing = []
    for module, package in REQUIRED_IMPORTS.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)

    if missing:
        print(f"   FAIL: missing packages: {', '.join(sorted(missing))}")
        return False

    print(f"   PASS: {len(REQUIRED_IMPORTS)} core dependencies import successfully")
    return True


def check_codex_registration() -> bool:
    """Confirm this MCP is registered with the local Codex installation."""
    print("3. Codex registration")
    if not shutil.which("codex"):
        print("   FAIL: codex command was not found")
        return False

    result = subprocess.run(
        ["codex", "mcp", "get", SERVER_NAME],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        print(f"   FAIL: MCP server '{SERVER_NAME}' is not registered")
        return False

    expected_command = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    expected_script = str(SERVER_SCRIPT)
    fields = {}
    for line in result.stdout.splitlines():
        name, separator, value = line.strip().partition(":")
        if separator:
            fields[name] = value.strip()

    if fields.get("command") != expected_command or fields.get("args") != expected_script:
        print(f"   FAIL: '{SERVER_NAME}' points to a different Python or server script")
        return False

    print(f"   PASS: '{SERVER_NAME}' points to this installation")
    return True


async def check_mcp_server() -> bool:
    """Start the real stdio server and verify its complete tool contract."""
    print("4. MCP server handshake")
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        print("   FAIL: mcp is not installed")
        return False

    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_SCRIPT)])
    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=15)
                result = await asyncio.wait_for(session.list_tools(), timeout=15)
    except Exception as exc:
        print(f"   FAIL: server did not initialize ({type(exc).__name__})")
        return False

    tool_names = {tool.name for tool in result.tools}
    if tool_names != EXPECTED_TOOLS:
        print(
            "   FAIL: tool contract mismatch "
            f"(expected {len(EXPECTED_TOOLS)}, found {len(tool_names)})"
        )
        return False

    print(f"   PASS: server initialized with all {len(tool_names)} tools")
    return True


def check_yahoo_access(values: dict[str, str | None]) -> str:
    """Conditionally verify Yahoo Fantasy entitlement without exposing the token."""
    print("5. Yahoo Fantasy access")
    access_token = values.get("YAHOO_ACCESS_TOKEN")
    if not is_configured(access_token):
        print("   PENDING: OAuth has not been completed yet")
        return "pending"

    try:
        import requests
    except ImportError:
        print("   FAIL: requests is not installed")
        return "failed"

    try:
        response = requests.get(
            "https://fantasysports.yahooapis.com/fantasy/v2/game/nfl?format=json",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException as exc:
        print(f"   FAIL: Yahoo access check could not run ({type(exc).__name__})")
        return "failed"

    if response.status_code == 200:
        print("   PASS: Yahoo Fantasy API access is approved")
        return "ready"
    if response.status_code == 401 and "additional_authorization_required" in response.text:
        print("   PENDING: token is valid, but Yahoo Fantasy approval has not landed")
        return "pending"

    print(f"   FAIL: Yahoo returned HTTP {response.status_code}")
    return "failed"


async def main() -> int:
    """Run local readiness checks and return a meaningful shell exit code."""
    print("Yahoo Fantasy Football MCP readiness")
    print("=" * 40)

    env_ok, values = check_env_file()
    local_checks = [
        env_ok,
        check_dependencies(),
        check_codex_registration(),
        await check_mcp_server(),
    ]
    yahoo_status = check_yahoo_access(values)

    print("=" * 40)
    if all(local_checks) and yahoo_status != "failed":
        if yahoo_status == "ready":
            print("READY: local setup and Yahoo access are working")
        else:
            print("LOCAL READY: waiting only on Yahoo credentials or approval")
        return 0

    print("NOT READY: fix the failed checks above")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
