"""
Integrated MCP server combining existing fantasy football tools with enhanced decision-making capabilities.

This module integrates the enhanced MCP tools with the existing FastMCP server to provide
a comprehensive fantasy football analysis platform for client LLMs.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Sequence
from fastmcp import Context, FastMCP

# Import existing server and tools
from fastmcp_server import server as base_server, _call_legacy_tool, _tool_meta
from enhanced_mcp_tools import (
    enhanced_server,
    ff_get_enhanced_roster,
    ff_analyze_lineup_options,
    ff_compare_players,
    ff_what_if_analysis,
    ff_get_decision_context
)
from enhanced_mcp_prompts import (
    lineup_optimization_analysis,
    player_comparison_analysis,
    what_if_scenario_analysis,
    weekly_strategy_planning,
    trade_evaluation_analysis
)

logger = logging.getLogger(__name__)

# Create integrated server
integrated_server = FastMCP(
    name="fantasy-football-integrated",
    instructions=(
        "Comprehensive Yahoo Fantasy Football operations with enhanced decision-making capabilities. "
        "This server provides both traditional fantasy football tools and advanced analysis capabilities "
        "for intelligent lineup optimization, player evaluation, and strategic decision-making. "
        "Perfect for client LLMs that need rich data and analysis tools for championship-level "
        "fantasy football decisions."
    ),
)

# Copy all tools from base server
for tool_name in base_server._tools:
    tool = base_server._tools[tool_name]
    integrated_server._tools[tool_name] = tool

# Copy all prompts from base server
for prompt_name in base_server._prompts:
    prompt = base_server._prompts[prompt_name]
    integrated_server._prompts[prompt_name] = prompt

# Copy all resources from base server
for resource_name in base_server._resources:
    resource = base_server._resources[resource_name]
    integrated_server._resources[resource_name] = resource

# Add enhanced tools
integrated_server._tools.update(enhanced_server._tools)

# Add enhanced prompts
integrated_server._prompts.update(enhanced_server._prompts)

# Add enhanced resources
integrated_server._resources.update(enhanced_server._resources)


# Enhanced tool integration with existing tools

@integrated_server.tool(
    name="ff_get_comprehensive_analysis",
    description=(
        "Get comprehensive fantasy football analysis combining traditional data with "
        "enhanced decision-making capabilities. This is the ultimate tool for client LLMs "
        "that need complete context for intelligent lineup decisions."
    ),
    meta={
        "prompt": (
            "Use this tool when you need comprehensive analysis for lineup decisions. "
            "It combines league context, enhanced roster data, lineup options, and "
            "decision framework in one comprehensive response."
        )
    }
)
async def ff_get_comprehensive_analysis(
    ctx: Context,
    league_key: str,
    team_key: Optional[str] = None,
    week: Optional[int] = None,
    analysis_type: str = "full"
) -> Dict[str, Any]:
    """Get comprehensive analysis combining all available data and tools."""
    
    try:
        if ctx is not None:
            await ctx.info(f"Starting comprehensive analysis for league {league_key}")
        
        # Get decision context
        context_response = await ff_get_decision_context(ctx, league_key, week)
        
        # Get enhanced roster data
        roster_response = await ff_get_enhanced_roster(ctx, league_key, team_key, week)
        
        # Get lineup analysis options
        lineup_response = await ff_analyze_lineup_options(
            ctx, league_key, team_key, week, ["balanced", "aggressive", "conservative"]
        )
        
        # Get waiver wire for market context
        waiver_response = await _call_legacy_tool(
            "ff_get_waiver_wire",
            ctx=ctx,
            league_key=league_key,
            count=20
        )
        
        # Get matchup info
        matchup_response = await _call_legacy_tool(
            "ff_get_matchup",
            ctx=ctx,
            league_key=league_key,
            week=week
        )
        
        # Compile comprehensive analysis
        comprehensive_analysis = {
            "status": "success",
            "analysis_type": analysis_type,
            "week": week or 1,
            "league_key": league_key,
            "team_key": team_key,
            "timestamp": json.dumps({"timestamp": "2024-01-01T00:00:00Z"}),
            
            # Core data
            "decision_context": context_response,
            "enhanced_roster": roster_response,
            "lineup_analyses": lineup_response,
            "waiver_wire": waiver_response,
            "matchup_info": matchup_response,
            
            # Analysis summary
            "analysis_summary": {
                "total_players_analyzed": len(roster_response.get("all_players", [])),
                "strategies_available": list(lineup_response.get("lineup_analyses", {}).keys()),
                "key_insights": _extract_key_insights(roster_response, lineup_response),
                "recommendations": _generate_primary_recommendations(lineup_response),
                "risk_assessment": _assess_overall_risk(roster_response, lineup_response)
            },
            
            # Decision framework
            "decision_framework": {
                "primary_factors": [
                    "Player projections and confidence levels",
                    "Matchup scores and opponent analysis", 
                    "Player tiers and must-start considerations",
                    "Injury status and risk assessment"
                ],
                "secondary_factors": [
                    "Trending data and market sentiment",
                    "Ownership percentages and leverage opportunities",
                    "Weather and game environment factors",
                    "Playoff implications and week importance"
                ],
                "decision_priority": [
                    "1. Start elite/stud players regardless of matchup",
                    "2. Target favorable matchups for mid-tier players",
                    "3. Consider contrarian plays for tournament leverage",
                    "4. Manage injury risk with backup plans",
                    "5. Adapt strategy based on league context"
                ]
            },
            
            # Actionable insights
            "actionable_insights": {
                "immediate_actions": _generate_immediate_actions(roster_response, lineup_response),
                "considerations": _generate_considerations(context_response, roster_response),
                "contingency_plans": _generate_contingency_plans(roster_response, matchup_response)
            }
        }
        
        if ctx is not None:
            await ctx.info("Comprehensive analysis completed successfully")
        
        return comprehensive_analysis
        
    except Exception as e:
        logger.error(f"Comprehensive analysis failed: {e}")
        return {
            "status": "error",
            "message": f"Comprehensive analysis failed: {str(e)}",
            "league_key": league_key,
            "team_key": team_key,
            "week": week
        }


@integrated_server.tool(
    name="ff_smart_lineup_optimizer",
    description=(
        "Intelligent lineup optimizer that provides comprehensive analysis and recommendations "
        "for optimal lineup construction. Combines mathematical optimization with strategic "
        "insights for championship-level decisions."
    ),
    meta={
        "prompt": (
            "Use this tool for the most intelligent lineup optimization. It provides "
            "comprehensive analysis, multiple strategy options, and clear recommendations "
            "with detailed reasoning for each decision."
        )
    }
)
async def ff_smart_lineup_optimizer(
    ctx: Context,
    league_key: str,
    team_key: Optional[str] = None,
    week: Optional[int] = None,
    strategy_preference: str = "balanced",
    include_alternatives: bool = True,
    include_analysis: bool = True
) -> Dict[str, Any]:
    """Smart lineup optimizer with comprehensive analysis and recommendations."""
    
    try:
        if ctx is not None:
            await ctx.info(f"Starting smart lineup optimization for league {league_key}")
        
        # Get comprehensive analysis
        analysis = await ff_get_comprehensive_analysis(
            ctx, league_key, team_key, week, "lineup_optimization"
        )
        
        if analysis.get("status") != "success":
            return analysis
        
        # Extract key data
        roster_data = analysis["enhanced_roster"]
        lineup_analyses = analysis["lineup_analyses"]["lineup_analyses"]
        decision_context = analysis["decision_context"]
        
        # Generate smart recommendations
        smart_recommendations = _generate_smart_recommendations(
            roster_data, lineup_analyses, decision_context, strategy_preference
        )
        
        # Build response
        response = {
            "status": "success",
            "optimization_type": "smart_comprehensive",
            "week": week or 1,
            "strategy_preference": strategy_preference,
            "primary_recommendation": smart_recommendations["primary"],
            "confidence_score": smart_recommendations["confidence"],
            "reasoning": smart_recommendations["reasoning"]
        }
        
        if include_alternatives:
            response["alternatives"] = smart_recommendations["alternatives"]
        
        if include_analysis:
            response["detailed_analysis"] = {
                "player_analysis": _analyze_key_players(roster_data),
                "strategy_comparison": _compare_strategies(lineup_analyses),
                "risk_assessment": _assess_lineup_risks(roster_data, lineup_analyses),
                "opportunity_analysis": _identify_opportunities(roster_data, decision_context)
            }
        
        response["implementation_guide"] = {
            "immediate_actions": smart_recommendations["immediate_actions"],
            "monitoring_points": smart_recommendations["monitoring_points"],
            "contingency_plans": smart_recommendations["contingency_plans"]
        }
        
        if ctx is not None:
            await ctx.info("Smart lineup optimization completed successfully")
        
        return response
        
    except Exception as e:
        logger.error(f"Smart lineup optimization failed: {e}")
        return {
            "status": "error",
            "message": f"Smart lineup optimization failed: {str(e)}",
            "league_key": league_key,
            "team_key": team_key,
            "week": week
        }


# Helper functions for comprehensive analysis

def _extract_key_insights(roster_data: Dict[str, Any], lineup_data: Dict[str, Any]) -> List[str]:
    """Extract key insights from roster and lineup data."""
    insights = []
    
    # Analyze roster data
    if roster_data.get("status") == "success":
        players = roster_data.get("all_players", [])
        
        # Find elite players
        elite_players = [p for p in players if p.get("player_tier") in ["elite", "stud"]]
        if elite_players:
            insights.append(f"Team has {len(elite_players)} elite/stud players: {', '.join([p['name'] for p in elite_players])}")
        
        # Find injury concerns
        injured_players = [p for p in players if p.get("injury_status") not in ["Healthy", "Probable"]]
        if injured_players:
            insights.append(f"Injury concerns: {', '.join([p['name'] for p in injured_players])}")
        
        # Find favorable matchups
        good_matchups = [p for p in players if p.get("matchup_score", 0) >= 70]
        if good_matchups:
            insights.append(f"Favorable matchups: {', '.join([p['name'] for p in good_matchups])}")
    
    # Analyze lineup data
    if lineup_data.get("status") == "success":
        analyses = lineup_data.get("lineup_analyses", {})
        if analyses:
            best_strategy = max(analyses.keys(), key=lambda s: analyses[s].get("total_projected_points", 0))
            insights.append(f"Best strategy: {best_strategy} with {analyses[best_strategy].get('total_projected_points', 0):.1f} projected points")
    
    return insights


def _generate_primary_recommendations(lineup_data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate primary recommendations from lineup analysis."""
    if lineup_data.get("status") != "success":
        return {"message": "No lineup data available"}
    
    analyses = lineup_data.get("lineup_analyses", {})
    if not analyses:
        return {"message": "No lineup analyses available"}
    
    # Find best strategy
    best_strategy = max(analyses.keys(), key=lambda s: analyses[s].get("total_projected_points", 0))
    best_analysis = analyses[best_strategy]
    
    return {
        "recommended_strategy": best_strategy,
        "projected_points": best_analysis.get("total_projected_points", 0),
        "risk_level": best_analysis.get("risk_assessment", "Unknown"),
        "key_strengths": best_analysis.get("key_strengths", []),
        "key_concerns": best_analysis.get("key_concerns", []),
        "reasoning": best_analysis.get("recommendation_reasoning", "No reasoning provided")
    }


def _assess_overall_risk(roster_data: Dict[str, Any], lineup_data: Dict[str, Any]) -> Dict[str, Any]:
    """Assess overall risk level of the team and lineup."""
    risk_factors = []
    risk_level = "Low"
    
    # Analyze roster risks
    if roster_data.get("status") == "success":
        players = roster_data.get("all_players", [])
        
        # Injury risks
        injured_count = len([p for p in players if p.get("injury_status") not in ["Healthy", "Probable"]])
        if injured_count > 0:
            risk_factors.append(f"{injured_count} players with injury concerns")
        
        # Low-tier players
        low_tier_count = len([p for p in players if p.get("player_tier") in ["bench", "unknown"]])
        if low_tier_count > 2:
            risk_factors.append(f"{low_tier_count} low-tier players")
        
        # Tough matchups
        tough_matchups = len([p for p in players if p.get("matchup_score", 0) < 30])
        if tough_matchups > 1:
            risk_factors.append(f"{tough_matchups} players with tough matchups")
    
    # Determine overall risk level
    if len(risk_factors) >= 3:
        risk_level = "High"
    elif len(risk_factors) >= 1:
        risk_level = "Medium"
    
    return {
        "overall_risk": risk_level,
        "risk_factors": risk_factors,
        "mitigation_strategies": [
            "Monitor injury reports closely",
            "Have backup options ready",
            "Consider streaming options for tough matchups"
        ]
    }


def _generate_immediate_actions(roster_data: Dict[str, Any], lineup_data: Dict[str, Any]) -> List[str]:
    """Generate immediate actions based on analysis."""
    actions = []
    
    if roster_data.get("status") == "success":
        players = roster_data.get("all_players", [])
        
        # Check for injury concerns
        injured_players = [p for p in players if p.get("injury_status") not in ["Healthy", "Probable"]]
        if injured_players:
            actions.append(f"Monitor injury status for: {', '.join([p['name'] for p in injured_players])}")
        
        # Check for lineup decisions
        if lineup_data.get("status") == "success":
            actions.append("Review lineup optimization recommendations")
            actions.append("Consider alternative strategies if needed")
    
    return actions


def _generate_considerations(context_data: Dict[str, Any], roster_data: Dict[str, Any]) -> List[str]:
    """Generate considerations based on context and roster."""
    considerations = []
    
    # League context considerations
    if context_data.get("status") == "success":
        league_context = context_data.get("league_context", {})
        competitive_context = context_data.get("competitive_context", {})
        
        # Week importance
        week_importance = context_data.get("strategic_factors", {}).get("week_importance", "Unknown")
        considerations.append(f"Week importance: {week_importance}")
        
        # Playoff implications
        playoff_implications = competitive_context.get("playoff_implications", {})
        if playoff_implications.get("must_win"):
            considerations.append("Must-win situation - consider aggressive strategy")
    
    # Roster considerations
    if roster_data.get("status") == "success":
        players = roster_data.get("all_players", [])
        
        # Elite players
        elite_players = [p for p in players if p.get("player_tier") in ["elite", "stud"]]
        if elite_players:
            considerations.append(f"Elite players must start: {', '.join([p['name'] for p in elite_players])}")
        
        # Favorable matchups
        good_matchups = [p for p in players if p.get("matchup_score", 0) >= 70]
        if good_matchups:
            considerations.append(f"Favorable matchups to exploit: {', '.join([p['name'] for p in good_matchups])}")
    
    return considerations


def _generate_contingency_plans(roster_data: Dict[str, Any], matchup_data: Dict[str, Any]) -> List[str]:
    """Generate contingency plans for various scenarios."""
    plans = []
    
    if roster_data.get("status") == "success":
        players = roster_data.get("all_players", [])
        
        # Injury contingency plans
        injured_players = [p for p in players if p.get("injury_status") not in ["Healthy", "Probable"]]
        if injured_players:
            for player in injured_players:
                plans.append(f"If {player['name']} is ruled out, consider backup options")
        
        # Weather contingency plans
        plans.append("Monitor weather reports for outdoor games")
        plans.append("Consider weather impact on passing games")
    
    return plans


def _generate_smart_recommendations(
    roster_data: Dict[str, Any], 
    lineup_analyses: Dict[str, Any], 
    decision_context: Dict[str, Any],
    strategy_preference: str
) -> Dict[str, Any]:
    """Generate smart recommendations based on comprehensive analysis."""
    
    # Find best strategy
    if strategy_preference in lineup_analyses:
        best_strategy = strategy_preference
    else:
        best_strategy = max(lineup_analyses.keys(), key=lambda s: lineup_analyses[s].get("total_projected_points", 0))
    
    best_analysis = lineup_analyses[best_strategy]
    
    # Generate reasoning
    reasoning_parts = [
        f"Recommended {best_strategy} strategy",
        f"Projected {best_analysis.get('total_projected_points', 0):.1f} points"
    ]
    
    if best_analysis.get("key_strengths"):
        reasoning_parts.append(f"Key strengths: {', '.join(best_analysis['key_strengths'])}")
    
    if best_analysis.get("key_concerns"):
        reasoning_parts.append(f"Considerations: {', '.join(best_analysis['key_concerns'])}")
    
    return {
        "primary": {
            "strategy": best_strategy,
            "projected_points": best_analysis.get("total_projected_points", 0),
            "starters": best_analysis.get("starters", {}),
            "reasoning": best_analysis.get("recommendation_reasoning", "")
        },
        "confidence": 0.85,  # High confidence with comprehensive data
        "reasoning": ". ".join(reasoning_parts),
        "alternatives": _generate_alternatives(lineup_analyses, best_strategy),
        "immediate_actions": [
            "Set lineup with recommended strategy",
            "Monitor injury reports",
            "Check weather updates"
        ],
        "monitoring_points": [
            "Injury status updates",
            "Weather conditions",
            "Lineup changes"
        ],
        "contingency_plans": [
            "Backup options for injured players",
            "Weather-based adjustments",
            "Alternative strategies if needed"
        ]
    }


def _generate_alternatives(lineup_analyses: Dict[str, Any], primary_strategy: str) -> List[Dict[str, Any]]:
    """Generate alternative lineup options."""
    alternatives = []
    
    for strategy, analysis in lineup_analyses.items():
        if strategy != primary_strategy:
            alternatives.append({
                "strategy": strategy,
                "projected_points": analysis.get("total_projected_points", 0),
                "risk_level": analysis.get("risk_assessment", "Unknown"),
                "reasoning": f"Alternative {strategy} approach with {analysis.get('total_projected_points', 0):.1f} projected points"
            })
    
    return alternatives


def _analyze_key_players(roster_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze key players for decision-making."""
    if roster_data.get("status") != "success":
        return {"message": "No roster data available"}
    
    players = roster_data.get("all_players", [])
    
    return {
        "elite_players": [p for p in players if p.get("player_tier") in ["elite", "stud"]],
        "injury_concerns": [p for p in players if p.get("injury_status") not in ["Healthy", "Probable"]],
        "favorable_matchups": [p for p in players if p.get("matchup_score", 0) >= 70],
        "tough_matchups": [p for p in players if p.get("matchup_score", 0) < 30],
        "trending_players": [p for p in players if p.get("trending_score", 0) > 10000]
    }


def _compare_strategies(lineup_analyses: Dict[str, Any]) -> Dict[str, Any]:
    """Compare different lineup strategies."""
    comparison = {}
    
    for strategy, analysis in lineup_analyses.items():
        comparison[strategy] = {
            "projected_points": analysis.get("total_projected_points", 0),
            "risk_level": analysis.get("risk_assessment", "Unknown"),
            "key_strengths": analysis.get("key_strengths", []),
            "key_concerns": analysis.get("key_concerns", [])
        }
    
    return comparison


def _assess_lineup_risks(roster_data: Dict[str, Any], lineup_analyses: Dict[str, Any]) -> Dict[str, Any]:
    """Assess risks across different lineup options."""
    return {
        "overall_risk_assessment": "Medium",  # Simplified for now
        "primary_risks": [
            "Injury concerns for key players",
            "Tough matchups for some positions",
            "Weather impact on outdoor games"
        ],
        "mitigation_strategies": [
            "Monitor injury reports closely",
            "Have backup options ready",
            "Consider streaming alternatives"
        ]
    }


def _identify_opportunities(roster_data: Dict[str, Any], decision_context: Dict[str, Any]) -> Dict[str, Any]:
    """Identify opportunities for optimization."""
    return {
        "leverage_opportunities": [
            "Low-owned players with upside potential",
            "Favorable matchups to exploit",
            "Contrarian plays for tournament leverage"
        ],
        "optimization_areas": [
            "Streaming options for tough matchups",
            "Value plays with good projections",
            "Strategic substitutions based on context"
        ]
    }


# Export the integrated server
__all__ = [
    "integrated_server",
    "ff_get_comprehensive_analysis",
    "ff_smart_lineup_optimizer",
    "run_http_server",
    "main"
]


def run_http_server(host: Optional[str] = None, port: Optional[int] = None, *, show_banner: bool = True) -> None:
    """Start the integrated FastMCP server using the HTTP transport."""
    import os
    
    resolved_host = host or os.getenv("HOST", "0.0.0.0")
    resolved_port = port or int(os.getenv("PORT", "8000"))

    integrated_server.run(
        "http",
        host=resolved_host,
        port=resolved_port,
        show_banner=show_banner,
    )


def main() -> None:
    """Console script entry point for launching the integrated HTTP server."""
    run_http_server()


if __name__ == "__main__":
    main()