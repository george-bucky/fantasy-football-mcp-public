"""Synthetic current-week collection: no provider credentials or network."""

import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.weekly_projection_inputs import (
    WeeklyProjectionInputsService,
    projection_context_with_inputs,
    verified_sleeper_identity,
)

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
KICKOFF = NOW + timedelta(days=2)


def identity(index=0):
    return {
        "player_key": f"461.p.{index}",
        "sleeper_id": str(index),
        "sleeper_identity_verified": True,
        "name": f"Receiver {index}",
        "team": "KC",
        "opponent": "BUF",
        "kickoff": KICKOFF,
    }


def quotes(index=0):
    return [
        {
            "event_id": "e1",
            "provider_entity_id": f"prop{index}",
            "subject": f"Receiver {index}",
            "scope": "next_game",
            "event": {
                "home_team_key": "kansas_city_chiefs",
                "away_team": "Buffalo Bills",
                "commence_time": KICKOFF.isoformat(),
            },
            "market_key": "player_reception_yds",
            "selection": side,
            "line": 60.5,
            "price": -110,
            "bookmaker_key": "draftkings",
            "period": "full_game",
            "period_source": "provider",
            "odds_format": "american",
            "odds_format_source": "provider",
            "quote_fetched_at": NOW.isoformat(),
            "provider_observed_at": NOW.isoformat(),
            "pricing_semantics": "quoted_single_leg",
            "pricing_semantics_source": "provider",
        }
        for side in ("Over", "Under")
    ]


def setup(count=1, **kwargs):
    sleeper = SimpleNamespace(
        get_projections=AsyncMock(
            return_value={
                str(i): {
                    "projection_source": "sleeper_api",
                    "rec_yd": 70,
                    "rec": 5,
                    "season": 2026,
                    "week": 10,
                }
                for i in range(count)
            }
        ),
        get_player_stats=AsyncMock(
            side_effect=lambda season, week: {
                str(i): {
                    "stats_source": "sleeper_api",
                    "rec_yd": week * 10,
                    "rec": 0,
                    "season": season,
                    "week": week,
                }
                for i in range(count)
            }
        ),
    )

    async def odds(**arguments):
        assert len(arguments["players"]) <= 10
        assert arguments["bookmakers"] == ["draftkings", "fanduel"]
        assert arguments["primary_lines_only"] is True
        return {
            "results": [
                quote
                for i in range(count)
                if f"Receiver {i}" in arguments["players"]
                for quote in quotes(i)
            ]
        }

    odds_mock = AsyncMock(side_effect=odds)
    service = WeeklyProjectionInputsService(
        sleeper, odds_fetcher=odds_mock, now=lambda: NOW, **kwargs
    )
    return service, sleeper, odds_mock


async def collect(service, rows=None, **kwargs):
    arguments = {
        "season": 2026,
        "week": 10,
        "current_season": 2026,
        "current_week": 10,
        "scoring_coefficients": {"receiving_yards": 0.1, "receptions": 1},
    }
    arguments.update(kwargs)
    return await service.collect(rows or [identity()], **arguments)


@pytest.mark.asyncio
async def test_entire_roster_chunks_deduplicates_history_and_keeps_zero_actuals():
    service, sleeper, odds = setup(23)
    result = await collect(service, [identity(i) for i in range(23)])
    assert len(result["players"]) == 23
    assert sleeper.get_projections.await_count == 1
    assert sleeper.get_player_stats.await_count == 9
    assert odds.await_count == 3
    for report in result["players"].values():
        assert report["available"]
        assert report["baseline_stats"] == {"receiving_yards": 70.0, "receptions": 5.0}
        assert len(report["observations"]) == 18
        assert report["observations"][1]["value"] == 0
        assert report["observations"][0]["period_id"] == "2026:regular:1"
        assert "occurred_at" not in report["observations"][0]
        assert "game_id" not in report["observations"][0]
        assert all(row["week"] < 10 for row in report["observations"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("sleeper_identity_verified", False),
        ("sleeper_id", ""),
        ("kickoff", None),
        ("team", "UNKNOWN"),
        ("opponent", "KC"),
        ("kickoff", NOW),
    ],
)
async def test_unverified_input_has_no_provider_calls(field, value):
    service, sleeper, odds = setup()
    row = identity()
    row[field] = value
    result = await collect(service, [row])
    assert result["provider_calls"] == 0
    assert result["players"][row["player_key"]]["unavailable_reasons"]
    sleeper.get_projections.assert_not_awaited()
    odds.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        {"subject": "Receiver 0 Jr"},
        {"provider_entity_id": None},
        {"event_id": ""},
        {
            "event": {
                "home_team": "KC",
                "away_team": "BUF",
                "commence_time": (KICKOFF + timedelta(hours=1)).isoformat(),
            }
        },
        {"event": {"home_team": "KC", "away_team": "NYJ", "commence_time": KICKOFF.isoformat()}},
    ],
)
async def test_provider_identity_requires_exact_fullname_game_and_nonempty_id(mutation):
    service, _, odds = setup()
    bad = quotes()
    for quote in bad:
        quote.update(mutation)
    odds.side_effect = None
    odds.return_value = {"results": bad}
    report = (await collect(service))["players"]["461.p.0"]
    assert not report["available"]
    assert "provider_identity_or_game_missing" in report["unavailable_reasons"]


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", [" (KC)", " (kc)", "  (KC)  "])
async def test_exact_provider_name_with_verified_team_suffix_retains_player_identity(suffix):
    service, _, odds = setup()
    odds.side_effect = None
    odds.return_value = {"results": [{**row, "subject": "Receiver 0" + suffix} for row in quotes()]}
    report = (await collect(service))["players"]["461.p.0"]
    assert report["available"]
    assert report["player_id"] == "prop0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subject",
    [
        "Receiver 0 (BUF)",
        "Receiver 0 (XYZ)",
        "Receiver 0 Jr (KC)",
        "Receiver 0 (KC) Jr",
        "Receiver-0 (KC)",
    ],
)
async def test_provider_suffix_never_overrides_conflicting_team_or_full_name(subject):
    service, _, odds = setup()
    odds.side_effect = None
    odds.return_value = {"results": [{**row, "subject": subject} for row in quotes()]}
    report = (await collect(service))["players"]["461.p.0"]
    assert not report["available"]
    assert "provider_identity_or_game_missing" in report["unavailable_reasons"]


@pytest.mark.asyncio
async def test_ambiguous_identity_and_explicit_id_constraint():
    service, _, odds = setup()
    bad = quotes()
    for quote in bad:
        quote["provider_entity_id"] = "other"
    odds.side_effect = None
    odds.return_value = {"results": quotes() + bad}
    report = (await collect(service))["players"]["461.p.0"]
    assert "ambiguous_provider_identity" in report["unavailable_reasons"]
    row = identity()
    row["provider_entity_id"] = "prop0"
    report = (await collect(service, [row]))["players"]["461.p.0"]
    assert report["player_id"] == "prop0"


@pytest.mark.asyncio
async def test_ranking_fallback_and_missing_stat_are_not_raw_forecasts():
    service, sleeper, _ = setup()
    sleeper.get_projections.return_value = {
        "0": {"projection_source": "fallback_ranking", "rec_yd": 70}
    }
    report = (await collect(service))["players"]["461.p.0"]
    assert report["baseline_stats"] == {}
    assert report["baseline_source"] is None
    assert not report["available"]


@pytest.mark.asyncio
async def test_cache_preserves_original_fetch_time_and_does_not_mutate_source():
    service, sleeper, odds = setup()
    raw = copy.deepcopy(sleeper.get_projections.return_value)
    first = await collect(service)
    service.now = lambda: NOW + timedelta(seconds=20)
    second = await collect(service)
    assert second["provider_calls"] == 0
    assert second["players"]["461.p.0"]["source_fetched_at"]["projections"] == NOW.isoformat()
    assert second["players"]["461.p.0"]["observations"][0]["known_at"] == NOW.isoformat()
    assert sleeper.get_projections.return_value == raw
    assert first["players"] is not second["players"]
    assert odds.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"current_week": 11},
        {"as_of": NOW - timedelta(days=1)},
        {"as_of": datetime(2026, 11, 3)},
        {"week": True},
    ],
)
async def test_no_historical_asof_or_unverified_live_period(changes):
    service, _, _ = setup()
    with pytest.raises(ValueError):
        await collect(service, **changes)


@pytest.mark.asyncio
async def test_provider_failure_is_partial_and_does_not_expose_exception_secrets():
    service, sleeper, _ = setup()
    sleeper.get_player_stats.side_effect = RuntimeError("synthetic-private-token")
    result = await collect(service)
    assert "stats_fetch_failed" in result["warnings"]
    assert "synthetic-private-token" not in str(result)
    assert result["players"]["461.p.0"]["observations"] == []


@pytest.mark.asyncio
async def test_provider_envelope_failure_is_not_reported_as_bad_player_identity():
    service, _, odds = setup()
    odds.side_effect = None
    odds.return_value = {
        "status": "partial",
        "results": [],
        "error": {
            "code": "invalid_response",
            "stage": "event:public-game",
            "message": "synthetic-private-token",
            "http_status": 200,
        },
        "unmatched": [{"query": "Receiver 0", "reason": "no_market"}],
    }
    result = await collect(service)
    report = result["players"]["461.p.0"]
    assert report["unavailable_reasons"] == ["odds_provider_failure"]
    assert report["odds_provider"]["error"] == {
        "code": "invalid_response",
        "stage": "event_odds",
        "http_status": 200,
    }
    assert report["odds_provider"]["result_count"] == 0
    assert report["odds_provider"]["unmatched_reasons"] == ["no_market"]
    assert "synthetic-private-token" not in str(result)


@pytest.mark.asyncio
async def test_partial_provider_failure_preserves_successful_exact_player_quotes():
    service, _, odds = setup()
    odds.side_effect = None
    odds.return_value = {
        "status": "partial",
        "results": quotes(),
        "error": {"code": "provider_timeout", "stage": "event:other-game"},
    }
    report = (await collect(service))["players"]["461.p.0"]
    assert report["available"]
    assert report["odds_provider"]["error"]["code"] == "provider_timeout"
    assert report["unavailable_reasons"] == ["odds_provider_failure"]


def test_verified_sleeper_identity_requires_catalog_name_and_team():
    player = SimpleNamespace(sleeper_id="1", name="Receiver One", team="KC")
    catalog = {"1": {"full_name": "Receiver One", "team": "KC"}}
    assert verified_sleeper_identity(player, catalog) == "1"
    catalog["1"]["team"] = "BUF"
    assert verified_sleeper_identity(player, catalog) is None
    catalog["1"].update(team="KC", full_name="Receiver Two")
    assert verified_sleeper_identity(player, catalog) is None


def test_context_patch_preserves_provenance_and_copies():
    context = {"source_provenance": {"provider": "Yahoo"}, "week": 10}
    report = {"baseline_stats": {"receptions": 5}}
    result = projection_context_with_inputs(context, report)
    result["source_provenance"]["provider"] = "changed"
    result["weekly_projection_inputs"]["baseline_stats"]["receptions"] = 9
    assert context["source_provenance"]["provider"] == "Yahoo"
    assert report["baseline_stats"]["receptions"] == 5


@pytest.mark.asyncio
async def test_collected_live_observations_feed_model_without_fabricated_game_dates():
    from src.services.performance_market_model import estimate_current_market_adjustment

    service, _, _ = setup()
    report = (await collect(service))["players"]["461.p.0"]
    result = estimate_current_market_adjustment(
        report["market_evidence"],
        report["observations"],
        event_id=report["event_id"],
        player_id=report["player_id"],
        kickoff=KICKOFF,
        as_of=NOW,
        scoring_coefficients=report["scoring_coefficients"],
        baseline_stats=report["baseline_stats"],
        baseline_source=report["baseline_source"],
        target_season=2026,
        target_week=10,
        current_period_verified=True,
    )
    assert result["available"]
    assert result["delta_points"] is not None
    assert abs(result["delta_points"]) <= 2
    assert "provisional" in result["model_status"]


@pytest.mark.asyncio
async def test_budget_exhaustion_is_explicit_and_bounded():
    service, _, odds = setup(max_calls=2)
    result = await collect(service)
    assert result["provider_calls"] == 2
    assert "provider_call_budget_exhausted" in result["warnings"]
    assert not result["players"]["461.p.0"]["available"]
    odds.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_expiry_refetches_and_bound_is_honored():
    service, sleeper, odds = setup(cache_size=24)
    await collect(service)
    service.now = lambda: NOW + timedelta(seconds=61)
    await collect(service)
    assert sleeper.get_projections.await_count == 2
    assert odds.await_count == 2
    assert len(service._cache) <= 24


@pytest.mark.asyncio
async def test_duplicate_sleeper_binding_is_not_shared_between_yahoo_players():
    service, _, odds = setup(2)
    rows = [identity(0), identity(1)]
    rows[1]["sleeper_id"] = rows[0]["sleeper_id"]
    result = await collect(service, rows)
    assert all(not report["available"] for report in result["players"].values())
    odds.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_stat_never_becomes_zero_and_cross_period_rows_rejected():
    service, sleeper, _ = setup()
    sleeper.get_player_stats.side_effect = lambda season, week: {
        "0": {
            "stats_source": "sleeper_api",
            "rec_yd": None,
            "season": season,
            "week": 10,
        }
    }
    report = (await collect(service))["players"]["461.p.0"]
    assert report["observations"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [10**400, -(10**400), float("inf"), float("nan"), True])
async def test_invalid_numeric_stats_do_not_abort_roster_or_erase_other_components(invalid):
    service, sleeper, _ = setup(2)
    sleeper.get_projections.return_value["0"]["rec_yd"] = invalid
    sleeper.get_player_stats.side_effect = lambda season, week: {
        "0": {
            "stats_source": "sleeper_api",
            "season": season,
            "week": week,
            "rec_yd": invalid,
            "rec": 0,
        },
        "1": {
            "stats_source": "sleeper_api",
            "season": season,
            "week": week,
            "rec_yd": 50,
            "rec": 3,
        },
    }
    result = await collect(service, [identity(0), identity(1)])
    invalid_report = result["players"]["461.p.0"]
    valid_report = result["players"]["461.p.1"]
    assert invalid_report["baseline_stats"] == {"receptions": 5.0}
    assert all(
        row["stat"] == "receptions" and row["value"] == 0 for row in invalid_report["observations"]
    )
    assert len(invalid_report["observations"]) == 9
    assert valid_report["baseline_stats"]["receiving_yards"] == 70
    assert len(valid_report["observations"]) == 18
    assert valid_report["available"]


def game_quotes():
    rows = quotes()
    for quote, side in zip(rows, ("Over", "Under")):
        quote.update(
            market_key="totals", subject=side, selection=side, line=45.5, provider_entity_id=None
        )
        quote["event"]["away_team_key"] = "buffalo_bills"
    return rows


@pytest.mark.asyncio
async def test_baseline_only_collects_genuine_all_stat_means_without_odds_or_history():
    service, sleeper, odds = setup()
    sleeper.get_projections.return_value["0"].update(rush_td=0.2, rec_td=0.4)
    report = (await collect(service, include_odds=False))["players"]["461.p.0"]
    assert report["baseline_stats"]["rushing_touchdowns"] == 0.2
    assert report["baseline_stats"]["receiving_touchdowns"] == 0.4
    assert report["baseline_source"] == "sleeper_api"
    assert report["available"]
    assert report["observations"] == []
    assert report["input_scope"] == "baseline_only_odds_disabled"
    odds.assert_not_awaited()
    sleeper.get_player_stats.assert_not_awaited()
    sleeper.get_projections.assert_awaited_once_with(2026, 10)


@pytest.mark.asyncio
async def test_game_only_quotes_bind_event_without_fabricating_player_identity():
    service, _, odds = setup()
    odds.side_effect = None
    odds.return_value = {"results": game_quotes()}
    report = (await collect(service))["players"]["461.p.0"]
    assert report["event_id"] == "e1"
    assert report["event_team_key"] == "kansas_city_chiefs"
    assert len(report["game_quotes"]) == 2
    assert "player_id" not in report
    assert "market_evidence" not in report
    assert report["baseline_stats"]["receiving_yards"] == 70
    arguments = odds.call_args.kwargs
    assert arguments["teams"] == ["KC"]
    assert set(arguments["markets"]) >= {"totals", "spreads", "h2h", "player_reception_yds"}


@pytest.mark.asyncio
async def test_game_quotes_deduplicate_team_and_player_query_copies():
    service, _, odds = setup()
    first = game_quotes()
    duplicates = copy.deepcopy(first)
    for quote in first:
        quote.update(query="Receiver 0", entity_type="player", matched_name="Receiver 0")
    for quote in duplicates:
        quote.update(query="KC", entity_type="team", matched_name="Chiefs")
    odds.side_effect = None
    odds.return_value = {"results": first + duplicates + quotes()}
    report = (await collect(service))["players"]["461.p.0"]
    assert len(report["game_quotes"]) == 2
    assert report["player_id"] == "prop0"
    assert report["market_evidence"]["available"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("event_id", "other"), ("scope", "season")])
async def test_game_quotes_explicit_event_constraint_and_scope(field, value):
    service, _, odds = setup()
    rows = game_quotes()
    for quote in rows:
        quote[field] = value
    odds.side_effect = None
    odds.return_value = {"results": rows}
    row = identity()
    row["event_id"] = "e1"
    report = (await collect(service, [row]))["players"]["461.p.0"]
    assert not report.get("game_quotes")
    assert not report.get("event_id")


@pytest.mark.asyncio
async def test_ambiguous_game_quotes_do_not_choose_event():
    service, _, odds = setup()
    duplicate = game_quotes()
    for quote in duplicate:
        quote["event_id"] = "e2"
    odds.side_effect = None
    odds.return_value = {"results": game_quotes() + duplicate}
    report = (await collect(service))["players"]["461.p.0"]
    assert "ambiguous_game_market_event" in report["unavailable_reasons"]
    assert not report.get("event_id")
    assert not report.get("game_quotes")
