"""Offline end-to-end game/weather effects on the shared projection and selector."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lineup_optimizer import LineupOptimizer, Player, assess_player_projection
from src.services.weekly_projection_runtime import enrich_weekly_projection_inputs

NOW = datetime(2026, 11, 3, 18, tzinfo=timezone.utc)
START = NOW + timedelta(days=2)


def weather(mph=20, heavy_rain=False):
    return {
        "available": True,
        "game_id": "schedule-game",
        "venue": {
            "stadium_id": "stadium",
            "source": "synthetic-verified",
            "verified_at": NOW.isoformat(),
            "exposure": "exposed",
        },
        "source": {
            "provider": "NWS",
            "kind": "forecast",
            "issued_at": NOW.isoformat(),
            "fetched_at": NOW.isoformat(),
            "sha256": "a" * 64,
            "forecast_url": "https://api.weather.gov/gridpoints/BUF/1,2/forecast/hourly",
        },
        "window": {"start": START.isoformat(), "end": (START + timedelta(hours=3)).isoformat()},
        "forecast_periods": [
            {
                "start": (START + timedelta(hours=h)).isoformat(),
                "end": (START + timedelta(hours=h + 1)).isoformat(),
                "sustained_wind_m_s": {"minimum": mph * 0.44704, "maximum": mph * 0.44704},
                "summary": "Heavy Rain" if heavy_rain else "Rain",
                "precipitation_probability": 1,
                "precipitation_amount_mm": None,
            }
            for h in range(3)
        ],
    }


def context(*, wind=20, heavy_rain=False, game_odds=False, touchdowns=0.6):
    quotes = [
        {
            "event_id": "event",
            "scope": "next_game",
            "event": {
                "home_team_key": "buffalo_bills",
                "away_team_key": "miami_dolphins",
                "commence_time": START.isoformat(),
            },
            "bookmaker_key": "draftkings",
            "market_key": "totals",
            "market_team": "buffalo_bills",
            "market_team_source": "provider",
            "line_type": "main",
            "line_type_source": "provider",
            "selection": side,
            "line": 30.5,
            "price": -110,
            "odds_format": "american",
            "odds_format_source": "provider",
            "period": "full_game",
            "period_source": "provider",
            "quote_fetched_at": NOW.isoformat(),
            "provider_observed_at": NOW.isoformat(),
        }
        for side in ("Over", "Under")
    ]
    return {
        "season": 2026,
        "week": 10,
        "game_id": "event" if game_odds else "schedule-game",
        "schedule_game_id": "schedule-game",
        "kickoff": START.isoformat(),
        "as_of": NOW.isoformat(),
        "weekly_projection_inputs": {
            "available": False,
            "player_key": "player",
            "season": 2026,
            "week": 10,
            "event_id": "event" if game_odds else None,
            "event_team_key": "buffalo_bills",
            "kickoff": START.isoformat(),
            "baseline_source": "sleeper_api",
            "baseline_stats": {
                "receiving_yards": 80,
                "receptions": 6,
                "receiving_touchdowns": touchdowns,
            },
            "scoring_coefficients": {
                "receiving_yards": 0.1,
                "receptions": 1,
                "receiving_touchdowns": 6,
            },
            "game_quotes": quotes if game_odds else [],
        },
        "game_environment_inputs": {
            "player_key": "player",
            "season": 2026,
            "week": 10,
            "team": "BUF",
            "schedule_game_id": "schedule-game",
            "kickoff": START.isoformat(),
            "weather": weather(wind, heavy_rain),
            "team_points_history": [
                {
                    "team": "BUF",
                    "game_id": f"past-{i}",
                    "points": 20,
                    "period": "full_game",
                    "occurred_at": (NOW - timedelta(days=7 * (i + 1))).isoformat(),
                    "known_at": NOW.isoformat(),
                }
                for i in range(8)
            ],
        },
    }


def player(ctx=None, **kwargs):
    args = {
        "name": "Receiver",
        "player_key": "player",
        "position": "WR",
        "team": "BUF",
        "yahoo_projection": 10,
        "sleeper_projection_ppr": 10,
        "sleeper_projection_source": "sleeper_api",
        "scoring_format": "ppr",
        "scoring_format_source": "yahoo_settings",
        "projection_context": context() if ctx is None else ctx,
    }
    args.update(kwargs)
    return Player(**args)


def test_verified_wind_and_heavy_rain_affect_points_without_mutating_baseline():
    p = player()
    original = deepcopy(p.projection_context)
    assessment = assess_player_projection(p)
    assert assessment["baseline_expected_points"] == 10
    assert assessment["final_expected_points"] == pytest.approx(9.3)
    assert assessment["adjustment_policy"]["status"] == "estimated_not_backtested"
    assert {a["kind"] for a in assessment["adjustment_ledger"]} == {"environment"}
    assert (
        assess_player_projection(p)["final_expected_points"] == assessment["final_expected_points"]
    )
    assert p.projection_context == original and p.yahoo_projection == 10
    rain = assess_player_projection(player(context(wind=0, heavy_rain=True)))
    assert rain["final_expected_points"] == pytest.approx(9.65)
    assert assess_player_projection(player(context(wind=0)))["final_expected_points"] == 10


@pytest.mark.asyncio
async def test_weather_can_change_actual_starter_selection():
    p = player()
    other = player(
        {},
        name="Dome receiver",
        player_key="other",
        yahoo_projection=9.8,
        sleeper_projection_ppr=9.8,
    )
    result = await LineupOptimizer().optimize_lineup_smart([p, other], roster_slots={"WR": 1})
    assert result["starters"]["WR"].player_key == "other"


def test_game_fallback_and_weather_have_disjoint_components_and_shared_cap():
    p = player(context(game_odds=True, touchdowns=10))
    result = assess_player_projection(p)
    assert result["context_estimate"]["game_market"]["available"] is True
    assert result["context_estimate"]["game_market"]["team_scoring_index"] == 30.5
    assert {a["kind"] for a in result["adjustment_ledger"]} == {"market", "environment"}
    assert sum(
        abs(a["applied_delta_points"]) for a in result["adjustment_ledger"]
    ) == pytest.approx(2)
    assert all(a["applied"] for a in result["adjustment_ledger"])
    assert result["final_expected_points"] == pytest.approx(10 + result["total_adjustment_points"])


@pytest.mark.parametrize("change", ["stale", "unknown_roof", "wrong_game", "wrong_week"])
def test_unverified_weather_never_changes_provider_points(change):
    ctx = context()
    if change == "stale":
        ctx["game_environment_inputs"]["weather"]["source"]["fetched_at"] = (
            NOW - timedelta(minutes=6)
        ).isoformat()
    elif change == "unknown_roof":
        ctx["game_environment_inputs"]["weather"]["venue"]["exposure"] = "unknown"
    elif change == "wrong_game":
        ctx["game_environment_inputs"]["weather"]["game_id"] = "other-game"
    else:
        ctx["game_environment_inputs"]["week"] = 9
    assert assess_player_projection(player(ctx))["final_expected_points"] == 10


def test_weather_optout_retains_game_market_and_yahoo_only_has_no_context_effect():
    from src.handlers.roster_handlers import _yahoo_only_player

    ctx = context(game_odds=True)
    ctx["environment_adjustments_enabled"] = False
    p = player(ctx)
    result = assess_player_projection(p)
    assert result["final_expected_points"] > 10
    assert {a["kind"] for a in result["adjustment_ledger"]} == {"market"}
    assert assess_player_projection(_yahoo_only_player(p))["final_expected_points"] is None


@pytest.mark.asyncio
async def test_runtime_can_disable_odds_while_collecting_weather_once_per_game():
    p = player()
    p.sleeper_id = "sleeper"
    state = SimpleNamespace(
        get_nfl_state=AsyncMock(return_value={"season": "2026", "week": 10}),
        get_all_players=AsyncMock(
            return_value={"sleeper": {"full_name": "Receiver", "team": "BUF"}}
        ),
    )
    schedule = SimpleNamespace(
        get_game_bindings=AsyncMock(
            return_value=[
                {
                    "status": "matched",
                    "team": "BUF",
                    "opponent": "MIA",
                    "home_away": "home",
                    "schedule_game_id": "schedule-game",
                    "kickoff": START.isoformat(),
                }
            ]
        )
    )
    row = context()["weekly_projection_inputs"]
    collector = SimpleNamespace(
        collect=AsyncMock(return_value={"players": {"player": row}, "warnings": []})
    )
    environment = SimpleNamespace(
        collect=AsyncMock(
            return_value={
                "games": {"schedule-game": context()["game_environment_inputs"]},
                "warnings": [],
            }
        )
    )
    await enrich_weekly_projection_inputs(
        [p],
        season=2026,
        week=10,
        coefficients=row["scoring_coefficients"],
        enabled=False,
        environment_enabled=True,
        sleeper=state,
        schedule_service=schedule,
        collector=collector,
        environment_collector=environment,
        now=lambda: NOW,
    )
    assert collector.collect.call_args.kwargs["include_odds"] is False
    assert environment.collect.call_count == 1
    assert environment.collect.call_args.kwargs["include_weather"] is True
    result = assess_player_projection(p)
    assert result["final_expected_points"] < 10
    assert {a["kind"] for a in result["adjustment_ledger"]} == {"environment"}


def test_fresh_player_props_suppress_game_and_weather_point_layers():
    from src.services.market_evidence import assess_player_markets

    ctx = context(game_odds=True)
    row = ctx["weekly_projection_inputs"]
    quotes = [
        {
            **quote,
            "market_key": "player_reception_yds",
            "market_team": None,
            "provider_entity_id": "provider-player",
            "line": 79.5,
        }
        for quote in row["game_quotes"]
    ]
    row.update(
        available=True,
        player_id="provider-player",
        observations=[
            {
                "player_id": "provider-player",
                "game_id": f"prior-{i}",
                "stat": "receiving_yards",
                "value": value,
                "period": "full_game",
                "occurred_at": (NOW - timedelta(days=7 * (i + 1))).isoformat(),
                "known_at": NOW.isoformat(),
            }
            for i, value in enumerate([0, 0, 0, 0, 20, 20, 20, 100])
        ],
    )
    row["market_evidence"] = assess_player_markets(
        quotes, event_id="event", player_id="provider-player", kickoff=START, as_of=NOW
    )
    result = assess_player_projection(player(ctx))
    assert result["market_estimate"]["available"] is True
    assert (
        result["context_estimate"]["game_market"]["reason"] == "suppressed_overlapping_player_props"
    )
    assert (
        result["context_estimate"]["environment"]["reason"]
        == "weather_suppressed_overlapping_player_props"
    )
    assert all(a["model_id"] == "current_player_props" for a in result["adjustment_ledger"])


def test_bad_game_market_binding_does_not_suppress_independent_verified_weather():
    ctx = context(game_odds=True)
    ctx["weekly_projection_inputs"]["event_id"] = "wrong-event"
    result = assess_player_projection(player(ctx))
    assert result["final_expected_points"] == pytest.approx(9.3)
    assert {a["kind"] for a in result["adjustment_ledger"]} == {"environment"}


@pytest.mark.parametrize("cutoff", [NOW + timedelta(minutes=6), START])
def test_final_decision_clock_rechecks_expiry_and_kickoff_after_later_io(cutoff):
    from src.services.weekly_projection_runtime import refresh_live_assessment_clock

    ctx = context(game_odds=True)
    ctx["live_context_collected"] = True
    p = player(ctx)
    assert assess_player_projection(p)["total_adjustment_points"] != 0
    p.projection_assessment = {"stale": "cached"}
    refresh_live_assessment_clock([p], as_of=cutoff)
    assert p.projection_assessment == {}
    result = assess_player_projection(p)
    assert result["total_adjustment_points"] == 0
    assert result["final_expected_points"] == 10


@pytest.mark.asyncio
async def test_lineup_handler_rechecks_clock_after_delayed_decision_news(monkeypatch):
    from lineup_optimizer import lineup_optimizer
    from src.handlers import matchup_handlers
    from src.services import weekly_projection_runtime as runtime

    ctx = context()
    ctx["live_context_collected"] = True
    p = player(ctx)
    clock = {"current": NOW}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["current"]

    async def delayed_news(names):
        clock["current"] = NOW + timedelta(minutes=6)
        return {"by_player": {}, "sources": [], "warnings": []}

    monkeypatch.setattr(runtime, "datetime", Clock)
    monkeypatch.setattr(matchup_handlers, "get_user_team_key", AsyncMock(return_value="league.t.1"))
    monkeypatch.setattr(
        matchup_handlers, "yahoo_api_call", AsyncMock(return_value={"fantasy_content": {}})
    )
    monkeypatch.setattr(
        matchup_handlers,
        "_get_lineup_context",
        AsyncMock(
            return_value={
                "season": 2026,
                "current_week": 10,
                "scoring_format": "ppr",
                "scoring_format_source": "yahoo_settings",
                "canonical_scoring_basis": "ppr",
                "roster_slots": {"WR": 1},
                "warnings": [],
                "projection_stat_coefficients": {"receiving_yards": 0.1},
            }
        ),
    )
    monkeypatch.setattr(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=[p]))
    monkeypatch.setattr(lineup_optimizer, "enhance_with_external_data", AsyncMock(return_value=[p]))
    monkeypatch.setattr(runtime, "enrich_weekly_projection_inputs", AsyncMock(return_value=[p]))
    monkeypatch.setattr(matchup_handlers, "get_decision_news_context", delayed_news)
    result = await matchup_handlers.handle_ff_build_lineup({"league_key": "league"})
    assessment = result["optimal_lineup"]["WR"]["projection_assessment"]
    assert assessment["as_of"] == clock["current"].isoformat()
    assert assessment["total_adjustment_points"] == 0
    assert assessment["final_expected_points"] == 10


@pytest.mark.parametrize("game_odds", [False, True])
@pytest.mark.parametrize(
    "strategy,projection_weight,history_component",
    [("balanced", 0.8, 1.6), ("conservative", 0.5, 2.8), ("aggressive", 0.5, 5.4)],
)
def test_strategy_uses_weather_and_game_adjusted_forecast_once(
    game_odds, strategy, projection_weight, history_component
):
    p = player(context(game_odds=game_odds))
    p.recent_performance_data = SimpleNamespace(
        weeks_data=[{"points": value} for value in [4, 8, 12]]
    )
    result = assess_player_projection(p, strategy)
    kinds = {a["kind"] for a in result["adjustment_ledger"] if a["applied"]}
    assert "environment" in kinds
    if game_odds:
        assert "market" in kinds
    assert result["final_expected_points"] == pytest.approx(10 + result["total_adjustment_points"])
    assert result["strategy_utility"] == pytest.approx(
        projection_weight * result["final_expected_points"] + history_component
    )
    assert assess_player_projection(p, strategy) == result
    assert p.sleeper_projection_ppr == 10
