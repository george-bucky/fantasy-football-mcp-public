"""Focused handler tests for opt-in rookie decision context."""

from types import SimpleNamespace
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
            "rookie_intelligence": {"status": "not_on_current_rookie_board"},
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
        ) as legacy_fetch,
        patch.object(player_handlers, "get_user_team_key", AsyncMock(return_value="team.1")),
        patch.object(
            player_handlers, "get_league_context", AsyncMock(side_effect=ValueError("bad context"))
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
    legacy_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_waiver_rookie_only_uses_complete_context_not_legacy_first_page():
    complete_players = [
        {
            "name": "Deep Rookie",
            "position": "WR",
            "rookie_intelligence": {"status": "matched", "base_rank": 40},
            "league_fit": {"roster_need": True},
        }
    ]
    with (
        patch.object(
            player_handlers,
            "get_waiver_wire_players",
            AsyncMock(return_value=[{"name": "Veteran", "position": "WR"}]),
        ) as legacy_fetch,
        patch.object(player_handlers, "get_user_team_key", AsyncMock(return_value="team.1")),
        patch.object(player_handlers, "get_league_context", AsyncMock(return_value=object())),
        patch.object(
            player_handlers,
            "build_rookie_add_recommendations",
            return_value={
                "players": complete_players,
                "evidence": {
                    "enabled": True,
                    "rookie_only": True,
                    "warnings": [],
                    "league_context": {"availability_pages": 4},
                },
            },
        ) as build_rookies,
    ):
        result = await player_handlers.handle_ff_get_waiver_wire(
            {
                "league_key": "league.test",
                "rookie_only": True,
                "include_analysis": False,
                "include_projections": False,
                "include_external_data": False,
            }
        )

    assert result["players"] == complete_players
    assert result["total_players"] == 1
    assert result["decision_evidence"]["rookie_intelligence"]["league_context"][
        "availability_pages"
    ] == 4
    legacy_fetch.assert_not_awaited()
    build_rookies.assert_called_once()


@pytest.mark.asyncio
async def test_waiver_rookie_only_keeps_requested_enhancement_pipeline():
    complete_players = [
        {
            "name": "Deep Rookie",
            "position": "WR",
            "rookie_intelligence": {"status": "matched", "base_rank": 40},
            "league_fit": {"roster_need": True},
        }
    ]
    with (
        patch.object(player_handlers, "get_user_team_key", AsyncMock(return_value="team.1")),
        patch.object(player_handlers, "get_league_context", AsyncMock(return_value=object())),
        patch.object(
            player_handlers,
            "build_rookie_add_recommendations",
            return_value={
                "players": complete_players,
                "evidence": {"enabled": True, "rookie_only": True},
            },
        ),
        patch(
            "lineup_optimizer.lineup_optimizer.parse_yahoo_roster",
            AsyncMock(return_value=[]),
        ) as parse_roster,
    ):
        result = await player_handlers.handle_ff_get_waiver_wire(
            {
                "league_key": "league.test",
                "rookie_only": True,
                "include_analysis": False,
                "include_projections": True,
                "include_external_data": False,
            }
        )

    parse_roster.assert_awaited_once()
    assert result["players"] == complete_players
    assert result["note"] == "No players could be enhanced"


def test_rookie_only_enrichment_preserves_complete_order_and_fit_evidence():
    complete_players = [
        {
            "name": "First Rookie",
            "position": "QB",
            "player_key": "461.p.1",
            "player_id": "1",
            "rookie_intelligence": {"status": "matched", "base_rank": 10},
            "league_fit": {"roster_need": True},
        },
        {
            "name": "Second Rookie",
            "position": "RB",
            "player_key": "461.p.2",
            "player_id": "2",
            "rookie_intelligence": {"status": "matched", "base_rank": 1},
            "league_fit": {"roster_need": False},
        },
    ]
    enhanced_players = [
        {"name": "Second Rookie", "position": "RB", "waiver_priority": 99},
    ]

    ordered = player_handlers._preserve_rookie_add_order(
        enhanced_players, complete_players
    )

    assert [player["name"] for player in ordered] == ["First Rookie", "Second Rookie"]
    assert ordered[0]["player_key"] == "461.p.1"
    assert ordered[0]["league_fit"] == {"roster_need": True}
    assert "waiver_priority" not in ordered[0]
    assert ordered[1]["waiver_priority"] == 99


@pytest.mark.asyncio
async def test_rookie_only_analysis_omits_unsupported_ownership_scores():
    complete_players = [
        {
            "name": "Deep Rookie",
            "position": "WR",
            "player_key": "461.p.1",
            "player_id": "1",
            "rookie_intelligence": {"status": "matched", "base_rank": 40},
            "league_fit": {"roster_need": True},
        }
    ]
    enhanced_player = SimpleNamespace(
        name="Deep Rookie",
        position="WR",
        team="NYG",
        opponent=None,
        status="Available",
        yahoo_projection=8.0,
        sleeper_projection=9.0,
        sleeper_id="s1",
        sleeper_match_method="exact",
        floor_projection=5.0,
        ceiling_projection=15.0,
        consistency_score=75,
        player_tier="Depth",
        matchup_score=6.0,
        matchup_description="Neutral",
        trending_score=4.0,
        risk_level="Medium",
        injury_status="Healthy",
        is_valid=lambda: True,
    )
    with (
        patch.object(player_handlers, "get_user_team_key", AsyncMock(return_value="team.1")),
        patch.object(player_handlers, "get_league_context", AsyncMock(return_value=object())),
        patch.object(
            player_handlers,
            "build_rookie_add_recommendations",
            return_value={
                "players": complete_players,
                "evidence": {"enabled": True, "rookie_only": True},
            },
        ),
        patch(
            "lineup_optimizer.lineup_optimizer.parse_yahoo_roster",
            AsyncMock(return_value=[enhanced_player]),
        ),
        patch(
            "lineup_optimizer.lineup_optimizer.enhance_with_external_data",
            AsyncMock(return_value=[enhanced_player]),
        ),
        patch(
            "sleeper_api.sleeper_client.get_expert_advice",
            AsyncMock(
                return_value={
                    "tier": "Upside",
                    "recommendation": "Monitor",
                    "confidence": 70,
                    "advice": "Watch usage",
                }
            ),
        ),
        patch("sleeper_api.get_trending_adds", AsyncMock(return_value=[])),
    ):
        result = await player_handlers.handle_ff_get_waiver_wire(
            {
                "league_key": "league.test",
                "rookie_only": True,
                "include_analysis": True,
                "include_projections": True,
                "include_external_data": True,
            }
        )

    enhanced = result["enhanced_players"][0]
    assert enhanced["owned_pct"] is None
    assert enhanced["weekly_change"] is None
    assert enhanced["bye"] is None
    assert "waiver_priority" not in enhanced
    assert "pickup_urgency" not in enhanced
    assert result["analysis_context"]["algorithm"] is None
    assert "ownership-dependent waiver scoring was omitted" in result[
        "analysis_context"
    ]["warnings"][0]


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
