from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

import fantasy_football_multi_league
import fastmcp_server
from lineup_optimizer import Player, lineup_optimizer
from src.handlers import matchup_handlers, roster_handlers
from src.services import empty_player_environment_context

LINEUP_CONTEXT = {
    "scoring_format": "half-ppr",
    "scoring_format_source": "yahoo_settings",
    "canonical_scoring_basis": "half_ppr",
    "season": 2026,
    "current_week": 5,
}

ENVIRONMENT_CONTEXT_KEYS = set(empty_player_environment_context("fixture"))


def _players(count: int = 7) -> list[Player]:
    return [
        Player(
            name=f"Player {index}",
            position="QB",
            team="BUF",
            roster_position="QB" if index == 0 else "BN",
            yahoo_projection=20 - index,
        )
        for index in range(count)
    ]


def _service_result(players: list[Player]) -> dict:
    return {
        "enabled": True,
        "season": 2026,
        "target_week": 5,
        "cutoff_week": 4,
        "canonical_scoring_basis": "half_ppr",
        "players": [
            {
                "enabled": True,
                "available": True,
                "applied": False,
                "opponent": "MIA",
                "home_away": "home",
                "kickoff": "2026-10-01T00:15:00+00:00",
                "schedule": {"status": "matched", "game_id": f"game-{index}"},
                "strength": {"status": "available"},
                "percentile": 60.0,
                "player_environment_context": {
                    "status": "partial",
                    "applied": False,
                    "current_environment": {
                        "weekday": "Thursday",
                        "kickoff_window": "night",
                        "venue_type": "outdoor",
                    },
                    "history": {"comparable_stat_rows_count": 3},
                    "warnings": ["Identity is unverified"],
                },
            }
            for index, _player in enumerate(players)
        ],
        "warnings": [],
        "attribution": "nflverse",
        "schedule_source": {"url": "schedule", "version": "v1"},
        "strength_source": {"url": "stats", "version": "v1"},
    }


def _optimization(players: list[Player]) -> dict:
    return {
        "status": "success",
        "starters": {"QB": players[0]},
        "bench": players[1:],
        "recommendations": [],
        "errors": [],
        "strategy_used": "balanced",
        "data_quality": {
            "total_players": len(players),
            "valid_players": len(players),
            "players_with_projections": len(players),
            "players_with_matchup_data": 0,
        },
        "strategy_summary": {"inputs_used": [], "opponent_aware": False},
        "player_evidence": {},
    }


def test_missing_nested_context_uses_canonical_empty_structure():
    players = _players(1)
    service_result = _service_result(players)
    service_result["players"][0].pop("player_environment_context")

    context = matchup_handlers._weekly_player_context(service_result, players)
    row = context["players"][0]

    assert set(row["player_environment_context"]) == ENVIRONMENT_CONTEXT_KEYS
    assert row["player_environment_context"]["status"] == "unavailable"
    assert row["identity"] == {"name": "Player 0", "team": "BUF", "position": "QB"}


def test_source_failure_context_uses_canonical_empty_structure():
    players = _players(1)

    context = matchup_handlers._unavailable_weekly_player_context(
        players,
        reason="Weekly player context unavailable: offline",
        season=2026,
        target_week=5,
        scoring_basis="half_ppr",
    )
    row = context["players"][0]

    assert set(row["player_environment_context"]) == ENVIRONMENT_CONTEXT_KEYS
    assert row["player_environment_context"]["status"] == "source_unavailable"
    assert row["identity"] == {"name": "Player 0", "team": "BUF", "position": "QB"}


@pytest.mark.asyncio
async def test_both_transports_expose_weekly_context_default_off():
    for function in (fastmcp_server.ff_get_roster.fn, fastmcp_server.ff_build_lineup.fn):
        assert inspect.signature(function).parameters["include_weekly_context"].default is False

    tools = await fantasy_football_multi_league.list_tools()
    for tool_name in ("ff_get_roster", "ff_build_lineup"):
        tool = next(tool for tool in tools if tool.name == tool_name)
        flag = tool.inputSchema["properties"]["include_weekly_context"]
        assert flag["type"] == "boolean"
        assert flag["default"] is False


@pytest.mark.asyncio
async def test_fastmcp_forwards_weekly_context_for_roster_and_lineup():
    call = AsyncMock(return_value={"status": "success"})
    with patch.object(fastmcp_server, "_call_legacy_tool", call):
        await fastmcp_server.ff_get_roster.fn(
            None, "461.l.1", data_level="basic", include_weekly_context=True
        )
        await fastmcp_server.ff_build_lineup.fn(None, "461.l.1", include_weekly_context=True)

    assert call.await_args_list[0].kwargs["include_weekly_context"] is True
    assert call.await_args_list[1].kwargs["include_weekly_context"] is True


@pytest.mark.asyncio
async def test_basic_roster_default_does_not_fetch_or_add_weekly_context():
    raw_roster = [{"name": "Player 0", "team": "BUF", "position": "QB"}]
    get_evidence = AsyncMock()
    with (
        patch.object(
            roster_handlers,
            "get_user_team_info",
            AsyncMock(return_value={"team_key": "t.1"}),
        ),
        patch.object(roster_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(roster_handlers, "parse_team_roster", return_value=raw_roster),
        patch.object(
            matchup_handlers.weekly_matchup_evidence_service,
            "get_evidence",
            get_evidence,
        ),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {"league_key": "461.l.1", "data_level": "basic"}
        )

    assert result["status"] == "success"
    assert "weekly_player_context" not in result
    get_evidence.assert_not_awaited()


@pytest.mark.asyncio
async def test_basic_roster_context_is_independent_and_covers_every_player():
    players = _players()
    raw_roster = [
        {"name": player.name, "team": player.team, "position": player.position}
        for player in players
    ]
    get_evidence = AsyncMock(return_value=_service_result(players))
    enhance = AsyncMock()
    with (
        patch.object(
            roster_handlers,
            "get_user_team_info",
            AsyncMock(return_value={"team_key": "t.1", "team_name": "Test Team"}),
        ),
        patch.object(roster_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(roster_handlers, "parse_team_roster", return_value=raw_roster),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(lineup_optimizer, "enhance_with_external_data", enhance),
        patch.object(
            matchup_handlers, "_get_lineup_context", AsyncMock(return_value=LINEUP_CONTEXT)
        ),
        patch.object(
            matchup_handlers, "_resolve_matchup_period", AsyncMock(return_value=(2026, 5, 4))
        ),
        patch.object(
            matchup_handlers.weekly_matchup_evidence_service,
            "get_evidence",
            get_evidence,
        ),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {
                "league_key": "461.l.1",
                "data_level": "basic",
                "include_weekly_context": True,
            }
        )

    assert result["status"] == "success"
    assert "all_players" not in result
    assert len(result["weekly_player_context"]["players"]) == len(players)
    assert result["weekly_player_context"]["players"][0]["identity"] == {
        "name": "Player 0",
        "team": "BUF",
        "position": "QB",
    }
    assert result["weekly_player_context"]["influence"] == "report_only"
    enhance.assert_not_awaited()
    assert get_evidence.await_args.kwargs["include_player_context"] is True


@pytest.mark.asyncio
async def test_lineup_context_failure_is_explicit_and_does_not_fail_lineup():
    players = _players(3)
    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value="t.1")),
        patch.object(matchup_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(
            lineup_optimizer, "enhance_with_external_data", AsyncMock(return_value=players)
        ),
        patch.object(
            lineup_optimizer,
            "optimize_lineup_smart",
            AsyncMock(return_value=_optimization(players)),
        ),
        patch.object(
            matchup_handlers, "_get_lineup_context", AsyncMock(return_value=LINEUP_CONTEXT)
        ),
        patch.object(
            matchup_handlers, "_resolve_matchup_period", AsyncMock(return_value=(2026, 5, 4))
        ),
        patch.object(
            matchup_handlers.weekly_matchup_evidence_service,
            "get_evidence",
            AsyncMock(side_effect=RuntimeError("offline")),
        ),
        patch.object(
            matchup_handlers,
            "get_decision_news_context",
            AsyncMock(return_value={"by_player": {}, "sources": [], "warnings": []}),
        ),
    ):
        result = await matchup_handlers.handle_ff_build_lineup(
            {"league_key": "461.l.1", "include_weekly_context": True}
        )

    context = result["weekly_player_context"]
    assert result["status"] == "success"
    assert context["available"] is False
    assert len(context["players"]) == len(players)
    assert "offline" in context["warnings"][0]
    assert "weekly_matchup_evidence" not in result["optimal_lineup"]["QB"]


@pytest.mark.asyncio
async def test_roster_context_failure_is_explicit_and_does_not_fail_roster():
    players = _players(3)
    raw_roster = [
        {"name": player.name, "team": player.team, "position": player.position}
        for player in players
    ]
    with (
        patch.object(
            roster_handlers,
            "get_user_team_info",
            AsyncMock(return_value={"team_key": "t.1"}),
        ),
        patch.object(roster_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(roster_handlers, "parse_team_roster", return_value=raw_roster),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(
            matchup_handlers, "_get_lineup_context", AsyncMock(return_value=LINEUP_CONTEXT)
        ),
        patch.object(
            matchup_handlers, "_resolve_matchup_period", AsyncMock(return_value=(2026, 5, 4))
        ),
        patch.object(
            matchup_handlers.weekly_matchup_evidence_service,
            "get_evidence",
            AsyncMock(side_effect=RuntimeError("offline")),
        ),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {
                "league_key": "461.l.1",
                "data_level": "basic",
                "include_weekly_context": True,
            }
        )

    context = result["weekly_player_context"]
    assert result["status"] == "success"
    assert context["available"] is False
    assert len(context["players"]) == len(players)
    assert "offline" in context["warnings"][0]


@pytest.mark.asyncio
async def test_lineup_context_only_is_report_only_and_covers_full_roster():
    players = _players()
    optimize = AsyncMock(return_value=_optimization(players))
    get_evidence = AsyncMock(return_value=_service_result(players))
    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value="t.1")),
        patch.object(matchup_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(
            lineup_optimizer, "enhance_with_external_data", AsyncMock(return_value=players)
        ),
        patch.object(lineup_optimizer, "optimize_lineup_smart", optimize),
        patch.object(
            matchup_handlers, "_get_lineup_context", AsyncMock(return_value=LINEUP_CONTEXT)
        ),
        patch.object(
            matchup_handlers, "_resolve_matchup_period", AsyncMock(return_value=(2026, 5, 4))
        ),
        patch.object(
            matchup_handlers.weekly_matchup_evidence_service,
            "get_evidence",
            get_evidence,
        ),
        patch.object(
            matchup_handlers,
            "get_decision_news_context",
            AsyncMock(return_value={"by_player": {}, "sources": [], "warnings": []}),
        ),
    ):
        result = await matchup_handlers.handle_ff_build_lineup(
            {"league_key": "461.l.1", "include_weekly_context": True}
        )

    assert len(result["bench"]) == 5
    assert len(result["weekly_player_context"]["players"]) == len(players)
    assert "weekly_matchup_evidence" not in result["optimal_lineup"]["QB"]
    assert "weekly_matchup_evidence" not in result["analysis"]
    assert optimize.await_args.kwargs["use_matchup_evidence"] is False
    assert get_evidence.await_args.kwargs["include_player_context"] is True
