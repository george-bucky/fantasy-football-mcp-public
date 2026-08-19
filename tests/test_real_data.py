#!/usr/bin/env python3
"""Test enhancement layer with real Yahoo Fantasy data."""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

REQUIRED_YAHOO_VARS = [
    "YAHOO_CLIENT_ID",
    "YAHOO_CLIENT_SECRET",
    "YAHOO_ACCESS_TOKEN",
    "YAHOO_REFRESH_TOKEN",
]


async def test_with_real_roster():
    """Test enhancement layer with real roster from Yahoo."""
    print("=" * 60)
    print("REAL DATA TEST: Roster Enhancement")
    print("=" * 60)

    # Check for environment variables
    missing = [var for var in REQUIRED_YAHOO_VARS if not os.getenv(var)]
    if missing:
        pytest.skip(f"Yahoo credentials pending: {', '.join(missing)}")

    try:
        from src.handlers.roster_handlers import handle_ff_get_roster
        from fantasy_football_multi_league import (
            discover_leagues,
            get_user_team_info,
            yahoo_api_call,
        )
        from src.parsers.yahoo_parsers import parse_team_roster

        # Discover leagues
        print("\n1. Discovering leagues...")
        leagues = await discover_leagues()

        if not leagues:
            raise AssertionError("No Yahoo leagues found")

        league_list = list(leagues.values())
        print(f"Found {len(league_list)} league(s):")
        for league in league_list[:3]:  # Show first 3
            print(f"  - {league.get('name')} ({league.get('key')})")

        # Use first league
        league_key = league_list[0].get("key")
        print(f"\n2. Testing with league: {league_key}")

        # Inject dependencies for handlers
        from src.handlers import (
            inject_roster_dependencies,
        )

        inject_roster_dependencies(
            get_user_team_info=get_user_team_info,
            yahoo_api_call=yahoo_api_call,
            parse_team_roster=parse_team_roster,
        )

        # Get roster with enhancements
        print("\n3. Fetching roster with enhancements...")
        result = await handle_ff_get_roster(
            {
                "league_key": league_key,
                "data_level": "enhanced",  # This triggers enhancement
                "include_projections": True,
                "include_external_data": True,
                "include_analysis": True,
            }
        )

        if result.get("status") != "success":
            raise AssertionError(result.get("error", "Roster enhancement failed"))

        # Analyze results
        print(f"\n4. Analyzing enhancement results...")

        all_players = result.get("all_players", [])
        print(f"Total players: {len(all_players)}")

        # Check for bye week players
        bye_week_players = [p for p in all_players if p.get("on_bye")]
        print(f"\n✓ Players on bye this week: {len(bye_week_players)}")
        for player in bye_week_players[:5]:  # Show first 5
            print(
                f"  - {player.get('name')} ({player.get('position')}) - Week {player.get('bye_week')}"
            )
            print(f"    Yahoo proj: {player.get('yahoo_projection', 0):.1f}")
            print(f"    Sleeper proj: {player.get('sleeper_projection', 0):.1f}")
            print(f"    Context: {player.get('enhancement_context', 'N/A')}")

        # Check for players with performance flags
        flagged_players = [p for p in all_players if p.get("performance_flags")]
        print(f"\n✓ Players with performance flags: {len(flagged_players)}")
        for player in flagged_players[:5]:  # Show first 5
            flags = player.get("performance_flags", [])
            print(f"  - {player.get('name')} ({player.get('position')}): {', '.join(flags)}")
            if player.get("enhancement_context"):
                print(f"    {player.get('enhancement_context')}")

        # Check for adjusted projections
        adjusted_players = [p for p in all_players if p.get("adjusted_projection") is not None]
        print(f"\n✓ Players with adjusted projections: {len(adjusted_players)}")

        # Show some examples of adjustments
        for player in adjusted_players[:5]:
            sleeper = player.get("sleeper_projection", 0)
            adjusted = player.get("adjusted_projection", 0)
            if sleeper > 0:
                diff = adjusted - sleeper
                print(f"  - {player.get('name')}: {sleeper:.1f} → {adjusted:.1f} ({diff:+.1f})")

        print("\n✅ PASS: Enhancement layer successfully integrated with real data")
        return None

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        raise


async def test_waiver_wire_enhancements():
    """Test enhancement with waiver wire players."""
    print("\n" + "=" * 60)
    print("REAL DATA TEST: Waiver Wire Enhancement")
    print("=" * 60)

    missing = [var for var in REQUIRED_YAHOO_VARS if not os.getenv(var)]
    if missing:
        pytest.skip(f"Yahoo credentials pending: {', '.join(missing)}")

    try:
        from src.handlers.player_handlers import handle_ff_get_waiver_wire
        from fantasy_football_multi_league import (
            discover_leagues,
            get_waiver_wire_players,
            yahoo_api_call,
        )

        # Get league
        leagues = await discover_leagues()
        if not leagues:
            raise AssertionError("No Yahoo leagues found")

        league_key = next(iter(leagues.values())).get("key")
        print(f"Testing with league: {league_key}")

        # Inject dependencies
        from src.handlers import inject_player_dependencies

        inject_player_dependencies(
            yahoo_api_call=yahoo_api_call,
            get_waiver_wire_players=get_waiver_wire_players,
        )

        # Get waiver wire with enhancements
        print("\nFetching top waiver wire RBs with enhancements...")
        result = await handle_ff_get_waiver_wire(
            {
                "league_key": league_key,
                "position": "RB",
                "count": 10,
                "include_projections": True,
                "include_external_data": True,
                "include_analysis": True,
            }
        )

        if result.get("status") != "success":
            raise AssertionError(result.get("error", "Waiver enhancement failed"))

        players = result.get("enhanced_players", [])
        print(f"\nFound {len(players)} RBs on waiver wire")

        # Check enhancements
        bye_players = [p for p in players if p.get("on_bye")]
        print(f"\n✓ RBs on bye: {len(bye_players)}")
        for player in bye_players[:3]:
            print(f"  - {player['name']}: {player.get('enhancement_context', 'N/A')}")

        flagged = [p for p in players if p.get("performance_flags")]
        print(f"\n✓ RBs with performance flags: {len(flagged)}")
        for player in flagged[:3]:
            print(f"  - {player['name']}: {', '.join(player.get('performance_flags', []))}")

        print("\n✅ PASS: Waiver wire enhancements working")
        return None

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        raise


async def main():
    print("=" * 60)
    print("REAL DATA ENHANCEMENT TESTS")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    missing = [var for var in REQUIRED_YAHOO_VARS if not os.getenv(var)]
    if missing:
        print(f"Yahoo credentials pending: {', '.join(missing)}")
        return 2

    results = []
    for name, test in [
        ("Roster Enhancement", test_with_real_roster),
        ("Waiver Wire Enhancement", test_waiver_wire_enhancements),
    ]:
        try:
            await test()
            results.append((name, True))
        except Exception:
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{len(results)} tests passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
