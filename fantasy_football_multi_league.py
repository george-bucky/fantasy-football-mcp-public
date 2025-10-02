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
from src.services import analyze_reddit_sentiment

# Import rate limiting and caching utilities
from yahoo_api_utils import rate_limiter, response_cache

# Draft functionality is built-in (no complex imports needed)
DRAFT_AVAILABLE = True

# Load environment
load_dotenv()

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

    # Get current NFL leagues (game key 461 for 2025)
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
                                                            "season": league_dict.get(
                                                                "season", 2025
                                                            ),
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
        user_guid = os.getenv("YAHOO_GUID", "your_redacted_value")

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

                                for element in player_data:
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
                                        if "bye_weeks" in element:
                                            player_info["bye"] = element["bye_weeks"].get(
                                                "week", "N/A"
                                            )

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

                                for element in player_data:
                                    if isinstance(element, dict):
                                        if "name" in element:
                                            player_info["name"] = element["name"]["full"]
                                        if "editorial_team_abbr" in element:
                                            player_info["team"] = element["editorial_team_abbr"]
                                        if "display_position" in element:
                                            player_info["position"] = element["display_position"]
                                        if "bye_weeks" in element:
                                            player_info["bye"] = element["bye_weeks"].get(
                                                "week", "N/A"
                                            )

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
                        "description": "League key (e.g., '461.l.900001'). Use ff_get_leagues to get available keys.",
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
                        "description": "League key (e.g., '461.l.900001')",
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
                        "description": "League key (e.g., '461.l.900001')",
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
                        "description": "League key (e.g., '461.l.900001')",
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
                        "description": "League key (e.g., '461.l.900001')",
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
                        "description": "League key (e.g., '461.l.900001')",
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
                        "description": "League key (e.g., '461.l.900001')",
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
                        "description": "League key (e.g., '461.l.900001')",
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
                        "description": "League key (e.g., '461.l.900001')",
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
                        "description": "League key (e.g., '461.l.900001')",
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
    ]

    # Add draft tools if available
    if DRAFT_AVAILABLE:
        draft_tools = [
            Tool(
                name="ff_get_draft_recommendation",
                description="Get AI-powered draft recommendations for live fantasy football drafts",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_key": {
                            "type": "string",
                            "description": "League key (e.g., '461.l.900001')",
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
                            "description": "Current overall pick number (optional)",
                        },
                    },
                    "required": ["league_key"],
                },
            ),
            Tool(
                name="ff_analyze_draft_state",
                description="Analyze current draft state including roster needs and strategic insights",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_key": {
                            "type": "string",
                            "description": "League key (e.g., '461.l.900001')",
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


async def _handle_ff_get_leagues(arguments: dict) -> dict:
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


async def _handle_ff_get_league_info(arguments: dict) -> dict:
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


async def _handle_ff_get_standings(arguments: dict) -> dict:
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


async def _handle_ff_get_teams(arguments: dict) -> dict:
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


async def _handle_ff_get_roster(arguments: dict) -> dict:
    league_key = arguments.get("league_key")
    team_key = arguments.get("team_key")
    data_level = arguments.get("data_level", "basic")
    include_projections = arguments.get("include_projections", True)
    include_external_data = arguments.get("include_external_data", True)
    include_analysis = arguments.get("include_analysis", True)
    week = arguments.get("week")

    if data_level == "basic":
        effective_projections = False
        effective_external = False
        effective_analysis = False
    elif data_level == "standard":
        effective_projections = True
        effective_external = False
        effective_analysis = False
    else:
        effective_projections = True
        effective_external = True
        effective_analysis = True

    if not include_projections:
        effective_projections = False
    if not include_external_data:
        effective_external = False
    if not include_analysis:
        effective_analysis = False

    needs_enhanced = effective_projections or effective_external or effective_analysis

    team_info = None
    if not team_key:
        team_info = await get_user_team_info(league_key)
        if team_info:
            team_key = team_info.get("team_key")
        else:
            return {
                "error": f"Could not find your team in league {league_key}",
                "suggestion": "Provide team_key explicitly if multiple teams exist",
            }

    data = await yahoo_api_call(f"team/{team_key}/roster")
    roster = parse_team_roster(data)

    if not roster:
        print(
            f"DEBUG: Empty roster for team {team_key}. Raw data keys: {list(data.keys()) if data else 'None'}"
        )
        if data:
            import json

            print("DEBUG: Truncated raw data:", json.dumps(data, indent=2)[:2000])

    if team_info is None or team_info.get("team_key") != team_key:
        team_info = await get_user_team_info(league_key)

    result: dict[str, Any] = {
        "status": "success",
        "league_key": league_key,
        "team_key": team_key,
        "team_name": team_info.get("team_name") if team_info else None,
        "draft_position": team_info.get("draft_position") if team_info else None,
        "draft_grade": team_info.get("draft_grade") if team_info else None,
        "roster": roster,
    }

    if not roster and data:
        result["debug_info"] = {
            "raw_response_keys": list(data.keys()),
            "fantasy_content_present": "fantasy_content" in data,
            "team_structure": str(type(data.get("fantasy_content", {}).get("team", []))),
            "note": "Empty roster - possibly off-season or parsing variation. Check logs for raw data.",
        }

    if not needs_enhanced:
        return result

    try:
        from lineup_optimizer import lineup_optimizer, Player  # type: ignore
    except ImportError as exc:
        result["note"] = f"Enhanced view unavailable: {exc}"
        return result

    try:
        optimizer_payload = {
            "league_key": league_key,
            "team_key": team_key,
            "roster": roster,
        }
        players = await lineup_optimizer.parse_yahoo_roster(optimizer_payload)
        if not players:
            raise ValueError("No players parsed from roster payload")
        players = await lineup_optimizer.enhance_with_external_data(players, week=week)
    except Exception as exc:
        result["note"] = f"Enhanced view unavailable: {exc}"
        return result

    def serialize_player(player: Player) -> Dict[str, Any]:
        base = {
            "name": player.name,
            "position": player.position,
            "team": player.team,
            "opponent": player.opponent,
            "status": player.status,
            "yahoo_projection": player.yahoo_projection if effective_projections else None,
            "sleeper_projection": player.sleeper_projection if effective_external else None,
            "sleeper_id": player.sleeper_id if effective_external else None,
            "sleeper_match_method": player.sleeper_match_method if effective_external else None,
            "floor_projection": player.floor_projection if effective_projections else None,
            "ceiling_projection": player.ceiling_projection if effective_projections else None,
            "consistency_score": player.consistency_score,
            "player_tier": player.player_tier,
            "matchup_score": player.matchup_score if effective_external else None,
            "matchup_description": player.matchup_description if effective_external else None,
            "trending_score": player.trending_score if effective_external else None,
            "risk_level": player.risk_level,
            # Expert advice fields
            "expert_tier": player.expert_tier if effective_external else None,
            "expert_recommendation": player.expert_recommendation if effective_external else None,
            "expert_confidence": player.expert_confidence if effective_external else None,
            "expert_advice": player.expert_advice if effective_external else None,
            "search_rank": player.search_rank if effective_external else None,
        }

        # Add analysis if flagged
        if effective_analysis:
            total_proj = (player.yahoo_projection or 0) + (player.sleeper_projection or 0)
            base["roster_analysis"] = {
                "projected_points": round(total_proj, 1),
                "tier_summary": f"{player.player_tier} tier player",
                "start_recommendation": "Start" if total_proj > 10 else "Bench/Consider",
            }

        return base

    players_by_position: Dict[str, List[Dict[str, Any]]] = {}
    for player in players:
        bucket = players_by_position.setdefault(player.position, [])
        bucket.append(serialize_player(player))

    for bucket in players_by_position.values():
        bucket.sort(key=lambda entry: entry.get("yahoo_projection", 0), reverse=True)

    result.update(
        {
            "total_players": len(players),
            "players_by_position": players_by_position,
            "all_players": [serialize_player(player) for player in players],
            "analysis_context": {
                "data_sources": ["Yahoo"] + (["Sleeper"] if effective_external else []),
                "data_level": data_level,
                "includes": {
                    "projections": effective_projections,
                    "external_data": effective_external,
                    "analysis": effective_analysis,
                },
                "week": week or "current",
                "enhancement_features": (
                    [
                        "Expert tiers and recommendations",
                        "Position rankings and confidence scores",
                        "Risk assessment and trending data",
                        "Sleeper player matching and IDs",
                    ]
                    if effective_external
                    else []
                ),
            },
        }
    )

    # Add overall analysis if flagged
    if effective_analysis:
        total_proj = sum(p.get("projected_points", 0) for p in result["all_players"])
        starters_count = sum(1 for pos in players_by_position if pos not in ["BN", "IR"])
        result["overall_analysis"] = {
            "total_projected_points": round(total_proj, 1),
            "starters_count": starters_count,
            "recommendation": (
                f"Strong lineup with {total_proj:.1f} projected points"
                if total_proj > 150
                else "Consider upgrades"
            ),
        }

    return result


async def _handle_ff_get_matchup(arguments: dict) -> dict:
    league_key = arguments.get("league_key")
    week = arguments.get("week")
    team_key = await get_user_team_key(league_key)

    if not team_key:
        return {"error": f"Could not find your team in league {league_key}"}

    week_param = f";week={week}" if week else ""
    data = await yahoo_api_call(f"team/{team_key}/matchups{week_param}")
    return {
        "league_key": league_key,
        "team_key": team_key,
        "week": week or "current",
        "message": "Matchup data retrieved",
        "raw_matchups": data,
    }


async def _handle_ff_get_players(arguments: dict) -> dict:
    if not arguments.get("league_key"):
        return {"error": "league_key is required"}

    league_key = arguments.get("league_key")
    position = arguments.get("position", "")
    count = arguments.get("count", 10)
    week = arguments.get("week")
    include_analysis = arguments.get("include_analysis", False)
    include_projections = arguments.get("include_projections", True)
    include_external_data = arguments.get("include_external_data", True)

    pos_filter = f";position={position}" if position else ""
    data = await yahoo_api_call(f"league/{league_key}/players;status=A{pos_filter};count={count}")

    def _iter_payload_dicts(container: Any):
        if isinstance(container, dict):
            yield container
        elif isinstance(container, list):
            for item in container:
                yield from _iter_payload_dicts(item)

    basic_players: list[dict[str, Any]] = []
    league = data.get("fantasy_content", {}).get("league", [])
    for item in league:
        if not (isinstance(item, dict) and "players" in item):
            continue
        players_data = item["players"]
        if not isinstance(players_data, dict):
            continue

        for key, player_entry in players_data.items():
            if key == "count" or not isinstance(player_entry, dict):
                continue
            player_array = player_entry.get("player")
            if not isinstance(player_array, list):
                continue

            player_info: dict[str, Any] = {}
            for payload in _iter_payload_dicts(player_array):
                if "name" in payload and isinstance(payload["name"], dict):
                    player_info["name"] = payload["name"].get("full")
                if "editorial_team_abbr" in payload:
                    player_info["team"] = payload["editorial_team_abbr"]
                if "display_position" in payload:
                    player_info["position"] = payload["display_position"]
                if "ownership" in payload and isinstance(payload["ownership"], dict):
                    player_info["owned_pct"] = payload["ownership"].get("ownership_percentage", 0.0)
                if "percent_owned" in payload:
                    player_info["owned_pct"] = float(payload.get("percent_owned", 0.0))
                # Add injury, bye as in waiver
                if "status" in payload:
                    player_info["injury_status"] = payload["status"]
                if "bye_weeks" in payload:
                    player_info["bye"] = payload["bye_weeks"].get("week", "N/A")
            if player_info:
                basic_players.append(player_info)

    result = {
        "status": "success",
        "league_key": league_key,
        "position": position or "all",
        "total_players": len(basic_players),
        "players": basic_players[:count],
    }

    needs_enhancement = include_projections or include_external_data or include_analysis

    if not needs_enhancement:
        return result

    try:
        from lineup_optimizer import lineup_optimizer, Player
    except ImportError as exc:
        result["note"] = f"Enhanced data unavailable: {exc}"
        return result

    try:
        # Parse and enhance
        optimizer_payload = {
            "league_key": league_key,
            "roster": basic_players,  # Treat as roster for parsing
        }
        enhanced_players = await lineup_optimizer.parse_yahoo_roster(optimizer_payload)
        if enhanced_players:
            enhanced_players = await lineup_optimizer.enhance_with_external_data(
                enhanced_players, week=week
            )

            def serialize_free_agent_player(player: Player) -> Dict[str, Any]:
                base = {
                    "name": player.name,
                    "position": player.position,
                    "team": player.team,
                    "opponent": player.opponent or "N/A",
                    "status": "Available",
                    "yahoo_projection": player.yahoo_projection if include_projections else None,
                    "sleeper_projection": (
                        player.sleeper_projection if include_projections else None
                    ),
                    "sleeper_id": player.sleeper_id,
                    "sleeper_match_method": player.sleeper_match_method,
                    "floor_projection": player.floor_projection if include_projections else None,
                    "ceiling_projection": (
                        player.ceiling_projection if include_projections else None
                    ),
                    "consistency_score": player.consistency_score,
                    "player_tier": player.player_tier,
                    "matchup_score": player.matchup_score if include_external_data else None,
                    "matchup_description": (
                        player.matchup_description if include_external_data else None
                    ),
                    "trending_score": player.trending_score if include_external_data else None,
                    "risk_level": player.risk_level,
                    "owned_pct": next(
                        (
                            p.get("owned_pct") or 0
                            for p in basic_players
                            if p.get("name", "").lower() == player.name.lower()
                        ),
                        0,
                    ),
                    "injury_status": getattr(player, "injury_status", "Healthy"),
                    "bye": next(
                        (
                            p.get("bye")
                            for p in basic_players
                            if p.get("name", "").lower() == player.name.lower()
                        ),
                        "N/A",
                    ),
                }

                # Add analysis if flagged
                if include_analysis:
                    proj = (player.yahoo_projection or 0) + (player.sleeper_projection or 0)
                    owned = base.get("owned_pct", 0.0)
                    base["free_agent_value"] = round(proj * (1 - owned / 100), 1)
                    base["analysis"] = (
                        f"Value based on low ownership ({owned}%) and proj ({proj:.1f})"
                    )

                return base

            enhanced_list = [
                serialize_free_agent_player(p) for p in enhanced_players if p.is_valid()
            ]
            if include_analysis:
                enhanced_list.sort(key=lambda x: x.get("free_agent_value", 0), reverse=True)
            elif include_projections:
                enhanced_list.sort(
                    key=lambda x: (x.get("sleeper_projection") or 0)
                    + (x.get("yahoo_projection") or 0),
                    reverse=True,
                )

            result.update(
                {
                    "enhanced_players": enhanced_list,
                    "analysis_context": {
                        "data_sources": ["Yahoo"] + (["Sleeper"] if include_external_data else []),
                        "includes": {
                            "projections": include_projections,
                            "external_data": include_external_data,
                            "analysis": include_analysis,
                        },
                        "week": week or "current",
                    },
                }
            )
        else:
            result["note"] = "No players could be enhanced"
    except Exception as exc:
        result["note"] = f"Enhancement failed: {exc}. Using basic data."

    return result


async def _handle_ff_compare_teams(arguments: dict) -> dict:
    league_key = arguments.get("league_key")
    team_key_a = arguments.get("team_key_a")
    team_key_b = arguments.get("team_key_b")

    data_a = await yahoo_api_call(f"team/{team_key_a}/roster")
    data_b = await yahoo_api_call(f"team/{team_key_b}/roster")

    roster_a = parse_team_roster(data_a)
    roster_b = parse_team_roster(data_b)

    return {
        "league_key": league_key,
        "team_a": {"team_key": team_key_a, "roster": roster_a},
        "team_b": {"team_key": team_key_b, "roster": roster_b},
    }


async def _handle_ff_build_lineup(arguments: dict) -> dict:
    league_key = arguments.get("league_key")
    week = arguments.get("week")
    strategy = arguments.get("strategy", "balanced")
    use_llm = arguments.get("use_llm", False)

    team_key = await get_user_team_key(league_key)
    if not team_key:
        return {"error": f"Could not find your team in league {league_key}"}

    try:
        roster_data = await yahoo_api_call(f"team/{team_key}/roster")
        try:
            from lineup_optimizer import lineup_optimizer
        except ImportError as exc:
            return {
                "error": f"Lineup optimizer unavailable: {exc}",
                "suggestion": "Please check lineup_optimizer.py dependencies",
                "league_key": league_key,
                "team_key": team_key,
            }

        players = await lineup_optimizer.parse_yahoo_roster(roster_data)
        if not players:
            return {
                "error": "Failed to parse Yahoo roster data",
                "league_key": league_key,
                "team_key": team_key,
                "suggestion": "Check roster data format or try refreshing",
            }

        players = await lineup_optimizer.enhance_with_external_data(players, week=week)
        optimization = await lineup_optimizer.optimize_lineup_smart(
            players,
            strategy,
            week,
            use_llm,
        )
        if optimization["status"] == "error":
            return {
                "status": "error",
                "error": "Lineup optimization failed",
                "league_key": league_key,
                "team_key": team_key,
                "errors": optimization.get("errors", []),
                "details": optimization.get("errors", []),
                "data_quality": optimization.get("data_quality", {}),
            }

        starters_formatted = {}
        for pos, player in optimization["starters"].items():
            starters_formatted[pos] = {
                "name": player.name,
                "tier": player.player_tier.upper() if player.player_tier else "UNKNOWN",
                "team": player.team,
                "opponent": player.opponent,
                "matchup_score": player.matchup_score,
                "matchup": player.matchup_description,
                "composite_score": round(player.composite_score, 1),
                "yahoo_proj": (
                    round(player.yahoo_projection, 1) if player.yahoo_projection else None
                ),
                "sleeper_proj": (
                    round(player.sleeper_projection, 1) if player.sleeper_projection else None
                ),
                "trending": (
                    f"{player.trending_score:,} adds" if player.trending_score > 0 else None
                ),
                "floor": round(player.floor_projection, 1) if player.floor_projection else None,
                "ceiling": (
                    round(player.ceiling_projection, 1) if player.ceiling_projection else None
                ),
            }

        bench_formatted = [
            {
                "name": player.name,
                "position": player.position,
                "opponent": player.opponent,
                "composite_score": round(player.composite_score, 1),
                "matchup_score": player.matchup_score,
                "tier": player.player_tier.upper() if player.player_tier else "UNKNOWN",
            }
            for player in optimization["bench"][:5]
        ]

        result: dict[str, Any] = {
            "status": optimization["status"],
            "league_key": league_key,
            "team_key": team_key,
            "week": week or "current",
            "strategy": strategy,
            "optimal_lineup": starters_formatted,
            "bench": bench_formatted,
            "recommendations": optimization["recommendations"],
            "errors": optimization.get("errors", []),
            "analysis": {
                "total_players": optimization["data_quality"]["total_players"],
                "valid_players": optimization["data_quality"]["valid_players"],
                "players_with_projections": optimization["data_quality"][
                    "players_with_projections"
                ],
                "players_with_matchup_data": optimization["data_quality"][
                    "players_with_matchup_data"
                ],
                "strategy_used": optimization["strategy_used"],
                "data_sources": [
                    "Yahoo projections",
                    "Sleeper rankings",
                    "Matchup analysis",
                    "Trending data",
                ],
            },
        }
        if optimization.get("errors"):
            result["warnings"] = optimization["errors"]
        return result
    except Exception as exc:
        return {
            "error": f"Unexpected error during lineup optimization: {exc}",
            "league_key": league_key,
            "team_key": team_key,
            "suggestion": "Try again or check system logs for details",
        }


async def _handle_ff_refresh_token(arguments: dict) -> dict:
    return await refresh_yahoo_token()


async def _handle_ff_get_api_status(arguments: dict) -> dict:
    return {
        "rate_limit": rate_limiter.get_status(),
        "cache": response_cache.get_stats(),
    }


async def _handle_ff_clear_cache(arguments: dict) -> dict:
    pattern = arguments.get("pattern")
    await response_cache.clear(pattern)
    suffix = f" for pattern: {pattern}" if pattern else " completely"
    return {
        "status": "success",
        "message": f"Cache cleared{suffix}",
    }


async def _handle_ff_get_draft_results(arguments: dict) -> dict:
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


async def _handle_ff_get_waiver_wire(arguments: dict) -> dict:
    if not arguments.get("league_key"):
        return {"error": "league_key is required"}

    league_key: Optional[str] = arguments.get("league_key")
    if league_key is None:
        return {"error": "league_key cannot be None"}

    position = arguments.get("position", "all")
    sort = arguments.get("sort", "rank")
    count = arguments.get("count", 30)
    week = arguments.get("week")
    team_key = arguments.get("team_key")
    include_analysis = arguments.get("include_analysis", False)
    include_projections = arguments.get("include_projections", True)
    include_external_data = arguments.get("include_external_data", True)

    # Fetch basic Yahoo waiver players
    basic_players = await get_waiver_wire_players(league_key, position, sort, count)
    if not basic_players:
        return {
            "league_key": league_key,
            "message": "No available players found or error retrieving data",
        }

    result = {
        "status": "success",
        "league_key": league_key,
        "position": position,
        "sort": sort,
        "total_players": len(basic_players),
        "players": basic_players,
    }

    needs_enhancement = include_projections or include_external_data or include_analysis

    if not needs_enhancement:
        return result

    try:
        from lineup_optimizer import lineup_optimizer, Player
        from sleeper_api import get_trending_adds, sleeper_client
    except ImportError as exc:
        result["note"] = f"Enhanced data unavailable: {exc}"
        return result

    try:
        # Create payload for optimizer (mimic roster format)
        optimizer_payload = {
            "league_key": league_key,
            "team_key": team_key or "",  # Optional for waivers
            "roster": basic_players,  # Use as 'roster' for parsing
        }
        enhanced_players = await lineup_optimizer.parse_yahoo_roster(optimizer_payload)
        if enhanced_players:
            enhanced_players = await lineup_optimizer.enhance_with_external_data(
                enhanced_players, week=week
            )

            # Add expert advice for waiver wire analysis
            if include_analysis:
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

            # Fetch and merge trending data
            trending = await get_trending_adds(count)
            trending_dict = {p["name"].lower(): p for p in trending}

            def serialize_waiver_player(player: Player) -> Dict[str, Any]:
                base = {
                    "name": player.name,
                    "position": player.position,
                    "team": player.team,
                    "opponent": player.opponent or "N/A",
                    "status": getattr(player, "status", "Available"),
                    "yahoo_projection": player.yahoo_projection if include_projections else None,
                    "sleeper_projection": (
                        player.sleeper_projection if include_projections else None
                    ),
                    "sleeper_id": player.sleeper_id,
                    "sleeper_match_method": player.sleeper_match_method,
                    "floor_projection": player.floor_projection if include_projections else None,
                    "ceiling_projection": (
                        player.ceiling_projection if include_projections else None
                    ),
                    "consistency_score": player.consistency_score,
                    "player_tier": player.player_tier,
                    "matchup_score": player.matchup_score if include_external_data else None,
                    "matchup_description": (
                        player.matchup_description if include_external_data else None
                    ),
                    "trending_score": player.trending_score if include_external_data else None,
                    "risk_level": player.risk_level,
                    "owned_pct": next(
                        (
                            p.get("owned_pct") or 0.0
                            for p in basic_players
                            if p.get("name", "").lower() == player.name.lower()
                        ),
                        0.0,
                    ),
                    "weekly_change": next(
                        (
                            p.get("weekly_change")
                            for p in basic_players
                            if p.get("name", "").lower() == player.name.lower()
                        ),
                        0,
                    ),
                    "injury_status": getattr(player, "injury_status", "Healthy"),
                    "bye": next(
                        (
                            p.get("bye")
                            for p in basic_players
                            if p.get("name", "").lower() == player.name.lower()
                        ),
                        "N/A",
                    ),
                    # Expert advice fields
                    "expert_tier": (
                        getattr(player, "expert_tier", None) if include_analysis else None
                    ),
                    "expert_recommendation": (
                        getattr(player, "expert_recommendation", None) if include_analysis else None
                    ),
                    "expert_confidence": (
                        getattr(player, "expert_confidence", None) if include_analysis else None
                    ),
                    "expert_advice": (
                        getattr(player, "expert_advice", None) if include_analysis else None
                    ),
                }

                # Merge trending
                name_lower = player.name.lower()
                if name_lower in trending_dict:
                    trend = trending_dict[name_lower]
                    base["trending_count"] = trend.get("count", 0)
                    base["trending_position"] = trend.get("position")

                return base

            # Analyze positional scarcity in league for context
            position_scarcity = {}
            if include_analysis:
                try:
                    # Simple scarcity analysis based on ownership and position
                    position_counts = {}

                    for p in basic_players:
                        pos = p.get("position", "Unknown")
                        owned = p.get("owned_pct", 0.0)

                        if pos not in position_counts:
                            position_counts[pos] = {"total": 0, "owned_sum": 0}

                        position_counts[pos]["total"] += 1
                        position_counts[pos]["owned_sum"] += owned

                    # Calculate scarcity scores
                    for pos, data in position_counts.items():
                        avg_owned = data["owned_sum"] / data["total"] if data["total"] > 0 else 0
                        # Higher average ownership = more scarcity
                        scarcity_score = min(avg_owned / 10, 10)  # 0-10 scale
                        position_scarcity[pos] = {
                            "scarcity_score": round(scarcity_score, 1),
                            "avg_ownership": round(avg_owned, 1),
                            "available_count": data["total"],
                        }
                except Exception:
                    # If scarcity analysis fails, continue without it
                    pass

            # Serialize enhanced players with analysis
            enhanced_list = []
            for player in enhanced_players:
                if not player.is_valid():
                    continue

                # Create serialized player data
                base = serialize_waiver_player(player)

                # Add waiver-specific analysis if flagged
                if include_analysis:
                    # Calculate comprehensive waiver priority score
                    expert_confidence = getattr(player, "expert_confidence", 50)
                    proj = (player.yahoo_projection or 0) + (player.sleeper_projection or 0)
                    trend_score = base.get("trending_count", 0)
                    owned = base.get("owned_pct", 0.0)

                    # Position scarcity bonus (0-5 points)
                    pos_scarcity = position_scarcity.get(player.position, {}).get(
                        "scarcity_score", 0
                    )
                    scarcity_bonus = min(pos_scarcity * 0.5, 5)

                    # Waiver-specific scoring algorithm
                    # Base score from expert confidence (35% weight, reduced to add scarcity)
                    confidence_score = expert_confidence * 0.35

                    # Projection score (30% weight)
                    projection_score = min(proj * 2, 30)  # Cap at 30 points

                    # Ownership bonus - lower ownership = higher priority (20% weight)
                    ownership_bonus = max(0, (50 - owned) * 0.4)  # Max 20 points for 0% owned

                    # Trending bonus (10% weight)
                    trending_bonus = min(trend_score * 1.5, 10)  # Cap at 10 points

                    # Final waiver priority score
                    waiver_priority = (
                        confidence_score
                        + projection_score
                        + ownership_bonus
                        + trending_bonus
                        + scarcity_bonus
                    )
                    base["waiver_priority"] = round(waiver_priority, 1)

                    # Enhanced analysis explanation
                    expert_tier = getattr(player, "expert_tier", "Unknown")
                    expert_rec = getattr(player, "expert_recommendation", "Monitor")

                    # Add scarcity context to analysis
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

                    # Add pickup urgency classification (adjusted for scarcity)
                    urgency_threshold = waiver_priority + (
                        scarcity_bonus * 2
                    )  # Boost urgency for scarce positions
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

                    # Add position context
                    base["position_context"] = position_scarcity.get(
                        player.position,
                        {"scarcity_score": 0, "avg_ownership": 0, "available_count": 0},
                    )

                enhanced_list.append(base)
            # Sort by waiver_priority or projection if analysis/projections
            if include_analysis:
                enhanced_list.sort(key=lambda x: x.get("waiver_priority", 0), reverse=True)
            elif include_projections:
                enhanced_list.sort(
                    key=lambda x: (x.get("sleeper_projection") or 0)
                    + (x.get("yahoo_projection") or 0),
                    reverse=True,
                )

            result.update(
                {
                    "enhanced_players": enhanced_list,
                    "analysis_context": {
                        "data_sources": ["Yahoo"] + (["Sleeper"] if include_external_data else []),
                        "includes": {
                            "projections": include_projections,
                            "external_data": include_external_data,
                            "analysis": include_analysis,
                            "expert_advice": include_analysis,  # Expert advice tied to analysis flag
                        },
                        "features": [
                            "Yahoo ownership and change data",
                            "Sleeper projections and rankings" if include_external_data else None,
                            "Matchup analysis" if include_external_data else None,
                            "Expert tier classification" if include_analysis else None,
                            "Waiver priority scoring" if include_analysis else None,
                            "Pickup urgency assessment" if include_analysis else None,
                            "Positional scarcity analysis" if include_analysis else None,
                        ],
                        "algorithm": (
                            {
                                "waiver_priority_weights": {
                                    "expert_confidence": "35%",
                                    "projections": "30%",
                                    "ownership_bonus": "20%",
                                    "trending_bonus": "10%",
                                    "scarcity_bonus": "5%",
                                }
                            }
                            if include_analysis
                            else None
                        ),
                        "position_scarcity": position_scarcity if include_analysis else None,
                        "week": week or "current",
                        "trending_count": len(trending),
                    },
                }
            )
        else:
            result["note"] = "No players could be enhanced"
    except Exception as exc:
        result["note"] = f"Enhancement failed: {exc}. Using basic data."

    return result


async def _handle_ff_get_draft_rankings(arguments: dict) -> dict:
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


async def _handle_ff_get_draft_recommendation(arguments: dict) -> dict:
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


async def _handle_ff_analyze_draft_state(arguments: dict) -> dict:
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


async def _handle_ff_analyze_reddit_sentiment(arguments: dict) -> dict:
    players = arguments.get("players", [])
    time_window = arguments.get("time_window_hours", 48)

    if not players:
        return {"error": "No players specified for sentiment analysis"}
    return await analyze_reddit_sentiment(players, time_window)


TOOL_HANDLERS: dict[str, Callable[[dict], Awaitable[dict]]] = {
    "ff_get_leagues": _handle_ff_get_leagues,
    "ff_get_league_info": _handle_ff_get_league_info,
    "ff_get_standings": _handle_ff_get_standings,
    "ff_get_teams": _handle_ff_get_teams,
    "ff_get_roster": _handle_ff_get_roster,
    "ff_get_roster_with_projections": _handle_ff_get_roster,
    "ff_get_matchup": _handle_ff_get_matchup,
    "ff_get_players": _handle_ff_get_players,
    "ff_compare_teams": _handle_ff_compare_teams,
    "ff_build_lineup": _handle_ff_build_lineup,
    "ff_refresh_token": _handle_ff_refresh_token,
    "ff_get_api_status": _handle_ff_get_api_status,
    "ff_clear_cache": _handle_ff_clear_cache,
    "ff_get_draft_results": _handle_ff_get_draft_results,
    "ff_get_waiver_wire": _handle_ff_get_waiver_wire,
    "ff_get_draft_rankings": _handle_ff_get_draft_rankings,
    "ff_get_draft_recommendation": _handle_ff_get_draft_recommendation,
    "ff_analyze_draft_state": _handle_ff_analyze_draft_state,
    "ff_analyze_reddit_sentiment": _handle_ff_analyze_reddit_sentiment,
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


async def get_draft_recommendation_simple(
    league_key: str, strategy: str, num_recommendations: int, current_pick: Optional[int] = None
) -> dict:
    """Simplified draft recommendation using available data."""
    try:
        # Get available players using existing waiver wire function
        available_players = await get_waiver_wire_players(league_key, count=100)
        draft_rankings = await get_draft_rankings(league_key, count=50)

        # Simple scoring based on rankings and availability
        recommendations = []

        # Create a quick lookup for available players
        available_names = {p.get("name", "").lower() for p in available_players}

        for player in draft_rankings:
            player_name = player.get("name", "").lower()
            if player_name in available_names:
                # Simple scoring based on strategy
                rank = player.get("rank", 999)
                base_score = max(0, 100 - rank)

                if strategy == "conservative":
                    # Prefer higher-ranked (safer) picks
                    score = base_score + (10 if rank <= 24 else 0)
                    reasoning = f"Rank #{rank}, conservative choice (proven player)"
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
                    upside_bonus = max(0, 20 - (owned_pct / 5))  # Bonus for lower ownership
                    score = base_score + upside_bonus
                    reasoning = f"Rank #{rank}, high upside potential ({owned_pct}% owned)"
                else:  # balanced
                    score = base_score + (5 if rank <= 50 else 0)
                    reasoning = f"Rank #{rank}, balanced value pick"

                recommendations.append({"player": player, "score": score, "reasoning": reasoning})

        # Sort by score and take top N
        recommendations.sort(key=lambda x: x["score"], reverse=True)
        top_picks = recommendations[:num_recommendations]

        return {
            "status": "success",
            "league_key": league_key,
            "strategy": strategy,
            "current_pick": current_pick,
            "recommendations": top_picks,
            "total_analyzed": len(recommendations),
            "insights": [
                f"Using {strategy} draft strategy",
                f"Analyzed {len(available_players)} available players",
                "Cross-referenced with Yahoo rankings",
                "Recommendations prioritize available players only",
            ],
        }

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


async def main():
    """Run the MCP server."""
    # Use stdio transport
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
