import asyncio
import json
import os
from typing import Dict, Tuple

import pytest
from dotenv import load_dotenv

from fantasy_football_multi_league import call_tool

load_dotenv(".env")

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Set RUN_LIVE_TESTS=1 to execute live Yahoo API integration tests.",
)


async def _get_primary_league_and_team() -> Tuple[str, str]:
    """Helper to get a valid league_key and team_key for testing."""
    leagues_response = await call_tool("ff_get_leagues", {})
    leagues_payload: Dict = json.loads(leagues_response[0].text)  # type: ignore
    if leagues_payload.get("error"):
        raise AssertionError(f"No leagues available: {leagues_payload['error']}")

    leagues_list = leagues_payload.get("leagues", [])
    if not leagues_list:
        raise AssertionError("No leagues found")
    league_info = leagues_list[0]
    league_key = league_info.get("key", "")
    if not league_key:
        raise AssertionError("No league_key found")

    team_info_response = await call_tool("ff_get_league_info", {"league_key": league_key})
    team_info_payload: Dict = json.loads(team_info_response[0].text)  # type: ignore
    team_key = team_info_payload.get("your_team", {}).get("key")
    if not team_key:
        raise AssertionError(f"Unable to resolve team_key for league {league_key}")

    return league_key, team_key


@pytest.mark.asyncio
async def test_ff_get_roster_basic_returns_roster_data():
    """Test basic data_level: should return roster without projections or external data."""
    league_key, team_key = await _get_primary_league_and_team()

    response = await call_tool(
        "ff_get_roster", {"league_key": league_key, "team_key": team_key, "data_level": "basic"}
    )
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert result["status"] == "success"
    assert "roster" in result
    assert len(result["roster"]) > 0
    assert result["team_key"] == team_key
    assert "team_name" in result

    # Basic should not include projections or external fields
    for player in result["roster"]:
        assert "name" in player
        assert "position" in player
        assert "team" in player
        assert "yahoo_projection" not in player
        assert "sleeper_projection" not in player
        assert "matchup_score" not in player


@pytest.mark.asyncio
async def test_ff_get_roster_standard_includes_projections():
    """Test standard data_level: should include projections but no external data."""
    league_key, team_key = await _get_primary_league_and_team()

    response = await call_tool(
        "ff_get_roster", {"league_key": league_key, "team_key": team_key, "data_level": "standard"}
    )
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert result["status"] == "success"
    assert "players_by_position" in result
    assert "all_players" in result
    assert len(result["all_players"]) > 0

    # Standard should include projections
    has_projection = any(
        p.get("yahoo_projection") is not None or p.get("sleeper_projection") is not None
        for p in result["all_players"]
    )
    assert has_projection

    # But no external data like sleeper_id or matchup
    for player in result["all_players"]:
        assert "sleeper_id" not in player or player["sleeper_id"] is None
        assert "matchup_score" not in player or player["matchup_score"] is None


@pytest.mark.asyncio
async def test_ff_get_roster_full_includes_external_data_and_analysis():
    """Test full data_level: should include everything - projections, external data, analysis."""
    league_key, team_key = await _get_primary_league_and_team()

    response = await call_tool(
        "ff_get_roster", {"league_key": league_key, "team_key": team_key, "data_level": "full"}
    )
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert result["status"] == "success"
    assert "total_players" in result
    assert result["total_players"] > 0
    assert "analysis_context" in result
    assert "includes" in result["analysis_context"]

    # Full should have external data
    has_external = any(
        p.get("sleeper_id") or p.get("matchup_score") or p.get("trending_score")
        for p in result["all_players"]
    )
    assert has_external

    # And analysis if enabled
    if result["analysis_context"]["includes"]["analysis"]:
        assert "overall_analysis" in result
        assert "roster_analysis" in result["all_players"][0]


@pytest.mark.asyncio
async def test_ff_get_roster_handles_missing_league_key():
    """Test error handling for missing required league_key."""
    response = await call_tool("ff_get_roster", {"data_level": "basic"})
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert "error" in result
    assert "Could not find your team in league None" in result["error"]


@pytest.mark.asyncio
async def test_ff_get_roster_returns_team_info_when_team_key_provided():
    """Test that team_key is respected and team info is included."""
    league_key, team_key = await _get_primary_league_and_team()

    response = await call_tool(
        "ff_get_roster",
        {"league_key": league_key, "team_key": team_key, "data_level": "basic"},  # Explicit team
    )
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert result["status"] == "success"
    assert result["team_key"] == team_key
    assert "draft_position" in result or "draft_grade" in result  # Optional fields


@pytest.mark.asyncio
async def test_ff_get_roster_week_parameter():
    """Test week parameter for future/historical projections."""
    league_key, team_key = await _get_primary_league_and_team()

    # Test with specific week (use current +1 if possible)
    current_week = 1  # Placeholder; in real test, fetch from league info
    response = await call_tool(
        "ff_get_roster",
        {
            "league_key": league_key,
            "team_key": team_key,
            "week": current_week + 1,
            "data_level": "standard",
        },
    )
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert result["status"] == "success"
    assert "analysis_context" in result
    assert result["analysis_context"]["week"] == current_week + 1


@pytest.mark.asyncio
async def test_ff_get_roster_via_call_tool():
    """Test calling through the legacy call_tool interface."""
    league_key, team_key = await _get_primary_league_and_team()

    response = await call_tool(
        "ff_get_roster", {"league_key": league_key, "team_key": team_key, "data_level": "basic"}
    )

    payload: Dict = json.loads(response[0].text)  # type: ignore
    assert payload["status"] == "success"
    assert "roster" in payload
