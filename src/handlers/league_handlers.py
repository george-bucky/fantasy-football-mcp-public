"""League-level MCP tool handlers (leagues, standings, teams)."""

from typing import Dict, Optional

from src.api import yahoo_api_call


# These functions need to be imported from main file since they use global cache
# We'll import them when updating fantasy_football_multi_league.py
async def discover_leagues():
    """Placeholder - will be imported from main module."""
    raise NotImplementedError("Must import from fantasy_football_multi_league")


async def get_user_team_info(league_key):
    """Placeholder - will be imported from main module."""
    raise NotImplementedError("Must import from fantasy_football_multi_league")


async def get_all_teams_info(league_key):
    """Placeholder - will be imported from main module."""
    raise NotImplementedError("Must import from fantasy_football_multi_league")


async def handle_ff_get_leagues(arguments: Dict) -> Dict:
    """Get all fantasy football leagues for the authenticated user.

    Args:
        arguments: Empty dict (no arguments required)

    Returns:
        Dict with total_leagues and list of league summaries
    """
    leagues = await discover_leagues()

    if not leagues:
        return {
            "error": "No active NFL leagues found",
            "suggestion": "Make sure your Yahoo token is valid and you have active leagues",
        }

    return {
        "total_leagues": len(leagues),
        "leagues": [
            {
                "key": league["key"],
                "name": league["name"],
                "teams": league["num_teams"],
                "current_week": league["current_week"],
                "scoring": league["scoring_type"],
            }
            for league in leagues.values()
        ],
    }


async def handle_ff_get_league_info(arguments: Dict) -> Dict:
    """Get detailed information about a specific league.

    Args:
        arguments: Dict with 'league_key'

    Returns:
        Dict with league details and your team summary
    """
    if not arguments.get("league_key"):
        return {"error": "league_key is required"}

    league_key = arguments.get("league_key")

    leagues = await discover_leagues()
    if league_key not in leagues:
        return {
            "error": f"League {league_key} not found",
            "available_leagues": list(leagues.keys()),
        }

    league = leagues[league_key]
    team_info = await get_user_team_info(league_key)
    _ = await yahoo_api_call(f"league/{league_key}")

    return {
        "league": league["name"],
        "key": league_key,
        "season": league["season"],
        "teams": league["num_teams"],
        "current_week": league["current_week"],
        "scoring_type": league["scoring_type"],
        "status": "active" if not league["is_finished"] else "finished",
        "your_team": {
            "name": team_info.get("team_name", "Unknown") if team_info else "Not found",
            "key": team_info.get("team_key") if team_info else None,
            "draft_position": team_info.get("draft_position") if team_info else None,
            "draft_grade": team_info.get("draft_grade") if team_info else None,
        },
    }


async def handle_ff_get_standings(arguments: Dict) -> Dict:
    """Get current standings for a league.

    Args:
        arguments: Dict with 'league_key'

    Returns:
        Dict with league_key and sorted standings list
    """
    if not arguments.get("league_key"):
        return {"error": "league_key is required"}

    league_key = arguments.get("league_key")
    data = await yahoo_api_call(f"league/{league_key}/standings")

    standings = []
    league = data.get("fantasy_content", {}).get("league", [])

    for item in league:
        if isinstance(item, dict) and "standings" in item:
            standings_list = item["standings"]
            teams = {}
            if isinstance(standings_list, list) and standings_list:
                teams = standings_list[0].get("teams", {})
            elif isinstance(standings_list, dict):
                teams = standings_list.get("teams", {})

            for key, team_entry in teams.items():
                if key == "count" or not isinstance(team_entry, dict):
                    continue
                if "team" in team_entry:
                    team_array = team_entry["team"]
                    team_info = {}
                    team_standings = {}
                    if isinstance(team_array, list) and team_array:
                        core = team_array[0]
                        if isinstance(core, list):
                            for elem in core:
                                if isinstance(elem, dict) and "name" in elem:
                                    team_info["name"] = elem["name"]
                        for part in team_array[1:]:
                            if isinstance(part, dict) and "team_standings" in part:
                                team_standings = part["team_standings"]

                    if team_info and team_standings:
                        standings.append(
                            {
                                "rank": team_standings.get("rank", 0),
                                "team": team_info.get("name", "Unknown"),
                                "wins": team_standings.get("outcome_totals", {}).get("wins", 0),
                                "losses": team_standings.get("outcome_totals", {}).get("losses", 0),
                                "ties": team_standings.get("outcome_totals", {}).get("ties", 0),
                                "points_for": team_standings.get("points_for", 0),
                                "points_against": team_standings.get("points_against", 0),
                            }
                        )

    standings.sort(key=lambda row: row["rank"])
    return {"league_key": league_key, "standings": standings}


async def handle_ff_get_teams(arguments: Dict) -> Dict:
    """Get all teams in a league.

    Args:
        arguments: Dict with 'league_key'

    Returns:
        Dict with league_key, teams list, and total_teams count
    """
    if not arguments.get("league_key"):
        return {"error": "league_key is required"}

    league_key: Optional[str] = arguments.get("league_key")
    if league_key is None:
        return {"error": "league_key cannot be None"}

    teams_info = await get_all_teams_info(league_key)
    return {
        "league_key": league_key,
        "teams": teams_info,
        "total_teams": len(teams_info),
    }
