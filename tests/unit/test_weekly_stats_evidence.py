"""Weekly source evidence must survive the optimizer and each MCP response."""

from dataclasses import asdict
from unittest.mock import AsyncMock, patch

import pytest

from lineup_optimizer import LineupOptimizer, Player
from src.handlers import player_handlers, roster_handlers
from src.services.player_enhancement import (
    RecentPerformance,
    calculate_recent_avg,
    serialize_weekly_evidence,
)


def _player():
    projection = {
        "player_id": "8161",
        "season": 2026,
        "week": 9,
        "opponent": "DET",
        "company": "rotowire",
        "source_url": "https://api.sleeper.app/projections/nfl/2026/9?season_type=regular",
        "pts": 17.44,
        "pts_ppr": 17.44,
        "pass_yd": 221.09,
        "projection_source": "sleeper_api",
    }
    recent = RecentPerformance(
        weeks_analyzed=2,
        avg_points=20.83,
        total_points=41.66,
        weeks_data=[
            {"week": 8, "points": 15.64, "stats": {"pass_yd": 211, "rush_yd": 2}},
            {"week": 7, "points": 26.02, "stats": {"pass_yd": 208, "rush_yd": 37}},
        ],
        trend="declining",
    )
    return Player(
        name="Malik Willis",
        position="QB",
        team="MIA",
        opponent="DET",
        sleeper_projection=17.44,
        sleeper_projection_source="sleeper_api",
        recent_performance_data=recent,
        raw={"weekly_projection": projection},
    )


def test_weekly_evidence_exposes_source_period_and_raw_actuals():
    player = _player()
    evidence = serialize_weekly_evidence(player, include_projections=True, include_recent=True)
    assert evidence["projection"]["provider_data"]["company"] == "rotowire"
    assert evidence["projection"]["provider_data"]["week"] == 9
    assert evidence["projection"]["provider_data"]["opponent"] == "DET"
    assert evidence["recent_performance"]["data"] == asdict(player.recent_performance_data)
    assert "custom Yahoo scoring is not applied" in evidence["scoring_scope"]


def test_weekly_evidence_missing_and_disabled_are_explicit():
    player = _player()
    player.sleeper_projection_source = "fallback_ranking"
    player.recent_performance_data = None
    evidence = serialize_weekly_evidence(player, include_projections=True, include_recent=True)
    assert evidence["projection"]["status"] == "unavailable"
    assert evidence["projection"]["provider_data"] is None
    assert evidence["recent_performance"]["status"] == "unavailable"
    disabled = serialize_weekly_evidence(_player(), include_projections=False, include_recent=False)
    assert disabled["projection"]["status"] == "not_requested"
    assert disabled["projection"]["provider_data"] is None
    assert disabled["recent_performance"]["data"] is None


def test_recent_average_includes_real_zero_and_negative_games():
    assert calculate_recent_avg([{"pts_ppr": 10}, {"pts_ppr": 0}, {"pts_ppr": -4}, {}]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_error", [False, True])
async def test_failed_new_week_refresh_cannot_reuse_previous_projection(provider_error):
    player = _player()
    player.raw["weekly_projection"]["week"] = 8
    player.sleeper_projection_ppr = 17.44
    player.sleeper_projection_half_ppr = 17.44
    projections = AsyncMock(side_effect=TimeoutError() if provider_error else None, return_value={})
    with (
        patch("sleeper_api.get_current_season", AsyncMock(return_value=2026)),
        patch("sleeper_api.get_current_week", AsyncMock(return_value=9)),
        patch("sleeper_api.sleeper_client.get_all_players", AsyncMock(return_value={})),
        patch("sleeper_api.sleeper_client.map_yahoo_to_sleeper", AsyncMock(return_value="8161")),
        patch("sleeper_api.sleeper_client.get_projections", projections),
        patch("sleeper_api.sleeper_client.get_expert_advice", AsyncMock(return_value={})),
        patch("sleeper_api.sleeper_client.get_trending_players", AsyncMock(return_value=[])),
        patch("sleeper_api.sleeper_client.get_player_stats", AsyncMock(return_value={})),
    ):
        refreshed = (await LineupOptimizer().enhance_with_external_data([player], week=9))[0]
    evidence = serialize_weekly_evidence(refreshed, include_projections=True, include_recent=True)
    assert evidence["projection"]["status"] == "unavailable"
    assert evidence["projection"]["provider_data"] is None
    assert refreshed.sleeper_projection == 0
    assert refreshed.sleeper_projection_ppr == 0
    assert refreshed.sleeper_projection_half_ppr == 0
    assert evidence["recent_performance"]["status"] == "unavailable"
    assert player.raw["weekly_projection"]["week"] == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["roster", "players", "waiver"])
async def test_all_player_handlers_return_weekly_evidence(tool):
    player = _player()
    basic = [{"name": player.name, "position": "QB", "team": "MIA"}]
    yahoo_data = {
        "fantasy_content": {
            "league": [
                {
                    "players": {
                        "0": {
                            "player": [
                                [
                                    {"name": {"full": player.name}},
                                    {"editorial_team_abbr": "MIA"},
                                    {"display_position": "QB"},
                                ]
                            ]
                        }
                    }
                }
            ]
        }
    }
    with (
        patch(
            "lineup_optimizer.lineup_optimizer.parse_yahoo_roster", AsyncMock(return_value=[player])
        ),
        patch(
            "lineup_optimizer.lineup_optimizer.enhance_with_external_data",
            AsyncMock(return_value=[player]),
        ),
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": "t.1"})
        ),
        patch.object(roster_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(roster_handlers, "parse_team_roster", return_value=basic),
        patch.object(player_handlers, "yahoo_api_call", AsyncMock(return_value=yahoo_data)),
        patch.object(player_handlers, "get_waiver_wire_players", AsyncMock(return_value=basic)),
        patch("sleeper_api.get_trending_adds", AsyncMock(return_value=[])),
    ):
        arguments = {"league_key": "470.l.1", "week": 9, "include_analysis": False}
        if tool == "roster":
            result = await roster_handlers.handle_ff_get_roster(
                {**arguments, "data_level": "enhanced"}
            )
            rows = result["all_players"]
        elif tool == "players":
            result = await player_handlers.handle_ff_get_players(arguments)
            rows = result["enhanced_players"]
        else:
            result = await player_handlers.handle_ff_get_waiver_wire(arguments)
            rows = result["enhanced_players"]
    evidence = rows[0]["weekly_evidence"]
    assert evidence["projection"]["provider_data"]["pts"] == 17.44
    assert evidence["recent_performance"]["data"]["weeks_analyzed"] == 2
    assert evidence["recent_performance"]["data"]["weeks_data"][0]["stats"]["rush_yd"] == 2


@pytest.mark.parametrize("mismatch", ["identity", "week", "season", "nonfinite", "malformed"])
def test_weekly_projection_evidence_rejects_mismatched_or_invalid_snapshot(mismatch):
    player = _player()
    player.sleeper_id = "8161"
    player.projection_context = {"season": 2026, "week": 9}
    if mismatch == "identity":
        player.raw["weekly_projection"]["player_id"] = "other"
    elif mismatch in {"week", "season"}:
        player.raw["weekly_projection"][mismatch] -= 1
    elif mismatch == "nonfinite":
        player.raw["weekly_projection"]["pts"] = float("nan")
        player.raw["weekly_projection"]["pts_ppr"] = float("inf")
    else:
        player.raw["weekly_projection"] = "invalid"
    evidence = serialize_weekly_evidence(player, include_projections=True, include_recent=False)
    assert evidence["projection"]["status"] == "unavailable"
    assert evidence["projection"]["provider_data"] is None


def test_weekly_evidence_is_defensive_finite_and_omits_credential_shaped_fields():
    import json

    player = _player()
    player.raw["weekly_projection"].update(
        api_key="synthetic-sensitive",
        extra={"access_token": "synthetic-token", "value": 2},
        invalid=float("nan"),
    )
    evidence = serialize_weekly_evidence(player, include_projections=True, include_recent=True)
    encoded = json.dumps(evidence, allow_nan=False)
    assert "synthetic-sensitive" not in encoded
    assert "synthetic-token" not in encoded
    assert evidence["projection"]["provider_data"]["invalid"] is None
    evidence["projection"]["provider_data"]["extra"]["value"] = 99
    evidence["recent_performance"]["data"]["weeks_data"][0]["stats"]["pass_yd"] = 1
    assert player.raw["weekly_projection"]["extra"]["value"] == 2
    assert player.recent_performance_data.weeks_data[0]["stats"]["pass_yd"] == 211


def test_unexpected_recent_data_type_is_unavailable_not_a_serialization_failure():
    from types import SimpleNamespace

    player = _player()
    player.recent_performance_data = SimpleNamespace(avg_points=20)
    evidence = serialize_weekly_evidence(player, include_projections=False, include_recent=True)
    assert evidence["recent_performance"]["status"] == "unavailable"
    assert evidence["recent_performance"]["data"] is None


@pytest.mark.asyncio
async def test_failed_player_mapping_cannot_reuse_previous_actuals_or_projection():
    player = _player()
    player.sleeper_id = "8161"
    with (
        patch("sleeper_api.get_current_season", AsyncMock(return_value=2026)),
        patch("sleeper_api.get_current_week", AsyncMock(return_value=9)),
        patch("sleeper_api.sleeper_client.get_all_players", AsyncMock(return_value={})),
        patch(
            "sleeper_api.sleeper_client.map_yahoo_to_sleeper", AsyncMock(side_effect=TimeoutError())
        ),
    ):
        refreshed = (await LineupOptimizer().enhance_with_external_data([player], week=9))[0]
    evidence = serialize_weekly_evidence(refreshed, include_projections=True, include_recent=True)
    assert evidence["projection"]["status"] == "unavailable"
    assert evidence["recent_performance"]["status"] == "unavailable"
    assert player.recent_performance_data is not None


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf")])
def test_invalid_recent_summary_is_unavailable(invalid):
    player = _player()
    player.recent_performance_data.avg_points = invalid
    evidence = serialize_weekly_evidence(player, include_projections=False, include_recent=True)
    assert evidence["recent_performance"]["status"] == "unavailable"
    assert evidence["recent_performance"]["data"] is None
