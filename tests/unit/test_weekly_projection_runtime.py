"""Offline current-odds integration, with synthetic players and league settings."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lineup_optimizer import LineupOptimizer, Player, assess_player_projection
from src.services.market_evidence import assess_player_markets
from src.services.weekly_projection_runtime import (
    enrich_weekly_projection_inputs,
    scoring_coefficients,
)

NOW = datetime(2026, 11, 3, 18, tzinfo=timezone.utc)
START = NOW + timedelta(days=2)


def market_context(line=30.5):
    quotes = [
        {
            "event_id": "event",
            "provider_entity_id": "provider-player",
            "scope": "next_game",
            "period": "full_game",
            "period_source": "provider",
            "event": {"commence_time": START.isoformat()},
            "bookmaker_key": "draftkings",
            "market_key": "player_reception_yds",
            "selection": side,
            "line": line,
            "price": -110,
            "odds_format": "american",
            "odds_format_source": "provider",
            "quote_fetched_at": NOW.isoformat(),
            "provider_observed_at": NOW.isoformat(),
        }
        for side in ("Over", "Under")
    ]
    evidence = assess_player_markets(
        quotes, event_id="event", player_id="provider-player", kickoff=START, as_of=NOW
    )
    observations = [
        {
            "player_id": "provider-player",
            "stat": "receiving_yards",
            "value": value,
            "period": "full_game",
            "game_id": f"prior-{index}",
            "occurred_at": (NOW - timedelta(days=7 * (index + 1))).isoformat(),
            "known_at": (NOW - timedelta(days=7 * (index + 1)) + timedelta(hours=4)).isoformat(),
        }
        for index, value in enumerate([0, 0, 0, 0, 20, 20, 20, 100])
    ]
    return {
        "season": 2026,
        "week": 10,
        "game_id": "event",
        "kickoff": START.isoformat(),
        "as_of": NOW.isoformat(),
        "weekly_projection_inputs": {
            "available": True,
            "event_id": "event",
            "player_id": "provider-player",
            "player_key": "yahoo-player",
            "kickoff": START.isoformat(),
            "as_of": NOW.isoformat(),
            "season": 2026,
            "week": 10,
            "market_evidence": evidence,
            "observations": observations,
            "baseline_stats": {"receiving_yards": 25},
            "baseline_source": "sleeper_api",
            "scoring_coefficients": {"receiving_yards": 0.1},
        },
    }


def player(context=None, **kwargs):
    args = {
        "name": "Receiver",
        "position": "WR",
        "team": "BUF",
        "player_key": "yahoo-player",
        "yahoo_projection": 10,
        "sleeper_projection_ppr": 10,
        "sleeper_projection_source": "sleeper_api",
        "sleeper_id": "sleeper-player",
        "scoring_format": "ppr",
        "scoring_format_source": "yahoo_settings",
        "projection_context": market_context() if context is None else context,
    }
    args.update(kwargs)
    return Player(**args)


def test_fresh_market_changes_points_and_selection_once_from_unchanged_baseline():
    p = player()
    original = deepcopy(p.projection_context)
    result = assess_player_projection(p)
    assert result["baseline_expected_points"] == 10
    assert result["final_expected_points"] > 10
    assert 0 < result["total_adjustment_points"] <= 2
    assert result["strategy_utility"] == pytest.approx(10 + result["total_adjustment_points"])
    assert result["adjustment_policy"]["status"] == "estimated_not_backtested"
    assert assess_player_projection(p)["final_expected_points"] == result["final_expected_points"]
    assert p.projection_context == original
    assert p.yahoo_projection == 10 and p.sleeper_projection_ppr == 10


def test_current_line_changes_recompute_direction_and_stale_quotes_stop_effect():
    high = assess_player_projection(player())
    low = assess_player_projection(player(context=market_context(0.5)))
    assert low["final_expected_points"] < high["final_expected_points"]
    stale = market_context()
    stale["as_of"] = (NOW + timedelta(minutes=6)).isoformat()
    result = assess_player_projection(player(context=stale))
    assert result["final_expected_points"] == result["baseline_expected_points"]
    assert result["total_adjustment_points"] == 0


@pytest.mark.asyncio
async def test_market_adjustment_can_change_actual_start_sit_choice():
    p = player()
    other = player(
        context={},
        name="Other",
        player_key="other",
        yahoo_projection=10.1,
        sleeper_projection_ppr=10.1,
    )
    result = await LineupOptimizer().optimize_lineup_smart([other, p], roster_slots={"WR": 1})
    assert result["starters"]["WR"].player_key == p.player_key


@pytest.mark.parametrize(
    "field,value", [("season", 2025), ("week", 9), ("player_key", "different")]
)
def test_mismatched_collected_report_does_not_adjust_request(field, value):
    context = market_context()
    context["weekly_projection_inputs"][field] = value
    assert assess_player_projection(player(context=context))["total_adjustment_points"] == 0


def test_explicit_stat_scoring_not_inferred_from_reception_class():
    categories = {
        "stats": [
            {"stat_id": 4, "name": "Passing Yards"},
            {"stat_id": 5, "name": "Passing Touchdowns"},
            {"stat_id": 6, "name": "Receptions"},
        ]
    }
    settings = {
        "stats": [
            {"stat_id": 4, "value": ".04"},
            {"stat_id": 5, "value": 6},
            {"stat_id": 6, "value": 0.5},
        ]
    }
    assert scoring_coefficients(settings, categories) == {
        "passing_yards": 0.04,
        "passing_touchdowns": 6,
        "receptions": 0.5,
    }
    settings["stats"].append({"stat_id": 5, "value": 4})
    assert "passing_touchdowns" not in scoring_coefficients(settings, categories)
    assert scoring_coefficients({}, categories) == {}


@pytest.mark.asyncio
async def test_no_explicit_stat_scoring_skips_all_provider_collection():
    p = player()
    sleeper = SimpleNamespace(get_nfl_state=AsyncMock())
    await enrich_weekly_projection_inputs(
        [p], season=2026, week=10, coefficients={}, sleeper=sleeper
    )
    sleeper.get_nfl_state.assert_not_awaited()
    assert "weekly_projection_inputs" not in p.projection_context
    assert assess_player_projection(p)["total_adjustment_points"] == 0


@pytest.mark.asyncio
async def test_runtime_collects_full_roster_and_preserves_baselines():
    p, other = player(), player(name="Bench", player_key="bench")
    sleeper = SimpleNamespace(
        get_nfl_state=AsyncMock(return_value={"season": "2026", "week": 10}),
        get_all_players=AsyncMock(
            return_value={"sleeper-player": {"full_name": "Receiver", "team": "BUF"}}
        ),
    )
    schedule = SimpleNamespace(
        get_game_bindings=AsyncMock(
            return_value=[
                {
                    "status": "matched",
                    "team": "BUF",
                    "opponent": "NYJ",
                    "kickoff": START.isoformat(),
                }
            ]
            * 2
        )
    )
    collector = SimpleNamespace(
        collect=AsyncMock(
            return_value={
                "players": {"yahoo-player": market_context()["weekly_projection_inputs"]},
                "warnings": [],
            }
        )
    )
    result = await enrich_weekly_projection_inputs(
        [p, other],
        season=2026,
        week=10,
        coefficients={"receiving_yards": 0.1},
        sleeper=sleeper,
        schedule_service=schedule,
        collector=collector,
        now=lambda: NOW,
    )
    assert len(collector.collect.call_args.args[0]) == 2
    assert result[0].yahoo_projection == 10
    assert result[1].projection_context["market_input_status"]["status"] == "unavailable"
    assert assess_player_projection(result[0])["total_adjustment_points"] > 0


@pytest.mark.asyncio
async def test_market_opt_out_removes_previous_delta_without_provider_calls():
    p = player()
    sleeper = SimpleNamespace(get_nfl_state=AsyncMock())
    await enrich_weekly_projection_inputs(
        [p],
        season=2026,
        week=10,
        coefficients={"receiving_yards": 0.1},
        enabled=False,
        environment_enabled=False,
        sleeper=sleeper,
    )
    sleeper.get_nfl_state.assert_not_awaited()
    result = assess_player_projection(p)
    assert result["baseline_expected_points"] == 10
    assert result["final_expected_points"] == 10
    assert result["market_input_status"]["reason"] == "disabled_by_request"


def test_external_disabled_copy_cannot_reuse_old_market_context():
    from src.handlers.roster_handlers import _yahoo_only_player

    p = player()
    scoped = _yahoo_only_player(p)
    result = assess_player_projection(scoped)
    assert result["total_adjustment_points"] == 0
    assert result["baseline_expected_points"] == 10
    assert "weekly_projection_inputs" in p.projection_context
