"""Environment-only launcher for the root stdio MCP; never configures the host."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import runpy
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_ENV_NAMES = [
    "YAHOO_CLIENT_ID",
    "YAHOO_CLIENT_SECRET",
    "YAHOO_ACCESS_TOKEN",
    "YAHOO_REFRESH_TOKEN",
    "YAHOO_GUID",
    "YAHOO_TOKEN_STORE",
    "PROPLINE_API_KEY",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USERNAME",
]


def prepare_runtime() -> None:
    """Use this checkout and injected variables, without loading a local .env."""
    os.environ["FANTASY_CLOUD_RUNTIME"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))


def block_network() -> None:
    """Contract checks must never authenticate or call a provider."""

    def denied(*_args, **_kwargs):
        raise OSError("Network disabled during local MCP contract check")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied
    socket.socket.sendto = denied


async def check_contract() -> bool:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from utils.verify_setup import EXPECTED_TOOLS

    # Do not pass any provider credentials or durable-store access to the child.
    # Explicit OS/runtime allowlist also excludes unknown credential names and
    # proxy URLs, which can themselves contain authentication values.
    child_env = {
        name: os.environ[name]
        for name in ("PATH", "HOME", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "TMPDIR")
        if name in os.environ
    }
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    child_env["FANTASY_CLOUD_CHECK"] = "1"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-B", str(Path(__file__).resolve())],
        cwd=str(ROOT),
        env=child_env,
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=15)
                result = await asyncio.wait_for(session.list_tools(), timeout=15)
    except Exception:
        # Exception text can include provider or environment details. Keep it private.
        print("FAIL: stdio initialization/list-tools failed", file=sys.stderr)
        return False
    names = {tool.name for tool in result.tools}
    if names != EXPECTED_TOOLS:
        print("FAIL: stdio tool contract mismatch", file=sys.stderr)
        return False
    print(f"PASS: root stdio contract has all {len(names)} tools (network disabled)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Initialize/list tools without network")
    group.add_argument("--config", action="store_true", help="Print non-secret MCP config preview")
    args = parser.parse_args()
    if args.config:
        print(
            json.dumps(
                {
                    "mcp_servers": {
                        "yahoo-fantasy-football": {
                            "command": sys.executable,
                            "args": ["-B", str(Path(__file__).resolve())],
                            "cwd": str(ROOT),
                            "env_vars": PROVIDER_ENV_NAMES,
                        }
                    }
                },
                indent=2,
            )
        )
        return 0
    prepare_runtime()
    if args.check:
        block_network()
        return 0 if asyncio.run(check_contract()) else 1
    if os.environ.get("FANTASY_CLOUD_CHECK") == "1":
        block_network()
    runpy.run_path(str(ROOT / "fantasy_football_multi_league.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
