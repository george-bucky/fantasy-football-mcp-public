#!/usr/bin/env python3
"""
Comprehensive test of the consolidated roster tool.
"""

import asyncio
import json
import os
import time
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


async def test_all_data_levels():
    """Test all data levels of the consolidated tool."""
    print("🧪 Testing Consolidated Roster Tool")
    print("=" * 50)

    try:
        from fantasy_football_multi_league import call_tool, refresh_yahoo_token

        # Refresh token first
        print("🔑 Refreshing Yahoo token...")
        await refresh_yahoo_token()

        # Get league
        leagues_result = await call_tool("ff_get_leagues", {})
        leagues_data = json.loads(leagues_result[0].text)
        league_key = leagues_data["leagues"][0]["key"]
        print(f"🎯 Using league: {league_key}")

        # Test all data levels
        data_levels = ["basic", "standard", "full"]
        results = {}

        for level in data_levels:
            print(f"\n📊 Testing data_level='{level}':")
            start_time = time.time()

            result = await call_tool(
                "ff_get_roster", {"league_key": league_key, "data_level": level}
            )

            end_time = time.time()
            duration = end_time - start_time

            if result:
                data = json.loads(result[0].text)

                if isinstance(data, dict) and "status" in data:
                    if data["status"] == "success":
                        total_players = data.get("total_players", 0)
                        print(f"   ✅ Success: {total_players} players ({duration:.2f}s)")

                        # Check what data we get
                        if level == "basic":
                            if "roster" in data:
                                print(f"   📋 Basic roster with {len(data['roster'])} players")
                        elif level in ["standard", "full"]:
                            if "players_by_position" in data:
                                positions = data["players_by_position"]
                                pos_summary = ", ".join(
                                    [f"{pos}:{len(players)}" for pos, players in positions.items()]
                                )
                                print(f"   📊 Positions: {pos_summary}")

                        results[level] = {
                            "success": True,
                            "players": total_players,
                            "duration": duration,
                            "data": data,
                        }
                    else:
                        print(f"   ❌ Error: {data.get('message', 'Unknown error')}")
                        results[level] = {"success": False, "error": data.get("message")}
                else:
                    print(f"   ❌ Unexpected format: {type(data)}")
                    results[level] = {"success": False, "error": "Unexpected format"}
            else:
                print(f"   ❌ No result")
                results[level] = {"success": False, "error": "No result"}

        # Summary
        print(f"\n📈 Test Summary:")
        print("=" * 30)

        all_success = True
        for level, result in results.items():
            if result["success"]:
                players = result["players"]
                duration = result["duration"]
                print(f"   {level:8s}: ✅ {players:2d} players ({duration:.2f}s)")
            else:
                print(f"   {level:8s}: ❌ {result.get('error', 'Failed')}")
                all_success = False

        # Validate consistency
        if all_success:
            player_counts = [r["players"] for r in results.values() if r["success"]]
            if len(set(player_counts)) == 1:
                print(f"\n✅ Consistency: All levels return {player_counts[0]} players")
            else:
                print(f"\n⚠️  Inconsistency: Player counts vary {player_counts}")

            # Performance comparison
            durations = [(level, r["duration"]) for level, r in results.items() if r["success"]]
            durations.sort(key=lambda x: x[1])
            print(f"\n⚡ Performance ranking:")
            for i, (level, duration) in enumerate(durations):
                print(f"   {i+1}. {level:8s}: {duration:.2f}s")

        # Test specific features for full mode
        if results.get("full", {}).get("success"):
            print(f"\n🔍 Full Mode Feature Check:")
            full_data = results["full"]["data"]

            features = [
                ("Team info", "team_info" in full_data),
                ("Position groups", "players_by_position" in full_data),
                ("All players list", "all_players" in full_data),
                ("Analysis context", "analysis_context" in full_data),
                ("Week info", "week" in full_data),
            ]

            for feature, present in features:
                status = "✅" if present else "❌"
                print(f"   {status} {feature}")

        return all_success

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_backward_compatibility():
    """Test that legacy tools still work."""
    print(f"\n🔄 Testing Backward Compatibility")
    print("=" * 40)

    try:
        from fantasy_football_multi_league import call_tool

        # Test legacy tool
        print("📜 Testing legacy ff_get_roster_with_projections...")
        result = await call_tool("ff_get_roster_with_projections", {"league_key": "nfl.l.XXXXXX"})

        if result:
            data = json.loads(result[0].text)
            if isinstance(data, dict) and data.get("status") == "success":
                players = data.get("total_players", 0)
                print(f"   ✅ Legacy tool works: {players} players")
                return True
            else:
                print(f"   ❌ Legacy tool error: {data.get('message', 'Unknown')}")
                return False
        else:
            print(f"   ❌ No result from legacy tool")
            return False

    except Exception as e:
        print(f"❌ Backward compatibility test failed: {e}")
        return False


if __name__ == "__main__":
    print("🚀 Starting Comprehensive Roster Tool Test")
    print("=" * 55)

    async def run_all_tests():
        # Test main functionality
        main_test = await test_all_data_levels()

        # Test backward compatibility
        compat_test = await test_backward_compatibility()

        # Final result
        print(f"\n🏁 Final Results:")
        print("=" * 20)
        print(f"   Main functionality: {'✅ PASS' if main_test else '❌ FAIL'}")
        print(f"   Backward compatibility: {'✅ PASS' if compat_test else '❌ FAIL'}")

        overall_success = main_test and compat_test
        print(f"\n{'🎉 ALL TESTS PASSED! 🎉' if overall_success else '❌ SOME TESTS FAILED'}")

        return overall_success

    success = asyncio.run(run_all_tests())
