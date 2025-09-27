#!/usr/bin/env python3
"""
Test a simplified fixed version of waiver wire enhancement
"""

import asyncio
import sys
import os
from typing import Dict, Any, List

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def fixed_waiver_wire_handler(arguments: dict) -> dict:
    """Fixed version of the waiver wire handler with proper structure"""
    from fantasy_football_multi_league import get_waiver_wire_players
    from lineup_optimizer import lineup_optimizer, Player
    from sleeper_api import get_trending_adds, sleeper_client

    # Extract arguments
    league_key = arguments.get("league_key")
    position = arguments.get("position", "all")
    sort_type = arguments.get("sort", "rank")
    count = arguments.get("count", 30)
    week = arguments.get("week")
    team_key = arguments.get("team_key")
    include_analysis = arguments.get("include_analysis", False)
    include_projections = arguments.get("include_projections", True)
    include_external_data = arguments.get("include_external_data", True)

    # Fetch basic Yahoo waiver players
    basic_players = await get_waiver_wire_players(league_key, position, sort_type, count)
    if not basic_players:
        return {
            "league_key": league_key,
            "message": "No available players found or error retrieving data",
        }

    result = {
        "status": "success",
        "league_key": league_key,
        "position": position,
        "sort": sort_type,
        "total_players": len(basic_players),
        "players": basic_players,
    }

    # Check if enhancement is needed
    needs_enhancement = include_projections or include_external_data or include_analysis
    if not needs_enhancement:
        return result

    try:
        # Create payload for optimizer
        optimizer_payload = {
            "league_key": league_key,
            "team_key": team_key or "",
            "roster": basic_players,
        }
        enhanced_players = await lineup_optimizer.parse_yahoo_roster(optimizer_payload)

        if not enhanced_players:
            result["note"] = "No players could be enhanced"
            return result

        # Enhance with external data
        enhanced_players = await lineup_optimizer.enhance_with_external_data(enhanced_players, week=week)

        # Add expert advice for waiver wire analysis
        if include_analysis:
            print(f"Adding expert advice for {len(enhanced_players)} players...")
            for player in enhanced_players:
                try:
                    expert_advice = await sleeper_client.get_expert_advice(player.name, week)
                    player.expert_tier = expert_advice.get("tier", "Depth")
                    player.expert_recommendation = expert_advice.get("recommendation", "Bench")
                    player.expert_confidence = expert_advice.get("confidence", 50)
                    player.expert_advice = expert_advice.get("advice", "No analysis available")
                except Exception as e:
                    # Continue with default values if expert advice fails
                    player.expert_tier = "Depth"
                    player.expert_recommendation = "Monitor"
                    player.expert_confidence = 50
                    player.expert_advice = f"Expert analysis unavailable: {str(e)[:50]}"

        # Fetch trending data
        trending = await get_trending_adds(count)
        trending_dict = {p["name"].lower(): p for p in trending}

        # Calculate position scarcity
        position_scarcity = {}
        if include_analysis:
            position_counts = {}
            for p in basic_players:
                pos = p.get("position", "Unknown")
                owned = p.get("owned_pct", 0.0)
                if pos not in position_counts:
                    position_counts[pos] = {"total": 0, "owned_sum": 0}
                position_counts[pos]["total"] += 1
                position_counts[pos]["owned_sum"] += owned

            for pos, data in position_counts.items():
                avg_owned = data["owned_sum"] / data["total"] if data["total"] > 0 else 0
                scarcity_score = min(avg_owned / 10, 10)
                position_scarcity[pos] = {
                    "scarcity_score": round(scarcity_score, 1),
                    "avg_ownership": round(avg_owned, 1),
                    "available_count": data["total"]
                }

        # Serialize enhanced players
        enhanced_list = []
        for player in enhanced_players:
            if not player.is_valid():
                continue

            # Create base player data
            base = {
                "name": player.name,
                "position": player.position,
                "team": player.team,
                "opponent": player.opponent or "N/A",
                "status": getattr(player, "status", "Available"),
                "yahoo_projection": player.yahoo_projection if include_projections else None,
                "sleeper_projection": player.sleeper_projection if include_projections else None,
                "sleeper_id": player.sleeper_id,
                "sleeper_match_method": player.sleeper_match_method,
                "floor_projection": player.floor_projection if include_projections else None,
                "ceiling_projection": player.ceiling_projection if include_projections else None,
                "consistency_score": player.consistency_score,
                "player_tier": player.player_tier,
                "matchup_score": player.matchup_score if include_external_data else None,
                "matchup_description": player.matchup_description if include_external_data else None,
                "trending_score": player.trending_score if include_external_data else None,
                "risk_level": player.risk_level,
                "injury_status": getattr(player, "injury_status", "Healthy"),
                # Expert advice fields
                "expert_tier": getattr(player, "expert_tier", None) if include_analysis else None,
                "expert_recommendation": getattr(player, "expert_recommendation", None) if include_analysis else None,
                "expert_confidence": getattr(player, "expert_confidence", None) if include_analysis else None,
                "expert_advice": getattr(player, "expert_advice", None) if include_analysis else None,
            }

            # Add Yahoo-specific data
            for p in basic_players:
                if p.get("name", "").lower() == player.name.lower():
                    base["owned_pct"] = p.get("owned_pct", 0.0)
                    base["weekly_change"] = p.get("weekly_change", 0)
                    base["bye"] = p.get("bye", "N/A")
                    break

            # Merge trending data
            name_lower = player.name.lower()
            if name_lower in trending_dict:
                trend = trending_dict[name_lower]
                base["trending_count"] = trend.get("count", 0)
                base["trending_position"] = trend.get("position")

            # Add waiver-specific analysis
            if include_analysis:
                expert_confidence = getattr(player, "expert_confidence", 50)
                proj = (player.yahoo_projection or 0) + (player.sleeper_projection or 0)
                trend_score = base.get("trending_count", 0)
                owned = base.get("owned_pct", 0.0)

                # Position scarcity bonus
                pos_scarcity = position_scarcity.get(player.position, {}).get("scarcity_score", 0)
                scarcity_bonus = min(pos_scarcity * 0.5, 5)

                # Calculate waiver priority
                confidence_score = expert_confidence * 0.35
                projection_score = min(proj * 2, 30)
                ownership_bonus = max(0, (50 - owned) * 0.4)
                trending_bonus = min(trend_score * 1.5, 10)

                waiver_priority = confidence_score + projection_score + ownership_bonus + trending_bonus + scarcity_bonus
                base["waiver_priority"] = round(waiver_priority, 1)

                # Analysis text
                expert_tier = getattr(player, "expert_tier", "Unknown")
                expert_rec = getattr(player, "expert_recommendation", "Monitor")
                scarcity_text = ""
                if pos_scarcity > 7:
                    scarcity_text = f" HIGH SCARCITY at {player.position}!"
                elif pos_scarcity > 4:
                    scarcity_text = f" Moderate scarcity at {player.position}."

                base["analysis"] = (
                    f"{expert_tier} tier player with {expert_confidence}% confidence. "
                    f"Recommendation: {expert_rec}. Priority: {base['waiver_priority']}/100 "
                    f"(proj: {proj:.1f}, owned: {owned:.1f}%, trending: {trend_score}){scarcity_text}"
                )

                # Pickup urgency
                urgency_threshold = waiver_priority + (scarcity_bonus * 2)
                if urgency_threshold >= 80:
                    base["pickup_urgency"] = "MUST ADD - Elite waiver target"
                elif urgency_threshold >= 65:
                    base["pickup_urgency"] = "High Priority - Strong pickup"
                elif urgency_threshold >= 50:
                    base["pickup_urgency"] = "Moderate - Worth a claim"
                elif urgency_threshold >= 35:
                    base["pickup_urgency"] = "Low Priority - Depth option"
                else:
                    base["pickup_urgency"] = "Avoid - Better options available"

                # Position context
                base["position_context"] = position_scarcity.get(player.position, {
                    "scarcity_score": 0,
                    "avg_ownership": 0,
                    "available_count": 0
                })

            enhanced_list.append(base)

        # Sort enhanced list
        if include_analysis:
            enhanced_list.sort(key=lambda x: x.get("waiver_priority", 0), reverse=True)
        elif include_projections:
            enhanced_list.sort(
                key=lambda x: (x.get("sleeper_projection") or 0) + (x.get("yahoo_projection") or 0),
                reverse=True,
            )

        # Update result with enhanced data
        result["enhanced_players"] = enhanced_list
        result["analysis_context"] = {
            "data_sources": ["Yahoo"] + (["Sleeper"] if include_external_data else []),
            "includes": {
                "projections": include_projections,
                "external_data": include_external_data,
                "analysis": include_analysis,
                "expert_advice": include_analysis,
            },
            "features": [f for f in [
                "Yahoo ownership and change data",
                "Sleeper projections and rankings" if include_external_data else None,
                "Matchup analysis" if include_external_data else None,
                "Expert tier classification" if include_analysis else None,
                "Waiver priority scoring" if include_analysis else None,
                "Pickup urgency assessment" if include_analysis else None,
                "Positional scarcity analysis" if include_analysis else None,
            ] if f],
            "algorithm": {
                "waiver_priority_weights": {
                    "expert_confidence": "35%",
                    "projections": "30%",
                    "ownership_bonus": "20%",
                    "trending_bonus": "10%",
                    "scarcity_bonus": "5%"
                }
            } if include_analysis else None,
            "position_scarcity": position_scarcity if include_analysis else None,
            "week": week or "current",
            "trending_count": len(trending),
        }

    except Exception as exc:
        result["note"] = f"Enhancement failed: {exc}. Using basic data."

    return result


async def test_fixed_waiver():
    """Test the fixed waiver wire function"""
    print("🧪 Testing Fixed Waiver Wire Function")
    print("=" * 50)

    test_args = {
        "league_key": "461.l.900001",
        "position": "RB",
        "count": 3,
        "include_analysis": True,
        "include_projections": True,
        "include_external_data": True,
    }

    result = await fixed_waiver_wire_handler(test_args)

    print(f"Status: {result.get('status')}")
    print(f"Enhanced Players: {len(result.get('enhanced_players', []))}")

    if result.get("enhanced_players"):
        sample = result["enhanced_players"][0]
        print(f"\nSample Player: {sample.get('name')}")
        print(f"  Expert Tier: {sample.get('expert_tier')}")
        print(f"  Expert Confidence: {sample.get('expert_confidence')}")
        print(f"  Waiver Priority: {sample.get('waiver_priority')}")
        print(f"  Pickup Urgency: {sample.get('pickup_urgency')}")
        print(f"  Analysis: {sample.get('analysis', 'None')[:100]}...")

        # Check algorithm info
        context = result.get("analysis_context", {})
        print(f"\nAlgorithm Weights: {context.get('algorithm', {}).get('waiver_priority_weights', {})}")
        print(f"Position Scarcity: {len(context.get('position_scarcity', {}))}")

        # Overall assessment
        has_expert = sample.get('expert_tier') is not None
        has_priority = sample.get('waiver_priority') is not None
        has_urgency = sample.get('pickup_urgency') is not None

        print(f"\n✅ Enhancement Check:")
        print(f"  Expert Advice: {'✅ PASS' if has_expert else '❌ FAIL'}")
        print(f"  Waiver Priority: {'✅ PASS' if has_priority else '❌ FAIL'}")
        print(f"  Pickup Urgency: {'✅ PASS' if has_urgency else '❌ FAIL'}")

        success = sum([has_expert, has_priority, has_urgency])
        print(f"  Overall: {success}/3 features working")

if __name__ == "__main__":
    asyncio.run(test_fixed_waiver())