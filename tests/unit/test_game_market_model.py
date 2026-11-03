"""Synthetic full-game scoring-index tests; no provider calls or betting history."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from src.services.game_market_model import GameMarketConfig, estimate_game_market_adjustment

NOW = datetime(2026, 11, 3, 18, tzinfo=timezone.utc)
START = NOW + timedelta(hours=2)
EVENT = {
    "home_team_key": "buffalo_bills",
    "home_team": "Buffalo Bills",
    "away_team_key": "miami_dolphins",
    "away_team": "Miami Dolphins",
    "commence_time": START.isoformat(),
}


def quote(selection, line, *, market="totals", team=None, book="draftkings"):
    return {
        "event_id": "target",
        "scope": "next_game",
        "event": deepcopy(EVENT),
        "bookmaker_key": book,
        "market_key": market,
        "market_team": team,
        "market_team_source": "provider",
        "line_type": "main",
        "line_type_source": "provider",
        "selection": selection,
        "line": line,
        "price": -110,
        "odds_format": "american",
        "odds_format_source": "provider",
        "period": "full_game",
        "period_source": "provider",
        "provider_observed_at": NOW.isoformat(),
        "quote_fetched_at": NOW.isoformat(),
    }


def team_total(points=24.5, *, team="buffalo_bills", book="draftkings"):
    return [
        quote("Over", points, team=team, book=book),
        quote("Under", points, team=team, book=book),
    ]


def game_lines(total=47.5, home_spread=-3.5, *, book="draftkings"):
    return [
        quote("Over", total, book=book),
        quote("Under", total, book=book),
        quote("Buffalo Bills", home_spread, market="spreads", book=book),
        quote("Miami Dolphins", -home_spread, market="spreads", book=book),
    ]


def history(points=None, *, team="buffalo_bills"):
    return [
        {
            "team_key": team,
            "game_id": f"past-{index}",
            "points": value,
            "period": "full_game",
            "occurred_at": (NOW - timedelta(days=7 * (index + 1))).isoformat(),
            "known_at": NOW.isoformat(),
        }
        for index, value in enumerate([20] * 8 if points is None else points)
    ]


def estimate(rows=None, samples=None, **kwargs):
    params = {
        "event_id": "target",
        "team_key": "buffalo_bills",
        "kickoff": START,
        "as_of": NOW,
        "baseline_stats": {"passing_touchdowns": 2, "rushing_touchdowns": 0.5},
        "scoring_coefficients": {"passing_touchdowns": 4, "rushing_touchdowns": 6},
        "baseline_source": "sleeper_api",
    }
    params.update(kwargs)
    return estimate_game_market_adjustment(
        team_total() if rows is None else rows, history() if samples is None else samples, **params
    )


def test_direct_team_index_scales_only_explicit_td_fantasy_contribution():
    rows, samples = team_total(), history()
    before = deepcopy((rows, samples))
    result = estimate(rows, samples)
    assert result["available"] is True and result["applied"] is False
    assert result["team_scoring_index"] == 24.5
    assert result["historical_team_points_mean"] == 20
    assert result["delta_points"] == pytest.approx((2 * 4 + 0.5 * 6) * (24.5 / 20 - 1) * 0.25)
    assert result["model_status"] == "provisional_heuristic_not_empirically_validated"
    assert all(row["source"] == "direct_team_total" for row in result["book_indices"])
    assert (rows, samples) == before


def test_spread_orientation_and_home_away_are_correct_for_favorite_and_underdog():
    rows = game_lines()
    home = estimate(rows)
    away = estimate(rows, history(team="miami_dolphins"), team_key="miami_dolphins")
    assert home["team_scoring_index"] == 25.5
    assert away["team_scoring_index"] == 22
    assert home["delta_points"] > away["delta_points"]
    assert estimate(game_lines(home_spread=3.5))["team_scoring_index"] == 22


def test_integer_lines_remain_threshold_indices_not_push_adjusted_probabilities():
    result = estimate(game_lines(total=47, home_spread=-3))
    assert result["available"] is True
    assert result["team_scoring_index"] == 25
    assert all("probabilities" not in row for row in result["book_indices"])


def test_direct_team_total_precedes_derivation_once_per_book():
    result = estimate(team_total(22.5) + game_lines())
    assert result["team_scoring_index"] == 22.5
    assert result["book_count"] == 1


def test_consensus_is_robust_and_does_not_claim_independent_book_samples():
    result = estimate(
        team_total(20.5) + team_total(22.5, book="fanduel") + team_total(100.5, book="bovada")
    )
    assert result["team_scoring_index"] == 22.5
    assert result["book_count"] == 3
    assert result["independent_book_sample_size"] is None


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"event_id": "other"}, "event_or_scope_mismatch"),
        ({"scope": "season"}, "event_or_scope_mismatch"),
        ({"period": "first_half"}, "unverified_full_game_period"),
        ({"period_source": "inferred"}, "unverified_full_game_period"),
        ({"line_type": "alternate"}, "unverified_main_line"),
        ({"line_type_source": "unavailable"}, "unverified_main_line"),
        ({"market_team_source": "unavailable"}, "game_vs_team_total_unverified"),
        ({"market_team": "Unknown Team"}, "team_total_identity_unverified"),
        ({"market_suspended_at": NOW.isoformat()}, "market_suspended"),
        ({"bookmaker_key": "prizepicks"}, "unverified_single_leg_pricing"),
        ({"quote_fetched_at": (NOW + timedelta(seconds=1)).isoformat()}, "invalid_quote_time"),
        ({"provider_observed_at": (NOW - timedelta(hours=1)).isoformat()}, "stale_quote"),
        ({"last_change_at": "bad"}, "invalid_quote_time"),
        ({"odds_format_source": "guessed"}, "unverified_odds_format"),
        ({"price": float("nan")}, "invalid_price"),
    ],
)
def test_bad_or_ambiguous_game_quote_does_not_change_baseline(change, reason):
    rows = team_total()
    for row in rows:
        row.update(change)
    result = estimate(rows)
    assert result["available"] is False
    assert result["delta_points"] is None
    assert any(row["reason"] == reason for row in result["rejected"])


def test_game_total_cannot_masquerade_as_a_team_total_or_vice_versa():
    assert estimate([quote("Over", 47.5), quote("Under", 47.5)])["available"] is False
    rows = team_total(team="miami_dolphins")
    assert estimate(rows)["available"] is False
    rows = [quote("Over", 24.5, market="team_totals"), quote("Under", 24.5, market="team_totals")]
    result = estimate(rows)
    assert any(row["reason"] == "missing_team_total_team" for row in result["rejected"])


def test_incomplete_conflicting_or_wrongly_oriented_pairs_fail_closed():
    assert estimate(team_total()[:1])["available"] is False
    assert estimate(team_total() + team_total(30.5))["available"] is False
    rows = game_lines()
    rows[-1]["line"] = 3
    assert estimate(rows)["available"] is False
    rows = game_lines()
    rows[-1]["event"]["home_team_key"], rows[-1]["event"]["away_team_key"] = (
        "miami_dolphins",
        "buffalo_bills",
    )
    result = estimate(rows)
    assert any(row["reason"] == "conflicting_event_orientation" for row in result["rejected"])


def test_different_snapshots_cannot_join_total_and_spread():
    rows = game_lines()
    for row in rows[2:]:
        row["quote_fetched_at"] = (NOW - timedelta(seconds=1)).isoformat()
        row["provider_observed_at"] = (NOW - timedelta(seconds=1)).isoformat()
    assert estimate(rows)["available"] is False


def test_prop_adjustment_prevents_layering_and_started_games_are_excluded():
    assert (
        estimate(player_prop_adjustment_available=True)["rejected"][0]["reason"]
        == "player_prop_adjustment_takes_precedence"
    )
    assert estimate(as_of=START)["rejected"][0]["reason"] == "game_started"
    assert estimate(baseline_source="fallback_ranking")["available"] is False
    assert estimate(rows=[])["rejected"][0]["reason"] == "no_usable_game_market"


def test_documented_full_game_contract_requires_its_exact_reference():
    rows = team_total()
    for row in rows:
        row["period_source"] = "propline_documented_contract"
        row["period_reference"] = "https://prop-line.com/docs"
    assert estimate(rows)["available"] is True
    rows[0]["period_reference"] = "unverified"
    assert estimate(rows)["available"] is False


def test_actual_zero_scores_count_missing_or_negative_scores_do_not():
    result = estimate(samples=history([0, 10, 20, 30, 20, 20, 20, 40]))
    assert result["available"] is True
    assert result["sample_count"] == 8
    samples = history()
    samples[0]["points"] = None
    assert estimate(samples=samples)["available"] is False
    samples[0]["points"] = -1
    assert estimate(samples=samples)["available"] is False
    assert (
        estimate(samples=history([0] * 8))["rejected"][-1]["reason"]
        == "nonpositive_reported_team_mean"
    )


def test_future_wrong_team_and_duplicate_history_do_not_create_samples():
    samples = history()[:7]
    assert estimate(samples=samples + samples)["available"] is False
    samples = history()
    samples[0]["known_at"] = (NOW + timedelta(seconds=1)).isoformat()
    assert estimate(samples=samples)["available"] is False
    assert estimate(samples=history(team="miami_dolphins"))["available"] is False
    samples = history()
    other = deepcopy(samples[0])
    other["points"] = 40
    assert estimate(samples=samples + [other])["available"] is False


def test_current_verified_prior_week_history_needs_no_invented_game_time():
    samples = [
        {
            "team_key": "buffalo_bills",
            "points": 20,
            "period": "full_game",
            "season": 2026,
            "season_type": "regular",
            "week": index + 1,
            "period_id": f"2026:regular:{index+1}",
            "known_at": NOW.isoformat(),
        }
        for index in range(8)
    ]
    result = estimate(
        samples=samples, target_season=2026, target_week=9, current_period_verified=True
    )
    assert result["available"] is True
    assert result["sample_ids"][0] == "2026:regular:1"
    assert estimate(samples=samples, target_season=2026, target_week=9)["available"] is False


def test_bounded_td_only_effect_does_not_allocate_points_to_yards_or_receptions():
    result = estimate(
        team_total(100.5),
        baseline_stats={"passing_touchdowns": 4, "receiving_yards": 300, "receptions": 10},
        scoring_coefficients={"passing_touchdowns": 6, "receiving_yards": 0.1, "receptions": 1},
    )
    assert result["delta_points"] == 2
    assert [row["stat"] for row in result["components"]] == ["passing_touchdowns"]
    assert (
        estimate(baseline_stats={"receptions": 10}, scoring_coefficients={"receptions": 1})[
            "available"
        ]
        is False
    )
    assert estimate(config=GameMarketConfig(shrinkage=0))["delta_points"] == 0


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
def test_dated_team_history_cannot_bypass_explicit_period_validation(metadata, reason):
    samples = history()
    samples[0].update(metadata)
    result = estimate(
        samples=samples, target_season=2026, target_week=9, current_period_verified=True
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


def test_mixed_game_and_period_aliases_cannot_inflate_team_sample_count():
    samples = _with_period_aliases(history()[:7])
    stripped = deepcopy(samples[0])
    for field in ("season", "week", "season_type", "period_id"):
        stripped.pop(field)
    result = estimate(
        samples=samples + [stripped],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["available"] is False
    assert any(row.get("sample_count") == 7 for row in result["rejected"])
    samples = _with_period_aliases(history())
    result = estimate(
        samples=samples + [stripped],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["sample_count"] == 8


def test_conflicting_team_alias_periods_fail_closed():
    samples = _with_period_aliases(history())
    conflict = deepcopy(samples[0])
    conflict["week"], conflict["period_id"] = 2, "2026:regular:2"
    result = estimate(
        samples=samples + [conflict],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["available"] is False
    assert any(row["reason"] == "conflicting_team_history" for row in result["rejected"])


def test_partial_conflicting_week_on_same_team_game_is_not_ignored():
    samples = _with_period_aliases(history())
    conflict = deepcopy(samples[0])
    conflict.pop("period_id")
    conflict.pop("season_type")
    conflict["week"] = 2
    result = estimate(
        samples=samples + [conflict],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["available"] is False
    assert any(row["reason"] == "conflicting_team_history" for row in result["rejected"])


def test_unlinked_team_game_only_and_period_only_samples_do_not_assume_independence():
    samples = _with_period_aliases(history()[:7])
    for row in samples:
        row.pop("game_id")
    samples.append(history()[0])
    result = estimate(
        samples=samples, target_season=2026, target_week=9, current_period_verified=True
    )
    assert result["available"] is False
    assert any(row["reason"] == "unresolved_history_aliases" for row in result["rejected"])


def test_stripped_team_game_alias_value_conflict_fails_closed():
    samples = _with_period_aliases(history())
    conflict = deepcopy(samples[0])
    for field in ("season", "week", "season_type", "period_id"):
        conflict.pop(field)
    conflict["points"] = 40
    result = estimate(
        samples=samples + [conflict],
        target_season=2026,
        target_week=9,
        current_period_verified=True,
    )
    assert result["available"] is False
    assert any(row["reason"] == "conflicting_team_history" for row in result["rejected"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_samples": True},
        {"min_samples": 1},
        {"shrinkage": float("nan")},
        {"shrinkage": 2},
        {"max_points": -1},
        {"max_quote_age_seconds": 0},
    ],
)
def test_invalid_config_controls_rejected(kwargs):
    with pytest.raises(ValueError):
        GameMarketConfig(**kwargs)
