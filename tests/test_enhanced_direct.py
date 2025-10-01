#!/usr/bin/env python3
"""
Test the enhanced tool directly to see if there's an exception.
"""

import asyncio
import json
import os
from pathlib import Path


def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value


load_env()


async def test_enhanced_direct():
    """Test the enhanced tool directly."""
    print("🔍 Testing Enhanced Tool Directly")
    print("=" * 40)

    try:
        from enhanced_mcp_tools import ff_get_roster_with_projections

        class MockContext:
            async def info(self, message: str):
                print(f"[INFO] {message}")

        ctx = MockContext()

        print("🧠 Calling enhanced tool directly...")
        result = await ff_get_roster_with_projections(ctx=ctx, league_key="nfl.l.XXXXXX")

        print(f"✅ Enhanced tool succeeded!")
        print(f"   Type: {type(result)}")
        print(f"   Status: {result.get('status', 'unknown')}")
        print(f"   Players: {result.get('total_players', 'unknown')}")

        return True

    except Exception as e:
        print(f"❌ Enhanced tool failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_fastmcp_import():
    """Test if the import from fastmcp works."""
    print("\n🔍 Testing FastMCP Import")
    print("=" * 30)

    try:
        from fastmcp_server import _ff_get_roster_with_projections

        print("✅ Import successful")

        class MockContext:
            async def info(self, message: str):
                print(f"[INFO] {message}")

        ctx = MockContext()

        print("🧠 Calling through FastMCP import...")
        result = await _ff_get_roster_with_projections(
            ctx=ctx, league_key="nfl.l.XXXXXX", team_key=None, week=None
        )

        print(f"✅ FastMCP import call succeeded!")
        print(f"   Type: {type(result)}")
        print(f"   Status: {result.get('status', 'unknown')}")
        print(f"   Players: {result.get('total_players', 'unknown')}")

        return True

    except Exception as e:
        print(f"❌ FastMCP import call failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":

    async def run_tests():
        test1 = await test_enhanced_direct()
        test2 = await test_fastmcp_import()

        print(f"\n🏁 Results:")
        print(f"   Direct enhanced tool: {'✅' if test1 else '❌'}")
        print(f"   FastMCP import: {'✅' if test2 else '❌'}")

    asyncio.run(run_tests())
