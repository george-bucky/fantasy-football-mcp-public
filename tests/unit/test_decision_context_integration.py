"""Decision-tool integration tests for attributed news evidence."""

from unittest.mock import AsyncMock, patch

import pytest

import lineup_optimizer
from lineup_optimizer import Player
from src.handlers import matchup_handlers
from src.services.rookie_intelligence import rookie_identity_key


def _optimization(starter, bench):
    return {
        "status": "success",
        "starters": {"QB": starter},
        "bench": [bench],
        "recommendations": [f"Start {starter.name} at QB"],
        "errors": [],
        "strategy_used": "balanced",
        "data_quality": {
            "total_players": 2,
            "valid_players": 2,
            "players_with_projections": 2,
            "players_with_matchup_data": 2,
        },
    }


@pytest.mark.asyncio
async def test_lineup_attaches_news_after_selection_without_changing_starter():
    starter = Player(
        name="Josh Allen", position="QB", team="BUF", yahoo_projection=24
    )
    bench = Player(
        name="Other QB", position="BN", team="NYJ", yahoo_projection=15
    )
    news = {
        "by_player": {
            "Josh Allen": {
                "espn": [
                    {
                        "headline": "Allen practices",
                        "source": "ESPN NFL News API",
                        "team_refs": [
                            {"name": "Buffalo Bills", "espn_team_id": "2"}
                        ],
                    }
                ],
                "rotowire": [],
                "espn_athlete_refs": [
                    {"name": "Josh Allen", "espn_athlete_id": "3918298"}
                ],
            }
        },
        "sources": ["ESPN NFL News API"],
        "warnings": [],
    }
    optimizer = lineup_optimizer.lineup_optimizer
    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value="t.1")),
        patch.object(matchup_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(optimizer, "parse_yahoo_roster", AsyncMock(return_value=[starter, bench])),
        patch.object(
            optimizer,
            "enhance_with_external_data",
            AsyncMock(return_value=[starter, bench]),
        ),
        patch.object(
            optimizer,
            "optimize_lineup_smart",
            AsyncMock(return_value=_optimization(starter, bench)),
        ),
        patch.object(
            matchup_handlers,
            "get_decision_news_context",
            AsyncMock(return_value=news),
        ) as get_news,
    ):
        result = await matchup_handlers.handle_ff_build_lineup(
            {"league_key": "league.test"}
        )

    assert result["optimal_lineup"]["QB"]["name"] == "Josh Allen"
    assert result["optimal_lineup"]["QB"]["news_context"]["espn_athlete_refs"][0][
        "espn_athlete_id"
    ] == "3918298"
    assert result["optimal_lineup"]["QB"]["news_context"]["espn"][0][
        "team_refs"
    ][0]["espn_team_id"] == "2"
    assert "ESPN NFL News API" in result["analysis"]["data_sources"]
    get_news.assert_awaited_once_with(["Josh Allen", "Other QB"])


@pytest.mark.asyncio
async def test_lineup_news_failure_is_a_warning_not_a_lineup_failure():
    starter = Player(
        name="Josh Allen", position="QB", team="BUF", yahoo_projection=24
    )
    bench = Player(
        name="Other QB", position="BN", team="NYJ", yahoo_projection=15
    )
    optimizer = lineup_optimizer.lineup_optimizer
    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value="t.1")),
        patch.object(matchup_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(optimizer, "parse_yahoo_roster", AsyncMock(return_value=[starter, bench])),
        patch.object(
            optimizer,
            "enhance_with_external_data",
            AsyncMock(return_value=[starter, bench]),
        ),
        patch.object(
            optimizer,
            "optimize_lineup_smart",
            AsyncMock(return_value=_optimization(starter, bench)),
        ),
        patch.object(
            matchup_handlers,
            "get_decision_news_context",
            AsyncMock(side_effect=RuntimeError("offline")),
        ),
    ):
        result = await matchup_handlers.handle_ff_build_lineup(
            {"league_key": "league.test"}
        )

    assert result["status"] == "success"
    assert result["optimal_lineup"]["QB"]["name"] == "Josh Allen"
    assert result["warnings"] == ["Decision news unavailable: offline"]


@pytest.mark.asyncio
async def test_lineup_rookie_context_is_opt_in_and_passed_as_near_tie_evidence():
    starter = Player(name="Rookie QB", position="QB", team="NYJ", yahoo_projection=20)
    bench = Player(name="Veteran QB", position="BN", team="BUF", yahoo_projection=20)
    rookie_context = {
        "players": [],
        "by_identity": {
            rookie_identity_key("Rookie QB", "QB"): {
                "status": "matched",
                "base_rank": 2,
                "outlook_scope": "season-long; not a weekly projection",
            },
            rookie_identity_key("Veteran QB", "BN"): {
                "status": "quarantined",
                "match_method": "none",
            },
        },
        "evidence": {
            "enabled": True,
            "warnings": [],
            "opponent_aware": False,
            "influence": "near tie only",
        },
    }
    optimizer = lineup_optimizer.lineup_optimizer
    optimize = AsyncMock(return_value=_optimization(starter, bench))
    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value="t.1")),
        patch.object(matchup_handlers, "yahoo_api_call", AsyncMock(return_value={})),
        patch.object(optimizer, "parse_yahoo_roster", AsyncMock(return_value=[starter, bench])),
        patch.object(
            optimizer,
            "enhance_with_external_data",
            AsyncMock(return_value=[starter, bench]),
        ),
        patch.object(optimizer, "optimize_lineup_smart", optimize),
        patch.object(
            matchup_handlers,
            "get_decision_news_context",
            AsyncMock(return_value={"by_player": {}, "sources": [], "warnings": []}),
        ),
        patch.object(
            matchup_handlers,
            "apply_rookie_intelligence",
            return_value=rookie_context,
        ) as apply_rookies,
    ):
        result = await matchup_handlers.handle_ff_build_lineup(
            {"league_key": "league.test", "use_rookie_intelligence": True}
        )

    assert result["optimal_lineup"]["QB"]["rookie_intelligence"]["base_rank"] == 2
    assert result["analysis"]["rookie_intelligence"]["opponent_aware"] is False
    assert optimize.await_args.kwargs["rookie_intelligence"] == rookie_context["by_identity"]
    apply_rookies.assert_called_once()
