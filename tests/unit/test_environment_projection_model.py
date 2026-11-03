"""Synthetic checks for explicitly provisional weather component arithmetic."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.services.environment_projection_model import (
    EnvironmentRuleConfig,
    estimate_environment_adjustment,
)

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
KICKOFF = NOW + timedelta(hours=3)


def evidence(mph=20):
    return {
        "available": True,
        "game_id": "game-1",
        "venue": {
            "stadium_id": "stadium",
            "source": "verified-venue",
            "exposure": "exposed",
            "verified_at": NOW.isoformat(),
        },
        "source": {
            "kind": "forecast",
            "provider": "NWS",
            "issued_at": NOW.isoformat(),
            "fetched_at": NOW.isoformat(),
        },
        "window": {"start": KICKOFF.isoformat(), "end": (KICKOFF + timedelta(hours=3)).isoformat()},
        "forecast_periods": [
            {
                "start": (KICKOFF + timedelta(hours=h)).isoformat(),
                "end": (KICKOFF + timedelta(hours=h + 1)).isoformat(),
                "sustained_wind_m_s": {"minimum": mph * 0.44704, "maximum": mph * 0.44704},
                "precipitation_probability": 1.0,
                "precipitation_amount_mm": None,
                "temperature_c": -15,
            }
            for h in range(3)
        ],
    }


def estimate(weather=None, **kwargs):
    args = {
        "event_id": "game-1",
        "kickoff": KICKOFF,
        "as_of": NOW,
        "baseline_stats": {"passing_yards": 200, "receiving_yards": 80, "receptions": 6},
        "baseline_source": "sleeper_api",
        "scoring_coefficients": {"passing_yards": 0.04, "receiving_yards": 0.1, "receptions": 1},
    }
    args.update(kwargs)
    return estimate_environment_adjustment(weather if weather is not None else evidence(), **args)


@pytest.mark.parametrize(
    "mph,reduction", [(0, 0), (14.99, 0), (15, 0.025), (20, 0.05), (25, 0.1), (40, 0.1)]
)
def test_wind_rules_and_point_cap(mph, reduction):
    report = estimate(evidence(mph), config=EnvironmentRuleConfig(max_points=10))
    assert report["rules"]["wind_reduction"] == reduction
    assert report["total_adjustment_points"] == pytest.approx(-22 * reduction)
    assert report["heuristic_not_calibrated"]
    for row in report["candidate_components"]:
        assert row["stat_delta"] == pytest.approx(-row["baseline_stat"] * reduction)
        assert row["delta_points"] == pytest.approx(row["stat_delta"] * row["scoring_coefficient"])


def test_raw_inputs_unchanged_shared_absolute_budget_and_idempotence():
    weather, baseline = evidence(25), {"passing_yards": 200, "receiving_yards": 80, "receptions": 6}
    original = copy.deepcopy((weather, baseline))
    a = estimate(weather, baseline_stats=baseline)
    b = estimate(weather, baseline_stats=baseline)
    assert a == b
    assert (weather, baseline) == original
    assert sum(abs(c["delta_points"]) for c in a["candidate_components"]) == pytest.approx(1)
    assert a["total_adjustment_points"] == pytest.approx(-1)


def test_chance_unverified_summary_and_temperature_cannot_establish_rain_severity():
    weather = evidence(0)
    for p in weather["forecast_periods"]:
        p["summary"] = "Heavy rain"
    report = estimate(weather)
    assert report["total_adjustment_points"] == 0
    assert any("Rain severity unknown" in s for s in report["limitations"])


@pytest.mark.parametrize("kind", ["intensity", "amount"])
def test_explicit_heavy_rain(kind):
    weather = evidence(0)
    for p in weather["forecast_periods"]:
        if kind == "intensity":
            p["rain_intensity_mm_per_hour"] = 8
        else:
            p.update(precipitation_amount_mm=8, precipitation_type="rain")
    report = estimate(weather)
    assert report["rules"]["rain_reduction"] == 0.025
    assert report["total_adjustment_points"] == pytest.approx(-0.55)


def test_generic_precipitation_amount_cannot_be_assumed_rain():
    weather = evidence(0)
    for p in weather["forecast_periods"]:
        p["precipitation_amount_mm"] = 20
    assert estimate(weather)["total_adjustment_points"] == 0


def test_incomplete_wind_cannot_promote_other_hours_or_gusts():
    weather = evidence(25)
    weather["forecast_periods"][1]["sustained_wind_m_s"] = None
    weather["forecast_periods"][1]["gust_wind_m_s"] = {"minimum": 30, "maximum": 30}
    assert estimate(weather)["total_adjustment_points"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda w: w.update(game_id="different"),
        lambda w: w.update(available=False),
        lambda w: w["venue"].update(exposure="unknown"),
        lambda w: w["venue"].update(verified_at=(NOW - timedelta(days=2)).isoformat()),
        lambda w: w["source"].update(issued_at=(NOW - timedelta(hours=3)).isoformat()),
        lambda w: w["source"].update(fetched_at=(NOW + timedelta(seconds=1)).isoformat()),
        lambda w: w["source"].update(kind="observation"),
        lambda w: w["window"].update(start=(KICKOFF + timedelta(hours=1)).isoformat()),
        lambda w: w["forecast_periods"].pop(1),
        lambda w: w["forecast_periods"].append(copy.deepcopy(w["forecast_periods"][0])),
        lambda w: w["forecast_periods"][0].update(start="2026-11-03T15:00:00"),
    ],
)
def test_unverified_stale_or_ambiguous_evidence_fails_closed(mutation):
    weather = evidence()
    mutation(weather)
    report = estimate(weather)
    assert report["available"] is False
    assert report["total_adjustment_points"] == 0


def test_sheltered_is_explicit_noop_without_forecast():
    weather = evidence()
    weather["venue"]["exposure"] = "sheltered"
    weather.pop("source")
    report = estimate(weather)
    assert report["status"] == "not_applicable"
    assert report["reason"] == "verified_sheltered_venue"


def test_started_game_and_provider_fallback_rejected():
    assert estimate(as_of=KICKOFF)["available"] is False
    assert estimate(baseline_source="fallback_ranking")["available"] is False


def test_fresh_relevant_props_suppress_all_weather():
    report = estimate(relevant_player_props_applied=True)
    assert report["status"] == "suppressed"
    assert report["candidate_components"] == []
    assert "overlapping_player_props" in report["reason"]


def test_explicit_scoring_only_no_inferred_reception_weight():
    report = estimate(scoring_coefficients={"receiving_yards": 0.1})
    assert [c["stat"] for c in report["candidate_components"]] == ["receiving_yards"]
    assert report["total_adjustment_points"] == pytest.approx(-0.4)


def test_nonfinite_inputs_cannot_serialize_infinite_candidates():
    report = estimate(
        baseline_stats={
            "passing_yards": float("inf"),
            "receiving_yards": 1e308,
            "receptions": True,
        },
        scoring_coefficients={"passing_yards": 0.04, "receiving_yards": 1e308, "receptions": 1},
    )
    assert report["available"] is False
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_points": float("inf")},
        {"max_points": True},
        {"rain_reduction": 2},
        {"wind_tiers_mph": ((20, 0.1), (15, 0.05))},
        {"max_forecast_age_seconds": 0},
    ],
)
def test_invalid_rule_configuration(kwargs):
    with pytest.raises(ValueError):
        EnvironmentRuleConfig(**kwargs)


@pytest.mark.parametrize(
    "summary,expected",
    [
        ("Heavy Rain", True),
        ("Heavy Rain Showers", True),
        ("heavy rain", True),
        ("Rain", False),
        ("Showers", False),
        ("Chance Heavy Rain", False),
        ("Heavy Rain Possible", False),
    ],
)
def test_explicit_nws_text_intensity_without_invented_amount(summary, expected):
    weather = evidence(0)
    weather["source"].update(
        sha256="a" * 64, forecast_url="https://api.weather.gov/gridpoints/OKX/1,1/forecast/hourly"
    )
    for period in weather["forecast_periods"]:
        period["summary"] = summary
    report = estimate(weather)
    assert (report["rules"]["rain_reduction"] > 0) is expected
    assert report["total_adjustment_points"] == pytest.approx(-0.55 if expected else 0)
    if expected:
        assert report["rules"]["rain_evidence_kinds"] == ["nws_explicit_text_intensity"] * 3
        assert all(p["precipitation_amount_mm"] is None for p in weather["forecast_periods"])


def test_cached_forecast_fetch_expired_even_if_issue_fresh():
    weather = evidence()
    weather["source"]["fetched_at"] = (NOW - timedelta(seconds=301)).isoformat()
    assert estimate(weather)["reason"] == "forecast_stale_or_future"


def test_report_exposes_fetch_time_and_verified_exposure():
    report = estimate()
    assert report["source"]["fetched_at"] == NOW.isoformat()
    assert report["evidence_as_of"] == NOW.isoformat()
    assert report["exposure_verified"] is True
