#!/usr/bin/env python3
"""
Fantasy Football MCP Server - Multi-League Support
"""

import asyncio
import json
import os
import socket
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Reddit sentiment analysis imports
try:
    import praw
    from textblob import TextBlob

    REDDIT_AVAILABLE = True
except ImportError:
    REDDIT_AVAILABLE = False

# Import rate limiting and caching utilities
from yahoo_api_utils import rate_limiter, response_cache

# Draft functionality is built-in (no complex imports needed)
DRAFT_AVAILABLE = True

# Load environment
load_dotenv()

# Configuration
YAHOO_ACCESS_TOKEN = os.getenv("YAHOO_ACCESS_TOKEN")
YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

# Reddit configuration
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")

# Create server instance
server = Server("fantasy-football")

# Cache for leagues
LEAGUES_CACHE = {}


async def yahoo_api_call(
    endpoint: str, retry_on_auth_fail: bool = True, use_cache: bool = True
) -> dict:
    """Make Yahoo API request with rate limiting, caching, and automatic token refresh."""
    global YAHOO_ACCESS_TOKEN

    # Check cache first (if enabled)
    if use_cache:
        cached_response = await response_cache.get(endpoint)
        if cached_response is not None:
            return cached_response

    # Apply rate limiting
    await rate_limiter.acquire()

    url = f"{YAHOO_API_BASE}/{endpoint}?format=json"
    headers = {"Authorization": f"Bearer {YAHOO_ACCESS_TOKEN}", "Accept": "application/json"}

    connector = aiohttp.TCPConnector(family=socket.AF_INET)
    async with aiohttp.ClientSession(connector=connector, trust_env=True) as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                # Cache successful response
                if use_cache:
                    await response_cache.set(endpoint, data)
                return data
            elif response.status == 401 and retry_on_auth_fail:
                # Token expired, try to refresh
                refresh_result = await refresh_yahoo_token()
                if refresh_result.get("status") == "success":
                    # Token refreshed, retry the API call with new token
                    return await yahoo_api_call(
                        endpoint, retry_on_auth_fail=False, use_cache=use_cache
                    )
                else:
                    # Refresh failed, raise the original error
                    text = await response.text()
                    raise Exception(f"Yahoo API auth failed and token refresh failed: {text[:200]}")
            else:
                text = await response.text()
                raise Exception(f"Yahoo API error {response.status}: {text[:200]}")


async def refresh_yahoo_token() -> dict:
    """Refresh the Yahoo access token using the refresh token."""
    global YAHOO_ACCESS_TOKEN

    client_id = os.getenv("YAHOO_CONSUMER_KEY")
    client_secret = os.getenv("YAHOO_CONSUMER_SECRET")
    refresh_token = os.getenv("YAHOO_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        return {"status": "error", "message": "Missing credentials in environment"}

    token_url = "https://api.login.yahoo.com/oauth2/get_token"

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    try:
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector, trust_env=True) as session:
            async with session.post(token_url, data=data) as response:
                if response.status == 200:
                    token_data = await response.json()
                    new_access_token = token_data.get("access_token")
                    new_refresh_token = token_data.get("refresh_token", refresh_token)
                    expires_in = token_data.get("expires_in", 3600)

                    # Update global token
                    YAHOO_ACCESS_TOKEN = new_access_token

                    # Update environment
                    os.environ["YAHOO_ACCESS_TOKEN"] = new_access_token
                    if new_refresh_token != refresh_token:
                        os.environ["YAHOO_REFRESH_TOKEN"] = new_refresh_token

                    return {
                        "status": "success",
                        "message": "Token refreshed successfully",
                        "expires_in": expires_in,
                        "expires_in_hours": round(expires_in / 3600, 1),
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "message": f"Failed to refresh token: {response.status}",
                        "details": error_text[:200],
                    }
    except Exception as e:
        return {"status": "error", "message": f"Error refreshing token: {str(e)}"}


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


async def get_user_team_info(league_key: str) -> Optional[dict]:
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


async def get_user_team_key(league_key: str) -> Optional[str]:
    """Get the user's team key in a specific league (legacy function for compatibility)."""
    team_info = await get_user_team_info(league_key)
    return team_info["team_key"] if team_info else None


def parse_team_roster(data: dict) -> list[dict]:
    """Extract a simple roster list from Yahoo team data."""
    roster: list[dict] = []
    team = data.get("fantasy_content", {}).get("team", [])

    for item in team:
        if isinstance(item, dict) and "roster" in item:
            roster_data = item["roster"]
            players = (
                roster_data.get("0", {}).get("players") if isinstance(roster_data, dict) else None
            )
            if not players:
                continue

            for key, pdata in players.items():
                if key == "count" or not isinstance(pdata, dict) or "player" not in pdata:
                    continue

                player_array = pdata["player"]
                if not isinstance(player_array, list):
                    continue

                info: dict[str, Any] = {}

                # Helper to robustly extract selected position regardless of structure
                def _extract_position(selected_position_obj: Any) -> Optional[str]:
                    if not selected_position_obj:
                        return None
                    if isinstance(selected_position_obj, dict):
                        # Direct form: {"position": "WR"}
                        if "position" in selected_position_obj:
                            return selected_position_obj.get("position")
                        # Keyed form: {"0": {"position": "WR"}, "count": 1}
                        for k, v in selected_position_obj.items():
                            if k == "count":
                                continue
                            if isinstance(v, dict) and "position" in v:
                                return v["position"]
                    elif isinstance(selected_position_obj, list):
                        for entry in selected_position_obj:
                            if isinstance(entry, dict) and "position" in entry:
                                return entry["position"]
                    return None

                def _scan_container(container: Any) -> None:
                    if not isinstance(container, dict):
                        return
                    name_dict = container.get("name")
                    if isinstance(name_dict, dict) and "full" in name_dict:
                        info["name"] = name_dict.get("full")
                    # Status, default will be set later if absent
                    if "status" in container:
                        info["status"] = container.get("status", "OK")
                    # Prefer selected_position when available
                    if "selected_position" in container:
                        pos = _extract_position(container.get("selected_position"))
                        if pos:
                            info["position"] = pos
                    # Fallback to display position if selected_position not found
                    if "position" not in info and "display_position" in container:
                        info["position"] = container.get("display_position")

                for element in player_array:
                    if isinstance(element, dict):
                        _scan_container(element)
                    elif isinstance(element, list):
                        for sub in element:
                            _scan_container(sub)

                if info:
                    if "status" not in info:
                        info["status"] = "OK"
                    roster.append(info)

    return roster


async def get_waiver_wire_players(
    league_key: str, position: str = "all", sort: str = "rank", count: int = 20
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
                                    players.append(player_info)

        return players
    except Exception:
        return []


async def get_draft_rankings(
    league_key: str = None, position: str = "all", count: int = 50
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


async def analyze_reddit_sentiment(
    players: list[str], time_window_hours: int = 48
) -> dict[str, Any]:
    """
    Analyze Reddit sentiment for fantasy football players using enhanced analyzer.
    Used for Start/Sit decisions based on community consensus.
    """
    try:
        # Import enhanced Reddit analyzer
        from src.agents.reddit_analyzer import RedditSentimentAgent
        
        # Create mock settings for the analyzer
        class MockSettings:
            mcp_server_version = "1.0.0"
        
        # Initialize enhanced analyzer
        analyzer = RedditSentimentAgent(MockSettings())
        
        # Analyze sentiment with enhanced error handling
        if len(players) == 1:
            # Single player analysis
            result = await analyzer.analyze_player_sentiment(players[0], time_window_hours)
            
            # Convert to legacy format for compatibility
            return {
                "players": players,
                "analysis_type": "single",
                "time_window_hours": time_window_hours,
                "player_data": {
                    players[0]: {
                        "sentiment_score": result.overall_sentiment or 0.0,
                        "consensus": result.consensus or "MIXED",
                        "posts_analyzed": result.posts_analyzed,
                        "comments_analyzed": result.comments_analyzed,
                        "injury_mentions": result.injury_mentions,
                        "hype_score": result.hype_score,
                        "top_comments": result.top_comments[:3],
                        "status": result.status,
                        "confidence": result.confidence,
                        "fallback_used": result.fallback_used
                    }
                },
                "enhanced_analyzer": True  # Flag to indicate enhanced version
            }
        else:
            # Multiple player comparison
            comparison = await analyzer.compare_players(players, time_window_hours)
            
            # Convert results to legacy format
            player_data = {}
            for player_name, result in comparison.get('results', {}).items():
                player_data[player_name] = {
                    "sentiment_score": result.overall_sentiment or 0.0,
                    "consensus": result.consensus or "MIXED",
                    "posts_analyzed": result.posts_analyzed,
                    "comments_analyzed": result.comments_analyzed,
                    "injury_mentions": result.injury_mentions,
                    "hype_score": result.hype_score,
                    "top_comments": result.top_comments[:3],
                    "status": result.status,
                    "confidence": result.confidence,
                    "fallback_used": result.fallback_used
                }
            
            return {
                "players": players,
                "analysis_type": "comparison",
                "time_window_hours": time_window_hours,
                "player_data": player_data,
                "recommendation": comparison.get('recommendation', {}),
                "confidence": comparison.get('confidence', 0),
                "successful_analyses": comparison.get('successful_analyses', 0),
                "total_players": comparison.get('total_players', len(players)),
                "timestamp": comparison.get('timestamp', ''),
                "enhanced_analyzer": True  # Flag to indicate enhanced version
            }
        
        # Clean up
        await analyzer.cleanup()
        
    except ImportError as e:
        # Fallback to basic implementation if enhanced analyzer not available
        return await _analyze_reddit_sentiment_fallback(players, time_window_hours, f"Enhanced analyzer unavailable: {e}")
    except Exception as e:
        # Fallback to basic implementation on any error
        return await _analyze_reddit_sentiment_fallback(players, time_window_hours, f"Enhanced analyzer failed: {e}")


async def _analyze_reddit_sentiment_fallback(
    players: list[str], time_window_hours: int = 48, error_reason: str = ""
) -> dict[str, Any]:
    """
    Fallback Reddit sentiment analysis using basic implementation.
    Used when enhanced analyzer is unavailable.
    """
    if not REDDIT_AVAILABLE:
        return {
            "error": "Reddit analysis not available. Install 'praw' and 'textblob' packages.",
            "fallback_reason": error_reason
        }

    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        return {
            "error": "Reddit API credentials not configured",
            "fallback_reason": error_reason
        }

    try:
        # Initialize Reddit client
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=f'fantasy-football-mcp:v1.0 by /u/{REDDIT_USERNAME or "unknown"}',
        )

        results = {
            "players": players,
            "analysis_type": "comparison" if len(players) > 1 else "single",
            "time_window_hours": time_window_hours,
            "player_data": {},
            "fallback_used": True,
            "fallback_reason": error_reason
        }

        subreddits = ["fantasyfootball", "DynastyFF", "Fantasy_Football", "nfl"]

        for player in players:
            player_sentiments = []
            total_posts = 0
            total_engagement = 0
            injury_mentions = 0
            relevant_comments = []

            # Search across subreddits
            for subreddit_name in subreddits:
                try:
                    subreddit = reddit.subreddit(subreddit_name)
                    posts = list(subreddit.search(player, time_filter="week", limit=5))

                    for post in posts:
                        total_posts += 1
                        total_engagement += post.score + post.num_comments

                        # Analyze sentiment
                        text = f"{post.title} {post.selftext[:500] if post.selftext else ''}"
                        blob = TextBlob(text)
                        sentiment = blob.sentiment.polarity
                        player_sentiments.append(sentiment)

                        # Check for injuries
                        injury_keywords = [
                            "injured",
                            "injury",
                            "out",
                            "doubtful",
                            "questionable",
                            "IR",
                        ]
                        if any(keyword.lower() in text.lower() for keyword in injury_keywords):
                            injury_mentions += 1

                        # Get top comments
                        if post.score > 10:
                            relevant_comments.append(
                                {
                                    "text": post.title[:100],
                                    "score": post.score,
                                    "sentiment": sentiment,
                                }
                            )
                except Exception:
                    continue

            # Calculate metrics
            avg_sentiment = (
                sum(player_sentiments) / len(player_sentiments) if player_sentiments else 0
            )

            # Determine consensus
            if avg_sentiment > 0.1:
                consensus = "START"
            elif avg_sentiment < -0.1:
                consensus = "SIT"
            else:
                consensus = "MIXED"

            # Calculate hype score (combination of sentiment and engagement)
            hype_score = ((avg_sentiment + 1) / 2) * min(total_engagement / 100, 1.0)

            results["player_data"][player] = {
                "sentiment_score": round(avg_sentiment, 3),
                "consensus": consensus,
                "posts_analyzed": total_posts,
                "total_engagement": total_engagement,
                "injury_mentions": injury_mentions,
                "hype_score": round(hype_score, 3),
                "top_comments": sorted(relevant_comments, key=lambda x: x["score"], reverse=True)[
                    :3
                ],
            }

        # Add comparison recommendation if multiple players
        if len(players) > 1:
            sorted_players = sorted(
                results["player_data"].items(),
                key=lambda x: x[1]["sentiment_score"] + x[1]["hype_score"],
                reverse=True,
            )

            results["recommendation"] = {
                "start": sorted_players[0][0],
                "sit": [p[0] for p in sorted_players[1:]],
                "confidence": min(
                    abs(
                        sorted_players[0][1]["sentiment_score"]
                        - sorted_players[-1][1]["sentiment_score"]
                    )
                    * 100,
                    100,
                ),
            }

        return results

    except Exception as e:
        return {"error": f"Reddit analysis failed: {str(e)}"}


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
                        "type": "string",
                        "description": "Optional team key if not the logged-in team",
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
            name="ff_get_optimal_lineup",
            description="Get AI-optimized lineup recommendations for a league",
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
                        "description": "Number of players to return (default: 20)",
                        "default": 20,
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


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a fantasy football tool."""
    try:
        debug_flag = arguments.get("debug") is True
        if debug_flag:
            # Lightweight initial debug envelope we can append to
            debug_msgs = [f"debug: call_tool entered for {name}"]
        if name == "ff_get_leagues":
            # Get all leagues
            leagues = await discover_leagues()

            if not leagues:
                result = {
                    "error": "No active NFL leagues found",
                    "suggestion": "Make sure your Yahoo token is valid and you have active leagues",
                }
            else:
                result = {
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

        elif name == "ff_get_league_info":
            # Get specific league info
            league_key = arguments.get("league_key")

            # First check cache
            leagues = await discover_leagues()
            if league_key in leagues:
                league = leagues[league_key]

                # Get user's team info
                team_info = await get_user_team_info(league_key)

                # Get additional details
                data = await yahoo_api_call(f"league/{league_key}")
                result = {
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
            else:
                result = {
                    "error": f"League {league_key} not found",
                    "available_leagues": list(leagues.keys()),
                }

        elif name == "ff_get_standings":
            # Get standings
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
                                        "wins": team_standings.get("outcome_totals", {}).get(
                                            "wins", 0
                                        ),
                                        "losses": team_standings.get("outcome_totals", {}).get(
                                            "losses", 0
                                        ),
                                        "ties": team_standings.get("outcome_totals", {}).get(
                                            "ties", 0
                                        ),
                                        "points_for": team_standings.get("points_for", 0),
                                        "points_against": team_standings.get("points_against", 0),
                                    }
                                )

            # Sort by rank
            standings.sort(key=lambda x: x["rank"])

            result = {"league_key": league_key, "standings": standings}

        elif name == "ff_get_roster":
            league_key = arguments.get("league_key")
            team_key = arguments.get("team_key")
            team_info = None

            if not team_key:
                team_info = await get_user_team_info(league_key)
                if team_info:
                    team_key = team_info.get("team_key")
                else:
                    result = {
                        "error": f"Could not find your team in league {league_key}",
                        "suggestion": "Provide team_key explicitly if multiple teams exist",
                    }
                    return [TextContent(type="text", text=json.dumps(result, indent=2))]

            data = await yahoo_api_call(f"team/{team_key}/roster")
            roster = parse_team_roster(data)

            if team_info is None or team_info.get("team_key") != team_key:
                team_info = await get_user_team_info(league_key)

            result = {
                "league_key": league_key,
                "team_key": team_key,
                "team_name": team_info.get("team_name") if team_info else None,
                "draft_position": team_info.get("draft_position") if team_info else None,
                "draft_grade": team_info.get("draft_grade") if team_info else None,
                "roster": roster,
            }

        elif name == "ff_get_matchup":
            # Get matchup
            league_key = arguments.get("league_key")
            week = arguments.get("week", None)

            # Get user's team key
            team_key = await get_user_team_key(league_key)

            if team_key:
                week_param = f";week={week}" if week else ""
                data = await yahoo_api_call(f"team/{team_key}/matchups{week_param}")

                result = {
                    "league_key": league_key,
                    "team_key": team_key,
                    "week": week or "current",
                    "message": "Matchup data retrieved",
                }
            else:
                result = {"error": f"Could not find your team in league {league_key}"}

        elif name == "ff_get_players":
            # Get available players
            league_key = arguments.get("league_key")
            position = arguments.get("position", "")
            count = arguments.get("count", 10)

            pos_filter = f";position={position}" if position else ""
            data = await yahoo_api_call(
                f"league/{league_key}/players;status=A{pos_filter};count={count}"
            )

            players = []
            league = data.get("fantasy_content", {}).get("league", [])

            for item in league:
                if isinstance(item, dict) and "players" in item:
                    players_data = item["players"]

                    for key in players_data:
                        if key != "count" and isinstance(players_data[key], dict):
                            if "player" in players_data[key]:
                                player_array = players_data[key]["player"]
                                if isinstance(player_array, list) and len(player_array) > 0:
                                    player_info = {}

                                    for p in player_array:
                                        if isinstance(p, dict):
                                            if "name" in p:
                                                player_info["name"] = p["name"]["full"]
                                            if "editorial_team_abbr" in p:
                                                player_info["team"] = p["editorial_team_abbr"]
                                            if "display_position" in p:
                                                player_info["position"] = p["display_position"]
                                            if "ownership" in p:
                                                player_info["owned_pct"] = p["ownership"].get(
                                                    "ownership_percentage", 0
                                                )

                                    if player_info:
                                        players.append(player_info)

            result = {
                "league_key": league_key,
                "position": position or "all",
                "count": len(players),
                "players": players[:count],
            }
        elif name == "ff_compare_teams":
            league_key = arguments.get("league_key")
            team_key_a = arguments.get("team_key_a")
            team_key_b = arguments.get("team_key_b")

            data_a = await yahoo_api_call(f"team/{team_key_a}/roster")
            data_b = await yahoo_api_call(f"team/{team_key_b}/roster")

            roster_a = parse_team_roster(data_a)
            roster_b = parse_team_roster(data_b)

            result = {
                "league_key": league_key,
                "team_a": {"team_key": team_key_a, "roster": roster_a},
                "team_b": {"team_key": team_key_b, "roster": roster_b},
            }

        elif name == "ff_get_optimal_lineup":
            # Get optimal lineup recommendations with Sleeper integration
            league_key = arguments.get("league_key")
            week = arguments.get("week", None)
            strategy = arguments.get("strategy", "balanced")

            # Get user's roster
            team_key = await get_user_team_key(league_key)

            if team_key:
                try:
                    roster_data = await yahoo_api_call(f"team/{team_key}/roster")
                    try:
                        from lineup_optimizer import lineup_optimizer
                    except ImportError as e:
                        result = {
                            "error": f"Lineup optimizer unavailable: {e}",
                            "suggestion": "Please check lineup_optimizer.py dependencies",
                            "league_key": league_key,
                            "team_key": team_key,
                        }
                    else:
                        players = await lineup_optimizer.parse_yahoo_roster(roster_data)
                        if not players:
                            result = {
                                "error": "Failed to parse Yahoo roster data",
                                "league_key": league_key,
                                "team_key": team_key,
                                "suggestion": "Check roster data format or try refreshing",
                            }
                        else:
                            players = await lineup_optimizer.enhance_with_external_data(players)
                            optimization = lineup_optimizer.optimize_lineup(players, strategy, week)
                            if optimization["status"] == "error":
                                result = {
                                    "status": "error",
                                    "error": "Lineup optimization failed",
                                    "league_key": league_key,
                                    "team_key": team_key,
                                    "errors": optimization.get("errors", []),
                                    "details": optimization.get("errors", []),
                                    "data_quality": optimization.get("data_quality", {}),
                                }
                            else:
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
                                        "yahoo_proj": (round(player.yahoo_projection, 1) if player.yahoo_projection else None),
                                        "sleeper_proj": (round(player.sleeper_projection, 1) if player.sleeper_projection else None),
                                        "trending": (f"{player.trending_score:,} adds" if player.trending_score > 0 else None),
                                        "floor": round(player.floor_projection, 1) if player.floor_projection else None,
                                        "ceiling": round(player.ceiling_projection, 1) if player.ceiling_projection else None,
                                    }
                                bench_formatted = []
                                for player in optimization["bench"][:5]:
                                    bench_formatted.append(
                                        {
                                            "name": player.name,
                                            "position": player.position,
                                            "opponent": player.opponent,
                                            "composite_score": round(player.composite_score, 1),
                                            "matchup_score": player.matchup_score,
                                            "tier": player.player_tier.upper() if player.player_tier else "UNKNOWN",
                                        }
                                    )
                                result = {
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
                                        "players_with_projections": optimization["data_quality"]["players_with_projections"],
                                        "players_with_matchup_data": optimization["data_quality"]["players_with_matchup_data"],
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
                except Exception as e:
                    result = {
                        "error": f"Unexpected error during lineup optimization: {str(e)}",
                        "league_key": league_key,
                        "team_key": team_key,
                        "suggestion": "Try again or check system logs for details",
                    }
            else:
                result = {"error": f"Could not find your team in league {league_key}"}

        elif name == "ff_refresh_token":
            # Refresh the Yahoo access token
            result = await refresh_yahoo_token()

        elif name == "ff_get_api_status":
            # Get API rate limit and cache status
            rate_status = rate_limiter.get_status()
            cache_stats = response_cache.get_stats()

            result = {"rate_limit": rate_status, "cache": cache_stats}

        elif name == "ff_clear_cache":
            # Clear cache
            pattern = arguments.get("pattern", None)
            await response_cache.clear(pattern)

            result = {
                "status": "success",
                "message": f"Cache cleared{f' for pattern: {pattern}' if pattern else ' completely'}",
            }

        elif name == "ff_get_draft_results":
            # Get draft results for all teams
            league_key = arguments.get("league_key")

            # Get all teams with draft info
            teams = await get_all_teams_info(league_key)

            if teams:
                result = {
                    "league_key": league_key,
                    "total_teams": len(teams),
                    "draft_results": teams,
                }
            else:
                result = {"error": f"Could not retrieve draft results for league {league_key}"}

        elif name == "ff_get_waiver_wire":
            # Get waiver wire players
            league_key = arguments.get("league_key")
            position = arguments.get("position", "all")
            sort = arguments.get("sort", "rank")
            count = arguments.get("count", 20)

            players = await get_waiver_wire_players(league_key, position, sort, count)

            if players:
                result = {
                    "league_key": league_key,
                    "position": position,
                    "sort": sort,
                    "total_players": len(players),
                    "players": players,
                }
            else:
                result = {
                    "league_key": league_key,
                    "message": "No available players found or error retrieving data",
                }

        elif name == "ff_get_draft_rankings":
            # Get pre-draft rankings
            league_key = arguments.get("league_key", None)
            position = arguments.get("position", "all")
            count = arguments.get("count", 50)

            players = await get_draft_rankings(league_key, position, count)

            if players:
                result = {"position": position, "total_players": len(players), "rankings": players}
            else:
                result = {"message": "Could not retrieve draft rankings"}

        elif name == "ff_get_draft_recommendation":
            # Get AI-powered draft recommendations
            if not DRAFT_AVAILABLE:
                result = {
                    "error": "Draft functionality not available. Please check module dependencies."
                }
            else:
                try:
                    league_key = arguments.get("league_key")
                    strategy = arguments.get("strategy", "balanced")
                    num_recommendations = arguments.get("num_recommendations", 10)
                    current_pick = arguments.get("current_pick")

                    # Create simplified draft recommendation
                    result = await get_draft_recommendation_simple(
                        league_key, strategy, num_recommendations, current_pick
                    )
                except Exception as e:
                    result = {
                        "error": f"Draft recommendation failed: {str(e)}",
                        "available_tools": ["ff_get_draft_rankings", "ff_get_players"],
                    }

        elif name == "ff_analyze_draft_state":
            # Analyze current draft state
            if not DRAFT_AVAILABLE:
                result = {
                    "error": "Draft functionality not available. Please check module dependencies."
                }
            else:
                try:
                    league_key = arguments.get("league_key")
                    strategy = arguments.get("strategy", "balanced")

                    # Create simplified draft state analysis
                    result = await analyze_draft_state_simple(league_key, strategy)
                except Exception as e:
                    result = {
                        "error": f"Draft analysis failed: {str(e)}",
                        "suggestion": "Try using ff_get_roster to check current team composition",
                    }

        elif name == "ff_analyze_reddit_sentiment":
            # Analyze Reddit sentiment for players
            players = arguments.get("players", [])
            time_window = arguments.get("time_window_hours", 48)

            if not players:
                result = {"error": "No players specified for sentiment analysis"}
            else:
                result = await analyze_reddit_sentiment(players, time_window)

        else:
            result = {"error": f"Unknown tool: {name}"}

        # Final defensive guard: never return raw '0' (observed upstream)
        if isinstance(result, str) and result.strip() == "0":
            result = {
                "status": "error",
                "message": "Internal legacy layer produced sentinel '0' string",
                "tool": name,
                "stage": "legacy.call_tool.guard",
            }
        if debug_flag:
            # Attach debug messages & echo minimal arguments (excluding secrets)
            safe_args = {k: v for k, v in arguments.items() if not k.lower().endswith("token")}
            result["_debug"] = {
                "messages": debug_msgs,
                "tool": name,
                "arguments": safe_args,
            }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        error_result = {"error": str(e), "tool": name, "arguments": arguments}
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
