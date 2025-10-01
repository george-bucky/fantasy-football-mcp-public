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


async def _get_primary_league_key() -> str:
    """Helper to get a valid league_key for testing."""
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

    return league_key


@pytest.mark.asyncio
async def test_ff_get_waiver_wire_basic_returns_available_players():
    """Test basic call: should return available players without enhancements."""
    league_key = await _get_primary_league_key()

    response = await call_tool(
        "ff_get_waiver_wire",
        {"league_key": league_key, "position": "all", "count": 5, "include_analysis": False},
    )
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert result["status"] == "success"
    assert "players" in result
    assert len(result["players"]) > 0
    assert result["total_players"] >= len(result["players"])

    # Basic should include name, position, team, owned_pct
    for player in result["players"]:
        assert "name" in player
        assert "position" in player
        assert "team" in player
        assert "owned_pct" in player
        assert "sleeper_id" not in player  # No external data


@pytest.mark.asyncio
async def test_ff_get_waiver_wire_full_includes_enhancements():
    """Test full mode: should include projections, external data, expert analysis."""
    league_key = await _get_primary_league_key()

    response = await call_tool(
        "ff_get_waiver_wire",
        {
            "league_key": league_key,
            "position": "all",
            "count": 10,
            "include_analysis": True,
            "include_projections": True,
            "include_external_data": True,
        },
    )
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert result["status"] == "success"
    assert "enhanced_players" in result
    assert len(result["enhanced_players"]) > 0

    # Full should have expert tiers, recommendations, Sleeper data
    has_enhancement = any(
        p.get("expert_tier") or p.get("sleeper_id") or p.get("trending_score")
        for p in result["enhanced_players"]
    )
    assert has_enhancement

    # Analysis context
    assert "analysis_context" in result
    # Note: analysis flag may vary based on implementation


@pytest.mark.asyncio
async def test_ff_get_waiver_wire_position_filter():
    """Test position filtering (e.g., QB only)."""
    league_key = await _get_primary_league_key()

    response = await call_tool(
        "ff_get_waiver_wire", {"league_key": league_key, "position": "QB", "count": 3}
    )
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert result["status"] == "success"
    assert "position" in result and result["position"] == "QB"
    assert all(p.get("position") == "QB" for p in result["players"])


@pytest.mark.asyncio
async def test_ff_get_waiver_wire_sort_options():
    """Test different sort options (rank, points, owned, trending)."""
    league_key = await _get_primary_league_key()

    for sort in ["rank", "owned", "trending"]:
        response = await call_tool(
            "ff_get_waiver_wire", {"league_key": league_key, "sort": sort, "count": 5}
        )
        result: Dict = json.loads(response[0].text)  # type: ignore

        assert result["status"] == "success"
        assert "sort" in result and result["sort"] == sort
        assert len(result["players"]) == 5


@pytest.mark.asyncio
async def test_ff_get_waiver_wire_handles_missing_league_key():
    """Test error handling for missing required league_key."""
    response = await call_tool("ff_get_waiver_wire", {"position": "all"})
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert "error" in result
    assert "league_key is required" in result["error"]


@pytest.mark.asyncio
async def test_ff_get_waiver_wire_count_parameter():
    """Test count limits the number of returned players."""
    league_key = await _get_primary_league_key()

    response = await call_tool("ff_get_waiver_wire", {"league_key": league_key, "count": 2})
    result: Dict = json.loads(response[0].text)  # type: ignore

    assert result["status"] == "success"
    assert len(result["players"]) == 2
    assert result["total_players"] >= 2


@pytest.mark.asyncio
async def test_ff_get_waiver_wire_via_call_tool_integration():
    """Test integration via call_tool with enhancements."""
    league_key = await _get_primary_league_key()

    response = await call_tool(
        "ff_get_waiver_wire",
        {"league_key": league_key, "include_expert_analysis": True, "count": 5},
    )

    payload: Dict = json.loads(response[0].text)  # type: ignore
    assert payload["status"] == "success"
    assert "enhanced_players" in payload
