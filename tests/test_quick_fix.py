#!/usr/bin/env python3
"""
Quick test of the position fix.
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


async def test_fix():
    """Quick test of the position fix."""
    print("🔧 Testing Position Fix")
    print("=" * 30)

    try:
        # Test the consolidated tool directly
        from fastmcp_server import ff_get_roster

        class MockContext:
            async def info(self, message: str):
                print(f"[INFO] {message}")

        ctx = MockContext()

        # Test with enhanced mode
        print("🧠 Testing Enhanced Mode:")
        result = await ff_get_roster(ctx=ctx, league_key="nfl.l.XXXXXX", data_level="full")

        if isinstance(result, dict) and "status" in result:
            if result["status"] == "success":
                total_players = result.get("total_players", 0)
                print(f"   ✅ Success! Found {total_players} players")

                if "players_by_position" in result:
                    positions = result["players_by_position"]
                    print(f"   📊 Positions found:")
                    for pos, players in positions.items():
                        print(f"      {pos}: {len(players)} players")

                return True
            else:
                print(f"   ❌ Error: {result.get('message', 'Unknown error')}")
                return False
        else:
            print(f"   ❌ Unexpected result format: {type(result)}")
            return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    asyncio.run(test_fix())
