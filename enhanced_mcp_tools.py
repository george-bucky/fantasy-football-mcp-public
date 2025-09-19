"""
Enhanced MCP tools for client LLM decision-making.

This module provides enhanced tools that give the client LLM rich, structured data
to make intelligent fantasy football lineup decisions without requiring a backend LLM.
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple
from dataclasses import dataclass, asdict

from fastmcp import Context, FastMCP
from mcp.types import TextContent

# Import your existing modules
import fantasy_football_multi_league
from lineup_optimizer import LineupOptimizer, Player
from matchup_analyzer import matchup_analyzer
from sleeper_api import sleeper_client, get_trending_adds

logger = logging.getLogger(__name__)

# Create enhanced server
enhanced_server = FastMCP(
    name="fantasy-football-enhanced",
    instructions=(
        "Enhanced Yahoo Fantasy Football operations with rich player data, "
        "comprehensive analysis tools, and decision support for intelligent "
        "lineup optimization. The client LLM can use these tools to make "
        "championship-level fantasy football decisions."
    ),
)

# Initialize optimizer
lineup_optimizer = LineupOptimizer()


@dataclass
class EnhancedPlayerData:
    """Enhanced player data structure for LLM decision-making."""
    name: str
    position: str
    team: str
    opponent: str
    yahoo_projection: float
    sleeper_projection: float
    consensus_projection: float
    matchup_score: int
    matchup_description: str
    trending_score: int
    trending_description: str
    player_tier: str
    injury_status: str
    injury_probability: float
    ownership_pct: float
    recent_performance: List[float]
    season_avg: float
    target_share: float
    snap_count_pct: float
    weather_impact: str
    vegas_total: float
    team_implied_total: float
    spread: float
    def_rank_vs_pos: str
    value_score: float
    floor_projection: float
    ceiling_projection: float
    consistency_score: float
    risk_level: str
    recommendation_reasoning: str


@dataclass
class LineupAnalysis:
    """Comprehensive lineup analysis for LLM decision-making."""
    total_projected_points: float
    total_salary_used: int
    salary_remaining: int
    risk_assessment: str
    upside_potential: str
    floor_assessment: str
    key_strengths: List[str]
    key_concerns: List[str]
    leverage_opportunities: List[str]
    correlation_analysis: Dict[str, Any]
    weather_considerations: List[str]
    injury_risks: List[str]
    ownership_analysis: Dict[str, Any]
    matchup_advantages: List[str]
    alternative_considerations: List[str]


def _enhance_player_data(player: Player) -> EnhancedPlayerData:
    """Convert Player object to enhanced data structure."""
    
    # Calculate consensus projection
    projections = [p for p in [player.yahoo_projection, player.sleeper_projection] if p > 0]
    consensus_proj = sum(projections) / len(projections) if projections else 0.0
    
    # Determine risk level
    risk_level = "Low"
    if player.player_tier in ["bench", "unknown"]:
        risk_level = "High"
    elif player.matchup_score < 30:
        risk_level = "High"
    elif player.trending_score > 20000:
        risk_level = "Medium"
    
    # Generate recommendation reasoning
    reasoning_parts = []
    if player.player_tier in ["elite", "stud"]:
        reasoning_parts.append(f"Elite/stud tier player with {consensus_proj:.1f} projected points")
    if player.matchup_score >= 80:
        reasoning_parts.append(f"Excellent matchup vs {player.opponent} (score: {player.matchup_score}/100)")
    elif player.matchup_score <= 30:
        reasoning_parts.append(f"Tough matchup vs {player.opponent} (score: {player.matchup_score}/100)")
    if player.trending_score > 10000:
        reasoning_parts.append(f"High trending activity ({player.trending_score:,} adds)")
    
    reasoning = ". ".join(reasoning_parts) if reasoning_parts else "Standard player with average projections"
    
    return EnhancedPlayerData(
        name=player.name,
        position=player.position,
        team=player.team,
        opponent=player.opponent or "Unknown",
        yahoo_projection=player.yahoo_projection,
        sleeper_projection=player.sleeper_projection,
        consensus_projection=consensus_proj,
        matchup_score=player.matchup_score,
        matchup_description=player.matchup_description or "Unknown matchup",
        trending_score=player.trending_score,
        trending_description=f"{player.trending_score:,} adds" if player.trending_score > 0 else "No trending data",
        player_tier=player.player_tier,
        injury_status=getattr(player, 'injury_status', 'Healthy'),
        injury_probability=getattr(player, 'injury_probability', 0.0),
        ownership_pct=getattr(player, 'ownership_pct', 0.0),
        recent_performance=getattr(player, 'recent_performance', []),
        season_avg=getattr(player, 'season_avg', 0.0),
        target_share=getattr(player, 'target_share', 0.0),
        snap_count_pct=getattr(player, 'snap_count_pct', 0.0),
        weather_impact=getattr(player, 'weather_impact', 'Unknown'),
        vegas_total=getattr(player, 'vegas_total', 0.0),
        team_implied_total=getattr(player, 'implied_team_total', 0.0),
        spread=getattr(player, 'spread', 0.0),
        def_rank_vs_pos=getattr(player, 'defense_rank_allowed', 'Unknown'),
        value_score=getattr(player, 'value', 0.0),
        floor_projection=player.floor_projection,
        ceiling_projection=player.ceiling_projection,
        consistency_score=player.consistency_score,
        risk_level=risk_level,
        recommendation_reasoning=reasoning
    )


@enhanced_server.tool(
    name="ff_get_enhanced_roster",
    description=(
        "Get comprehensive roster data with enhanced player information including "
        "projections, matchups, trending data, injury status, and decision context. "
        "This provides rich data for intelligent lineup decisions."
    ),
)
async def ff_get_enhanced_roster(
    ctx: Context,
    league_key: str,
    team_key: Optional[str] = None,
    week: Optional[int] = None
) -> Dict[str, Any]:
    """Get enhanced roster data with comprehensive player information."""
    
    try:
        # Get basic roster data
        roster_response = await fantasy_football_multi_league.call_tool(
            "ff_get_roster",
            {"league_key": league_key, "team_key": team_key}
        )
        
        if not roster_response:
            return {"status": "error", "message": "Failed to get roster data"}
        
        roster_data = json.loads(roster_response[0].text)
        
        if roster_data.get("status") != "success":
            return roster_data
        
        # Parse players using the lineup optimizer
        players = await lineup_optimizer.parse_yahoo_roster(roster_data)
        
        if not players:
            return {"status": "error", "message": "Failed to parse player data"}
        
        # Enhance with external data
        enhanced_players = await lineup_optimizer.enhance_with_external_data(players)
        
        # Convert to enhanced data structure
        enhanced_data = []
        for player in enhanced_players:
            if player.is_valid():
                enhanced_data.append(_enhance_player_data(player))
        
        # Group by position for easier analysis
        players_by_position = {}
        for player_data in enhanced_data:
            pos = player_data.position
            if pos not in players_by_position:
                players_by_position[pos] = []
            players_by_position[pos].append(asdict(player_data))
        
        # Sort each position by consensus projection
        for pos in players_by_position:
            players_by_position[pos].sort(
                key=lambda x: x['consensus_projection'], 
                reverse=True
            )
        
        return {
            "status": "success",
            "team_info": roster_data.get("team_info", {}),
            "week": week or 1,
            "total_players": len(enhanced_data),
            "players_by_position": players_by_position,
            "all_players": [asdict(p) for p in enhanced_data],
            "analysis_context": {
                "data_sources": ["Yahoo", "Sleeper", "Matchup Analysis", "Trending Data"],
                "last_updated": datetime.now().isoformat(),
                "enhancement_level": "comprehensive"
            }
        }
        
    except Exception as e:
        logger.error(f"Enhanced roster fetch failed: {e}")
        return {"status": "error", "message": f"Enhanced roster fetch failed: {str(e)}"}


@enhanced_server.tool(
    name="ff_analyze_lineup_options",
    description=(
        "Analyze different lineup construction options with comprehensive data "
        "including risk assessment, upside potential, and strategic considerations. "
        "Provides multiple lineup scenarios for the client LLM to evaluate."
    ),
)
async def ff_analyze_lineup_options(
    ctx: Context,
    league_key: str,
    team_key: Optional[str] = None,
    week: Optional[int] = None,
    strategies: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Analyze different lineup construction strategies."""
    
    try:
        if strategies is None:
            strategies = ["balanced", "aggressive", "conservative"]
        
        # Get enhanced roster data
        roster_response = await ff_get_enhanced_roster(ctx, league_key, team_key, week)
        
        if roster_response.get("status") != "success":
            return roster_response
        
        # Parse players for optimization
        roster_data = {"fantasy_content": {"team": [{"roster": {"0": {"players": {}}}}]}}
        # This is a simplified approach - in practice you'd reconstruct the proper format
        
        players = await lineup_optimizer.parse_yahoo_roster(roster_response)
        enhanced_players = await lineup_optimizer.enhance_with_external_data(players)
        
        lineup_analyses = {}
        
        for strategy in strategies:
            try:
                # Optimize lineup with this strategy
                result = await lineup_optimizer.optimize_lineup_smart(
                    enhanced_players, 
                    strategy=strategy, 
                    week=week,
                    use_llm=False  # Use mathematical optimization only
                )
                
                if result.get("status") == "success":
                    # Create comprehensive analysis
                    analysis = _create_lineup_analysis(result, enhanced_players, strategy)
                    lineup_analyses[strategy] = analysis
                    
            except Exception as e:
                logger.warning(f"Strategy {strategy} optimization failed: {e}")
                continue
        
        return {
            "status": "success",
            "week": week or 1,
            "strategies_analyzed": list(lineup_analyses.keys()),
            "lineup_analyses": lineup_analyses,
            "recommendation_summary": _create_recommendation_summary(lineup_analyses),
            "analysis_metadata": {
                "total_players_analyzed": len(enhanced_players),
                "optimization_method": "mathematical",
                "analysis_timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Lineup analysis failed: {e}")
        return {"status": "error", "message": f"Lineup analysis failed: {str(e)}"}


@enhanced_server.tool(
    name="ff_compare_players",
    description=(
        "Compare multiple players with comprehensive analysis including projections, "
        "matchups, trends, and decision factors. Perfect for evaluating trade-offs "
        "and making informed decisions."
    ),
)
async def ff_compare_players(
    ctx: Context,
    league_key: str,
    player_names: List[str],
    comparison_factors: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Compare multiple players with detailed analysis."""
    
    try:
        if comparison_factors is None:
            comparison_factors = [
                "projections", "matchups", "trending", "injury_risk", 
                "ownership", "value", "consistency", "upside"
            ]
        
        # Get enhanced roster data to find players
        roster_response = await ff_get_enhanced_roster(ctx, league_key)
        
        if roster_response.get("status") != "success":
            return roster_response
        
        # Find the requested players
        all_players = roster_response.get("all_players", [])
        found_players = []
        
        for player_name in player_names:
            for player in all_players:
                if player_name.lower() in player["name"].lower():
                    found_players.append(player)
                    break
        
        if not found_players:
            return {
                "status": "error", 
                "message": f"No players found matching: {player_names}"
            }
        
        # Create comparison analysis
        comparison = _create_player_comparison(found_players, comparison_factors)
        
        return {
            "status": "success",
            "players_compared": len(found_players),
            "comparison_factors": comparison_factors,
            "player_data": found_players,
            "comparison_analysis": comparison,
            "recommendation": _generate_comparison_recommendation(found_players, comparison)
        }
        
    except Exception as e:
        logger.error(f"Player comparison failed: {e}")
        return {"status": "error", "message": f"Player comparison failed: {str(e)}"}


@enhanced_server.tool(
    name="ff_what_if_analysis",
    description=(
        "Perform 'what if' analysis for lineup changes. Compare current lineup "
        "with alternative scenarios to help make informed decisions about "
        "substitutions, strategy changes, or constraint modifications."
    ),
)
async def ff_what_if_analysis(
    ctx: Context,
    league_key: str,
    team_key: Optional[str] = None,
    week: Optional[int] = None,
    scenario_type: str = "player_substitution",
    scenario_data: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Perform what-if analysis for lineup scenarios."""
    
    try:
        if scenario_data is None:
            scenario_data = {}
        
        # Get current lineup analysis
        current_analysis = await ff_analyze_lineup_options(
            ctx, league_key, team_key, week, ["balanced"]
        )
        
        if current_analysis.get("status") != "success":
            return current_analysis
        
        current_lineup = current_analysis["lineup_analyses"].get("balanced", {})
        
        # Perform scenario analysis based on type
        if scenario_type == "player_substitution":
            scenario_analysis = await _analyze_player_substitution(
                ctx, league_key, scenario_data, current_lineup
            )
        elif scenario_type == "strategy_change":
            scenario_analysis = await _analyze_strategy_change(
                ctx, league_key, scenario_data, current_lineup
            )
        elif scenario_type == "constraint_change":
            scenario_analysis = await _analyze_constraint_change(
                ctx, league_key, scenario_data, current_lineup
            )
        else:
            return {
                "status": "error",
                "message": f"Unknown scenario type: {scenario_type}"
            }
        
        return {
            "status": "success",
            "scenario_type": scenario_type,
            "current_lineup": current_lineup,
            "scenario_analysis": scenario_analysis,
            "impact_summary": _create_impact_summary(current_lineup, scenario_analysis),
            "recommendation": _generate_scenario_recommendation(scenario_analysis)
        }
        
    except Exception as e:
        logger.error(f"What-if analysis failed: {e}")
        return {"status": "error", "message": f"What-if analysis failed: {str(e)}"}


@enhanced_server.tool(
    name="ff_get_decision_context",
    description=(
        "Get comprehensive decision context including league settings, "
        "opponent analysis, market conditions, and strategic factors "
        "to inform lineup decisions."
    ),
)
async def ff_get_decision_context(
    ctx: Context,
    league_key: str,
    week: Optional[int] = None
) -> Dict[str, Any]:
    """Get comprehensive decision context for lineup optimization."""
    
    try:
        # Get league info
        league_response = await fantasy_football_multi_league.call_tool(
            "ff_get_league_info",
            {"league_key": league_key}
        )
        
        if not league_response:
            return {"status": "error", "message": "Failed to get league info"}
        
        league_data = json.loads(league_response[0].text)
        
        # Get matchup info
        matchup_response = await fantasy_football_multi_league.call_tool(
            "ff_get_matchup",
            {"league_key": league_key, "week": week}
        )
        
        matchup_data = {}
        if matchup_response:
            matchup_data = json.loads(matchup_response[0].text)
        
        # Get standings for competitive context
        standings_response = await fantasy_football_multi_league.call_tool(
            "ff_get_standings",
            {"league_key": league_key}
        )
        
        standings_data = {}
        if standings_response:
            standings_data = json.loads(standings_response[0].text)
        
        # Get waiver wire for market context
        waiver_response = await fantasy_football_multi_league.call_tool(
            "ff_get_waiver_wire",
            {"league_key": league_key, "count": 20}
        )
        
        waiver_data = {}
        if waiver_response:
            waiver_data = json.loads(waiver_response[0].text)
        
        return {
            "status": "success",
            "week": week or 1,
            "league_context": {
                "league_info": league_data,
                "scoring_settings": league_data.get("scoring", {}),
                "roster_requirements": league_data.get("roster_requirements", {})
            },
            "competitive_context": {
                "matchup_info": matchup_data,
                "standings": standings_data,
                "playoff_implications": _analyze_playoff_implications(standings_data, week)
            },
            "market_context": {
                "waiver_wire": waiver_data,
                "trending_players": _get_trending_players(),
                "injury_report": _get_injury_report()
            },
            "strategic_factors": {
                "week_importance": _assess_week_importance(week),
                "weather_considerations": _get_weather_considerations(),
                "bye_week_impact": _analyze_bye_weeks(league_data, week)
            },
            "decision_framework": {
                "key_considerations": [
                    "Projected points vs matchup difficulty",
                    "Risk tolerance vs upside potential", 
                    "Ownership leverage vs chalk plays",
                    "Injury risk vs consistency",
                    "Playoff implications vs weekly wins"
                ],
                "decision_priority": [
                    "1. Elite/stud players must start regardless of matchup",
                    "2. Favorable matchups for mid-tier players",
                    "3. Contrarian plays for tournament leverage",
                    "4. Injury risk assessment and backup plans",
                    "5. Weather and game environment factors"
                ]
            }
        }
        
    except Exception as e:
        logger.error(f"Decision context fetch failed: {e}")
        return {"status": "error", "message": f"Decision context fetch failed: {str(e)}"}


# Helper functions for analysis

def _create_lineup_analysis(result: Dict[str, Any], players: List[Player], strategy: str) -> Dict[str, Any]:
    """Create comprehensive lineup analysis."""
    
    starters = result.get("starters", {})
    total_points = sum(
        player.get_best_projection() for player in starters.values() 
        if hasattr(player, 'get_best_projection')
    )
    
    # Analyze strengths and concerns
    strengths = []
    concerns = []
    
    for pos, player in starters.items():
        if hasattr(player, 'player_tier') and player.player_tier in ["elite", "stud"]:
            strengths.append(f"{pos}: {player.name} is {player.player_tier} tier")
        
        if hasattr(player, 'matchup_score') and player.matchup_score < 30:
            concerns.append(f"{pos}: {player.name} has tough matchup (score: {player.matchup_score})")
    
    return {
        "strategy": strategy,
        "total_projected_points": total_points,
        "starters": {pos: player.name for pos, player in starters.items()},
        "key_strengths": strengths,
        "key_concerns": concerns,
        "risk_assessment": _assess_lineup_risk(starters),
        "upside_potential": _assess_upside_potential(starters),
        "recommendation_reasoning": _generate_lineup_reasoning(starters, strategy)
    }


def _create_player_comparison(players: List[Dict[str, Any]], factors: List[str]) -> Dict[str, Any]:
    """Create detailed player comparison analysis."""
    
    comparison = {}
    
    for factor in factors:
        if factor == "projections":
            comparison[factor] = {
                "leader": max(players, key=lambda x: x["consensus_projection"]),
                "analysis": "Projection comparison with confidence levels"
            }
        elif factor == "matchups":
            comparison[factor] = {
                "leader": max(players, key=lambda x: x["matchup_score"]),
                "analysis": "Matchup difficulty and opportunity assessment"
            }
        elif factor == "trending":
            comparison[factor] = {
                "leader": max(players, key=lambda x: x["trending_score"]),
                "analysis": "Market sentiment and trending activity"
            }
        # Add more factor analyses as needed
    
    return comparison


def _generate_comparison_recommendation(players: List[Dict[str, Any]], comparison: Dict[str, Any]) -> str:
    """Generate recommendation based on player comparison."""
    
    # Simple recommendation logic - can be enhanced
    best_projection = max(players, key=lambda x: x["consensus_projection"])
    best_matchup = max(players, key=lambda x: x["matchup_score"])
    
    if best_projection == best_matchup:
        return f"Strong recommendation for {best_projection['name']} - best projection ({best_projection['consensus_projection']:.1f}) and matchup ({best_matchup['matchup_score']}/100)"
    else:
        return f"Consider {best_projection['name']} for projection ({best_projection['consensus_projection']:.1f}) or {best_matchup['name']} for matchup ({best_matchup['matchup_score']}/100)"


def _create_recommendation_summary(analyses: Dict[str, Any]) -> Dict[str, Any]:
    """Create summary of lineup strategy recommendations."""
    
    if not analyses:
        return {"message": "No analyses available"}
    
    # Find best strategy by total points
    best_strategy = max(analyses.keys(), key=lambda s: analyses[s].get("total_projected_points", 0))
    
    return {
        "recommended_strategy": best_strategy,
        "reasoning": f"Highest projected points ({analyses[best_strategy].get('total_projected_points', 0):.1f})",
        "strategy_comparison": {
            strategy: {
                "points": analysis.get("total_projected_points", 0),
                "risk": analysis.get("risk_assessment", "Unknown")
            }
            for strategy, analysis in analyses.items()
        }
    }


# Additional helper functions for context analysis
def _analyze_playoff_implications(standings_data: Dict[str, Any], week: int) -> Dict[str, Any]:
    """Analyze playoff implications based on standings and week."""
    return {
        "playoff_race": "Active" if week >= 10 else "Early season",
        "must_win": week >= 12,
        "strategy_impact": "Aggressive if must-win, balanced if playoff secure"
    }


def _get_trending_players() -> List[Dict[str, Any]]:
    """Get trending players data."""
    # This would integrate with your trending data source
    return []


def _get_injury_report() -> List[Dict[str, Any]]:
    """Get injury report data."""
    # This would integrate with your injury data source
    return []


def _assess_week_importance(week: int) -> str:
    """Assess the importance of the current week."""
    if week <= 3:
        return "Early season - focus on season-long value"
    elif week <= 10:
        return "Mid-season - balance weekly wins with long-term strategy"
    elif week <= 14:
        return "Playoff push - prioritize weekly wins"
    else:
        return "Playoffs - all-in approach"


def _get_weather_considerations() -> List[str]:
    """Get weather considerations for the week."""
    # This would integrate with weather data
    return []


def _analyze_bye_weeks(league_data: Dict[str, Any], week: int) -> Dict[str, Any]:
    """Analyze bye week impact."""
    return {
        "teams_on_bye": [],
        "impact_assessment": "Minimal" if week < 5 or week > 14 else "Moderate"
    }


def _assess_lineup_risk(starters: Dict[str, Any]) -> str:
    """Assess overall lineup risk level."""
    # Simple risk assessment logic
    high_risk_count = 0
    for player in starters.values():
        if hasattr(player, 'player_tier') and player.player_tier in ["bench", "unknown"]:
            high_risk_count += 1
    
    if high_risk_count >= 3:
        return "High"
    elif high_risk_count >= 1:
        return "Medium"
    else:
        return "Low"


def _assess_upside_potential(starters: Dict[str, Any]) -> str:
    """Assess lineup upside potential."""
    # Simple upside assessment logic
    elite_count = 0
    for player in starters.values():
        if hasattr(player, 'player_tier') and player.player_tier in ["elite", "stud"]:
            elite_count += 1
    
    if elite_count >= 4:
        return "Very High"
    elif elite_count >= 2:
        return "High"
    else:
        return "Medium"


def _generate_lineup_reasoning(starters: Dict[str, Any], strategy: str) -> str:
    """Generate reasoning for lineup construction."""
    reasoning_parts = [f"Built using {strategy} strategy"]
    
    elite_players = [player.name for player in starters.values() 
                    if hasattr(player, 'player_tier') and player.player_tier in ["elite", "stud"]]
    
    if elite_players:
        reasoning_parts.append(f"Features elite/stud players: {', '.join(elite_players)}")
    
    return ". ".join(reasoning_parts)


# Scenario analysis functions
async def _analyze_player_substitution(
    ctx: Context, 
    league_key: str, 
    scenario_data: Dict[str, Any], 
    current_lineup: Dict[str, Any]
) -> Dict[str, Any]:
    """Analyze player substitution scenario."""
    # Implementation for player substitution analysis
    return {"type": "player_substitution", "impact": "To be implemented"}


async def _analyze_strategy_change(
    ctx: Context, 
    league_key: str, 
    scenario_data: Dict[str, Any], 
    current_lineup: Dict[str, Any]
) -> Dict[str, Any]:
    """Analyze strategy change scenario."""
    # Implementation for strategy change analysis
    return {"type": "strategy_change", "impact": "To be implemented"}


async def _analyze_constraint_change(
    ctx: Context, 
    league_key: str, 
    scenario_data: Dict[str, Any], 
    current_lineup: Dict[str, Any]
) -> Dict[str, Any]:
    """Analyze constraint change scenario."""
    # Implementation for constraint change analysis
    return {"type": "constraint_change", "impact": "To be implemented"}


def _create_impact_summary(current: Dict[str, Any], scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Create impact summary for scenario analysis."""
    return {
        "point_impact": 0.0,  # Calculate actual impact
        "risk_impact": "Neutral",
        "recommendation": "No significant change"
    }


def _generate_scenario_recommendation(scenario_analysis: Dict[str, Any]) -> str:
    """Generate recommendation for scenario analysis."""
    return f"Scenario analysis: {scenario_analysis.get('impact', 'Unknown impact')}"


# Export the enhanced server
__all__ = ["enhanced_server", "ff_get_enhanced_roster", "ff_analyze_lineup_options", 
           "ff_compare_players", "ff_what_if_analysis", "ff_get_decision_context"]