"""Focused handler tests for opt-in rookie decision context."""

import sys
from unittest.mock import AsyncMock, patch

import pytest

from src.handlers import player_handlers


@pytest.mark.asyncio
async def test_waiver_opt_in_preserves_veteran_slots_and_orders_rookies():
    yahoo_players = [
        {"name": "Lower Rookie", "position": "WR"},
        {"name": "Veteran", "position": "WR"},
        {"name": "Better Rookie", "position": "WR"},
    ]
    ordered = [
        {
            "name": "Better Rookie",
            "position": "WR",
            "rookie_intelligence": {"status": "matched", "base_rank": 1},
        },
        {
            "name": "Veteran",
            "position": "WR",
            "rookie_intelligence": {"status": "quarantined"},
        },
        {
            "name": "Lower Rookie",
            "position": "WR",
            "rookie_intelligence": {"status": "matched", "base_rank": 20},
        },
    ]
    with (
        patch.object(
            player_handlers,
            "get_waiver_wire_players",
            AsyncMock(return_value=yahoo_players),
        ),
        patch.object(
            player_handlers,
            "apply_rookie_intelligence",
            return_value={
                "players": ordered,
                "by_player": {},
                "evidence": {
                    "enabled": True,
                    "matched_players": 2,
                    "warnings": [],
                    "opponent_aware": False,
                },
            },
        ) as apply_rookies,
    ):
        result = await player_handlers.handle_ff_get_waiver_wire(
            {
                "league_key": "league.test",
                "include_analysis": False,
                "include_projections": False,
                "include_external_data": False,
                "use_rookie_intelligence": True,
            }
        )

    assert [player["name"] for player in result["players"]] == [
        "Better Rookie",
        "Veteran",
        "Lower Rookie",
    ]
    assert result["decision_evidence"]["rookie_intelligence"]["matched_players"] == 2
    apply_rookies.assert_called_once()


@pytest.mark.asyncio
async def test_waiver_rookie_only_fails_closed_without_veterans():
    with (
        patch.object(
            player_handlers,
            "get_waiver_wire_players",
            AsyncMock(return_value=[{"name": "Veteran", "position": "WR"}]),
        ),
        patch.object(
            player_handlers,
            "apply_rookie_intelligence",
            side_effect=ValueError("bad reviewed artifact"),
        ),
    ):
        result = await player_handlers.handle_ff_get_waiver_wire(
            {
                "league_key": "league.test",
                "include_analysis": False,
                "include_projections": False,
                "include_external_data": False,
                "rookie_only": True,
            }
        )

    assert result["players"] == []
    assert result["total_players"] == 0
    assert result["decision_evidence"]["rookie_intelligence"]["enabled"] is False


@pytest.mark.asyncio
async def test_waiver_rookie_only_import_fallback_never_leaks_veterans():
    with (
        patch.object(
            player_handlers,
            "get_waiver_wire_players",
            AsyncMock(return_value=[{"name": "Veteran", "position": "WR"}]),
        ),
        patch.dict(sys.modules, {"lineup_optimizer": None}),
        patch.object(
            player_handlers,
            "apply_rookie_intelligence",
            return_value={
                "players": [],
                "evidence": {"enabled": True, "rookie_only": True, "warnings": []},
            },
        ) as apply_rookies,
    ):
        result = await player_handlers.handle_ff_get_waiver_wire(
            {"league_key": "league.test", "rookie_only": True}
        )

    assert result["players"] == []
    assert result["total_players"] == 0
    apply_rookies.assert_called_once()


@pytest.mark.asyncio
async def test_waiver_default_does_not_load_or_change_rookie_context():
    yahoo_players = [{"name": "Veteran", "position": "WR"}]
    with (
        patch.object(
            player_handlers,
            "get_waiver_wire_players",
            AsyncMock(return_value=yahoo_players),
        ),
        patch.object(player_handlers, "apply_rookie_intelligence") as apply_rookies,
    ):
        result = await player_handlers.handle_ff_get_waiver_wire(
            {
                "league_key": "league.test",
                "include_analysis": False,
                "include_projections": False,
                "include_external_data": False,
            }
        )

    assert result["players"] == yahoo_players
    assert "decision_evidence" not in result
    apply_rookies.assert_not_called()
