from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

import fastmcp_server
import fantasy_football_multi_league
from lineup_optimizer import LineupOptimizer, Player, lineup_optimizer as shared_optimizer
from src.handlers import matchup_handlers
from src.services.rookie_intelligence import rookie_identity_key


def _evidence(percentile, *, available=True, schedule="matched"):
    return {
        "enabled": True,
        "available": available,
        "applied": False,
        "unavailable_reason": None if available else "source_unavailable",
        "percentile": percentile,
        "tie_break_audit": [],
        "schedule": {"status": schedule},
        "strength": {"status": "available" if available else "source_unavailable"},
    }


def _quarterbacks():
    veteran = Player(
        name="Veteran QB",
        position="QB",
        team="BUF",
        roster_position="QB",
        yahoo_projection=20.04,
    )
    challenger = Player(
        name="Challenger QB",
        position="QB",
        team="NYJ",
        roster_position="BN",
        yahoo_projection=20.0,
    )
    return veteran, challenger


def test_schedule_evidence_never_mutates_existing_bye_score_inputs():
    existing_bye = Player(
        name="Existing Bye",
        position="QB",
        team="BUF",
        on_bye=True,
        performance_flags=["ON_BYE"],
    )
    schedule_bye = Player(name="Schedule Bye", position="QB", team="NYJ")
    matched = {**_evidence(50, available=False), "opponent": "MIA"}
    bye = {**_evidence(None, available=False, schedule="bye"), "opponent": None}

    matchup_handlers._apply_weekly_matchup_evidence(
        [existing_bye, schedule_bye], [matched, bye]
    )

    assert existing_bye.on_bye is True
    assert "ON_BYE" in existing_bye.performance_flags
    assert schedule_bye.on_bye is False
    assert "ON_BYE" not in schedule_bye.performance_flags
    assert schedule_bye.opponent == "BYE"


@pytest.mark.asyncio
async def test_matchup_only_breaks_positive_comparable_rounded_tie_at_threshold():
    veteran, challenger = _quarterbacks()
    veteran.weekly_matchup_evidence = _evidence(50.0)
    challenger.weekly_matchup_evidence = _evidence(62.5)

    result = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger], use_matchup_evidence=True
    )

    assert result["starters"]["QB"].name == "Challenger QB"
    summary = result["strategy_summary"]["weekly_matchup_evidence"]
    assert summary["applied"] is True
    assert summary["numeric_scores_changed"] is False
    assert summary["tie_break_audit"][0]["percentile_gap"] == 12.5
    assert result["strategy_summary"]["opponent_aware"] is True


@pytest.mark.asyncio
async def test_matchup_gap_below_threshold_and_schedule_only_never_influence():
    veteran, challenger = _quarterbacks()
    veteran.weekly_matchup_evidence = _evidence(50.0)
    challenger.weekly_matchup_evidence = _evidence(62.499)
    below = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger], use_matchup_evidence=True
    )

    challenger.weekly_matchup_evidence = _evidence(
        100.0, available=False, schedule="matched"
    )
    schedule_only = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger], use_matchup_evidence=True
    )

    assert below["starters"]["QB"].name == "Veteran QB"
    assert below["strategy_summary"]["opponent_aware"] is False
    assert schedule_only["starters"]["QB"].name == "Veteran QB"
    assert schedule_only["strategy_summary"]["opponent_aware"] is False


@pytest.mark.asyncio
async def test_threshold_compares_winner_to_runner_up_not_the_weakest_option():
    veteran, challenger = _quarterbacks()
    third = Player(
        name="Third QB",
        position="QB",
        team="MIA",
        roster_position="BN",
        yahoo_projection=20.0,
    )
    veteran.weekly_matchup_evidence = _evidence(65.0)
    challenger.weekly_matchup_evidence = _evidence(70.0)
    third.weekly_matchup_evidence = _evidence(20.0)

    result = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger, third], use_matchup_evidence=True
    )

    assert result["starters"]["QB"].name == "Veteran QB"
    assert result["strategy_summary"]["opponent_aware"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("risk", ["health", "bye", "news"])
async def test_health_bye_and_news_risk_win_over_matchup(risk):
    veteran, challenger = _quarterbacks()
    veteran.weekly_matchup_evidence = _evidence(25.0)
    challenger.weekly_matchup_evidence = _evidence(100.0)
    news = {}
    if risk == "health":
        challenger.status = "O"
    elif risk == "bye":
        challenger.on_bye = True
    else:
        news = {
            challenger.name: {
                "espn": [
                    {
                        "headline": "Challenger ruled out",
                        "summary": "Will not play",
                        "source": "ESPN",
                    }
                ],
                "rotowire": [],
            }
        }

    result = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger], decision_news=news, use_matchup_evidence=True
    )

    assert result["starters"]["QB"].name == "Veteran QB"
    assert result["strategy_summary"]["opponent_aware"] is False


@pytest.mark.asyncio
async def test_started_game_and_incomparable_or_zero_scores_never_use_matchup():
    veteran, challenger = _quarterbacks()
    veteran.weekly_matchup_evidence = _evidence(10.0)
    challenger.weekly_matchup_evidence = _evidence(100.0, available=False)
    started = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger], use_matchup_evidence=True
    )

    challenger.yahoo_projection = 0
    challenger.recent_performance_data = type(
        "Recent", (), {"weeks_data": [{"points": 20.0}]}
    )()
    incomparable = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger], use_matchup_evidence=True
    )

    veteran.yahoo_projection = 0
    challenger.recent_performance_data = None
    zero = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger], use_matchup_evidence=True
    )

    assert started["starters"]["QB"].name == "Veteran QB"
    assert incomparable["strategy_summary"]["opponent_aware"] is False
    assert zero["strategy_summary"]["opponent_aware"] is False


@pytest.mark.asyncio
async def test_matchup_precedes_rookie_outlook_and_rookie_remains_final_tiebreak():
    veteran, challenger = _quarterbacks()
    veteran.weekly_matchup_evidence = _evidence(70.0)
    challenger.weekly_matchup_evidence = _evidence(50.0)
    rookie = {
        rookie_identity_key(challenger.name, challenger.position): {
            "status": "matched",
            "base_rank": 1,
        }
    }
    matchup = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger],
        rookie_intelligence=rookie,
        use_matchup_evidence=True,
    )

    veteran.weekly_matchup_evidence = _evidence(60.0)
    challenger.weekly_matchup_evidence = _evidence(55.0)
    rookie_only = await LineupOptimizer().optimize_lineup_smart(
        [veteran, challenger],
        rookie_intelligence=rookie,
        use_matchup_evidence=True,
    )

    assert matchup["starters"]["QB"].name == "Veteran QB"
    assert matchup["strategy_summary"]["weekly_matchup_evidence"]["applied"] is True
    assert matchup["strategy_summary"]["rookie_intelligence"]["tiebreaks"] == []
    assert rookie_only["starters"]["QB"].name == "Challenger QB"
    assert rookie_only["strategy_summary"]["weekly_matchup_evidence"]["applied"] is False
    assert len(rookie_only["strategy_summary"]["rookie_intelligence"]["tiebreaks"]) == 1


@pytest.mark.asyncio
async def test_sleeper_week_fallback_requires_exact_yahoo_season():
    with patch("sleeper_api.sleeper_client.get_nfl_state", AsyncMock(return_value={"season": 2025, "week": 5})):
        with pytest.raises(Exception, match="does not match"):
            await matchup_handlers._resolve_matchup_period(
                season=2026, requested_week=None, yahoo_current_week=None
            )

    with patch("sleeper_api.sleeper_client.get_nfl_state", AsyncMock(return_value={"season": 2026, "week": 5})):
        assert await matchup_handlers._resolve_matchup_period(
            season=2026, requested_week=7, yahoo_current_week=None
        ) == (2026, 7, 4)


@pytest.mark.asyncio
async def test_opt_out_preserves_output_and_does_not_call_matchup_service():
    starter, bench = _quarterbacks()
    optimizer = shared_optimizer
    optimization = {
        "status": "success",
        "starters": {"QB": starter},
        "bench": [bench],
        "recommendations": [],
        "errors": [],
        "strategy_used": "balanced",
        "data_quality": {
            "total_players": 2,
            "valid_players": 2,
            "players_with_projections": 2,
            "players_with_matchup_data": 0,
        },
        "strategy_summary": {"inputs_used": []},
        "player_evidence": {},
    }
    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value="t.1")),
        patch.object(matchup_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(optimizer, "parse_yahoo_roster", AsyncMock(return_value=[starter, bench])),
        patch.object(optimizer, "enhance_with_external_data", AsyncMock(return_value=[starter, bench])),
        patch.object(optimizer, "optimize_lineup_smart", AsyncMock(return_value=optimization)),
        patch.object(matchup_handlers, "get_decision_news_context", AsyncMock(return_value={"by_player": {}, "sources": [], "warnings": []})),
        patch.object(matchup_handlers.weekly_matchup_evidence_service, "get_evidence", AsyncMock()) as get_evidence,
    ):
        result = await matchup_handlers.handle_ff_build_lineup({"league_key": "461.l.1"})

    assert "weekly_matchup_evidence" not in result["optimal_lineup"]["QB"]
    assert "weekly_matchup_evidence" not in result["bench"][0]
    assert "weekly_matchup_evidence" not in result["analysis"]
    get_evidence.assert_not_awaited()


@pytest.mark.asyncio
async def test_matchup_failure_is_reported_but_normal_lineup_still_returns():
    starter, bench = _quarterbacks()
    optimizer = shared_optimizer
    async def optimize(players, *args, **kwargs):
        return {
            "status": "success",
            "starters": {"QB": players[0]},
            "bench": [players[1]],
            "recommendations": [],
            "errors": [],
            "strategy_used": "balanced",
            "data_quality": {
                "total_players": 2,
                "valid_players": 2,
                "players_with_projections": 2,
                "players_with_matchup_data": 0,
            },
            "strategy_summary": {"inputs_used": [], "opponent_aware": False},
            "player_evidence": {},
        }
    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value="t.1")),
        patch.object(matchup_handlers, "yahoo_api_call", AsyncMock(return_value={"season": 2026, "current_week": 5})),
        patch.object(optimizer, "parse_yahoo_roster", AsyncMock(return_value=[starter, bench])),
        patch.object(optimizer, "enhance_with_external_data", AsyncMock(return_value=[starter, bench])),
        patch.object(optimizer, "optimize_lineup_smart", optimize),
        patch.object(matchup_handlers, "get_decision_news_context", AsyncMock(return_value={"by_player": {}, "sources": [], "warnings": []})),
        patch.object(matchup_handlers.weekly_matchup_evidence_service, "get_evidence", AsyncMock(side_effect=RuntimeError("offline"))),
    ):
        result = await matchup_handlers.handle_ff_build_lineup(
            {"league_key": "461.l.1", "use_matchup_evidence": True}
        )

    assert result["status"] == "success"
    assert result["analysis"]["strategy_evidence"]["opponent_aware"] is False
    assert "offline" in result["warnings"][0]
    assert result["optimal_lineup"]["QB"]["weekly_matchup_evidence"]["available"] is False


@pytest.mark.asyncio
async def test_both_transports_expose_default_off_flag():
    assert inspect.signature(fastmcp_server.ff_build_lineup.fn).parameters[
        "use_matchup_evidence"
    ].default is False
    tools = await fantasy_football_multi_league.list_tools()
    tool = next(tool for tool in tools if tool.name == "ff_build_lineup")
    flag = tool.inputSchema["properties"]["use_matchup_evidence"]
    assert flag["type"] == "boolean"
    assert flag["default"] is False
