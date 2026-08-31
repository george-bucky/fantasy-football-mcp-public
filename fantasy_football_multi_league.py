#!/usr/bin/env python3
"""
Fantasy Football MCP Server - Multi-League Support
"""

import asyncio
import json
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Import extracted modules
from src.api import get_access_token, refresh_yahoo_token, set_access_token, yahoo_api_call
from src.parsers import parse_team_roster, parse_yahoo_free_agent_players
from src.services import (
    SPORTSBOOK_ODDS_INPUT_SCHEMA,
    analyze_reddit_sentiment,
    apply_rookie_intelligence,
    get_decision_news_context,
    get_sportsbook_odds,
    rookie_identity_key,
)
from src.services.league_context import YahooLeagueContextService

# Import rate limiting and caching utilities
from src.api.yahoo_utils import rate_limiter, response_cache

# Import bye week utilities
from src.utils.bye_weeks import get_bye_week_with_fallback

# Import all handlers from the handlers module
from pathlib import Path

# Find project root and load .env from there
PROJECT_ROOT = Path(__file__).parent.absolute()
ENV_FILE_PATH = PROJECT_ROOT / ".env"

from src.handlers import (
    handle_ff_analyze_draft_state,
    handle_ff_analyze_reddit_sentiment,
    handle_ff_build_lineup,
    handle_ff_clear_cache,
    handle_ff_compare_teams,
    handle_ff_get_api_status,
    handle_ff_get_draft_rankings,
    handle_ff_get_draft_recommendation,
    handle_ff_get_draft_results,
    handle_ff_get_espn_nfl_news,
    handle_ff_get_league_info,
    handle_ff_get_leagues,
    handle_ff_get_matchup,
    handle_ff_get_player_news,
    handle_ff_get_players,
    handle_ff_get_roster,
    handle_ff_get_sportsbook_odds,
    handle_ff_get_standings,
    handle_ff_get_teams,
    handle_ff_get_waiver_wire,
    handle_ff_refresh_token,
    inject_draft_dependencies,
    inject_league_helpers,
    inject_matchup_dependencies,
    inject_player_dependencies,
    inject_roster_dependencies,
)

# Draft functionality is built-in (no complex imports needed)
DRAFT_AVAILABLE = True

DRAFT_RECOMMENDATION_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "league_key": {
            "type": "string",
            "description": "League key (e.g., 'nfl.l.XXXXXX')",
        },
        "strategy": {
            "type": "string",
            "description": "Draft strategy: 'conservative', 'aggressive', or 'balanced' (default: balanced)",
            "enum": ["conservative", "aggressive", "balanced"],
            "default": "balanced",
        },
        "num_recommendations": {
            "type": "integer",
            "description": "Number of top recommendations to return (1-20, default: 10)",
            "minimum": 1,
            "maximum": 20,
            "default": 10,
        },
        "current_pick": {
            "type": "integer",
            "minimum": 1,
            "description": "Current overall pick number; when omitted it is inferred from your roster and Yahoo draft slot",
        },
        "use_rookie_intelligence": {
            "type": "boolean",
            "default": False,
            "description": "Opt in to reviewed 2026 first-year PPR outlook for exact rookie matches",
        },
        "rookie_only": {
            "type": "boolean",
            "default": False,
            "description": "Return only exact current-class rookie matches; implies rookie intelligence and never falls back to veterans",
        },
        "include_sportsbook_odds": {
            "type": "boolean",
            "default": False,
            "description": "Opt in to attributed PropLine context for the final draft shortlist",
        },
        "sportsbook_scope": {
            "type": "string",
            "enum": ["auto", "season", "next_game"],
            "default": "auto",
            "description": "Sportsbook evidence scope; season and next-game markets remain distinct",
        },
        "sportsbook_shortlist_size": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "default": 5,
            "description": "Number of final candidates to enrich (1-5, default: 5)",
        },
    },
    "required": ["league_key"],
}

# Load environment from project root
load_dotenv(dotenv_path=ENV_FILE_PATH)

# Initialize access token in the API module
if os.getenv("YAHOO_ACCESS_TOKEN"):
    set_access_token(os.getenv("YAHOO_ACCESS_TOKEN"))

# Create server instance
server = Server("fantasy-football")

# Cache for leagues
LEAGUES_CACHE = {}


async def discover_leagues() -> dict[str, dict[str, Any]]:
    """Discover all active NFL leagues for the authenticated user."""
    global LEAGUES_CACHE

    if LEAGUES_CACHE:
        return LEAGUES_CACHE

    # Yahoo resolves the "nfl" alias to the current fantasy season.
    data = await yahoo_api_call("users;use_login=1/games;game_keys=nfl/leagues")

    leagues = {}
    try:
        users = data.get("fantasy_content", {}).get("users", {})

        if "0" in users:
            user = users["0"]["user"]

            if isinstance(user, list):
                for item in user:
                    if isinstance(item, dict) and "games" in item:
                        games = item["games"]

                        if "0" in games:  # First game (NFL)
                            game = games["0"]["game"]
                            if isinstance(game, list):
                                for g in game:
                                    if isinstance(g, dict) and "leagues" in g:
                                        league_data = g["leagues"]

                                        for key in league_data:
                                            if key != "count" and isinstance(
                                                league_data[key], dict
                                            ):
                                                if "league" in league_data[key]:
                                                    league_info = league_data[key]["league"]
                                                    if (
                                                        isinstance(league_info, list)
                                                        and len(league_info) > 0
                                                    ):
                                                        league_dict = league_info[0]

                                                        league_key = league_dict.get(
                                                            "league_key", ""
                                                        )
                                                        leagues[league_key] = {
                                                            "key": league_key,
                                                            "id": league_dict.get("league_id", ""),
                                                            "name": league_dict.get(
                                                                "name", "Unknown"
                                                            ),
                                                            "season": league_dict.get("season"),
                                                            "num_teams": league_dict.get(
                                                                "num_teams", 0
                                                            ),
                                                            "scoring_type": league_dict.get(
                                                                "scoring_type", "head"
                                                            ),
                                                            "current_week": league_dict.get(
                                                                "current_week", 1
                                                            ),
                                                            "is_finished": league_dict.get(
                                                                "is_finished", 0
                                                            ),
                                                        }
    except Exception:
        pass  # Silently handle error to not interfere with MCP protocol

    LEAGUES_CACHE = leagues
    return leagues


async def get_user_team_info(league_key: Optional[str]) -> Optional[dict]:
    if not league_key:
        return None
    """Get the user's team details in a league.

    Normalizes manager entries and `is_owned_by_current_login` flags so the
    caller can reliably identify which team belongs to the authenticated user.
    """
    try:
        data = await yahoo_api_call(f"league/{league_key}/teams")

        # Get user's GUID from environment
        user_guid = os.getenv("YAHOO_GUID", "your_yahoo_guid_here")

        # Parse to find user's team
        league = data.get("fantasy_content", {}).get("league", [])

        if len(league) > 1 and isinstance(league[1], dict) and "teams" in league[1]:
            teams = league[1]["teams"]

            for key in teams:
                if key != "count" and isinstance(teams[key], dict):
                    if "team" in teams[key]:
                        team_array = teams[key]["team"]

                        if isinstance(team_array, list) and len(team_array) > 0:
                            # The team data is in the first element
                            team_data = team_array[0]

                            if isinstance(team_data, list):
                                team_key = None
                                team_name = None
                                is_users_team = False
                                draft_grade = None
                                draft_position = None

                                # Parse each element in the team data
                                for element in team_data:
                                    if isinstance(element, dict):
                                        # Check for team key
                                        if "team_key" in element:
                                            team_key = element["team_key"]

                                        # Get team name
                                        if "name" in element:
                                            team_name = element["name"]

                                        # Get draft grade
                                        if "draft_grade" in element:
                                            draft_grade = element["draft_grade"]

                                        # Get draft position
                                        if "draft_position" in element:
                                            draft_position = element["draft_position"]

                                        # Check if owned by current login (API may return int, bool or string)
                                        owned_flag = element.get("is_owned_by_current_login")
                                        if str(owned_flag) == "1" or owned_flag is True:
                                            is_users_team = True

                                        # Also check by GUID
                                        if "managers" in element:
                                            managers = element["managers"]
                                            if isinstance(managers, dict):
                                                managers = [
                                                    m
                                                    for key, m in managers.items()
                                                    if key != "count"
                                                ]
                                            if managers:
                                                mgr = managers[0].get("manager", {})
                                                if mgr.get("guid") == user_guid:
                                                    is_users_team = True

                                if is_users_team and team_key:
                                    return {
                                        "team_key": team_key,
                                        "team_name": team_name,
                                        "draft_grade": draft_grade,
                                        "draft_position": draft_position,
                                    }

        return None
    except Exception:
        # Silently handle error to not interfere with MCP protocol
        return None


async def get_user_team_key(league_key: Optional[str]) -> Optional[str]:
    if not league_key:
        return None
    """Get the user's team key in a specific league (legacy function for compatibility)."""
    team_info = await get_user_team_info(league_key)
    return team_info["team_key"] if team_info else None


async def get_waiver_wire_players(
    league_key: str, position: str = "all", sort: str = "rank", count: int = 30
) -> list[dict]:
    """Get available waiver wire players with detailed stats."""
    try:
        # Build the API call with filters
        pos_filter = f";position={position}" if position != "all" else ""
        sort_type = {
            "rank": "OR",  # Overall rank
            "points": "PTS",  # Points
            "owned": "O",  # Ownership %
            "trending": "A",  # Added %
        }.get(sort, "OR")

        endpoint = (
            f"league/{league_key}/players;status=A{pos_filter};sort={sort_type};count={count}"
        )
        data = await yahoo_api_call(endpoint)

        players = []
        league = data.get("fantasy_content", {}).get("league", [])

        # Players are in the second element of the league array
        if len(league) > 1 and isinstance(league[1], dict) and "players" in league[1]:
            players_data = league[1]["players"]

            for key in players_data:
                if key != "count" and isinstance(players_data[key], dict):
                    if "player" in players_data[key]:
                        player_array = players_data[key]["player"]

                        # Player data is in nested array structure
                        if isinstance(player_array, list) and len(player_array) > 0:
                            player_data = player_array[0]

                            if isinstance(player_data, list):
                                player_info = {}
                                api_bye_week = None
                                player_elements = player_data + [
                                    item for item in player_array[1:] if isinstance(item, dict)
                                ]

                                for element in player_elements:
                                    if isinstance(element, dict):
                                        # Basic info
                                        if "name" in element:
                                            player_info["name"] = element["name"]["full"]
                                        if "player_key" in element:
                                            player_info["player_key"] = element["player_key"]
                                        if "editorial_team_abbr" in element:
                                            player_info["team"] = element["editorial_team_abbr"]
                                        if "display_position" in element:
                                            player_info["position"] = element["display_position"]

                                        # Extract bye week with fallback to static data
                                        if "bye_weeks" in element:
                                            bye_weeks_data = element["bye_weeks"]
                                            if isinstance(bye_weeks_data, dict) and "week" in bye_weeks_data:
                                                bye_week = bye_weeks_data.get("week")
                                                # Validate bye week is a valid week number (1-18)
                                                if bye_week and str(bye_week).isdigit():
                                                    bye_num = int(bye_week)
                                                    if 1 <= bye_num <= 18:
                                                        api_bye_week = bye_num

                                        # Ownership data
                                        if "ownership" in element:
                                            ownership = element["ownership"]
                                            player_info["owned_pct"] = ownership.get(
                                                "ownership_percentage", 0
                                            )
                                            player_info["weekly_change"] = ownership.get(
                                                "weekly_change", 0
                                            )

                                        # Injury status
                                        if "status" in element:
                                            player_info["injury_status"] = element["status"]
                                        if "status_full" in element:
                                            player_info["injury_detail"] = element["status_full"]

                                player_info["bye"] = get_bye_week_with_fallback(
                                    player_info.get("team", ""), api_bye_week
                                )

                                if player_info.get("name"):
                                    # Ensure all expected fields are present with defaults
                                    player_info.setdefault("team", "FA")  # Free Agent if no team
                                    player_info.setdefault(
                                        "owned_pct", 0
                                    )  # 0% if no ownership data
                                    player_info.setdefault(
                                        "weekly_change", 0
                                    )  # No change if no data
                                    player_info.setdefault(
                                        "injury_status", "Healthy"
                                    )  # Assume healthy if not specified
                                    players.append(player_info)

        return players
    except Exception:
        return []


async def get_draft_rankings(
    league_key: Optional[str] = None, position: str = "all", count: int = 50
) -> list[dict]:
    """Get pre-draft rankings with ADP data."""
    try:
        # If no league key provided, get the first available league
        if not league_key:
            leagues = await discover_leagues()
            if leagues:
                league_key = list(leagues.keys())[0]
            else:
                return []  # No leagues available

        pos_filter = f";position={position}" if position != "all" else ""

        # Get all players sorted by rank for the specified league
        endpoint = f"league/{league_key}/players{pos_filter};sort=OR;count={count}"
        data = await yahoo_api_call(endpoint)

        players = []
        league = data.get("fantasy_content", {}).get("league", [])

        # Players are in the second element of the league array
        if len(league) > 1 and isinstance(league[1], dict) and "players" in league[1]:
            players_data = league[1]["players"]

            for key in players_data:
                if key != "count" and isinstance(players_data[key], dict):
                    if "player" in players_data[key]:
                        player_array = players_data[key]["player"]

                        # Player data is in nested array structure
                        if isinstance(player_array, list) and len(player_array) > 0:
                            player_data = player_array[0]

                            if isinstance(player_data, list):
                                player_info = {}
                                rank = int(key) + 1  # Use the key as rank
                                api_bye_week = None
                                player_elements = player_data + [
                                    item for item in player_array[1:] if isinstance(item, dict)
                                ]

                                for element in player_elements:
                                    if isinstance(element, dict):
                                        if "name" in element:
                                            player_info["name"] = element["name"]["full"]
                                        if "editorial_team_abbr" in element:
                                            player_info["team"] = element["editorial_team_abbr"]
                                        if "display_position" in element:
                                            player_info["position"] = element["display_position"]

                                        # Extract bye week with fallback to static data
                                        if "bye_weeks" in element:
                                            bye_weeks_data = element["bye_weeks"]
                                            if isinstance(bye_weeks_data, dict) and "week" in bye_weeks_data:
                                                bye_week = bye_weeks_data.get("week")
                                                # Validate bye week is a valid week number (1-18)
                                                if bye_week and str(bye_week).isdigit():
                                                    bye_num = int(bye_week)
                                                    if 1 <= bye_num <= 18:
                                                        api_bye_week = bye_num

                                        # Draft data if available
                                        if "draft_analysis" in element:
                                            draft = element["draft_analysis"]
                                            player_info["average_draft_position"] = draft.get(
                                                "average_pick", rank
                                            )
                                            player_info["average_round"] = draft.get(
                                                "average_round", "N/A"
                                            )
                                            player_info["average_cost"] = draft.get(
                                                "average_cost", "N/A"
                                            )
                                            player_info["percent_drafted"] = draft.get(
                                                "percent_drafted", 0
                                            )
                                        else:
                                            # Use rank as ADP if no draft data
                                            player_info["rank"] = rank

                                player_info["bye"] = get_bye_week_with_fallback(
                                    player_info.get("team", ""), api_bye_week
                                )

                                if player_info.get("name"):
                                    players.append(player_info)

        # Sort by ADP if available
        players.sort(
            key=lambda x: (
                float(x.get("average_draft_position", 999))
                if x.get("average_draft_position") != "N/A"
                else 999
            )
        )

        return players
    except Exception:
        return []


async def get_all_teams_info(league_key: str) -> list[dict]:
    """Get all teams information including draft data."""
    try:
        data = await yahoo_api_call(f"league/{league_key}/teams")

        teams_list = []
        league = data.get("fantasy_content", {}).get("league", [])

        if len(league) > 1 and isinstance(league[1], dict) and "teams" in league[1]:
            teams = league[1]["teams"]

            for key in teams:
                if key != "count" and isinstance(teams[key], dict):
                    if "team" in teams[key]:
                        team_array = teams[key]["team"]

                        if isinstance(team_array, list) and len(team_array) > 0:
                            team_data = team_array[0]

                            if isinstance(team_data, list):
                                team_info = {}

                                for element in team_data:
                                    if isinstance(element, dict):
                                        if "team_key" in element:
                                            team_info["team_key"] = element["team_key"]
                                        if "team_id" in element:
                                            team_info["team_id"] = element["team_id"]
                                        if "name" in element:
                                            team_info["name"] = element["name"]
                                        if "draft_grade" in element:
                                            team_info["draft_grade"] = element["draft_grade"]
                                        if "draft_position" in element:
                                            team_info["draft_position"] = element["draft_position"]
                                        if "draft_recap_url" in element:
                                            team_info["draft_recap_url"] = element[
                                                "draft_recap_url"
                                            ]
                                        if "number_of_moves" in element:
                                            team_info["moves"] = element["number_of_moves"]
                                        if "number_of_trades" in element:
                                            team_info["trades"] = element["number_of_trades"]
                                        if "managers" in element:
                                            managers = element["managers"]
                                            if managers and len(managers) > 0:
                                                mgr = managers[0].get("manager", {})
                                                team_info["manager"] = mgr.get(
                                                    "nickname", "Unknown"
                                                )

                                if team_info.get("team_key"):
                                    teams_list.append(team_info)

        # Sort by draft position if available
        teams_list.sort(key=lambda x: x.get("draft_position", 999))
        return teams_list

    except Exception:
        return []


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available fantasy football tools."""
    base_tools = [
        Tool(
            name="ff_get_leagues",
            description="Get all your fantasy football leagues",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="ff_get_league_info",
            description="Get detailed information about a specific league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX'). Use ff_get_leagues to get available keys.",
                    }
                },
                "required": ["league_key"],
            },
        ),
        Tool(
            name="ff_get_standings",
            description="Get standings for a specific league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX')",
                    }
                },
                "required": ["league_key"],
            },
        ),
        Tool(
            name="ff_get_teams",
            description="Get all teams in a specific league with basic information",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX')",
                    }
                },
                "required": ["league_key"],
            },
        ),
        Tool(
            name="ff_get_roster",
            description="Get your team roster in a specific league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX')",
                    },
                    "team_key": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Optional team key if not the logged-in team",
                    },
                    "week": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Week for projections and analysis (optional, defaults to current)",
                    },
                    "data_level": {
                        "type": "string",
                        "description": "Data detail level: 'basic', 'standard', 'enhanced'",
                        "enum": ["basic", "standard", "enhanced"],
                        "default": "standard",
                    },
                    "include_analysis": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include basic roster analysis",
                        "default": False,
                    },
                    "include_projections": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include projections from Yahoo and Sleeper",
                        "default": True,
                    },
                    "include_external_data": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include Sleeper data, trending, and matchups",
                        "default": True,
                    },
                },
                "required": ["league_key"],
            },
        ),
        Tool(
            name="ff_get_matchup",
            description="Get matchup for a specific week in a league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX')",
                    },
                    "week": {
                        "type": "integer",
                        "description": "Week number (optional, defaults to current week)",
                    },
                },
                "required": ["league_key"],
            },
        ),
        Tool(
            name="ff_get_players",
            description="Get available free agent players in a league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX')",
                    },
                    "position": {
                        "type": "string",
                        "description": "Position filter (QB, RB, WR, TE, K, DEF)",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of players to return",
                        "default": 10,
                    },
                    "sort": {
                        "type": "string",
                        "description": "Sort by: 'rank', 'points', 'owned', 'trending'",
                        "enum": ["rank", "points", "owned", "trending"],
                        "default": "rank",
                    },
                    "week": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Week for projections and analysis (optional, defaults to current)",
                    },
                    "include_analysis": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include basic analysis and rankings",
                        "default": False,
                    },
                    "include_expert_analysis": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include expert analysis and recommendations",
                        "default": False,
                    },
                    "include_projections": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include projections from Yahoo and Sleeper",
                        "default": True,
                    },
                    "include_external_data": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include Sleeper data, trending, and matchups",
                        "default": True,
                    },
                },
                "required": ["league_key"],
            },
        ),
        Tool(
            name="ff_compare_teams",
            description="Compare two teams' rosters within a league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX')",
                    },
                    "team_key_a": {
                        "type": "string",
                        "description": "First team key to compare",
                    },
                    "team_key_b": {
                        "type": "string",
                        "description": "Second team key to compare",
                    },
                },
                "required": ["league_key", "team_key_a", "team_key_b"],
            },
        ),
        Tool(
            name="ff_build_lineup",
            description="Build optimal lineup from your roster using strategy-based optimization and positional constraints",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX')",
                    },
                    "week": {
                        "type": "integer",
                        "description": "Week number (optional, defaults to current week)",
                    },
                    "strategy": {
                        "type": "string",
                        "description": "Strategy: 'conservative', 'aggressive', or 'balanced' (default: balanced)",
                        "enum": ["conservative", "aggressive", "balanced"],
                    },
                    "use_llm": {
                        "type": "boolean",
                        "description": "Use LLM-based optimization instead of mathematical formulas (default: false)",
                    },
                    "use_rookie_intelligence": {
                        "type": "boolean",
                        "default": False,
                        "description": "Opt in to reviewed season-long first-year PPR as near-tie lineup context only",
                    },
                    "use_matchup_evidence": {
                        "type": "boolean",
                        "default": False,
                        "description": "Opt in to source-backed weekly NFL opponent evidence as a near-tie lineup tiebreak only",
                    },
                },
                "required": ["league_key"],
            },
        ),
        Tool(
            name="ff_refresh_token",
            description="Refresh the Yahoo API access token when it expires",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="ff_get_draft_results",
            description="Get draft results showing all teams with their draft positions and grades",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX')",
                    },
                    "team_key": {
                        "type": "string",
                        "description": "Optional team key if not the logged-in team",
                    },
                },
                "required": ["league_key"],
            },
        ),
        Tool(
            name="ff_get_waiver_wire",
            description="Get top available waiver wire players with detailed stats and projections",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (e.g., 'nfl.l.XXXXXX')",
                    },
                    "position": {
                        "type": "string",
                        "description": "Position filter (QB, RB, WR, TE, K, DEF, or 'all')",
                        "enum": ["QB", "RB", "WR", "TE", "K", "DEF", "all"],
                    },
                    "sort": {
                        "type": "string",
                        "description": "Sort by: 'rank', 'points', 'owned', 'trending'",
                        "enum": ["rank", "points", "owned", "trending"],
                        "default": "rank",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of players to return (default: 30)",
                        "default": 30,
                    },
                    "week": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Week for projections and analysis (optional, defaults to current)",
                    },
                    "team_key": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Optional team key for context (e.g., waiver priority)",
                    },
                    "include_analysis": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include basic waiver priority analysis",
                        "default": False,
                    },
                    "include_projections": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include projections from Yahoo and Sleeper",
                        "default": True,
                    },
                    "include_external_data": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Include Sleeper data, trending, and matchups",
                        "default": True,
                    },
                    "use_rookie_intelligence": {
                        "type": "boolean",
                        "default": False,
                        "description": "Opt in to reviewed 2026 first-year PPR outlook for exact rookie matches",
                    },
                    "rookie_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "Return only exact current-class rookie matches; implies rookie intelligence and never falls back to veterans",
                    },
                },
                "required": ["league_key"],
            },
        ),
        Tool(
            name="ff_get_api_status",
            description="Get Yahoo API rate limit status and cache statistics",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="ff_clear_cache",
            description="Clear the API response cache",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Optional pattern to match (e.g., 'standings', 'roster'). Clears all if not provided.",
                    }
                },
            },
        ),
        Tool(
            name="ff_get_draft_rankings",
            description="Get pre-draft player rankings and ADP (Average Draft Position)",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_key": {
                        "type": "string",
                        "description": "League key (optional, uses first available league if not provided)",
                    },
                    "position": {
                        "type": "string",
                        "description": "Position filter (QB, RB, WR, TE, K, DEF, or 'all')",
                        "enum": ["QB", "RB", "WR", "TE", "K", "DEF", "all"],
                        "default": "all",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of players to return (default: 50)",
                        "default": 50,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="ff_get_player_news",
            description=(
                "Get recent RotoWire NFL player news from the public RSS feed; "
                "no Yahoo or Reddit credentials required"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "players": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional player names to filter (for example, ['Josh Allen'])",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum news items to return (1-5, default: 5)",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 5,
                    },
                },
            },
        ),
        Tool(
            name="ff_get_espn_nfl_news",
            description=(
                "Get recent ESPN NFL reporting and analysis from its public JSON "
                "endpoint; no Yahoo or Reddit credentials required"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "players": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional player names to filter using ESPN article metadata and text",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum news items to return (1-10, default: 5)",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                    },
                },
            },
        ),
        Tool(
            name="ff_get_sportsbook_odds",
            description=(
                "Get read-only NFL futures and next-game sportsbook odds from "
                "PropLine; no Yahoo credentials required"
            ),
            inputSchema=SPORTSBOOK_ODDS_INPUT_SCHEMA,
        ),
    ]

    # Add draft tools if available
    if DRAFT_AVAILABLE:
        draft_tools = [
            Tool(
                name="ff_get_draft_recommendation",
                description="Get live draft recommendations using your roster needs, reception and passing-TD scoring, roster settings, and draft timing",
                inputSchema=DRAFT_RECOMMENDATION_INPUT_SCHEMA,
            ),
            Tool(
                name="ff_analyze_draft_state",
                description="Analyze current draft state including roster needs and strategic insights",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_key": {
                            "type": "string",
                            "description": "League key (e.g., 'nfl.l.XXXXXX')",
                        },
                        "strategy": {
                            "type": "string",
                            "description": "Draft strategy for analysis: 'conservative', 'aggressive', or 'balanced' (default: balanced)",
                            "enum": ["conservative", "aggressive", "balanced"],
                            "default": "balanced",
                        },
                    },
                    "required": ["league_key"],
                },
            ),
            Tool(
                name="ff_analyze_reddit_sentiment",
                description="Analyze Reddit sentiment for fantasy football players to help with Start/Sit decisions",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "players": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of player names to analyze (e.g., ['Josh Allen', 'Jared Goff'])",
                        },
                        "time_window_hours": {
                            "type": "integer",
                            "description": "How far back to look for Reddit posts (default: 48 hours)",
                            "default": 48,
                        },
                    },
                    "required": ["players"],
                },
            ),
        ]
        return base_tools + draft_tools

    return base_tools


TOOL_HANDLERS: dict[str, Callable[[dict], Awaitable[dict]]] = {
    "ff_get_leagues": handle_ff_get_leagues,
    "ff_get_league_info": handle_ff_get_league_info,
    "ff_get_standings": handle_ff_get_standings,
    "ff_get_teams": handle_ff_get_teams,
    "ff_get_roster": handle_ff_get_roster,
    "ff_get_roster_with_projections": handle_ff_get_roster,
    "ff_get_matchup": handle_ff_get_matchup,
    "ff_get_players": handle_ff_get_players,
    "ff_compare_teams": handle_ff_compare_teams,
    "ff_build_lineup": handle_ff_build_lineup,
    "ff_refresh_token": handle_ff_refresh_token,
    "ff_get_api_status": handle_ff_get_api_status,
    "ff_clear_cache": handle_ff_clear_cache,
    "ff_get_draft_results": handle_ff_get_draft_results,
    "ff_get_waiver_wire": handle_ff_get_waiver_wire,
    "ff_get_draft_rankings": handle_ff_get_draft_rankings,
    "ff_get_draft_recommendation": handle_ff_get_draft_recommendation,
    "ff_analyze_draft_state": handle_ff_analyze_draft_state,
    "ff_analyze_reddit_sentiment": handle_ff_analyze_reddit_sentiment,
    "ff_get_player_news": handle_ff_get_player_news,
    "ff_get_espn_nfl_news": handle_ff_get_espn_nfl_news,
    "ff_get_sportsbook_odds": handle_ff_get_sportsbook_odds,
}


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a fantasy football tool via modular handlers."""
    original_arguments = dict(arguments)
    handler_args = {k: v for k, v in original_arguments.items() if k != "debug"}
    debug_flag = original_arguments.get("debug") is True
    debug_msgs: list[str] = []
    if debug_flag:
        debug_msgs.append(f"debug: call_tool entered for {name}")

    try:
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            result: Any = {"error": f"Unknown tool: {name}"}
        else:
            result = await handler(handler_args)

        if isinstance(result, str) and result.strip() == "0":
            result = {
                "status": "error",
                "message": "Internal legacy layer produced sentinel '0' string",
                "tool": name,
                "stage": "legacy.call_tool.guard",
            }

        # Ensure result is always a dict for consistent handling
        if isinstance(result, str):
            result = {"content": result}

        if debug_flag:
            safe_args = {
                key: value
                for key, value in handler_args.items()
                if not key.lower().endswith("token")
            }
            debug_msgs.append(f"debug: sanitized arguments -> {sorted(safe_args.keys())}")
            result["_debug"] = {
                "messages": debug_msgs,
                "tool": name,
                "arguments": safe_args,
            }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as exc:  # pragma: no cover - defensive catch
        error_result = {
            "error": str(exc),
            "tool": name,
            "arguments": original_arguments,
        }
        return [TextContent(type="text", text=json.dumps(error_result, indent=2))]


_DEFAULT_DRAFT_ROSTER_SLOTS = {
    "QB": 1,
    "RB": 2,
    "WR": 2,
    "TE": 1,
    "FLEX": 1,
    "K": 1,
    "DEF": 1,
    "BN": 6,
}


def _walk_dicts(value: Any):
    """Yield every dictionary in a nested Yahoo response."""
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_dicts(nested)


def _normalize_draft_position(position: Any) -> str:
    aliases = {
        "D/ST": "DEF",
        "DST": "DEF",
        "W/R/T": "FLEX",
        "UTIL": "FLEX",
        "Q/W/R/T": "SUPERFLEX",
        "OP": "SUPERFLEX",
    }
    normalized = str(position or "").upper()
    return aliases.get(normalized, normalized)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_draft_settings(settings_data: dict, stat_categories_data: Optional[dict] = None) -> dict:
    """Extract roster slots and the reception modifier used for draft context."""
    roster_slots: dict[str, int] = {}
    stat_modifiers: dict[str, float] = {}
    reception_points: Optional[float] = None
    passing_touchdown_points: Optional[float] = None
    draft_type = "snake"

    stat_names = {}
    for node in _walk_dicts(stat_categories_data or {}):
        stat = node.get("stat")
        if not isinstance(stat, dict) and "stat_id" in node:
            stat = node
        if isinstance(stat, dict) and "stat_id" in stat:
            name = stat.get("display_name") or stat.get("name") or stat.get("abbr")
            if name:
                stat_names[str(stat["stat_id"])] = str(name)

    for node in _walk_dicts(settings_data):
        roster_position = node.get("roster_position")
        if isinstance(roster_position, dict):
            position = _normalize_draft_position(roster_position.get("position"))
            if position:
                roster_slots[position] = roster_slots.get(position, 0) + int(
                    _number(roster_position.get("count"), 1)
                )

        stat = node.get("stat")
        if not isinstance(stat, dict) and "stat_id" in node and "value" in node:
            stat = node
        if isinstance(stat, dict) and "stat_id" in stat and "value" in stat:
            stat_id = str(stat.get("stat_id"))
            value = _number(stat.get("value"))
            stat_modifiers[stat_id] = value
            stat_name = str(
                stat.get("display_name")
                or stat.get("name")
                or stat.get("abbr")
                or stat_names.get(stat_id)
                or ""
            ).lower()
            if stat_name.strip() in {"reception", "receptions", "rec"}:
                reception_points = value
            if "passing touchdown" in stat_name or stat_name.strip() in {"pass td", "pass tds"}:
                passing_touchdown_points = value

        for key in ("draft_type", "draft_order_type"):
            if key in node:
                draft_type = str(node[key]).lower()
        if str(node.get("is_auction_draft", "0")).lower() in {"1", "true", "yes"}:
            draft_type = "auction"

    if reception_points is None:
        scoring_format = "custom/unknown"
    elif reception_points >= 0.75:
        scoring_format = "PPR"
    elif reception_points > 0:
        scoring_format = "Half-PPR"
    else:
        scoring_format = "Standard"

    return {
        "roster_slots": roster_slots or dict(_DEFAULT_DRAFT_ROSTER_SLOTS),
        "roster_slots_source": "yahoo" if roster_slots else "standard fallback",
        "scoring_format": scoring_format,
        "scoring_adjustment": "receptions and passing touchdowns",
        "reception_points": reception_points,
        "passing_touchdown_points": passing_touchdown_points,
        "stat_modifier_count": len(stat_modifiers),
        "stat_modifiers": stat_modifiers,
        "draft_type": draft_type,
        "is_snake_draft": draft_type not in {"auction", "salary_cap", "linear"},
    }


def _drafted_position_counts(roster: list[dict], roster_data: dict) -> dict[str, int]:
    """Count natural positions even when Yahoo assigns a bench or flex slot."""
    natural_positions = []
    for node in _walk_dicts(roster_data):
        player = node.get("player")
        if not isinstance(player, list):
            continue
        player_nodes = list(_walk_dicts(player))
        position = next(
            (part.get("display_position") for part in player_nodes if part.get("display_position")),
            None,
        )
        name = next(
            (
                part["name"].get("full")
                for part in player_nodes
                if isinstance(part.get("name"), dict) and part["name"].get("full")
            ),
            None,
        )
        if position and name:
            natural_positions.append(_normalize_draft_position(str(position).split(",")[0]))

    positions = natural_positions or [
        _normalize_draft_position(player.get("position")) for player in roster
    ]
    counts: dict[str, int] = {}
    for position in positions:
        if position:
            counts[position] = counts.get(position, 0) + 1
    return counts


_FLEX_SLOT_ELIGIBILITY = {
    "FLEX": {"RB", "WR", "TE"},
    "W/R": {"WR", "RB"},
    "W/T": {"WR", "TE"},
    "R/T": {"RB", "TE"},
    "RB/WR": {"RB", "WR"},
    "WR/TE": {"WR", "TE"},
    "SUPERFLEX": {"QB", "RB", "WR", "TE"},
}


def _max_flexible_slots_filled(surplus: dict[str, int], slots: list[set[str]]) -> int:
    """Return the most flexible slots that can be filled by positional surplus."""
    ordered_slots = sorted(slots, key=len)

    def assign(index: int) -> int:
        if index == len(ordered_slots):
            return 0
        best = assign(index + 1)
        for position in ordered_slots[index]:
            if surplus.get(position, 0) <= 0:
                continue
            surplus[position] -= 1
            best = max(best, 1 + assign(index + 1))
            surplus[position] += 1
        return best

    return assign(0)


def _build_positional_needs(
    position_counts: dict[str, int], roster_slots: dict[str, int], roster_available: bool = True
) -> dict:
    surplus = {
        position: max(0, position_counts.get(position, 0) - roster_slots.get(position, 0))
        for position in ("QB", "RB", "WR", "TE")
    }
    regular_slots = [
        eligible
        for slot, eligible in _FLEX_SLOT_ELIGIBILITY.items()
        if slot != "SUPERFLEX"
        for _ in range(roster_slots.get(slot, 0))
    ]
    all_slots = regular_slots + [
        _FLEX_SLOT_ELIGIBILITY["SUPERFLEX"]
        for _ in range(roster_slots.get("SUPERFLEX", 0))
    ]
    regular_filled = _max_flexible_slots_filled(dict(surplus), regular_slots)
    all_filled = _max_flexible_slots_filled(dict(surplus), all_slots)

    needs = {}
    for position in ("QB", "RB", "WR", "TE", "K", "DEF"):
        current = position_counts.get(position, 0)
        starters = roster_slots.get(position, 0)
        missing_starters = max(0, starters - current)
        if not roster_available:
            level = "unknown"
            bonus = 0.0
        elif missing_starters:
            level = "critical"
            bonus = 18.0
        else:
            candidate_surplus = dict(surplus)
            candidate_surplus[position] = candidate_surplus.get(position, 0) + 1
            fills_regular = (
                _max_flexible_slots_filled(candidate_surplus, regular_slots) > regular_filled
            )
            fills_any = _max_flexible_slots_filled(candidate_surplus, all_slots) > all_filled
            if fills_regular:
                level = "flex"
                bonus = 9.0
            elif fills_any:
                level = "superflex"
                bonus = 12.0 if position == "QB" else 9.0
            elif starters and current == starters and position not in {"K", "DEF"}:
                level = "depth"
                bonus = 4.0
            elif starters:
                level = "filled"
                bonus = 0.0
            else:
                level = "not required"
                bonus = -4.0

        needs[position] = {
            "current_count": current,
            "starter_slots": starters,
            "missing_starters": missing_starters,
            "need": level,
            "recommendation_bonus": bonus,
        }
    return needs


def _snake_draft_timing(
    current_pick: Optional[int],
    drafted_count: int,
    num_teams: int,
    draft_slot: Any,
    is_snake_draft: Optional[bool] = True,
) -> dict:
    num_teams = max(2, int(_number(num_teams, 12)))
    slot = int(_number(draft_slot)) if _number(draft_slot) else None

    if is_snake_draft is None:
        return {
            "current_pick": current_pick,
            "source": "draft type unavailable",
            "num_teams": num_teams,
            "is_snake_draft": None,
        }
    if not is_snake_draft:
        return {
            "current_pick": current_pick,
            "source": "not applicable for non-snake draft",
            "num_teams": num_teams,
            "is_snake_draft": False,
        }

    if current_pick and current_pick > 0:
        pick = current_pick
        source = "explicit current_pick"
        round_number = ((pick - 1) // num_teams) + 1
        pick_in_round = ((pick - 1) % num_teams) + 1
        if slot is None:
            slot = pick_in_round if round_number % 2 else num_teams - pick_in_round + 1
    elif slot:
        round_number = drafted_count + 1
        pick_in_round = slot if round_number % 2 else num_teams - slot + 1
        pick = ((round_number - 1) * num_teams) + pick_in_round
        source = "inferred from roster and draft slot"
    else:
        return {
            "current_pick": current_pick,
            "source": "unavailable",
            "num_teams": num_teams,
            "is_snake_draft": True,
        }

    scheduled_pick_in_round = slot if round_number % 2 else num_teams - slot + 1
    scheduled_pick = ((round_number - 1) * num_teams) + scheduled_pick_in_round
    if current_pick and pick < scheduled_pick:
        next_pick = scheduled_pick
    else:
        next_round = round_number + 1
        next_pick_in_round = slot if next_round % 2 else num_teams - slot + 1
        next_pick = ((next_round - 1) * num_teams) + next_pick_in_round
    return {
        "current_pick": pick,
        "source": source,
        "num_teams": num_teams,
        "draft_slot": slot,
        "round": round_number,
        "pick_in_round": pick_in_round,
        "next_pick": next_pick,
        "picks_until_next": max(0, next_pick - pick - 1),
        "is_snake_draft": True,
    }


def _scoring_bonus(
    position: str, scoring_format: str, passing_touchdown_points: Optional[float] = None
) -> float:
    bonus = 0.0
    if scoring_format == "PPR":
        bonus += {"RB": 4.0, "WR": 7.0, "TE": 7.0}.get(position, 0.0)
    elif scoring_format == "Half-PPR":
        bonus += {"RB": 2.0, "WR": 4.0, "TE": 4.0}.get(position, 0.0)
    if position == "QB" and passing_touchdown_points is not None:
        bonus += max(-6.0, min(6.0, (passing_touchdown_points - 4.0) * 3.0))
    return bonus


async def _get_draft_context(league_key: str, current_pick: Optional[int]) -> dict:
    warnings = []
    leagues, team_info = await asyncio.gather(
        discover_leagues(), get_user_team_info(league_key), return_exceptions=True
    )
    if isinstance(leagues, Exception):
        warnings.append("League summary unavailable")
        league_info = {}
    else:
        league_info = leagues.get(league_key, {})
    if isinstance(team_info, Exception) or not team_info:
        warnings.append("Your team and draft slot could not be identified")
        team_info = {}

    game_key = league_key.split(".", 1)[0]
    settings_data, stat_categories_data = await asyncio.gather(
        yahoo_api_call(f"league/{league_key}/settings"),
        yahoo_api_call(f"game/{game_key}/stat_categories"),
        return_exceptions=True,
    )
    if isinstance(settings_data, Exception):
        settings_data = {}
        warnings.append("Yahoo league settings unavailable; standard roster fallback used")
    if isinstance(stat_categories_data, Exception):
        stat_categories_data = {}
        warnings.append("Yahoo stat categories unavailable; scoring adjustments may be limited")
    settings = _parse_draft_settings(settings_data, stat_categories_data)
    settings_available = bool(settings_data)
    roster_configuration_available = settings["roster_slots_source"] == "yahoo"

    roster = []
    roster_data = {}
    roster_available = False
    team_key = team_info.get("team_key")
    if team_key:
        try:
            roster_data = await yahoo_api_call(f"team/{team_key}/roster")
            roster = parse_team_roster(roster_data)
            roster_available = True
        except Exception:
            warnings.append("Your drafted roster could not be loaded")
    else:
        warnings.append("Your drafted roster could not be loaded")

    position_counts = _drafted_position_counts(roster, roster_data)
    needs = _build_positional_needs(
        position_counts,
        settings["roster_slots"],
        roster_available=roster_available and roster_configuration_available,
    )
    timing = _snake_draft_timing(
        current_pick,
        sum(position_counts.values()),
        league_info.get("num_teams", 12),
        team_info.get("draft_position") if current_pick or roster_available else None,
        settings["is_snake_draft"] if settings_available else None,
    )
    if timing["source"] == "unavailable":
        warnings.append("Pass current_pick to apply snake-draft timing")
    elif timing["source"] == "draft type unavailable":
        warnings.append("Draft timing was not applied because Yahoo draft settings are unavailable")

    return {
        "drafted_roster": roster,
        "roster_available": roster_available,
        "roster_configuration_available": roster_configuration_available,
        "position_counts": position_counts,
        "positional_needs": needs,
        "league": {
            "name": league_info.get("name", "Unknown"),
            "num_teams": timing["num_teams"],
            "matchup_scoring_type": league_info.get("scoring_type", "unknown"),
            **settings,
        },
        "draft_timing": timing,
        "warnings": warnings,
    }


def _sportsbook_warning_messages(response: dict) -> list[str]:
    warnings = [str(warning) for warning in response.get("warnings", [])]
    error = response.get("error")
    if isinstance(error, dict):
        code = error.get("code", "provider_error")
        message = error.get("message", "PropLine context unavailable")
        warnings.append(f"PropLine {code}: {message}")
    for unmatched in response.get("unmatched", []):
        if not isinstance(unmatched, dict):
            continue
        entity_type = unmatched.get("entity_type", "entity")
        query = unmatched.get("query", "unknown")
        reason = unmatched.get("reason", "not_found")
        warnings.append(f"No sportsbook context for {entity_type} '{query}': {reason}")
    return list(dict.fromkeys(warnings))


async def _get_draft_sportsbook_context(
    top_picks: list[dict], scope: str, shortlist_size: int
) -> tuple[dict, list[str]]:
    shortlist = top_picks[: max(1, min(5, shortlist_size))]
    players = [pick["player"].get("name", "") for pick in shortlist]
    players = [name for name in players if name]
    teams = []
    seen_teams = set()
    player_context = {}
    for pick in shortlist:
        player_name = str(pick["player"].get("name", "")).strip()
        team = str(pick["player"].get("team", "")).strip()
        team_key = team.casefold()
        if not team or team_key in {"fa", "n/a", "na"}:
            continue
        if player_name:
            player_context[player_name] = {
                "team": team,
                "position": str(pick["player"].get("position", "")),
            }
        if team_key in seen_teams:
            continue
        seen_teams.add(team_key)
        teams.append(team)

    try:
        response = await get_sportsbook_odds(
            players=players,
            teams=teams or None,
            scope=scope,
            player_context=player_context or None,
        )
    except Exception:
        response = {
            "status": "error",
            "provider": "propline",
            "scope_requested": scope,
            "sources": [],
            "results": [],
            "unmatched": [],
            "warnings": [],
            "error": {
                "code": "provider_error",
                "message": "Sportsbook context unavailable",
                "stage": "enrichment",
            },
        }

    context = {
        key: response[key]
        for key in (
            "status",
            "provider",
            "served_at",
            "scope_requested",
            "sources",
            "quota",
            "error",
        )
        if key in response
    }
    results = response.get("results", [])
    unmatched = response.get("unmatched", [])
    context["players"] = [
        {
            "name": pick["player"].get("name", ""),
            "team": pick["player"].get("team"),
            "position": pick["player"].get("position"),
            "results": [
                row
                for row in results
                if isinstance(row, dict)
                and row.get("entity_type") == "player"
                and row.get("query") == pick["player"].get("name", "")
            ],
            "unmatched": [
                row
                for row in unmatched
                if isinstance(row, dict)
                and row.get("entity_type") == "player"
                and row.get("query") == pick["player"].get("name", "")
            ],
        }
        for pick in shortlist
    ]
    context["teams"] = [
        {
            "team": team,
            "results": [
                row
                for row in results
                if isinstance(row, dict)
                and row.get("entity_type") == "team"
                and row.get("query") == team
            ],
            "unmatched": [
                row
                for row in unmatched
                if isinstance(row, dict)
                and row.get("entity_type") == "team"
                and row.get("query") == team
            ],
        }
        for team in teams
    ]
    return context, _sportsbook_warning_messages(response)


async def get_draft_recommendation_simple(
    league_key: str,
    strategy: str,
    num_recommendations: int,
    current_pick: Optional[int] = None,
    use_rookie_intelligence: bool = False,
    rookie_only: bool = False,
    include_sportsbook_odds: bool = False,
    sportsbook_scope: str = "auto",
    sportsbook_shortlist_size: int = 5,
) -> dict:
    """Simplified draft recommendation using available data."""
    try:
        use_rookie_intelligence = use_rookie_intelligence or rookie_only
        # Get available players using existing waiver wire function
        available_players = await get_waiver_wire_players(league_key, count=100)
        draft_rankings = await get_draft_rankings(league_key, count=50)
        draft_context = await _get_draft_context(league_key, current_pick)
        rookie_evidence = None
        if use_rookie_intelligence:
            try:
                rookie_context = apply_rookie_intelligence(
                    draft_rankings,
                    context="draft",
                    rookie_only=rookie_only,
                )
                draft_rankings = rookie_context["players"]
                rookie_evidence = rookie_context["evidence"]
            except Exception as exc:
                if rookie_only:
                    draft_rankings = []
                rookie_evidence = {
                    "enabled": False,
                    "rookie_only": rookie_only,
                    "warnings": [f"Rookie intelligence unavailable: {exc}"],
                    "opponent_aware": False,
                    "influence": "None; reviewed rookie data failed closed.",
                }

        # Simple scoring based on rankings and availability
        recommendations = []

        available_names = {p.get("name", "").lower() for p in available_players}
        available_candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
        if use_rookie_intelligence:
            # Rookie requests use the board's exact name+position identity and
            # quarantine duplicates. Opt-out keeps the legacy name-only join.
            for available_player in available_players:
                identity = rookie_identity_key(
                    available_player.get("name"), available_player.get("position")
                )
                if all(identity):
                    available_candidates.setdefault(identity, []).append(available_player)

        for player in draft_rankings:
            player_name = player.get("name", "").lower()
            available_matches = available_candidates.get(
                rookie_identity_key(player.get("name"), player.get("position")), []
            )
            is_available = (
                len(available_matches) == 1
                if use_rookie_intelligence
                else player_name in available_names
            )
            if is_available:
                # Simple scoring based on strategy
                rank = _number(
                    player.get("rank"),
                    _number(player.get("average_draft_position"), 999),
                )
                rookie_outlook = player.get("rookie_intelligence", {})
                if rookie_only and rookie_outlook.get("status") == "matched":
                    rank = _number(rookie_outlook.get("base_rank"), rank)
                adp = _number(player.get("average_draft_position"), rank)
                base_score = max(0, 100 - rank)
                strategy_bonus = 0.0

                if strategy == "conservative":
                    # Prefer higher-ranked (safer) picks
                    strategy_bonus = 10 if rank <= 24 else 0
                    reasoning = f"Rank #{rank:g}, conservative choice (proven player)"
                elif strategy == "aggressive":
                    # Prefer potential breakouts (lower owned %)
                    owned_pct = next(
                        (
                            p.get("owned_pct", 50)
                            for p in available_players
                            if p.get("name", "").lower() == player_name
                        ),
                        50,
                    )
                    strategy_bonus = max(
                        0, 20 - (_number(owned_pct, 50) / 5)
                    )  # Bonus for lower ownership
                    reasoning = f"Rank #{rank:g}, high upside potential ({owned_pct}% owned)"
                else:  # balanced
                    strategy_bonus = 5 if rank <= 50 else 0
                    reasoning = f"Rank #{rank:g}, balanced value pick"

                position = _normalize_draft_position(player.get("position"))
                position_need = draft_context["positional_needs"].get(position, {})
                need_bonus = _number(position_need.get("recommendation_bonus"))
                scoring_bonus = _scoring_bonus(
                    position,
                    draft_context["league"]["scoring_format"],
                    draft_context["league"]["passing_touchdown_points"],
                )

                timing_bonus = 0.0
                next_pick = draft_context["draft_timing"].get("next_pick")
                if next_pick and adp <= next_pick:
                    draft_window = max(
                        1, draft_context["draft_timing"].get("picks_until_next", 0) + 1
                    )
                    timing_bonus = min(12.0, max(2.0, ((next_pick - adp) / draft_window) * 8))

                context_reasons = []
                if need_bonus > 0:
                    context_reasons.append(f"{position_need.get('need')} {position} need")
                if scoring_bonus > 0:
                    if position == "QB" and draft_context["league"][
                        "passing_touchdown_points"
                    ] not in (None, 4):
                        context_reasons.append(
                            f"{draft_context['league']['passing_touchdown_points']:g}-point passing TD fit"
                        )
                    else:
                        context_reasons.append(
                            f"{draft_context['league']['scoring_format']} scoring fit"
                        )
                if timing_bonus > 0:
                    context_reasons.append("unlikely to last until your next snake-draft pick")
                if context_reasons:
                    reasoning = f"{reasoning}; " + ", ".join(context_reasons)
                if rookie_outlook.get("status") == "matched":
                    reasoning = (
                        f"Reviewed rookie-year PPR rank #{rookie_outlook['base_rank']} "
                        f"(tier {rookie_outlook['tier']}); {reasoning}"
                    )

                score = base_score + strategy_bonus + need_bonus + scoring_bonus + timing_bonus
                recommendations.append(
                    {
                        "player": player,
                        "score": round(score, 2),
                        "reasoning": reasoning,
                        "score_breakdown": {
                            "base_rank": round(base_score, 2),
                            "strategy": round(strategy_bonus, 2),
                            "roster_need": round(need_bonus, 2),
                            "league_scoring": round(scoring_bonus, 2),
                            "draft_timing": round(timing_bonus, 2),
                        },
                    }
                )
                if rookie_outlook:
                    recommendations[-1]["rookie_intelligence"] = rookie_outlook
                    recommendations[-1]["score_breakdown"]["base_rank_source"] = (
                        "reviewed rookie-year PPR rank"
                        if rookie_only and rookie_outlook.get("status") == "matched"
                        else "Yahoo rank/ADP"
                    )

        # Sort by score and take top N
        recommendations.sort(key=lambda x: x["score"], reverse=True)
        if use_rookie_intelligence and not rookie_only:
            rookie_slots = [
                index
                for index, pick in enumerate(recommendations)
                if pick.get("rookie_intelligence", {}).get("status") == "matched"
            ]
            ordered_rookies = sorted(
                (recommendations[index] for index in rookie_slots),
                key=lambda pick: pick["rookie_intelligence"]["base_rank"],
            )
            for index, rookie_pick in zip(rookie_slots, ordered_rookies):
                recommendations[index] = rookie_pick
        top_picks = recommendations[:num_recommendations]

        try:
            decision_news = await get_decision_news_context(
                [pick["player"].get("name", "") for pick in top_picks]
            )
        except Exception as exc:
            decision_news = {
                "by_player": {},
                "sources": [],
                "warnings": [f"Decision news unavailable: {exc}"],
            }
        for pick in top_picks:
            name = pick["player"].get("name", "")
            pick["news_context"] = decision_news["by_player"].get(
                name,
                {"espn": [], "rotowire": [], "espn_athlete_refs": []},
            )

        result = {
            "status": "success",
            "league_key": league_key,
            "strategy": strategy,
            "current_pick": draft_context["draft_timing"].get("current_pick"),
            "recommendations": top_picks,
            "total_analyzed": len(recommendations),
            "draft_context": draft_context,
            "decision_evidence": {
                "news_sources": decision_news["sources"],
                "warnings": decision_news["warnings"],
                "note": "News is attached as attributed evidence and does not alter numeric draft scores.",
            },
            "insights": [
                f"Using {strategy} draft strategy",
                f"Analyzed {len(available_players)} available players",
                "Cross-referenced with Yahoo rankings",
                "Used your drafted roster and current positional needs when available",
                "Applied available Yahoo roster, supported scoring, and draft-timing context",
                "Attached recent ESPN and RotoWire evidence for recommended players when available",
            ],
        }
        if rookie_evidence is not None:
            result["decision_evidence"]["rookie_intelligence"] = rookie_evidence
            result["insights"].append(
                "Used reviewed first-year PPR outlook only for exact current-class rookie matches"
            )
        if include_sportsbook_odds:
            sportsbook_context, sportsbook_warnings = await _get_draft_sportsbook_context(
                top_picks,
                sportsbook_scope,
                sportsbook_shortlist_size,
            )
            result["sportsbook_context"] = sportsbook_context
            result["sportsbook_warnings"] = sportsbook_warnings
        return result

    except Exception as e:
        return {
            "status": "error",
            "error": f"Draft recommendation failed: {str(e)}",
            "fallback": "Use ff_get_draft_rankings and ff_get_players for manual analysis",
        }


async def analyze_draft_state_simple(league_key: str, strategy: str) -> dict:
    """Simplified draft state analysis."""
    try:
        # Get current roster and league info
        await yahoo_api_call(f"league/{league_key}/teams")
        leagues = await discover_leagues()
        league_info = leagues.get(league_key, {})

        # Analyze positional needs (simplified)
        user_team = await get_user_team_info(league_key)

        # Get current week to estimate draft progress
        current_week = league_info.get("current_week", 1)
        draft_phase = "pre_season" if current_week <= 1 else "mid_season"

        positional_needs = {
            "QB": "medium",  # Usually need 1-2
            "RB": "high",  # Need 3-5
            "WR": "high",  # Need 3-5
            "TE": "medium",  # Need 1-2
            "K": "low",  # Stream position
            "DEF": "low",  # Stream position
        }

        strategic_advice = []
        if strategy == "conservative":
            strategic_advice.append("Focus on proven players with consistent production")
            strategic_advice.append("Avoid injury-prone or rookie players early")
        elif strategy == "aggressive":
            strategic_advice.append("Target high-upside players and breakout candidates")
            strategic_advice.append("Consider reaching for players with league-winning potential")
        else:
            strategic_advice.append("Balance safety with upside potential")
            strategic_advice.append("Follow tier-based drafting approach")

        return {
            "status": "success",
            "league_key": league_key,
            "strategy": strategy,
            "analysis": {
                "draft_phase": draft_phase,
                "league_info": {
                    "name": league_info.get("name", "Unknown"),
                    "teams": league_info.get("num_teams", 12),
                    "scoring": league_info.get("scoring_type", "standard"),
                },
                "positional_needs": positional_needs,
                "strategic_advice": strategic_advice,
                "your_team": (
                    user_team.get("team_name", "Unknown") if user_team else "Team info unavailable"
                ),
            },
            "recommendations": [
                "Use ff_get_draft_recommendation for specific player suggestions",
                "Monitor ff_get_players for available free agents",
                "Check ff_get_draft_rankings for current ADP data",
            ],
        }

    except Exception as e:
        return {
            "status": "error",
            "error": f"Draft analysis failed: {str(e)}",
            "basic_info": "Use ff_get_league_info for basic league details",
        }


# ==============================================================================
# DEPENDENCY INJECTION - Wire up handler dependencies
# ==============================================================================

# Inject dependencies for league handlers
inject_league_helpers(
    discover_leagues=discover_leagues,
    get_user_team_info=get_user_team_info,
    get_all_teams_info=get_all_teams_info,
)

# Inject dependencies for roster handlers
inject_roster_dependencies(
    get_user_team_info=get_user_team_info,
    yahoo_api_call=yahoo_api_call,
    parse_team_roster=parse_team_roster,
)

# Inject dependencies for matchup handlers
inject_matchup_dependencies(
    get_user_team_key=get_user_team_key,
    get_user_team_info=get_user_team_info,
    yahoo_api_call=yahoo_api_call,
    parse_team_roster=parse_team_roster,
)

# Inject dependencies for player handlers
inject_player_dependencies(
    yahoo_api_call=yahoo_api_call,
    get_waiver_wire_players=get_waiver_wire_players,
    get_user_team_key=get_user_team_key,
    get_league_context=YahooLeagueContextService().fetch,
)

# Inject dependencies for draft handlers
inject_draft_dependencies(
    get_all_teams_info=get_all_teams_info,
    get_draft_rankings=get_draft_rankings,
    get_draft_recommendation_simple=get_draft_recommendation_simple,
    analyze_draft_state_simple=analyze_draft_state_simple,
    DRAFT_AVAILABLE=DRAFT_AVAILABLE,
)


async def main():
    """Run the MCP server."""
    # Use stdio transport
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
