import asyncio
import json
import os
from typing import Dict, Tuple

import pytest
from dotenv import load_dotenv

import enhanced_mcp_tools
from fantasy_football_multi_league import (
    call_tool,
    discover_leagues,
    get_user_team_info,
    parse_team_roster,
    yahoo_api_call,
)
from lineup_optimizer import LineupOptimizer


load_dotenv(".env")


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Set RUN_LIVE_TESTS=1 to execute live Yahoo API integration tests.",
)

async def _get_primary_league_and_team() -> Tuple[str, str]:
    leagues = await discover_leagues()
    if not leagues:
        raise AssertionError("No leagues available for the authenticated Yahoo account")

    league_key = next(iter(leagues))
    team_info = await get_user_team_info(league_key)
    if not team_info or not team_info.get("team_key"):
        raise AssertionError(f"Unable to resolve team for league {league_key}")

    return league_key, team_info["team_key"]


@pytest.mark.asyncio
async def test_parse_team_roster_populates_team_field():
    league_key, team_key = await _get_primary_league_and_team()

    raw_roster = await yahoo_api_call(f"team/{team_key}/roster", use_cache=False)
    simplified = parse_team_roster(raw_roster)

    assert simplified, "Roster should not be empty"
    for entry in simplified:
        assert entry.get("name"), "Every roster entry must include a player name"
        assert entry.get("position"), "Every roster entry must include a position"
        assert entry.get("team"), f"Missing team for player {entry.get('name')}"


@pytest.mark.asyncio
async def test_parse_yahoo_roster_accepts_simplified_payload():
    league_key, _ = await _get_primary_league_and_team()
    roster_response = await call_tool("ff_get_roster", {"league_key": league_key})
    roster_payload: Dict = json.loads(roster_response[0].text)

    optimizer = LineupOptimizer()
    players = await optimizer.parse_yahoo_roster(roster_payload)

    assert players, "Parser should yield player objects from simplified roster data"
    assert all(player.team for player in players)


@pytest.mark.asyncio
async def test_ff_get_roster_with_projections_returns_live_data():
    league_key, team_key = await _get_primary_league_and_team()

    result = await enhanced_mcp_tools.ff_get_roster_with_projections(
        None, league_key, team_key
    )

    assert result["status"] == "success"
    assert result["total_players"] > 0
    assert result["team_info"].get("team_key") == team_key
    assert result["team_info"].get("team_name")

    for position_group in result["players_by_position"].values():
        for player in position_group:
            assert player["name"]
            assert player["team"], f"Player {player['name']} missing team"
