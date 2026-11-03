"""Current-quote/past-actual location-shift checks with synthetic data only."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from src.services.market_evidence import assess_player_markets
from src.services.performance_market_model import (
    LocationShiftConfig,
    estimate_current_market_adjustment,
)

NOW = datetime(2026, 11, 3, 18, tzinfo=timezone.utc)
START = NOW + timedelta(hours=2)
VALUES = [0, 0, 0, 0, 20, 20, 20, 100]


def quotes(*, line=30.5, market="player_reception_yds", over=-110, under=-110):
    return [
        {
            "event_id": "target",
            "provider_entity_id": "player",
            "scope": "next_game",
            "period": "full_game",
            "period_source": "provider",
            "event": {"commence_time": START.isoformat()},
            "bookmaker_key": "draftkings",
            "market_key": market,
            "selection": side,
            "line": line,
            "price": price,
            "odds_format": "american",
            "odds_format_source": "provider",
            "quote_fetched_at": NOW.isoformat(),
            "provider_observed_at": NOW.isoformat(),
        }
        for side, price in [("Over", over), ("Under", under)]
    ]


def evidence(rows=None):
    return assess_player_markets(
        quotes() if rows is None else rows,
        event_id="target",
        player_id="player",
        kickoff=START,
        as_of=NOW,
    )


def history(values=VALUES, *, stat="receiving_yards"):
    return [
        {
            "player_id": "player",
            "game_id": f"game-{index}",
            "stat": stat,
            "value": value,
            "period": "full_game",
            "occurred_at": (NOW - timedelta(days=7 * (index + 1))).isoformat(),
            "known_at": (NOW - timedelta(days=7 * (index + 1)) + timedelta(hours=5)).isoformat(),
        }
        for index, value in enumerate(values)
    ]


def estimate(*, market=None, observations=None, **kwargs):
    options = {
        "event_id": "target",
        "player_id": "player",
        "kickoff": START,
        "as_of": NOW,
        "scoring_coefficients": {"receiving_yards": 0.1},
        "baseline_stats": {"receiving_yards": 25},
        "baseline_source": "sleeper_api",
    }
    options.update(kwargs)
    return estimate_current_market_adjustment(
        evidence() if market is None else market,
        history() if observations is None else observations,
        **options,
    )


def test_current_line_fits_shifted_history_shape_not_line_as_mean():
    market, observations = evidence(), history()
    original = deepcopy((market, observations))
    result = estimate(market=market, observations=observations)
    assert result["available"] is True and result["applied"] is False
    component = result["components"][0]
    assert component["sample_count"] == 8  # Real zero-point stat observations remain observations.
    assert component["historical_mean"] == 20
    assert component["constraints"][0]["historical_quantile"] == 10
    assert component["market_implied_mean"] == 40.5
    assert component["market_implied_mean"] != 30.5
    assert result["delta_points"] == pytest.approx((40.5 - 25) * 0.25 * 0.1)
    assert "provisional" in result["model_status"]
    assert (market, observations) == original


def test_changed_upcoming_quote_changes_adjustment_without_past_odds():
    first = estimate()
    second = estimate(market=evidence(quotes(line=40.5)))
    assert second["delta_points"] > first["delta_points"]
    assert all("price" not in row for row in history())


def test_component_requires_real_current_baseline_and_explicit_scoring():
    assert estimate(baseline_source="fallback_ranking")["delta_points"] is None
    assert estimate(baseline_source=None)["delta_points"] is None
    assert estimate(baseline_stats={})["delta_points"] is None
    assert estimate(scoring_coefficients={})["delta_points"] is None
    assert estimate(scoring_coefficients={"receiving_yards": 0})["delta_points"] == 0


def test_all_history_and_quote_inputs_are_bound_to_exact_identity_and_asof():
    observations = history()
    observations[-1]["known_at"] = (NOW + timedelta(seconds=1)).isoformat()
    result = estimate(observations=observations)
    assert result["available"] is False
    assert any(item["reason"] == "future_history" for item in result["rejected"])
    observations = history()
    observations[-1]["player_id"] = "other"
    assert estimate(observations=observations)["available"] is False
    market = evidence()
    market["player_id"] = "other"
    assert estimate(market=market)["rejected"][0]["reason"] == "market_identity_mismatch"
    assert estimate(as_of=NOW + timedelta(minutes=10))["available"] is False


def test_raw_quotes_recomputed_instead_of_trusting_injected_consensus():
    market = evidence()
    market["quantile_constraints"][0]["threshold"] = 1e20
    assert estimate(market=market)["delta_points"] == estimate()["delta_points"]
    market["raw_quotes"] = []
    assert estimate(market=market)["delta_points"] is None


def test_duplicate_records_do_not_fabricate_adequate_appearances():
    observations = history()[:7]
    assert estimate(observations=observations + observations)["available"] is False
    observations = history()
    assert estimate(observations=observations + observations)["components"][0]["sample_count"] == 8
    conflicting = deepcopy(observations[0])
    conflicting["value"] = 42
    result = estimate(observations=observations + [conflicting])
    assert result["available"] is False
    assert any(item["reason"] == "conflicting_history" for item in result["rejected"])


def test_actual_negative_yards_are_valid_but_negative_receptions_are_not():
    result = estimate(
        market=evidence(quotes(market="player_rush_yds", line=9.5)),
        observations=history([-4, -2, 0, 2, 4, 6, 8, 10], stat="rushing_yards"),
        baseline_stats={"rushing_yards": 8},
        scoring_coefficients={"rushing_yards": 0.1},
    )
    assert result["available"] is True
    assert result["components"][0]["historical_mean"] == 3
    result = estimate(
        market=evidence(quotes(market="player_receptions", line=4.5)),
        observations=history([-1, 0, 1, 2, 3, 4, 5, 6], stat="receptions"),
        baseline_stats={"receptions": 4},
        scoring_coefficients={"receptions": 0.5},
    )
    assert result["available"] is False
    assert any(item["reason"] == "invalid_stat_value" for item in result["rejected"])


def test_count_distribution_shift_respects_zero_support_and_integrates_mean():
    result = estimate(
        market=evidence(quotes(market="player_receptions", line=1.5)),
        observations=history([0, 0, 0, 0, 4, 4, 4, 20], stat="receptions"),
        baseline_stats={"receptions": 4},
        scoring_coefficients={"receptions": 0.5},
    )
    component = result["components"][0]
    assert component["location_shift"] < 0
    assert (
        component["market_implied_mean"]
        > component["historical_mean"] + component["location_shift"]
    )
    assert component["market_implied_mean"] >= 0
    assert component["market_implied_mean"] == pytest.approx(3.72265625)
    assert component["support_transform"] == "floor_at_zero"


def test_configurable_point_budget_limits_absolute_components_not_only_net():
    rows = quotes(line=300.5) + quotes(market="player_rush_yds", line=300.5)
    result = estimate(
        market=evidence(rows),
        observations=history() + history(stat="rushing_yards"),
        baseline_stats={"receiving_yards": 0, "rushing_yards": 0},
        scoring_coefficients={"receiving_yards": 0.1, "rushing_yards": -0.1},
    )
    assert len(result["components"]) == 2
    assert sum(abs(row["point_delta"]) for row in result["components"]) == pytest.approx(2)
    assert result["delta_points"] == pytest.approx(0)
    assert result["point_budget_scale"] < 1
    assert estimate(config=LocationShiftConfig(shrinkage=0))["delta_points"] == 0
    assert estimate(config=LocationShiftConfig(max_points=0))["delta_points"] == 0


def test_history_variation_tail_and_numeric_overflow_fail_explicitly():
    assert estimate(observations=history([20] * 8))["available"] is False
    result = estimate(market=evidence(quotes(over=-10000, under=9000)))
    assert result["available"] is False
    assert any(row["reason"] == "unsupported_empirical_tail" for row in result["rejected"])
    result = estimate(
        observations=history([1e308, -1e308, 1e308, -1e308, 1e308, -1e308, 1e308, -1e308]),
        scoring_coefficients={"receiving_yards": 1e308},
        baseline_stats={"receiving_yards": 1e308},
    )
    assert result["available"] is False
    assert any(row["reason"] == "numeric_overflow" for row in result["rejected"])


def test_live_current_prior_week_mode_uses_real_period_ids_without_fake_game_times():
    observations = [
        {
            "player_id": "player",
            "stat": "receiving_yards",
            "value": value,
            "season": 2026,
            "season_type": "regular",
            "week": index + 1,
            "period_id": f"2026:regular:{index+1}",
            "known_at": NOW.isoformat(),
            "period": "full_game",
        }
        for index, value in enumerate(VALUES)
    ]
    result = estimate(
        observations=observations, target_season=2026, target_week=9, current_period_verified=True
    )
    assert result["available"] is True
    component = result["components"][0]
    assert component["sample_game_ids"] == []
    assert len(component["sample_ids"]) == 8
    assert component["sample_time_bases"] == ["verified_current_prior_week"]
    assert (
        estimate(observations=observations, target_season=2026, target_week=9)["available"] is False
    )
    assert (
        estimate(
            observations=observations,
            target_season=2026,
            target_week=9,
            current_period_verified="true",
        )["available"]
        is False
    )
    observations[0]["week"] = 9
    observations[0]["period_id"] = "2026:regular:9"
    assert (
        estimate(
            observations=observations,
            target_season=2026,
            target_week=9,
            current_period_verified=True,
        )["available"]
        is False
    )


def test_anytime_td_binary_probability_is_not_a_touchdown_count_estimate():
    rows = quotes(market="player_anytime_td", line=None)
    rows[0]["selection"], rows[1]["selection"] = "Yes", "No"
    result = estimate(market=evidence(rows))
    assert result["available"] is False
    assert any(row["reason"] == "unsupported_expected_stat" for row in result["rejected"])


@pytest.mark.parametrize(
    "metadata,reason",
    [
        (
            {"season": 2026, "week": 10, "season_type": "regular", "period_id": "2026:regular:10"},
            "future_history_period",
        ),
        ({"period_id": "2026:regular:10"}, "future_history_period"),
        ({"season": 2027, "week": 1}, "future_history_period"),
        ({"season": 2026, "week": 8, "period_id": "2026:regular:7"}, "conflicting_history_period"),
        ({"period_id": "invalid"}, "invalid_history_period"),
    ],
)
def test_dated_history_cannot_bypass_explicit_period_validation(metadata, reason):
    samples = history()
    samples[0].update(metadata)
    result = estimate(
        observations=samples, target_season=2026, target_week=9, current_period_verified=True
    )
    assert result["available"] is False
    assert any(row["reason"] == reason for row in result["rejected"])


def _with_period_aliases(samples):
    for index, row in enumerate(samples):
        row.update(
            {
                "season": 2026,
                "week": index + 1,
                "season_type": "regular",
                "period_id": f"2026:regular:{index+1}",
            }
        )
    return samples


def test_mixed_game_and_period_aliases_cannot_inflate_player_sample_count():
    samples = _with_period_aliases(history()[:7])
    stripped = deepcopy(samples[0])
    for field in ("season", "week", "season_type", "period_id"):
        stripped.pop(field)
    result = estimate(
        observations=samples + [stripped],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["available"] is False
    assert any(row.get("sample_count") == 7 for row in result["rejected"])
    samples = _with_period_aliases(history())
    result = estimate(
        observations=samples + [stripped],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["components"][0]["sample_count"] == 8
    assert len(result["components"][0]["sample_game_ids"]) == 8


def test_conflicting_alias_values_or_periods_fail_closed_per_stat():
    samples = _with_period_aliases(history())
    conflict = deepcopy(samples[0])
    conflict["week"], conflict["period_id"] = 2, "2026:regular:2"
    result = estimate(
        observations=samples + [conflict],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["available"] is False
    assert any(row["reason"] == "conflicting_history" for row in result["rejected"])
    conflict = deepcopy(samples[0])
    for field in ("season", "week", "season_type", "period_id"):
        conflict.pop(field)
    conflict["value"] = 999
    result = estimate(
        observations=samples + [conflict],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["available"] is False
    assert any(row["reason"] == "conflicting_history" for row in result["rejected"])


def test_history_alias_dedup_does_not_merge_distinct_stats():
    samples = _with_period_aliases(history()) + _with_period_aliases(history(stat="rushing_yards"))
    result = estimate(
        market=evidence(quotes() + quotes(market="player_rush_yds")),
        observations=samples,
        baseline_stats={"receiving_yards": 25, "rushing_yards": 25},
        scoring_coefficients={"receiving_yards": 0.1, "rushing_yards": 0.1},
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert len(result["components"]) == 2
    assert all(row["sample_count"] == 8 for row in result["components"])


def test_partial_conflicting_week_on_same_game_is_not_ignored():
    samples = _with_period_aliases(history())
    conflict = deepcopy(samples[0])
    conflict.pop("period_id")
    conflict.pop("season_type")
    conflict["week"] = 2
    result = estimate(
        observations=samples + [conflict],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["available"] is False
    assert any(row["reason"] == "conflicting_history" for row in result["rejected"])


def test_unlinked_game_only_and_period_only_samples_do_not_assume_independence():
    samples = _with_period_aliases(history()[:7])
    for row in samples:
        row.pop("game_id")
    samples.append(history()[0])
    result = estimate(
        observations=samples, target_season=2026, target_week=9, current_period_verified=True
    )
    assert result["available"] is False
    assert any(row["reason"] == "unresolved_history_aliases" for row in result["rejected"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_samples": 1},
        {"min_samples": True},
        {"history_days": 0},
        {"shrinkage": "0.25"},
        {"shrinkage": float("nan")},
        {"shrinkage": 1.1},
        {"max_points": -1},
        {"max_quote_age_seconds": 0},
    ],
)
def test_invalid_heuristic_controls_are_rejected(kwargs):
    with pytest.raises(ValueError):
        LocationShiftConfig(**kwargs)
