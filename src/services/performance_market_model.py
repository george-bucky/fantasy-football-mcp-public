"""Provisional current-prop location shifts anchored to genuine baseline stats.

Past actual stat observations supply distribution shape, not historical betting
prices. Interpolation between empirical mid-rank quantiles gives a continuous,
bounded approximation whose mean equals the sample mean. Translating that shape
to a current market probability/threshold estimates a current mean. The implied
mean is NOT the betting line. This is a transparent heuristic, not a calibrated
forecast or a claim that current providers omit market/weather information.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .market_evidence import assess_player_markets

MODEL_VERSION = "empirical_midrank_location_shift_v1_provisional"
SUPPORTED_STATS = frozenset(
    {"passing_yards", "passing_touchdowns", "rushing_yards", "receiving_yards", "receptions"}
)
NONNEGATIVE_STATS = frozenset({"passing_touchdowns", "receptions"})


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class LocationShiftConfig:
    """User-adjustable heuristic controls; these values are not fitted coefficients."""

    min_samples: int = 8
    history_days: int = 730
    shrinkage: float = 0.25
    max_points: float = 2.0
    max_quote_age_seconds: float = 300.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.min_samples, bool)
            or not isinstance(self.min_samples, int)
            or self.min_samples < 3
            or isinstance(self.history_days, bool)
            or not isinstance(self.history_days, int)
            or not 1 <= self.history_days <= 36500
        ):
            raise ValueError("Sample count and history window must be valid integers")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in (self.shrinkage, self.max_points, self.max_quote_age_seconds)
        ):
            raise ValueError("Heuristic controls must be finite numeric values")
        shrinkage, cap, age = (
            _number(self.shrinkage),
            _number(self.max_points),
            _number(self.max_quote_age_seconds),
        )
        if (
            shrinkage is None
            or not 0 <= shrinkage <= 1
            or cap is None
            or cap < 0
            or age is None
            or age <= 0
        ):
            raise ValueError("Invalid shrinkage, point cap or quote-age control")


def _midrank_quantile(values: list[float], probability: float) -> float:
    """Invert the piecewise-linear quantile curve; do not extrapolate beyond data."""
    count = len(values)
    position = probability * count - 0.5
    if position < 0 or position > count - 1:
        raise ValueError("Market probability is outside supported empirical quantiles")
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    # Convex form avoids overflow in (upper_value - lower_value) for extreme inputs.
    return values[lower] * (1 - fraction) + values[upper] * fraction


def _shifted_nonnegative_mean(values: list[float], shift: float) -> float:
    """Integrate max(0, Q(u)+shift), retaining a nonnegative count support.

    Clipping below zero leaves probabilities at positive market thresholds
    unchanged. It changes the mean, so simply using sample_mean+shift would be
    wrong for these bounded stats.
    """
    count = len(values)
    points = [
        (0.0, values[0]),
        *[((index + 0.5) / count, value) for index, value in enumerate(values)],
        (1.0, values[-1]),
    ]
    areas = []
    for (left_p, left), (right_p, right) in zip(points, points[1:]):
        width = right_p - left_p
        a, b = left + shift, right + shift
        if a >= 0:
            areas.append(width * (a / 2 + b / 2))
        elif b > 0:
            fraction_positive = b / (b - a)
            areas.append(width * fraction_positive * b / 2)
    return math.fsum(areas)


def _history_period_identity(
    row: Mapping[str, Any], *, target_season: int | None, target_week: int | None
) -> tuple[dict[str, Any], str | None]:
    """Validate explicit period metadata before any dated-history fallback."""
    identity: dict[str, Any] = {}
    for field, upper in (("season", 9999), ("week", 22)):
        value = row.get(field)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
                return {}, "invalid_history_period"
            identity[field] = value
    phase = row.get("season_type")
    if phase is not None:
        aliases = {"regular": "regular", "reg": "regular", "post": "post", "postseason": "post"}
        if not isinstance(phase, str) or phase.casefold() not in aliases:
            return {}, "invalid_history_period"
        identity["season_type"] = aliases[phase.casefold()]
    period = row.get("period_id")
    if period is not None:
        if not isinstance(period, str):
            return {}, "invalid_history_period"
        parts = period.split(":")
        if (
            len(parts) != 3
            or not parts[0].isdigit()
            or not parts[2].isdigit()
            or parts[1] not in {"regular", "post"}
        ):
            return {}, "invalid_history_period"
        parsed = {"season": int(parts[0]), "season_type": parts[1], "week": int(parts[2])}
        if not 1 <= parsed["season"] <= 9999 or not 1 <= parsed["week"] <= 22:
            return {}, "invalid_history_period"
        if any(field in identity and identity[field] != value for field, value in parsed.items()):
            return {}, "conflicting_history_period"
        identity.update(parsed)
    if target_season is not None:
        if (
            isinstance(target_season, bool)
            or not isinstance(target_season, int)
            or not 1 <= target_season <= 9999
        ):
            return {}, "invalid_target_period"
        season = identity.get("season")
        if season is not None and season > target_season:
            return {}, "future_history_period"
        if season == target_season:
            if identity.get("season_type") == "post":
                return {}, "future_history_period"
            if target_week is not None:
                if (
                    isinstance(target_week, bool)
                    or not isinstance(target_week, int)
                    or not 1 <= target_week <= 22
                ):
                    return {}, "invalid_target_period"
                if identity.get("week", 0) >= target_week:
                    return {}, "future_history_period"
    if all(field in identity for field in ("season", "season_type", "week")):
        identity["period_id"] = f"{identity['season']}:{identity['season_type']}:{identity['week']}"
    return identity, None


def _deduplicate_history_aliases(
    rows: list[dict[str, Any]], *, value_field: str, conflict_reason: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Join game and natural-period aliases before counting independent samples.

    Call separately for each player/stat (or a single team). A stripped duplicate
    carrying only one alias still joins its full record. Conflicting aliases,
    actual values or nonmissing occurrence times reject the entire group.
    """
    parents: dict[tuple[str, str], tuple[str, str]] = {}

    def root(alias: tuple[str, str]) -> tuple[str, str]:
        parents.setdefault(alias, alias)
        while parents[alias] != alias:
            parents[alias] = parents[parents[alias]]
            alias = parents[alias]
        return alias

    def aliases(row: Mapping[str, Any]) -> list[tuple[str, str]]:
        return [(field, row[field]) for field in ("game_id", "period_id") if row.get(field)]

    for row in rows:
        identities = aliases(row)
        for alias in identities[1:]:
            parents[root(alias)] = root(identities[0])
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[root(aliases(row)[0])].append(row)
    unlinked_kinds = {
        next(iter(kinds))
        for group in grouped.values()
        if len(kinds := {field for row in group for field, _ in aliases(row)}) == 1
    }
    output, rejected = [], []
    for group in grouped.values():
        games = {row["game_id"] for row in group if row.get("game_id")}
        periods = {row["period_id"] for row in group if row.get("period_id")}
        occurred = {row["occurred_at"] for row in group if row.get("occurred_at")}
        if len(unlinked_kinds) > 1 and bool(games) != bool(periods):
            # Without any bridge, a game-only row could be a duplicate of a
            # period-only row. Do not fabricate independent samples by adding them.
            rejected.append(
                {"sample_ids": sorted(games | periods), "reason": "unresolved_history_aliases"}
            )
            continue
        period_conflict = any(
            len(
                {
                    row.get("history_period", {}).get(field)
                    for row in group
                    if row.get("history_period", {}).get(field) is not None
                }
            )
            > 1
            for field in ("season", "week", "season_type")
        )
        if (
            len(games) > 1
            or len(periods) > 1
            or len(occurred) > 1
            or len({row[value_field] for row in group}) != 1
            or period_conflict
        ):
            rejected.append({"sample_ids": sorted(games | periods), "reason": conflict_reason})
            continue
        record = dict(max(group, key=lambda row: row["known_at"]))
        record.update(
            {
                "game_id": next(iter(games), None),
                "period_id": next(iter(periods), None),
                "occurred_at": next(iter(occurred), None),
            }
        )
        record["sample_id"] = record["period_id"] or record["game_id"]
        output.append(record)
    return output, rejected


def _history(
    observations: Sequence[Mapping[str, Any]],
    *,
    player_id: str,
    event_id: str,
    as_of: datetime,
    config: LocationShiftConfig,
    target_season: int | None,
    target_week: int | None,
    current_period_verified: bool,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejected = []
    try:
        earliest = as_of - timedelta(days=config.history_days)
    except OverflowError:
        earliest = datetime.min.replace(tzinfo=timezone.utc)
    for index, row in enumerate(observations):
        reason = None
        if not isinstance(row, Mapping):
            rejected.append({"observation": index, "reason": "invalid_observation"})
            continue
        stat, game = row.get("stat"), row.get("game_id")
        period, period_error = _history_period_identity(
            row, target_season=target_season, target_week=target_week
        )
        natural_period = period.get("period_id")
        occurred, known, value = (
            _time(row.get("occurred_at")),
            _time(row.get("known_at")),
            _number(row.get("value")),
        )
        live_week = (
            current_period_verified is True
            and isinstance(target_season, int)
            and not isinstance(target_season, bool)
            and isinstance(target_week, int)
            and not isinstance(target_week, bool)
            and period.get("season") == target_season
            and isinstance(period.get("week"), int)
            and 1 <= period["week"] < target_week <= 22
            and period.get("season_type") == "regular"
            and natural_period is not None
        )
        if row.get("player_id") != player_id:
            reason = "history_player_mismatch"
        elif not isinstance(stat, str) or stat not in SUPPORTED_STATS:
            reason = "unsupported_history_stat"
        elif period_error:
            reason = period_error
        elif game == event_id or (not live_week and (not isinstance(game, str) or not game)):
            reason = "invalid_history_game"
        elif row.get("period") != "full_game":
            reason = "unsupported_history_period"
        elif (
            known is None
            or (occurred is not None and known < occurred)
            or (not live_week and occurred is None)
        ):
            reason = "unverified_history_times"
        elif known > as_of or (occurred is not None and occurred >= as_of):
            reason = "future_history"
        elif not live_week and occurred < earliest:
            reason = "history_outside_window"
        elif value is None or (stat in NONNEGATIVE_STATS and value < 0):
            reason = "invalid_stat_value"
        if reason:
            rejected.append({"observation": index, "reason": reason})
            continue
        grouped[stat].append(
            {
                "period_id": natural_period,
                "history_period": period,
                "game_id": game if isinstance(game, str) and game else None,
                "value": value,
                "occurred_at": occurred.isoformat() if occurred else None,
                "known_at": known.isoformat(),
                "time_basis": "verified_current_prior_week" if live_week else "dated_actual_game",
            }
        )
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stat, rows in grouped.items():
        samples, conflicts = _deduplicate_history_aliases(
            rows, value_field="value", conflict_reason="conflicting_history"
        )
        output[stat].extend(samples)
        rejected.extend({**item, "stat": stat} for item in conflicts)
    return output, rejected


def estimate_current_market_adjustment(
    evidence: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    *,
    event_id: str,
    player_id: str,
    kickoff: datetime,
    as_of: datetime,
    scoring_coefficients: Mapping[str, Any],
    baseline_stats: Mapping[str, Any],
    baseline_source: str | None = None,
    target_season: int | None = None,
    target_week: int | None = None,
    current_period_verified: bool = False,
    config: LocationShiftConfig | None = None,
) -> dict[str, Any]:
    """Estimate bounded candidate point deltas relative to matching baseline stat means.

    ``baseline_source='sleeper_api'`` certifies the caller used genuine Sleeper
    stat forecasts, not a ranking fallback. Observations need exact mapped IDs,
    actual values, full-game period and occurrence/availability timestamps. Live
    prior-week rows may instead carry a verified current season/week and natural
    period ID, never fabricated game IDs or occurrence times. For
    present-time decisions a current retrieval time may be ``known_at``; never
    invent an earlier known time for a historical backtest.
    """
    settings = config or LocationShiftConfig()
    decision, start = _time(as_of), _time(kickoff)
    if (
        decision is None
        or start is None
        or not isinstance(event_id, str)
        or not event_id.strip()
        or not isinstance(player_id, str)
        or not player_id.strip()
        or not isinstance(scoring_coefficients, Mapping)
        or not isinstance(baseline_stats, Mapping)
    ):
        raise ValueError("Aware decision/kickoff times and exact event/player IDs required")
    result: dict[str, Any] = {
        "available": False,
        "applied": False,
        "model_version": MODEL_VERSION,
        "model_status": "provisional_heuristic_not_empirically_validated",
        "event_id": event_id,
        "player_id": player_id,
        "as_of": decision.isoformat(),
        "baseline_source": baseline_source,
        "components": [],
        "delta_points": None,
        "rejected": [],
        "config": asdict(settings),
        "limitations": [
            "Historical distribution shape is assumed stable except for a location shift",
            "Proportional no-vig probabilities and empirical quantiles are estimates, not ground truth",
            "Shrinkage and point cap are configurable provisional heuristics, not calibrated weights",
            "Applying Sleeper-relative market disagreement to a blended baseline assumes incremental information; provider double-counting remains possible",
            "Partial stats only: no anytime-TD-to-count conversion, team-total allocation or nonlinear scoring bonuses",
            "Live natural-period samples use verified same-season prior weeks, not historical as-of snapshots or a precise calendar-day recency window",
        ],
    }
    if decision >= start:
        result["rejected"].append({"reason": "game_started"})
        return result
    if baseline_source != "sleeper_api":
        result["rejected"].append({"reason": "baseline_stat_source_unverified"})
        return result
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("event_id") != event_id
        or evidence.get("player_id") != player_id
    ):
        result["rejected"].append({"reason": "market_identity_mismatch"})
        return result
    # Revalidate raw quotes at the current decision time. Never trust an injected
    # consensus table or reuse previously fresh evidence after its useful lifetime.
    raw = evidence.get("raw_quotes")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        result["rejected"].append({"reason": "missing_verified_raw_quotes"})
        return result
    market = assess_player_markets(
        raw,
        event_id=event_id,
        player_id=player_id,
        kickoff=start,
        as_of=decision,
        max_age_seconds=settings.max_quote_age_seconds,
    )
    result["market_coverage"] = market["coverage"]
    result["rejected"].extend(market["rejected"])
    history, rejected = _history(
        observations,
        player_id=player_id,
        event_id=event_id,
        as_of=decision,
        config=settings,
        target_season=target_season,
        target_week=target_week,
        current_period_verified=current_period_verified,
    )
    result["rejected"].extend(rejected)
    constraints: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in market["quantile_constraints"]:
        stat = row["stat"]
        if stat not in SUPPORTED_STATS:
            result["rejected"].append({"stat": stat, "reason": "unsupported_expected_stat"})
        else:
            constraints[stat].append(row)

    for stat, rows in sorted(constraints.items()):
        baseline, coefficient = _number(baseline_stats.get(stat)), _number(
            scoring_coefficients.get(stat)
        )
        if baseline is None or coefficient is None or (stat in NONNEGATIVE_STATS and baseline < 0):
            result["rejected"].append({"stat": stat, "reason": "missing_valid_baseline_or_scoring"})
            continue
        samples = history.get(stat, [])
        values = sorted(row["value"] for row in samples)
        if len(values) < settings.min_samples or len(set(values)) < 2:
            result["rejected"].append(
                {
                    "stat": stat,
                    "reason": "insufficient_history_or_variation",
                    "sample_count": len(values),
                }
            )
            continue
        try:
            mean = statistics.fmean(values)
            shifts = []
            details = []
            for row in rows:
                if row["side"] != "over":
                    continue
                probability_under = 1 - row["fair_probability"]
                try:
                    quantile = _midrank_quantile(values, probability_under)
                except ValueError:
                    result["rejected"].append(
                        {
                            "stat": stat,
                            "reason": "unsupported_empirical_tail",
                            "threshold": row["threshold"],
                        }
                    )
                    continue
                shift = row["threshold"] - quantile
                shifts.append(shift)
                details.append(
                    {
                        "threshold": row["threshold"],
                        "probability_under": probability_under,
                        "historical_quantile": quantile,
                        "location_shift": shift,
                        "book_count": row["book_count"],
                    }
                )
            if not shifts:
                continue
            location_shift = statistics.median(shifts)
            market_mean = (
                _shifted_nonnegative_mean(values, location_shift)
                if stat in NONNEGATIVE_STATS
                else mean + location_shift
            )
            stat_delta = (market_mean - baseline) * settings.shrinkage
            point_delta = stat_delta * coefficient
            if not all(
                math.isfinite(value)
                for value in (mean, location_shift, market_mean, stat_delta, point_delta)
            ):
                raise ArithmeticError
        except (OverflowError, ArithmeticError, ValueError):
            result["rejected"].append({"stat": stat, "reason": "numeric_overflow"})
            continue
        result["components"].append(
            {
                "stat": stat,
                "baseline_stat": baseline,
                "historical_mean": mean,
                "sample_count": len(values),
                "sample_ids": sorted(row["sample_id"] for row in samples),
                "sample_game_ids": sorted(
                    row["game_id"] for row in samples if row["game_id"] is not None
                ),
                "sample_time_bases": sorted({row["time_basis"] for row in samples}),
                "market_implied_mean": market_mean,
                "location_shift": location_shift,
                "support_transform": (
                    "floor_at_zero" if stat in NONNEGATIVE_STATS else "unbounded_location_shift"
                ),
                "location_shift_range": [min(shifts), max(shifts)],
                "constraints": details,
                "shrinkage": settings.shrinkage,
                "scoring_coefficient": coefficient,
                "uncapped_stat_delta": stat_delta,
                "uncapped_point_delta": point_delta,
            }
        )
    components = result["components"]
    if not components:
        if not result["rejected"]:
            result["rejected"].append({"reason": "no_supported_market_components"})
        return result
    # A shared absolute point budget also limits opposing components which would
    # otherwise cancel to a small net value while each made an enormous change.
    try:
        absolute = math.fsum(abs(row["uncapped_point_delta"]) for row in components)
        scale = min(1.0, settings.max_points / absolute) if absolute else 1.0
        for row in components:
            row["point_delta"] = row["uncapped_point_delta"] * scale
            row["stat_delta"] = row["uncapped_stat_delta"] * scale
        total = math.fsum(row["point_delta"] for row in components)
    except (OverflowError, ArithmeticError):
        result["rejected"].append({"reason": "aggregate_numeric_overflow"})
        result["components"] = []
        return result
    result.update(
        {
            "available": True,
            "delta_points": total,
            "absolute_uncapped_points": absolute,
            "point_budget_scale": scale,
        }
    )
    return result
