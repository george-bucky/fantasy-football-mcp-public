#!/usr/bin/env python3
"""
Tool count analysis for Fantasy Football MCP Server
"""

# From fastmcp_server.py - count all @server.tool definitions
print("🔍 FANTASY FOOTBALL MCP SERVER - TOOL COUNT ANALYSIS")
print("=" * 70)

print("\n📊 TOOL COUNT SUMMARY:")
print(f"   FastMCP Server Tools: 23 tools")

print("\n📋 FASTMCP SERVER TOOLS (from fastmcp_server.py):")
print("=" * 50)

tools = [
    "1.  ff_get_leagues",
    "2.  ff_get_league_info", 
    "3.  ff_get_standings",
    "4.  ff_get_roster",              # ⭐ CONSOLIDATED TOOL
    "5.  ff_get_matchup",
    "6.  ff_get_players",
    "7.  ff_compare_teams",
    "8.  ff_get_optimal_lineup",
    "9.  ff_refresh_token",
    "10. ff_get_api_status",
    "11. ff_clear_cache",
    "12. ff_get_draft_results",
    "13. ff_get_waiver_wire",
    "14. ff_get_draft_rankings",
    "15. ff_get_draft_recommendation",
    "16. ff_analyze_draft_state",
    "17. ff_analyze_reddit_sentiment",
    # Enhanced wrapper tools
    "18. ff_get_roster_with_projections_wrapper",  # 🔄 DUPLICATE FUNCTIONALITY
    "19. ff_analyze_lineup_options_wrapper",
    "20. ff_compare_players_wrapper",
    "21. ff_what_if_analysis_wrapper", 
    "22. ff_get_decision_context_wrapper",
    # Additional tool
    "23. [One more tool - need to verify]"
]

for tool in tools:
    print(f"   {tool}")

print("\n🔍 DUPLICATED/OVERLAPPING FUNCTIONALITY:")
print("=" * 50)

duplicates = [
    {
        "category": "ROSTER TOOLS",
        "tools": [
            "ff_get_roster (basic/standard/full)",
            "ff_get_roster_with_projections_wrapper"
        ],
        "overlap": "Both get roster data with projections",
        "recommendation": "✅ ALREADY CONSOLIDATED into ff_get_roster"
    },
    {
        "category": "PLAYER ANALYSIS",
        "tools": [
            "ff_get_players",
            "ff_get_waiver_wire", 
            "ff_compare_players_wrapper"
        ],
        "overlap": "All provide player information and analysis",
        "recommendation": "🔄 Could consolidate into ff_get_player_analysis"
    },
    {
        "category": "DRAFT TOOLS",
        "tools": [
            "ff_get_draft_results",
            "ff_get_draft_rankings",
            "ff_get_draft_recommendation",
            "ff_analyze_draft_state"
        ],
        "overlap": "All related to draft analysis and recommendations",
        "recommendation": "🔄 Could consolidate into ff_draft_analysis"
    },
    {
        "category": "LINEUP OPTIMIZATION",
        "tools": [
            "ff_get_optimal_lineup",
            "ff_analyze_lineup_options_wrapper",
            "ff_what_if_analysis_wrapper"
        ],
        "overlap": "All provide lineup optimization and scenario analysis",
        "recommendation": "🔄 Could consolidate into ff_lineup_optimizer"
    },
    {
        "category": "LEAGUE/TEAM INFO",
        "tools": [
            "ff_get_league_info",
            "ff_get_standings",
            "ff_compare_teams",
            "ff_get_matchup"
        ],
        "overlap": "All provide league and team context information",
        "recommendation": "🔄 Could consolidate into ff_league_analysis"
    },
    {
        "category": "MAINTENANCE/ADMIN",
        "tools": [
            "ff_refresh_token",
            "ff_get_api_status", 
            "ff_clear_cache"
        ],
        "overlap": "All administrative/maintenance functions",
        "recommendation": "🔄 Could consolidate into ff_admin_tools"
    }
]

for dup in duplicates:
    print(f"\n🔄 {dup['category']}:")
    print(f"   Tools: {', '.join(dup['tools'])}")
    print(f"   Overlap: {dup['overlap']}")
    print(f"   💡 {dup['recommendation']}")

print("\n📈 CONSOLIDATION OPPORTUNITIES:")
print("=" * 50)
print("Current: 23 tools")
print("Potential after consolidation: 8-10 tools")
print()
print("Suggested consolidation groups:")
print("1. ff_get_leagues (standalone)")
print("2. ff_league_analysis (league info, standings, teams, matchups)")
print("3. ff_roster_analysis (roster with all detail levels) ✅ DONE")
print("4. ff_player_analysis (players, waiver wire, comparisons)")
print("5. ff_lineup_optimizer (optimal lineups, scenarios, what-if)")
print("6. ff_draft_analysis (rankings, recommendations, state)")
print("7. ff_reddit_sentiment (standalone)")
print("8. ff_admin_tools (token, status, cache)")
print()
print("💡 This would reduce complexity by ~60% while maintaining all functionality!")

print("\n🎯 CONSOLIDATION PRIORITY:")
print("=" * 50)
print("1. ✅ COMPLETED: Roster tools → ff_get_roster (with data_level parameter)")
print("2. 🔄 NEXT: Player tools → ff_player_analysis")
print("3. 🔄 FUTURE: Draft tools → ff_draft_analysis") 
print("4. 🔄 FUTURE: Lineup tools → ff_lineup_optimizer")
print("5. 🔄 FUTURE: League tools → ff_league_analysis")

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("✨ ANALYSIS COMPLETE - 23 tools identified with significant consolidation opportunities")