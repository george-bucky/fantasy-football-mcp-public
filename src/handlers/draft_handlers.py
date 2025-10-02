"""Draft MCP tool handlers."""

from typing import Optional

# These will be injected from main file
get_all_teams_info = None
get_draft_rankings = None
get_draft_recommendation_simple = None
analyze_draft_state_simple = None
DRAFT_AVAILABLE = True


async def handle_ff_get_draft_results(arguments: dict) -> dict:
    """Get draft results showing all teams and their draft info.

    Args:
        arguments: Dict containing:
            - league_key: League identifier (required)

    Returns:
        Dict with draft results for all teams
    """
    if not arguments.get("league_key"):
        return {"error": "league_key is required"}

    league_key: Optional[str] = arguments.get("league_key")
    if league_key is None:
        return {"error": "league_key cannot be None"}

    teams = await get_all_teams_info(league_key)
    if not teams:
        return {"error": f"Could not retrieve draft results for league {league_key}"}
    return {
        "league_key": league_key,
        "total_teams": len(teams),
        "draft_results": teams,
    }


async def handle_ff_get_draft_rankings(arguments: dict) -> dict:
    """Get draft rankings with ADP data.

    Args:
        arguments: Dict containing:
            - league_key: League identifier (required)
            - position: Filter by position (default: "all")
            - count: Number of players (default: 50)

    Returns:
        Dict with draft rankings
    """
    league_key = arguments.get("league_key")
    position = arguments.get("position", "all")
    count = arguments.get("count", 50)

    players = await get_draft_rankings(league_key, position, count)
    if players:
        return {
            "position": position,
            "total_players": len(players),
            "rankings": players,
        }
    return {"message": "Could not retrieve draft rankings"}


async def handle_ff_get_draft_recommendation(arguments: dict) -> dict:
    """Get draft recommendations based on strategy.

    Args:
        arguments: Dict containing:
            - league_key: League identifier (required)
            - strategy: "conservative", "aggressive", or "balanced" (default: "balanced")
            - num_recommendations: Number of recommendations (default: 10, max: 20)
            - current_pick: Current pick number (optional)

    Returns:
        Dict with draft recommendations
    """
    if not DRAFT_AVAILABLE:
        return {"error": "Draft functionality not available. Please check module dependencies."}

    try:
        league_key: Optional[str] = arguments.get("league_key")
        if league_key is None:
            return {"error": "league_key is required and cannot be None"}

        strategy = arguments.get("strategy", "balanced")
        num_recommendations = arguments.get("num_recommendations", 10)
        current_pick = arguments.get("current_pick")
        return await get_draft_recommendation_simple(
            league_key,
            strategy,
            num_recommendations,
            current_pick,
        )
    except Exception as exc:
        return {
            "error": f"Draft recommendation failed: {exc}",
            "available_tools": ["ff_get_draft_rankings", "ff_get_players"],
        }


async def handle_ff_analyze_draft_state(arguments: dict) -> dict:
    """Analyze current draft state and provide strategic advice.

    Args:
        arguments: Dict containing:
            - league_key: League identifier (required)
            - strategy: "conservative", "aggressive", or "balanced" (default: "balanced")

    Returns:
        Dict with draft state analysis
    """
    if not DRAFT_AVAILABLE:
        return {"error": "Draft functionality not available. Please check module dependencies."}

    try:
        league_key: Optional[str] = arguments.get("league_key")
        if league_key is None:
            return {"error": "league_key is required and cannot be None"}

        strategy = arguments.get("strategy", "balanced")
        return await analyze_draft_state_simple(league_key, strategy)
    except Exception as exc:
        return {
            "error": f"Draft analysis failed: {exc}",
            "suggestion": "Try using ff_get_roster to check current team composition",
        }
