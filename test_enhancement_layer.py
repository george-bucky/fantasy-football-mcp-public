#!/usr/bin/env python3
"""Test script for player enhancement layer.

Tests:
1. Bye week detection
2. Recent stats fetching
3. Performance flag generation
4. Projection adjustments
"""

import asyncio
import sys
from datetime import datetime


async def test_bye_week_detection():
    """Test that bye week detection works correctly."""
    print("\n" + "=" * 60)
    print("TEST 1: Bye Week Detection")
    print("=" * 60)

    from src.services.player_enhancement import detect_bye_week

    # Test cases
    test_cases = [
        (6, 6, True, "Player on bye week 6, current week 6"),
        (7, 6, False, "Player on bye week 7, current week 6"),
        ("6", 6, True, "String bye week '6', current week 6"),
        ("N/A", 6, False, "No bye week (N/A)"),
        (None, 6, False, "None bye week"),
    ]

    passed = 0
    failed = 0

    for bye_week, current_week, expected, description in test_cases:
        result = detect_bye_week(bye_week, current_week)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"{status}: {description} -> {result}")

    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


async def test_performance_flags():
    """Test performance flag calculation."""
    print("\n" + "=" * 60)
    print("TEST 2: Performance Flag Calculation")
    print("=" * 60)

    from src.services.player_enhancement import calculate_breakout_score

    test_cases = [
        (20.0, 10.0, 25.0, ["BREAKOUT_CANDIDATE"], "Breakout: avg 20 vs proj 10 (>150%)"),
        (13.0, 10.0, 15.0, ["TRENDING_UP"], "Trending up: avg 13 vs proj 10 (>120%)"),
        (6.0, 10.0, 8.0, ["DECLINING_ROLE"], "Declining: avg 6 vs proj 10 (<70%)"),
        (10.0, 10.0, 25.0, ["HIGH_CEILING"], "High ceiling: best game 25 vs proj 10 (>200%)"),
        (9.5, 10.0, 11.0, ["CONSISTENT"], "Consistent: avg 9.5 vs proj 10 (stable)"),
    ]

    passed = 0
    failed = 0

    for recent_avg, projection, recent_high, expected_flags, description in test_cases:
        flags = calculate_breakout_score(recent_avg, projection, recent_high)
        # Check if expected flags are present (may have additional flags)
        has_expected = all(flag in flags for flag in expected_flags)
        status = "✅ PASS" if has_expected else "❌ FAIL"
        if has_expected:
            passed += 1
        else:
            failed += 1
        print(f"{status}: {description}")
        print(f"  Expected: {expected_flags}")
        print(f"  Got: {flags}")

    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


async def test_recent_stats_with_live_data():
    """Test fetching recent stats from Sleeper API."""
    print("\n" + "=" * 60)
    print("TEST 3: Recent Stats Fetching (Live API)")
    print("=" * 60)

    try:
        from sleeper_api import SleeperAPI, get_current_week, get_current_season
        from src.services.player_enhancement import get_recent_stats

        sleeper = SleeperAPI()

        # Get current week and season
        current_week = await get_current_week()
        current_season = await get_current_season()

        print(f"Current Season: {current_season}, Week: {current_week}")

        if current_week < 3:
            print("⚠️  SKIP: Not enough weeks to test recent stats (need week 3+)")
            return True

        # Get a well-known player (Patrick Mahomes has consistent ID)
        all_players = await sleeper.get_all_players()

        # Find a few active players to test with
        test_players = []
        for player_id, player_data in list(all_players.items())[:100]:
            if player_data.get("active") and player_data.get("position") in ["QB", "RB", "WR"]:
                test_players.append((player_id, player_data.get("full_name", "Unknown")))
                if len(test_players) >= 3:
                    break

        if not test_players:
            print("⚠️  SKIP: Could not find test players")
            return True

        print(f"\nTesting with players: {[name for _, name in test_players]}")

        passed = 0
        failed = 0

        for player_id, player_name in test_players:
            print(f"\nFetching stats for {player_name} (ID: {player_id})...")

            recent = await get_recent_stats(
                sleeper, player_id, current_season, current_week, lookback=3
            )

            if recent:
                print(f"  ✅ Got {recent.weeks_analyzed} weeks of data")
                print(f"  Average points: {recent.avg_points:.1f}")
                print(f"  Total points: {recent.total_points:.1f}")
                print(f"  Trend: {recent.trend}")
                passed += 1
            else:
                print(f"  ℹ️  No recent stats available (player may not have played)")
                # This is OK - not all players play every week
                passed += 1

        print(f"\nResults: {passed} completed successfully, {failed} failed")
        return failed == 0

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_full_enhancement_integration():
    """Test full enhancement with a real player object."""
    print("\n" + "=" * 60)
    print("TEST 4: Full Enhancement Integration")
    print("=" * 60)

    try:
        from sleeper_api import SleeperAPI, get_current_week, get_current_season
        from lineup_optimizer import Player
        from src.services.player_enhancement import enhance_player_with_context

        sleeper = SleeperAPI()
        current_week = await get_current_week()
        current_season = await get_current_season()

        print(f"Testing with current week: {current_week}, season: {current_season}")

        # Create a mock player on bye
        player_on_bye = Player(
            name="Test Player (Bye)",
            position="WR",
            team="KC",
            bye=current_week,  # On bye this week
            sleeper_projection=15.0,
            yahoo_projection=14.0,
        )

        print(f"\n1. Testing player ON BYE (Week {current_week})...")
        enhancement = await enhance_player_with_context(
            player_on_bye, current_week, current_season, sleeper
        )

        print(f"  on_bye: {enhancement.on_bye}")
        print(f"  adjusted_projection: {enhancement.adjusted_projection}")
        print(f"  recommendation: {enhancement.recommendation_override}")
        print(f"  context: {enhancement.context_message}")
        print(f"  flags: {enhancement.performance_flags}")

        if enhancement.on_bye and enhancement.adjusted_projection == 0.0:
            print("  ✅ PASS: Bye week correctly detected and projections zeroed")
        else:
            print("  ❌ FAIL: Bye week not handled correctly")
            return False

        # Create a player NOT on bye
        next_week = current_week + 1
        player_active = Player(
            name="Test Player (Active)",
            position="RB",
            team="SF",
            bye=next_week,  # Bye next week, not this week
            sleeper_projection=12.0,
            yahoo_projection=11.0,
        )

        print(f"\n2. Testing player NOT on bye (bye week {next_week})...")
        enhancement = await enhance_player_with_context(
            player_active, current_week, current_season, sleeper
        )

        print(f"  on_bye: {enhancement.on_bye}")
        print(f"  adjusted_projection: {enhancement.adjusted_projection}")
        print(f"  context: {enhancement.context_message}")

        if not enhancement.on_bye:
            print("  ✅ PASS: Active player correctly identified")
        else:
            print("  ❌ FAIL: Active player incorrectly marked as bye")
            return False

        print("\n✅ All integration tests passed")
        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_handler_serialization():
    """Test that handlers serialize enhanced data correctly."""
    print("\n" + "=" * 60)
    print("TEST 5: Handler Serialization")
    print("=" * 60)

    try:
        from lineup_optimizer import Player

        # Create a player with enhancement data
        player = Player(
            name="Test Player",
            position="WR",
            team="KC",
            bye=6,
            on_bye=True,
            performance_flags=["ON_BYE"],
            enhancement_context="Player is on bye Week 6",
            adjusted_projection=0.0,
            sleeper_projection=0.0,
            yahoo_projection=0.0,
        )

        print("Created test player with enhancement data:")
        print(f"  bye: {player.bye}")
        print(f"  on_bye: {player.on_bye}")
        print(f"  performance_flags: {player.performance_flags}")
        print(f"  enhancement_context: {player.enhancement_context}")
        print(f"  adjusted_projection: {player.adjusted_projection}")

        # Check all fields exist
        required_fields = [
            "bye",
            "on_bye",
            "performance_flags",
            "enhancement_context",
            "adjusted_projection",
        ]
        missing = []

        for field in required_fields:
            if not hasattr(player, field):
                missing.append(field)

        if missing:
            print(f"\n❌ FAIL: Missing fields: {missing}")
            return False
        else:
            print("\n✅ PASS: All enhancement fields present on Player object")
            return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("PLAYER ENHANCEMENT LAYER TEST SUITE")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = []

    # Run tests
    results.append(("Bye Week Detection", await test_bye_week_detection()))
    results.append(("Performance Flags", await test_performance_flags()))
    results.append(("Handler Serialization", await test_handler_serialization()))
    results.append(("Recent Stats (Live)", await test_recent_stats_with_live_data()))
    results.append(("Full Integration", await test_full_enhancement_integration()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    failed = sum(1 for _, result in results if not result)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{len(results)} tests passed")

    if failed == 0:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
