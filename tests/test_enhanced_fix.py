#!/usr/bin/env python3
"""
Test the fix directly with enhanced tools.
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


async def test_enhanced_fix():
    """Test the enhanced tool directly."""
    print("🔧 Testing Enhanced Tool Fix")
    print("=" * 35)

    try:
        from enhanced_mcp_tools import ff_get_roster_with_projections

        class MockContext:
            async def info(self, message: str):
                print(f"[INFO] {message}")

        ctx = MockContext()

        print("🧠 Testing Enhanced Roster Tool:")
        result = await ff_get_roster_with_projections(ctx=ctx, league_key="nfl.l.XXXXXX")

        if isinstance(result, dict) and "status" in result:
            if result["status"] == "success":
                total_players = result.get("total_players", 0)
                print(f"   ✅ Success! Found {total_players} players")

                if "players_by_position" in result:
                    positions = result["players_by_position"]
                    print(f"   📊 Positions found:")
                    for pos, players in positions.items():
                        print(f"      {pos}: {len(players)} players")
                        if players:
                            # Show one example player
                            player = players[0]
                            print(f"         Example: {player['name']}")

                print(f"\n   🎯 Total players in enhanced mode: {total_players}")
                return total_players == 16  # Should be 16 now!
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
    success = asyncio.run(test_enhanced_fix())
    if success:
        print("\n🎉 FIX SUCCESSFUL! All 16 players now included!")
    else:
        print("\n❌ Fix didn't work, still missing players")
