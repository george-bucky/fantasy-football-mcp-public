#!/usr/bin/env python3
"""
Demo script showing the consolidated roster tool functionality
This shows what the enhanced tool does compared to the basic tool
"""

# Mock data representing what we get from Yahoo API
MOCK_YAHOO_ROSTER_DATA = {
    "fantasy_content": {
        "team": {
            "roster": {
                "players": {
                    "player": [
                        {
                            "player_key": "449.p.31862",
                            "player_id": "31862",
                            "name": {"full": "Josh Allen", "first": "Josh", "last": "Allen"},
                            "editorial_player_key": "nfl.p.31862",
                            "editorial_team_key": "nfl.t.2",
                            "editorial_team_full_name": "Buffalo Bills",
                            "editorial_team_abbr": "Buf",
                            "uniform_number": "17",
                            "display_position": "QB",
                            "headshot": {"url": "https://s.yimg.com/iu/api/res/1.2/example.jpg"},
                            "image_url": "https://s.yimg.com/iu/api/res/1.2/example.jpg",
                            "is_undroppable": "0",
                            "position_type": "O",
                            "primary_position": "QB",
                            "eligible_positions": {"position": ["QB"]},
                            "selected_position": {"position": "QB"},
                        },
                        {
                            "player_key": "449.p.30123",
                            "player_id": "30123",
                            "name": {
                                "full": "Christian McCaffrey",
                                "first": "Christian",
                                "last": "McCaffrey",
                            },
                            "editorial_team_full_name": "San Francisco 49ers",
                            "editorial_team_abbr": "SF",
                            "display_position": "RB",
                            "primary_position": "RB",
                            "eligible_positions": {"position": ["RB"]},
                            "selected_position": {"position": "RB"},
                        },
                        {
                            "player_key": "449.p.32671",
                            "player_id": "32671",
                            "name": {
                                "full": "Saquon Barkley",
                                "first": "Saquon",
                                "last": "Barkley",
                            },
                            "editorial_team_full_name": "Philadelphia Eagles",
                            "editorial_team_abbr": "Phi",
                            "display_position": "RB",
                            "primary_position": "RB",
                            "eligible_positions": {"position": ["RB"]},
                            "selected_position": {"position": "RB"},
                        },
                        {
                            "player_key": "449.p.31045",
                            "player_id": "31045",
                            "name": {"full": "Tyreek Hill", "first": "Tyreek", "last": "Hill"},
                            "editorial_team_full_name": "Miami Dolphins",
                            "editorial_team_abbr": "Mia",
                            "display_position": "WR",
                            "primary_position": "WR",
                            "eligible_positions": {"position": ["WR"]},
                            "selected_position": {"position": "WR"},
                        },
                        {
                            "player_key": "449.p.33086",
                            "player_id": "33086",
                            "name": {"full": "CeeDee Lamb", "first": "CeeDee", "last": "Lamb"},
                            "editorial_team_full_name": "Dallas Cowboys",
                            "editorial_team_abbr": "Dal",
                            "display_position": "WR",
                            "primary_position": "WR",
                            "eligible_positions": {"position": ["WR"]},
                            "selected_position": {"position": "WR"},
                        },
                        {
                            "player_key": "449.p.32720",
                            "player_id": "32720",
                            "name": {"full": "Jaylen Waddle", "first": "Jaylen", "last": "Waddle"},
                            "editorial_team_full_name": "Miami Dolphins",
                            "editorial_team_abbr": "Mia",
                            "display_position": "WR",
                            "primary_position": "WR",
                            "eligible_positions": {"position": ["WR"]},
                            "selected_position": {"position": "WR"},
                        },
                        {
                            "player_key": "449.p.31002",
                            "player_id": "31002",
                            "name": {"full": "Travis Kelce", "first": "Travis", "last": "Kelce"},
                            "editorial_team_full_name": "Kansas City Chiefs",
                            "editorial_team_abbr": "KC",
                            "display_position": "TE",
                            "primary_position": "TE",
                            "eligible_positions": {"position": ["TE"]},
                            "selected_position": {"position": "TE"},
                        },
                        {
                            "player_key": "449.p.30971",
                            "player_id": "30971",
                            "name": {"full": "Davante Adams", "first": "Davante", "last": "Adams"},
                            "editorial_team_full_name": "New York Jets",
                            "editorial_team_abbr": "NYJ",
                            "display_position": "WR",
                            "primary_position": "WR",
                            "eligible_positions": {"position": ["WR", "RB"]},
                            "selected_position": {"position": "W/R"},  # FLEX position
                        },
                        {
                            "player_key": "449.p.100042",
                            "player_id": "100042",
                            "name": {
                                "full": "Harrison Butker",
                                "first": "Harrison",
                                "last": "Butker",
                            },
                            "editorial_team_full_name": "Kansas City Chiefs",
                            "editorial_team_abbr": "KC",
                            "display_position": "K",
                            "primary_position": "K",
                            "eligible_positions": {"position": ["K"]},
                            "selected_position": {"position": "K"},
                        },
                        {
                            "player_key": "449.p.100023",
                            "player_id": "100023",
                            "name": {
                                "full": "San Francisco 49ers",
                                "first": "San Francisco",
                                "last": "49ers",
                            },
                            "editorial_team_full_name": "San Francisco 49ers",
                            "editorial_team_abbr": "SF",
                            "display_position": "DEF",
                            "primary_position": "DEF",
                            "eligible_positions": {"position": ["DEF"]},
                            "selected_position": {"position": "DEF"},
                        },
                        {
                            "player_key": "449.p.100018",
                            "player_id": "100018",
                            "name": {
                                "full": "Pittsburgh Steelers",
                                "first": "Pittsburgh",
                                "last": "Steelers",
                            },
                            "editorial_team_full_name": "Pittsburgh Steelers",
                            "editorial_team_abbr": "Pit",
                            "display_position": "DEF",
                            "primary_position": "DEF",
                            "eligible_positions": {"position": ["DEF"]},
                            "selected_position": {"position": "D"},  # Alternative DEF notation
                        },
                        # BENCH PLAYERS (BN position)
                        {
                            "player_key": "449.p.32671",
                            "player_id": "32671",
                            "name": {"full": "Derrick Henry", "first": "Derrick", "last": "Henry"},
                            "editorial_team_full_name": "Baltimore Ravens",
                            "editorial_team_abbr": "Bal",
                            "display_position": "RB",
                            "primary_position": "RB",
                            "eligible_positions": {"position": ["RB"]},
                            "selected_position": {"position": "BN"},  # BENCH
                        },
                        {
                            "player_key": "449.p.33086",
                            "player_id": "33086",
                            "name": {"full": "Stefon Diggs", "first": "Stefon", "last": "Diggs"},
                            "editorial_team_full_name": "Houston Texans",
                            "editorial_team_abbr": "Hou",
                            "display_position": "WR",
                            "primary_position": "WR",
                            "eligible_positions": {"position": ["WR"]},
                            "selected_position": {"position": "BN"},  # BENCH
                        },
                        {
                            "player_key": "449.p.33452",
                            "player_id": "33452",
                            "name": {"full": "Brock Bowers", "first": "Brock", "last": "Bowers"},
                            "editorial_team_full_name": "Las Vegas Raiders",
                            "editorial_team_abbr": "LV",
                            "display_position": "TE",
                            "primary_position": "TE",
                            "eligible_positions": {"position": ["TE"]},
                            "selected_position": {"position": "BN"},  # BENCH
                        },
                        {
                            "player_key": "449.p.32854",
                            "player_id": "32854",
                            "name": {"full": "Rome Odunze", "first": "Rome", "last": "Odunze"},
                            "editorial_team_full_name": "Chicago Bears",
                            "editorial_team_abbr": "Chi",
                            "display_position": "WR",
                            "primary_position": "WR",
                            "eligible_positions": {"position": ["WR"]},
                            "selected_position": {"position": "BN"},  # BENCH
                        },
                        {
                            "player_key": "449.p.31045",
                            "player_id": "31045",
                            "name": {"full": "Jordan Love", "first": "Jordan", "last": "Love"},
                            "editorial_team_full_name": "Green Bay Packers",
                            "editorial_team_abbr": "GB",
                            "display_position": "QB",
                            "primary_position": "QB",
                            "eligible_positions": {"position": ["QB"]},
                            "selected_position": {"position": "BN"},  # BENCH
                        },
                    ]
                }
            }
        }
    }
}


def simulate_basic_tool():
    """Simulates what the basic ff_get_roster tool returns"""
    print("📊 BASIC TOOL (Original ff_get_roster)")
    print("=" * 60)

    # Basic tool just returns simple roster info
    basic_result = {
        "success": True,
        "team_name": "My Fantasy Team",
        "total_players": 16,
        "message": "Roster retrieved successfully",
    }

    print(f"✅ Success: {basic_result['success']}")
    print(f"🏈 Team: {basic_result['team_name']}")
    print(f"👥 Total Players: {basic_result['total_players']}")
    print(f"💬 Message: {basic_result['message']}")
    print("\n⚠️  LIMITATION: No detailed player information or position breakdown")
    return basic_result


def simulate_enhanced_tool(data_level="full"):
    """Simulates what the enhanced consolidated tool returns"""
    print(f"🚀 ENHANCED TOOL (Consolidated with data_level='{data_level}')")
    print("=" * 60)

    # Process the mock data like our enhanced tool would
    players = MOCK_YAHOO_ROSTER_DATA["fantasy_content"]["team"]["roster"]["players"]["player"]

    processed_players = []
    position_counts = {}

    for player_data in players:
        # Extract player info
        name = player_data["name"]["full"]
        position = player_data.get("selected_position", {}).get("position", "UNKNOWN")
        primary_pos = player_data.get("primary_position", "UNKNOWN")
        team = player_data.get("editorial_team_abbr", "")

        # Apply position normalization (this was our bug fix!)
        normalized_position = position
        if position == "BN":
            normalized_position = "BENCH"
        elif position == "W/R":
            normalized_position = "FLEX"
        elif position == "D":
            normalized_position = "DEF"

        # Count positions
        position_counts[normalized_position] = position_counts.get(normalized_position, 0) + 1

        player_info = {
            "name": name,
            "position": normalized_position,
            "primary_position": primary_pos,
            "team": team,
            "player_id": player_data["player_id"],
        }

        if data_level in ["standard", "full"]:
            player_info["eligible_positions"] = player_data.get("eligible_positions", {}).get(
                "position", []
            )

        if data_level == "full":
            player_info["headshot"] = player_data.get("headshot", {}).get("url", "")
            player_info["uniform_number"] = player_data.get("uniform_number", "")

        processed_players.append(player_info)

    result = {
        "success": True,
        "data_level": data_level,
        "team_name": "My Fantasy Team",
        "total_players": len(processed_players),
        "position_breakdown": position_counts,
        "players": processed_players,
        "message": f"Enhanced roster with {data_level} details retrieved successfully",
    }

    print(f"✅ Success: {result['success']}")
    print(f"🏈 Team: {result['team_name']}")
    print(f"👥 Total Players: {result['total_players']}")
    print(f"📊 Data Level: {result['data_level']}")
    print()

    print("📋 POSITION BREAKDOWN:")
    for pos, count in sorted(position_counts.items()):
        print(f"   {pos}: {count} players")
    print()

    if data_level != "basic":
        print("👥 PLAYER DETAILS:")
        for player in processed_players[:5]:  # Show first 5 for demo
            pos_info = f"{player['position']}"
            if player["position"] != player["primary_position"]:
                pos_info += f" (primary: {player['primary_position']})"
            print(f"   • {player['name']} ({player['team']}) - {pos_info}")

        if len(processed_players) > 5:
            print(f"   ... and {len(processed_players) - 5} more players")
        print()

        # Show bench players specifically
        bench_players = [p for p in processed_players if p["position"] == "BENCH"]
        if bench_players:
            print("🪑 BENCH PLAYERS:")
            for player in bench_players:
                print(f"   • {player['name']} ({player['team']}) - {player['primary_position']}")
            print()

    return result


def main():
    print("🎯 FANTASY FOOTBALL ROSTER TOOL CONSOLIDATION DEMO")
    print("=" * 80)
    print("This demonstrates the difference between our original basic tool")
    print("and the new consolidated enhanced tool with position fix.\n")

    # Show basic tool
    basic_result = simulate_basic_tool()
    print("\n" + "─" * 80 + "\n")

    # Show enhanced tool with different data levels
    print("🔄 ENHANCED TOOL - DIFFERENT DATA LEVELS:")
    print()

    enhanced_basic = simulate_enhanced_tool("basic")
    print("─" * 60 + "\n")

    enhanced_standard = simulate_enhanced_tool("standard")
    print("─" * 60 + "\n")

    enhanced_full = simulate_enhanced_tool("full")

    print("\n" + "=" * 80)
    print("🎉 CONSOLIDATION BENEFITS:")
    print("   ✅ Single tool handles multiple data levels")
    print("   ✅ Detailed position breakdown (was missing before)")
    print("   ✅ Fixed bench player filtering (BN → BENCH)")
    print("   ✅ Fixed flex position mapping (W/R → FLEX)")
    print("   ✅ Fixed defense position mapping (D → DEF)")
    print("   ✅ Shows all 16 players instead of just 9")
    print("   ✅ Configurable detail levels for different use cases")
    print("   ✅ Backward compatible with existing tools")
    print()
    print("🐛 CRITICAL BUG FIXED:")
    print("   • Before: Only 9 players shown (bench players filtered out)")
    print("   • After: All 16 players shown with proper position mapping")
    print("   • Issue: Position validation didn't recognize BN, W/R, D positions")
    print("   • Solution: Added position normalization in parsing phase")


if __name__ == "__main__":
    main()
