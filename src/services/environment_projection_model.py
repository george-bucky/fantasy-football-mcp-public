"""Transparent provisional weather component rules, never a calibrated forecast.

Wind tiers use the minimum sustained wind throughout the verified game window:
15/20/25 mph reduce supported passing/receiving components by 2.5/5/10%.
Verified rain at >=7.5 mm/hour or an explicit NWS "Heavy Rain" / "Heavy
Rain Showers" forecast reduces those components by 2.5%. Text-derived intensity
is labeled separately and never converted to a fabricated rainfall amount. Chance
of precipitation and generic rain summaries cannot establish heavy rain. Concurrent rules
use the strongest reduction, not their sum. Defaults and the one-point shared
budget are configurable safeguards, not empirical estimates of provider error;
provider projections may already reflect weather. No temperature-only rule.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

MODEL_VERSION = "weather_component_rules_v1_provisional"
SUPPORTED_STATS = ("passing_yards", "receiving_yards", "receptions")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _time(value: Any) -> datetime | None:
    try:
        result = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
        if result.tzinfo is None or result.utcoffset() is None:
            return None
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class EnvironmentRuleConfig:
    """Explicit heuristic controls; no fitted accuracy or causal claims."""

    wind_tiers_mph: tuple[tuple[float, float], ...] = ((15.0, 0.025), (20.0, 0.05), (25.0, 0.10))
    heavy_rain_mm_per_hour: float = 7.5
    rain_reduction: float = 0.025
    max_points: float = 1.0
    max_fetch_age_seconds: float = 300
    max_forecast_age_seconds: float = 7200
    max_venue_age_seconds: float = 86400

    def __post_init__(self) -> None:
        for value in (
            self.heavy_rain_mm_per_hour,
            self.max_fetch_age_seconds,
            self.max_forecast_age_seconds,
            self.max_venue_age_seconds,
        ):
            if _number(value) is None or value <= 0:
                raise ValueError("Weather thresholds and freshness must be positive finite numbers")
        if (
            _number(self.max_points) is None
            or self.max_points < 0
            or _number(self.rain_reduction) is None
            or not 0 <= self.rain_reduction <= 1
        ):
            raise ValueError("Invalid weather budget or reduction")
        previous_threshold = previous_reduction = -1.0
        for threshold, reduction in self.wind_tiers_mph:
            if (
                _number(threshold) is None
                or _number(reduction) is None
                or threshold < 0
                or not 0 <= reduction <= 1
                or threshold <= previous_threshold
                or reduction < previous_reduction
            ):
                raise ValueError(
                    "Wind tiers must have increasing thresholds and nondecreasing reductions"
                )
            previous_threshold, previous_reduction = threshold, reduction


def estimate_environment_adjustment(
    weather_evidence: Mapping[str, Any],
    *,
    event_id: str,
    kickoff: datetime,
    as_of: datetime,
    baseline_stats: Mapping[str, Any],
    baseline_source: str | None,
    scoring_coefficients: Mapping[str, Any],
    relevant_player_props_applied: bool = False,
    config: EnvironmentRuleConfig | None = None,
) -> dict[str, Any]:
    """Report candidate stat/point deltas without mutating inputs or doing IO.

    Caller certifies genuine matching player/period Sleeper components with
    ``baseline_source='sleeper_api'`` and explicit Yahoo linear coefficients.
    Props flag means fresh usable relevant props actually applied, not mere odds
    availability. Suppression avoids adding an overlapping weather estimate.
    """
    config = config or EnvironmentRuleConfig()
    report: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "status": "unavailable",
        "available": False,
        "candidate_components": [],
        "total_adjustment_points": 0.0,
        "heuristic_not_calibrated": True,
        "limitations": [
            "Provisional configurable rules; providers may already account for weather",
            "Temperature alone has no configured effect",
        ],
        "provenance": {},
    }

    def stop(reason: str, *, status: str = "unavailable") -> dict[str, Any]:
        report.update(reason=reason, status=status)
        return report

    start, decision = _time(kickoff), _time(as_of)
    if start is None or decision is None or start <= decision:
        return stop("invalid_or_started_game")
    if (
        not isinstance(weather_evidence, Mapping)
        or not event_id
        or weather_evidence.get("game_id") != event_id
    ):
        return stop("weather_game_binding_mismatch")
    venue = weather_evidence.get("venue")
    if not isinstance(venue, Mapping) or not venue.get("stadium_id") or not venue.get("source"):
        return stop("venue_unverified")
    verified = _time(venue.get("verified_at"))
    if (
        verified is None
        or not 0 <= (decision - verified).total_seconds() <= config.max_venue_age_seconds
    ):
        return stop("venue_stale_or_future")
    report["provenance"]["venue"] = dict(venue)
    report["exposure_verified"] = venue.get("exposure") in {"exposed", "sheltered"}
    if venue.get("exposure") == "sheltered":
        return stop("verified_sheltered_venue", status="not_applicable")
    if venue.get("exposure") != "exposed":
        return stop("roof_exposure_unknown")
    if weather_evidence.get("available") is not True:
        return stop("weather_unavailable")
    source, window = weather_evidence.get("source"), weather_evidence.get("window")
    if (
        not isinstance(source, Mapping)
        or source.get("kind") != "forecast"
        or not isinstance(window, Mapping)
    ):
        return stop("forecast_provenance_missing")
    issued, fetched = _time(source.get("issued_at")), _time(source.get("fetched_at"))
    if (
        issued is None
        or fetched is None
        or not 0 <= (decision - issued).total_seconds() <= config.max_forecast_age_seconds
        or not 0 <= (decision - fetched).total_seconds() <= config.max_fetch_age_seconds
    ):
        return stop("forecast_stale_or_future")
    report["source"] = dict(source)
    report["evidence_as_of"] = fetched.isoformat()
    end = _time(window.get("end"))
    if (
        _time(window.get("start")) != start
        or end is None
        or not timedelta(hours=1) <= end - start <= timedelta(hours=6)
    ):
        return stop("forecast_window_mismatch")
    periods = weather_evidence.get("forecast_periods")
    if (
        not isinstance(periods, list)
        or not periods
        or any(not isinstance(p, Mapping) for p in periods)
    ):
        return stop("forecast_periods_unavailable")
    parsed = [(_time(p.get("start")), _time(p.get("end")), p) for p in periods]
    if any(
        a is None or b is None or not timedelta(0) < b - a <= timedelta(hours=1)
        for a, b, p in parsed
    ):
        return stop("forecast_window_incomplete_or_ambiguous")
    parsed.sort(key=lambda x: x[0])
    if (
        parsed[0][0] > start
        or parsed[-1][1] < end
        or any(left[1] != right[0] for left, right in zip(parsed, parsed[1:]))
    ):
        return stop("forecast_window_incomplete_or_ambiguous")
    parsed = [(a, b, p) for a, b, p in parsed if a < end and b > start]
    report["provenance"].update(
        source=dict(source),
        game_id=event_id,
        kickoff=start.isoformat(),
        assessed_at=decision.isoformat(),
    )
    if relevant_player_props_applied is True:
        return stop("weather_suppressed_overlapping_player_props", status="suppressed")
    if (
        baseline_source != "sleeper_api"
        or not isinstance(baseline_stats, Mapping)
        or not isinstance(scoring_coefficients, Mapping)
    ):
        return stop("genuine_sleeper_components_and_explicit_scoring_required")
    winds, rains, rain_kinds = [], [], []
    for a, b, p in parsed:
        wind = p.get("sustained_wind_m_s")
        low = _number(wind.get("minimum")) if isinstance(wind, Mapping) else None
        high = _number(wind.get("maximum")) if isinstance(wind, Mapping) else None
        winds.append(
            low / 0.44704 if low is not None and high is not None and 0 <= low <= high else None
        )
        # Only explicit rain measurements: generic precipitation could be snow.
        rate = _number(p.get("rain_intensity_mm_per_hour"))
        amount = _number(p.get("precipitation_amount_mm"))
        if (
            rate is None
            and p.get("precipitation_type") == "rain"
            and amount is not None
            and amount >= 0
        ):
            rate = amount / ((b - a).total_seconds() / 3600)
        if rate is not None and rate >= 0:
            rains.append(rate >= config.heavy_rain_mm_per_hour)
            rain_kinds.append("quantitative_rain_rate")
        elif (
            source.get("provider") == "NWS"
            and isinstance(source.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
            and isinstance(source.get("forecast_url"), str)
            and source["forecast_url"].startswith("https://api.weather.gov/gridpoints/")
            and isinstance(p.get("summary"), str)
            and re.fullmatch(r"heavy rain(?: showers)?", p["summary"].strip(), re.IGNORECASE)
        ):
            rains.append(True)
            rain_kinds.append("nws_explicit_text_intensity")
        else:
            rains.append(None)
            rain_kinds.append("unknown")
    wind_reduction = 0.0
    if all(w is not None for w in winds):
        for threshold, reduction in config.wind_tiers_mph:
            if min(winds) >= threshold:
                wind_reduction = reduction
    else:
        report["limitations"].append("Sustained wind unknown in part of game window")
    rain_reduction = config.rain_reduction if all(r is True for r in rains) else 0.0
    if any(r is None for r in rains):
        report["limitations"].append("Rain severity unknown; precipitation chance is not intensity")
    reduction = max(wind_reduction, rain_reduction)
    report["rules"] = {
        "wind_reduction": wind_reduction,
        "rain_reduction": rain_reduction,
        "rain_evidence_kinds": rain_kinds,
        "combination": "maximum_not_sum",
        "max_points": config.max_points,
    }
    report["available"] = True
    report["status"] = "no_effect"
    if reduction == 0:
        report["reason"] = "no_supported_adverse_rule_triggered_unknown_fields_retained"
        return report
    components = []
    for stat in SUPPORTED_STATS:
        baseline, coefficient = _number(baseline_stats.get(stat)), _number(
            scoring_coefficients.get(stat)
        )
        if baseline is None or baseline < 0 or coefficient is None:
            report["limitations"].append(
                f"{stat}: genuine baseline or explicit coefficient unavailable"
            )
            continue
        delta_stat = -baseline * reduction
        points = delta_stat * coefficient
        if not math.isfinite(points):
            report["limitations"].append(f"{stat}: nonfinite component rejected")
            continue
        components.append(
            {
                "stat": stat,
                "baseline_stat": baseline,
                "reduction_fraction": reduction,
                "candidate_stat_delta": delta_stat,
                "scoring_coefficient": coefficient,
                "uncapped_delta_points": points,
            }
        )
    # Scaled summation avoids overflow even for finite extreme inputs.
    largest = max((abs(c["uncapped_delta_points"]) for c in components), default=0.0)
    normalized_total = (
        math.fsum(abs(c["uncapped_delta_points"]) / largest for c in components) if largest else 0.0
    )
    scale = (
        min(1.0, (config.max_points / largest) / normalized_total)
        if largest and normalized_total
        else 1.0
    )
    for component in components:
        component["delta_points"] = component["uncapped_delta_points"] * scale
        component["stat_delta"] = component["candidate_stat_delta"] * scale
    report["candidate_components"] = components
    report["total_adjustment_points"] = math.fsum(c["delta_points"] for c in components)
    report["budget_scale"] = scale
    report["status"] = "candidate" if components else "unavailable"
    report["available"] = bool(components)
    return report
