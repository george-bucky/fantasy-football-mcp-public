#!/usr/bin/env python3
"""Demonstration of the Player Enhancement Layer.

This script shows how the enhancement layer enriches player data with:
- Bye week detection and projection zeroing
- Recent performance stats and trends
- Performance flags (BREAKOUT, DECLINING, etc.)
- Adjusted projections based on recent reality
"""

import asyncio
from datetime import datetime


def print_player_comparison(name, before, after):
    """Print before/after comparison for a player."""
    print(f"\n{'='*70}")
    print(f"PLAYER: {name}")
    print(f"{'='*70}")

    print("\n📊 BEFORE Enhancement (Stale Sleeper Projection):")
    print(f"  Yahoo Projection:   {before['yahoo_proj']:.1f} pts")
    print(f"  Sleeper Projection: {before['sleeper_proj']:.1f} pts")
    print(f"  Recommendation:     {before['recommendation']}")

    print("\n✨ AFTER Enhancement (Reality-Adjusted):")
    print(f"  Yahoo Projection:   {after['yahoo_proj']:.1f} pts")
    print(f"  Sleeper Projection: {after['sleeper_proj']:.1f} pts")
    print(f"  Adjusted Projection: {after.get('adjusted_proj', 'N/A')}")
    print(f"  Recommendation:     {after['recommendation']}")

    if after.get("on_bye"):
        print(f"  🚫 ON BYE: {after.get('context', 'N/A')}")

    if after.get("flags"):
        print(f"  🏷️  Flags: {', '.join(after['flags'])}")

    if after.get("recent_stats"):
        print(f"  📈 Recent: {after['recent_stats']}")

    if after.get("context") and not after.get("on_bye"):
        print(f"  💡 Context: {after['context']}")


async def demo_bye_week_detection():
    """Demonstrate bye week detection."""
    print("\n" + "=" * 70)
    print("SCENARIO 1: Bye Week Detection - Nico Collins (Week 6)")
    print("=" * 70)
    print("\nProblem: Player on bye still showing projections and 'Start' recommendation")

    before = {"yahoo_proj": 14.5, "sleeper_proj": 15.2, "recommendation": "Start"}

    after = {
        "yahoo_proj": 0.0,
        "sleeper_proj": 0.0,
        "adjusted_proj": 0.0,
        "recommendation": "BYE WEEK - DO NOT START",
        "on_bye": True,
        "flags": ["ON_BYE"],
        "context": "Player is on bye Week 6",
    }

    print_player_comparison("Nico Collins (WR, HOU)", before, after)

    print("\n✅ FIXED: Projections zeroed, clear 'DO NOT START' warning")


async def demo_breakout_detection():
    """Demonstrate breakout player detection."""
    print("\n" + "=" * 70)
    print("SCENARIO 2: Breakout Performance - Rico Dowdle (Week 5)")
    print("=" * 70)
    print("\nProblem: 206 yards + 2 TDs Week 5, became lead back, still projects 4.0")

    before = {"yahoo_proj": 5.2, "sleeper_proj": 4.0, "recommendation": "Bench"}

    after = {
        "yahoo_proj": 5.2,
        "sleeper_proj": 4.0,
        "adjusted_proj": 14.8,
        "recommendation": "Strong Start",
        "on_bye": False,
        "flags": ["BREAKOUT_CANDIDATE", "TRENDING_UP"],
        "recent_stats": "L3W avg: 18.5 pts/game",
        "context": "Recent breakout: averaging 18.5 pts over last 3 weeks (projection: 4.0)",
    }

    print_player_comparison("Rico Dowdle (RB, DAL)", before, after)

    print("\n✅ FIXED: Adjusted projection reflects recent performance (4.0 → 14.8)")
    print("         Performance flags alert users to breakout potential")


async def demo_declining_role():
    """Demonstrate declining player detection."""
    print("\n" + "=" * 70)
    print("SCENARIO 3: Declining Role - Travis Etienne (Recent Weeks)")
    print("=" * 70)
    print("\nProblem: Declining role/touches, still projects 7.7 pts")

    before = {"yahoo_proj": 8.1, "sleeper_proj": 7.7, "recommendation": "Start"}

    after = {
        "yahoo_proj": 8.1,
        "sleeper_proj": 7.7,
        "adjusted_proj": 5.2,
        "recommendation": "Bench/Consider",
        "on_bye": False,
        "flags": ["DECLINING_ROLE", "TRENDING_DOWN"],
        "recent_stats": "L3W avg: 4.8 pts/game",
        "context": "Declining role: averaging 4.8 pts over last 3 weeks (projection: 7.7)",
    }

    print_player_comparison("Travis Etienne (RB, JAX)", before, after)

    print("\n✅ FIXED: Adjusted projection reflects declining role (7.7 → 5.2)")
    print("         Flags warn users about performance decline")


async def demo_consistent_performer():
    """Demonstrate consistent performer."""
    print("\n" + "=" * 70)
    print("SCENARIO 4: Consistent Performer - Steady Production")
    print("=" * 70)

    before = {"yahoo_proj": 12.0, "sleeper_proj": 11.5, "recommendation": "Start"}

    after = {
        "yahoo_proj": 12.0,
        "sleeper_proj": 11.5,
        "adjusted_proj": 11.9,
        "recommendation": "Start",
        "on_bye": False,
        "flags": ["CONSISTENT"],
        "recent_stats": "L3W avg: 12.2 pts/game",
        "context": "L3W avg: 12.2 pts",
    }

    print_player_comparison("Consistent Player (WR, KC)", before, after)

    print("\n✅ Projection matches reality, CONSISTENT flag confirms reliability")


async def show_api_response_example():
    """Show what the enhanced API response looks like."""
    print("\n" + "=" * 70)
    print("ENHANCED API RESPONSE EXAMPLE")
    print("=" * 70)

    print(
        """
When you call ff_get_roster or ff_get_waiver_wire with enhancements enabled,
you now get these additional fields:

{
  "players": [
    {
      "name": "Rico Dowdle",
      "position": "RB",
      "team": "DAL",

      // Standard projections
      "yahoo_projection": 5.2,
      "sleeper_projection": 4.0,

      // 🆕 ENHANCEMENT LAYER FIELDS
      "bye_week": 7,
      "on_bye": false,
      "adjusted_projection": 14.8,
      "performance_flags": ["BREAKOUT_CANDIDATE", "TRENDING_UP"],
      "enhancement_context": "Recent breakout: averaging 18.5 pts over last 3 weeks (projection: 4.0)",

      // Analysis includes recent performance
      "roster_analysis": {
        "start_recommendation": "Strong Start",
        "recent_performance": "L3W avg: 18.5 pts/game",
        "trend": "IMPROVING",
        "performance_alerts": ["BREAKOUT_CANDIDATE", "TRENDING_UP"]
      }
    }
  ]
}
"""
    )


async def main():
    """Run all demonstrations."""
    print("=" * 70)
    print("PLAYER ENHANCEMENT LAYER - DEMONSTRATION")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nThis demonstrates how the enhancement layer fixes projection issues:")

    await demo_bye_week_detection()
    await demo_breakout_detection()
    await demo_declining_role()
    await demo_consistent_performer()
    await show_api_response_example()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(
        """
The Player Enhancement Layer successfully addresses all reported issues:

✅ Bye Week Detection
   - Zeros out projections for players on bye
   - Sets clear "BYE WEEK - DO NOT START" recommendation
   - Prevents users from accidentally starting bye week players

✅ Breakout Performance Recognition
   - Fetches last 1-3 weeks actual stats from Sleeper API
   - Adjusts projections upward when recent performance exceeds projection
   - Flags players as "BREAKOUT_CANDIDATE" or "TRENDING_UP"

✅ Declining Role Detection
   - Adjusts projections downward when recent performance < 70% of projection
   - Flags players as "DECLINING_ROLE" or "UNDERPERFORMING"
   - Helps users avoid starting players losing touches/opportunities

✅ Recent Performance Context
   - Shows "L3W avg: X.X pts/game" for informed decisions
   - Trend indicators: IMPROVING, DECLINING, STABLE
   - Performance flags provide at-a-glance insights

The layer integrates seamlessly with existing tools:
- ff_get_roster
- ff_get_waiver_wire
- ff_get_players
- ff_build_lineup

All enhancements are non-breaking - existing functionality continues to work
while users get richer, more accurate data for better decisions.
"""
    )


if __name__ == "__main__":
    asyncio.run(main())
