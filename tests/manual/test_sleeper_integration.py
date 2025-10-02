#!/usr/bin/env python3
"""Test script to verify Sleeper integration with roster data."""

import asyncio
import json
from fantasy_football_multi_league import call_tool


async def test_sleeper_integration():
    """Test that roster calls now include Sleeper data."""

    print("Testing Sleeper integration...")

    # Dynamically get a valid league key
    leagues_result = await call_tool(name="ff_get_leagues", arguments={})
    if isinstance(leagues_result, list) and leagues_result:
        leagues_text = getattr(leagues_result[0], "text", str(leagues_result[0]))
        leagues_data = json.loads(leagues_text)
        if leagues_data.get("leagues"):
            valid_league_key = leagues_data["leagues"][0]["key"]
            print(f"Using valid league key: {valid_league_key}")
        else:
            print("No leagues found. Skipping test.")
            return
    else:
        print("Failed to get leagues. Skipping test.")
        return

    # Test multiple tools with full Sleeper integration
    test_args_base = {
        "league_key": valid_league_key,
        "data_level": "full",
        "include_external_data": True,
        "include_projections": True,
        "include_analysis": True,
    }

    tools_to_test = [
        ("ff_get_roster", test_args_base),
        ("ff_get_players", {**test_args_base, "position": "all", "count": 10}),
        ("ff_get_waiver_wire", {**test_args_base, "position": "all", "count": 10}),
    ]

    for tool_name, tool_args in tools_to_test:
        try:
            print(f"\n--- Testing {tool_name} with Sleeper integration ---")
            result = await call_tool(name=tool_name, arguments=tool_args)

            if isinstance(result, list) and result:
                # Extract text content
                text_content = getattr(result[0], "text", str(result[0]))
                data = json.loads(text_content)

                print(f"Status: {data.get('status')}")
                print(f"Data sources: {data.get('analysis_context', {}).get('data_sources', [])}")

                # Print full result for debugging (truncated)
                print("Full result (truncated):", json.dumps(data, indent=2, default=str)[:3000])

                # Check players (adapt to tool response structure)
                players = (
                    data.get("all_players", [])
                    or data.get("enhanced_players", [])
                    or data.get("players", [])
                    or data.get("roster", [])
                )
                if players:
                    print(f"Total players found: {len(players)}")
                    sample_player = players[0]
                    print(f"\nSample player: {sample_player.get('name')}")
                    print(f"Yahoo projection: {sample_player.get('yahoo_projection', 0)}")
                    print(f"Sleeper projection: {sample_player.get('sleeper_projection', 0)}")
                    print(f"Sleeper ID: {sample_player.get('sleeper_id', 'None')}")
                    print(f"Match method: {sample_player.get('sleeper_match_method', 'None')}")
                    print(f"Expert advice: {sample_player.get('expert_advice', 'None')[:100]}...")

                    # Count successful Sleeper matches
                    matched_count = sum(1 for p in players if p.get("sleeper_id"))
                    print(f"\nPlayers with Sleeper matching: {matched_count}/{len(players)}")

                    # Check for actionable projections/advice
                    proj_count = sum(
                        1
                        for p in players
                        if (p.get("sleeper_projection", 0) > 0 or p.get("yahoo_projection", 0) > 0)
                    )
                    advice_count = sum(
                        1
                        for p in players
                        if p.get("expert_advice") and len(p.get("expert_advice", "")) > 10
                    )
                    print(f"Players with projections: {proj_count}/{len(players)}")
                    print(f"Players with actionable advice: {advice_count}/{len(players)}")

                else:
                    print("No players found in response")

            else:
                print(f"Unexpected result format for {tool_name}: {type(result)}")

        except Exception as e:
            print(f"Error testing {tool_name}: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_sleeper_integration())
