"""Snapshot integration uses synthetic roster/settings and no provider network."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

import fantasy_football_multi_league
import fastmcp_server
from lineup_optimizer import Player, lineup_optimizer
from src.handlers import matchup_handlers, roster_handlers

CONTEXT = {
    "season": 2026,
    "current_week": 9,
    "scoring_format": "ppr",
    "scoring_format_source": "yahoo_settings",
    "canonical_scoring_basis": "ppr",
    "roster_slots": {"QB": 1},
    "warnings": [],
}


def snapshot(value=15):
    return {
        "source_kind": "yahoo_visible_projection_snapshot",
        "source_url": "https://football.fantasysports.yahoo.com/f1/1234/2",
        "season": 2026,
        "week": 9,
        "scoring_basis": "ppr",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "rows": [{"player_id": "1001", "projection": value}],
    }


def player():
    return Player(
        name="Synthetic Quarterback",
        team="BUF",
        position="QB",
        roster_position="QB",
        player_key="777.p.1001",
    )


async def passthrough(players, **kwargs):
    return players


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_roster_standard_uses_snapshot_without_external_fetch(valid):
    p = player()
    snap = snapshot(0)
    if not valid:
        snap["week"] = 8
    with (
        patch.object(
            roster_handlers,
            "get_user_team_info",
            AsyncMock(return_value={"team_key": "777.l.1234.t.2"}),
        ),
        patch.object(roster_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(roster_handlers, "parse_team_roster", return_value=[{"name": p.name}]),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=[p])),
        patch.object(lineup_optimizer, "enhance_with_external_data", AsyncMock()) as enhance,
        patch.object(matchup_handlers, "_get_lineup_context", AsyncMock(return_value=CONTEXT)),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {
                "league_key": "777.l.1234",
                "data_level": "standard",
                "yahoo_projection_snapshot": snap,
            }
        )
    audit = result["yahoo_projection_snapshot_audit"]
    assert audit["available"] is valid
    assert enhance.await_count == 0
    assert (
        p.yahoo_projection == 0 and p.projection_context.get("yahoo_projection_present") is not True
    )
    assert "yahoo_projection_snapshot_audit" in result
    if valid:
        assert audit["applied_values"][0]["raw_snapshot_value"] == 0
        assert result["all_players"][0]["projection_assessment"]["baseline_expected_points"] == 0
    else:
        assert audit["reason"] == "snapshot_period_or_scoring_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_lineup_snapshot_applied_before_enrichment_and_selection(valid):
    original = player()
    seen = []

    async def enhance(players, **kwargs):
        seen.append(players[0].yahoo_projection)
        assert (players[0].projection_context.get("yahoo_projection_present") is True) is valid
        assert players[0].raw == original.raw
        players[0].sleeper_projection = 20
        players[0].sleeper_projection_ppr = 20
        players[0].sleeper_projection_source = "sleeper_api"
        return players

    snap = snapshot(15)
    if not valid:
        snap["week"] = 8
    with (
        patch.object(
            matchup_handlers, "get_user_team_key", AsyncMock(return_value="777.l.1234.t.2")
        ),
        patch.object(matchup_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(matchup_handlers, "_get_lineup_context", AsyncMock(return_value=CONTEXT)),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=[original])),
        patch.object(lineup_optimizer, "enhance_with_external_data", enhance),
        patch(
            "src.services.weekly_projection_runtime.enrich_weekly_projection_inputs",
            side_effect=passthrough,
        ),
        patch.object(
            matchup_handlers,
            "get_decision_news_context",
            AsyncMock(return_value={"by_player": {}, "sources": [], "warnings": []}),
        ),
    ):
        result = await matchup_handlers.handle_ff_build_lineup(
            {
                "league_key": "777.l.1234",
                "yahoo_projection_snapshot": snap,
                "include_market_adjustments": False,
                "include_environment_adjustments": False,
            }
        )
    assert result["status"] == "success"
    assert seen == [15 if valid else 0]
    assert original.yahoo_projection == 0
    assert result["yahoo_projection_snapshot_audit"]["applied_count"] == (1 if valid else 0)
    assessment = result["optimal_lineup"]["QB"]["projection_assessment"]
    assert assessment["baseline_expected_points"] == (16.875 if valid else 20)
    if valid:
        assert assessment["source_provenance"]["yahoo"]["server_refetched"] is False


@pytest.mark.asyncio
async def test_fastmcp_forwards_snapshot_both_paths():
    call = AsyncMock(return_value={"status": "success"})
    snap = snapshot()
    with patch.object(fastmcp_server, "_call_legacy_tool", call):
        await fastmcp_server.ff_get_roster.fn(None, "777.l.1234", yahoo_projection_snapshot=snap)
        await fastmcp_server.ff_build_lineup.fn(None, "777.l.1234", yahoo_projection_snapshot=snap)
    assert all(c.kwargs["yahoo_projection_snapshot"] == snap for c in call.await_args_list)


@pytest.mark.asyncio
async def test_stdio_schemas_add_optional_snapshot_without_required_change():
    tools = await fantasy_football_multi_league.list_tools()
    for name in ("ff_get_roster", "ff_build_lineup"):
        tool = next(t for t in tools if t.name == name)
        assert "yahoo_projection_snapshot" in tool.inputSchema["properties"]
        assert tool.inputSchema["required"] == ["league_key"]


def test_absent_snapshot_preserves_existing_player_objects_and_audit():
    players = [player()]
    result, audit = matchup_handlers._apply_yahoo_snapshot(
        players,
        {},
        CONTEXT,
        league_key="777.l.1234",
        team_key="777.l.1234.t.2",
        season=2026,
        week=9,
    )
    assert result is players
    assert result[0] is players[0]
    assert audit["available"] is False
    assert audit["reason"] == "yahoo_forecast_not_provided_by_api_or_snapshot"
