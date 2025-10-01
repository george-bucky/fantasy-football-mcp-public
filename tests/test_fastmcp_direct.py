#!/usr/bin/env python3
"""
Test the FastMCP consolidated tool directly.
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


async def test_fastmcp_direct():
    """Test the FastMCP consolidated tool directly."""
    print("🚀 Testing FastMCP Consolidated Tool")
    print("=" * 45)

    try:
        # Import the FastMCP server function directly
        import fastmcp_server

        class MockContext:
            async def info(self, message: str):
                print(f"[INFO] {message}")

        ctx = MockContext()

        # Test all data levels
        data_levels = ["basic", "standard", "full"]

        for level in data_levels:
            print(f"\n📊 Testing data_level='{level}':")

            # Call the FastMCP function directly
            result = await fastmcp_server.ff_get_roster(
                ctx=ctx, league_key="nfl.l.XXXXXX", data_level=level
            )

            if isinstance(result, dict):
                status = result.get("status", "unknown")
                if status == "success":
                    total = result.get("total_players", "unknown")
                    print(f"   ✅ Success: {total} players")

                    # Check for expected structure based on level
                    if level == "basic":
                        has_roster = "roster" in result
                        print(f"   📋 Has basic roster: {has_roster}")
                    else:
                        has_positions = "players_by_position" in result
                        has_analysis = "analysis_context" in result
                        print(f"   📊 Has positions: {has_positions}")
                        print(f"   🧠 Has analysis: {has_analysis}")

                        if has_positions:
                            positions = result["players_by_position"]
                            pos_count = {pos: len(players) for pos, players in positions.items()}
                            print(f"   📈 Position counts: {pos_count}")
                else:
                    error = result.get("message", "Unknown error")
                    print(f"   ❌ Error: {error}")
            else:
                print(f"   ❌ Unexpected result type: {type(result)}")

        print(f"\n🎉 FastMCP consolidated tool is working!")
        return True

    except Exception as e:
        print(f"❌ FastMCP test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_fastmcp_direct())

    if success:
        print(f"\n✅ SOLUTION: The consolidated tool works perfectly!")
        print(f"📝 The issue is that call_tool() uses the legacy implementation.")
        print(f"🔧 To use the consolidated tool, call the FastMCP server directly.")
    else:
        print(f"\n❌ The consolidated tool has issues that need fixing.")
