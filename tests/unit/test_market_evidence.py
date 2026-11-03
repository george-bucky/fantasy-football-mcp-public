"""Synthetic quote-to-probability checks; no API, secrets or fitted model."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from src.services.market_evidence import assess_player_markets, implied_probability

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
KICKOFF = NOW + timedelta(hours=2)


def quote(side="Over", *, line=70.5, price=-110, book="book-a", market="player_reception_yds"):
    return {
        "event_id": "game-1",
        "provider_entity_id": "player-1",
        "scope": "next_game",
        "period": "full_game",
        "period_source": "provider",
        "event": {"commence_time": KICKOFF.isoformat()},
        "bookmaker_key": book,
        "market_key": market,
        "selection": side,
        "line": line,
        "price": price,
        "odds_format": "american",
        "odds_format_source": "provider",
        "pricing_semantics": "quoted_single_leg",
        "pricing_semantics_source": "provider",
        "quote_fetched_at": NOW.isoformat(),
        "provider_observed_at": (NOW - timedelta(seconds=30)).isoformat(),
    }


def assess(rows, **kwargs):
    return assess_player_markets(
        rows,
        event_id="game-1",
        player_id="player-1",
        kickoff=KICKOFF,
        as_of=kwargs.pop("as_of", NOW),
        **kwargs,
    )


@pytest.mark.parametrize(
    "price,fmt,expected",
    [
        (100, "american", 0.5),
        (-200, "american", 2 / 3),
        (300, "american", 0.25),
        (2.5, "decimal", 0.4),
    ],
)
def test_price_conversion_requires_explicit_format(price, fmt, expected):
    assert implied_probability(price, fmt) == pytest.approx(expected)


@pytest.mark.parametrize(
    "price,fmt",
    [
        (True, "american"),
        (float("nan"), "decimal"),
        (float("inf"), "decimal"),
        (1, "decimal"),
        (0, "american"),
        (2, "american"),
        (-110, "guess"),
    ],
)
def test_invalid_prices_fail_closed(price, fmt):
    with pytest.raises(ValueError):
        implied_probability(price, fmt)


def test_paired_quotes_produce_fair_constraint_not_mean_or_fantasy_points():
    rows = [quote(), quote("Under")]
    before = deepcopy(rows)
    result = assess(rows)
    assert rows == before
    assert result["available"] is True
    assert result["applied"] is False
    assert result["probabilities"][0]["probabilities"] == {"over": 0.5, "under": 0.5}
    constraint = result["quantile_constraints"][0]
    assert constraint["threshold"] == 70.5
    assert constraint["expected_stat"] is None
    assert result["expected_stat"] is None
    assert result["model_status"] == "unavailable_no_validated_distribution"
    assert result["coverage"]["complete_fantasy_projection"] is False


def test_book_consensus_keeps_thresholds_distinct_and_makes_no_independence_claim():
    rows = [
        quote(),
        quote("Under"),
        quote(price=-150, book="book-b"),
        quote("Under", price=120, book="book-b"),
        quote(line=75.5, book="book-c"),
        quote("Under", line=75.5, book="book-c"),
    ]
    result = assess(rows)
    assert len(result["quantile_constraints"]) == 2
    first = result["quantile_constraints"][0]
    assert first["book_count"] == 2
    assert first["independent_sample_size"] is None
    assert first["fair_probability"] > 0.5
    assert len(result["raw_quotes"]) == 6


def test_prizepicks_synthetic_even_money_is_not_a_fair_probability_pair():
    rows = [quote(price=100, book="prizepicks"), quote("Under", price=100, book="prizepicks")]
    result = assess(rows)
    assert result["available"] is False
    assert result["quantile_constraints"] == []
    assert {item["reason"] for item in result["rejected"]} == {
        "synthetic_price_not_single_leg_odds"
    }


def test_real_even_money_sportsbook_pair_remains_valid_without_new_metadata():
    rows = [quote(price=100, book="draftkings"), quote("Under", price=100, book="draftkings")]
    for row in rows:
        row.pop("pricing_semantics")
        row.pop("pricing_semantics_source")
    result = assess(rows)
    assert result["available"] is True
    assert result["quantile_constraints"][0]["fair_probability"] == 0.5


@pytest.mark.parametrize("flag", ["synthetic_price", "is_synthetic", "price_is_synthetic"])
def test_explicit_synthetic_flag_overrides_real_book_and_quote_label(flag):
    rows = [quote(book="draftkings"), quote("Under", book="draftkings")]
    for row in rows:
        row[flag] = True
    result = assess(rows)
    assert result["available"] is False
    assert result["rejected"][0]["reason"] == "synthetic_price_not_single_leg_odds"


def test_unknown_book_without_pricing_provenance_fails_closed():
    rows = [quote(book="unknown-dfs"), quote("Under", book="unknown-dfs")]
    for row in rows:
        row.pop("pricing_semantics")
        row.pop("pricing_semantics_source")
    result = assess(rows)
    assert result["available"] is False
    assert result["rejected"][0]["reason"] == "unverified_pricing_semantics"


def test_underdog_real_prices_include_payout_multiplier_without_second_adjustment():
    rows = [quote(price=-135, book="underdog"), quote("Under", price=110, book="underdog")]
    for row in rows:
        row.pop("pricing_semantics")
        row.pop("pricing_semantics_source")
    rows[0]["payout_multiplier"] = 0.86
    rows[1]["payout_multiplier"] = 1.1
    result = assess(rows)
    assert result["available"] is True
    over = (135 / 235) / ((135 / 235) + (100 / 210))
    assert result["quantile_constraints"][0]["fair_probability"] == pytest.approx(over)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"event_id": "other"}, "event_mismatch"),
        ({"provider_entity_id": None}, "player_id_mismatch"),
        ({"scope": "season"}, "not_next_game"),
        ({"period_source": "inferred"}, "unverified_period"),
        ({"period": "first_half"}, "unverified_period"),
        ({"odds_format_source": "guessed"}, "unverified_odds_format"),
        ({"odds_format_source": []}, "unverified_odds_format"),
        ({"event": "not a verified event"}, "kickoff_mismatch"),
        (
            {"event": {"commence_time": (KICKOFF + timedelta(hours=1)).isoformat()}},
            "kickoff_mismatch",
        ),
        ({"market_key": "totals"}, "unsupported_player_market"),
        ({"market_key": []}, "unsupported_player_market"),
        ({"bookmaker_key": ""}, "missing_bookmaker"),
        ({"quote_fetched_at": None}, "missing_quote_time"),
        ({"provider_observed_at": "2026-11-03T18:00:00"}, "missing_quote_time"),
        ({"provider_observed_at": (NOW + timedelta(seconds=1)).isoformat()}, "future_quote"),
        ({"quote_fetched_at": (NOW + timedelta(seconds=1)).isoformat()}, "future_quote"),
        ({"provider_observed_at": (NOW - timedelta(minutes=10)).isoformat()}, "stale_quote"),
        ({"last_change_at": "malformed"}, "invalid_quote_time"),
        ({"price": float("nan")}, "invalid_price"),
        ({"line": 70}, "push_probability_unknown"),
        ({"line": -0.5}, "invalid_threshold_outcome"),
    ],
)
def test_unverified_or_inapplicable_quote_is_rejected(change, reason):
    row = quote()
    row.update(change)
    result = assess([row])
    assert result["available"] is False
    assert result["rejected"][0]["reason"] == reason


def test_game_already_started_cannot_create_pregame_evidence():
    result = assess([quote(), quote("Under")], as_of=KICKOFF)
    assert result["available"] is False
    assert {item["reason"] for item in result["rejected"]} == {"game_started"}


@pytest.mark.parametrize("marker", [NOW.isoformat(), False, True, 0, "malformed", []])
def test_suspended_or_malformed_suspension_marker_rejects_last_quoted_props(marker):
    rows = [quote(), quote("Under")]
    for row in rows:
        row["market_suspended_at"] = marker
    result = assess(rows)
    assert result["available"] is False
    assert all(row["reason"] == "market_suspended" for row in result["rejected"])


@pytest.mark.parametrize("marker", [None, ""])
def test_null_or_empty_suspension_marker_does_not_suspend_current_props(marker):
    rows = [quote(), quote("Under")]
    for row in rows:
        row["market_suspended_at"] = marker
    assert assess(rows)["available"] is True


def test_incomplete_or_conflicting_pair_cannot_have_margin_removed():
    assert assess([quote()])["rejected"][0]["reason"] == "incomplete_pair"
    result = assess([quote(), quote("Under"), quote(price=-120)])
    assert result["available"] is False
    assert result["rejected"][0]["reason"] == "conflicting_pair"
    # An exactly duplicated quote does not create another independent pair.
    result = assess([quote(), quote("Under"), quote()])
    assert len(result["probabilities"]) == 1


def test_noncontemporaneous_pair_is_rejected():
    under = quote("Under")
    under["quote_fetched_at"] = (NOW - timedelta(seconds=1)).isoformat()
    result = assess([quote(), under])
    assert result["rejected"][0]["reason"] == "conflicting_pair"


def test_anytime_touchdown_is_binary_probability_not_expected_touchdown_count():
    rows = [
        quote("Yes", line=None, price=120, market="player_anytime_td"),
        quote("No", line=None, price=-150, market="player_anytime_td"),
    ]
    result = assess(rows)
    assert result["probabilities"][0]["semantics"] == "probability_at_least_one_not_expected_count"
    assert result["quantile_constraints"][0]["expected_stat"] is None
    one_sided = assess([quote("Player Name", line=None, market="player_anytime_td")])
    assert one_sided["available"] is False
    assert one_sided["rejected"][0]["reason"] == "missing_exhaustive_td_pair"


def test_empty_partial_coverage_does_not_fabricate_missing_stats():
    result = assess([])
    assert result["available"] is False
    assert result["coverage"]["markets"] == []
    assert result["quantile_constraints"] == []
    assert result["expected_stat"] is None


def test_contradictory_same_book_thresholds_are_rejected():
    rows = [
        quote(line=60.5, price=150),
        quote("Under", line=60.5, price=-180),
        quote(line=80.5, price=-180),
        quote("Under", line=80.5, price=150),
    ]
    result = assess(rows)
    assert result["available"] is False
    assert result["probabilities"] == []
    assert result["rejected"][0]["reason"] == "non_monotone_thresholds"


def test_book_composition_cannot_create_contradictory_consensus_distribution():
    rows = [
        quote(line=60.5, price=150, book="book-a"),
        quote("Under", line=60.5, price=-180, book="book-a"),
        quote(line=80.5, price=-180, book="book-b"),
        quote("Under", line=80.5, price=150, book="book-b"),
    ]
    result = assess(rows)
    assert result["available"] is False
    assert len(result["probabilities"]) == 2
    assert result["quantile_constraints"] == []
    assert result["rejected"][0]["reason"] == "non_monotone_consensus"


def test_future_or_unknown_timestamp_cannot_be_used_for_asof_backtest():
    row = quote()
    row["quote_fetched_at"] = (NOW + timedelta(days=1)).isoformat()
    assert assess([row])["rejected"][0]["reason"] == "future_quote"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_age_seconds": 0},
        {"max_age_seconds": float("inf")},
        {"period": "first_half"},
        {"as_of": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_assessment_context_is_explicit(kwargs):
    with pytest.raises(ValueError):
        assess([], **kwargs)
