"""Provisional team-scoring index fallback from current full-game market lines.

A total is a threshold, not an expected score. This model explicitly uses main
team/game lines as a heuristic index relative to reported prior team scores. It
scales only genuine forecast touchdown fantasy contributions, with shrinkage and
a point cap. It does not allocate the game total to players or infer TD counts.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .market_evidence import implied_probability, quote_pricing_semantics
from .performance_market_model import _deduplicate_history_aliases, _history_period_identity

MODEL_VERSION = "game_scoring_index_v1_provisional"
TD_STATS = ("passing_touchdowns", "rushing_touchdowns", "receiving_touchdowns")


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
class GameMarketConfig:
    min_samples: int = 8
    shrinkage: float = 0.25
    max_points: float = 2.0
    max_quote_age_seconds: float = 300.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.min_samples, bool)
            or not isinstance(self.min_samples, int)
            or self.min_samples < 3
        ):
            raise ValueError("At least three actual team-game samples required")
        for value in (self.shrinkage, self.max_points, self.max_quote_age_seconds):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or _number(value) is None
            ):
                raise ValueError("Controls must be finite numbers")
        if not 0 <= self.shrinkage <= 1 or self.max_points < 0 or self.max_quote_age_seconds <= 0:
            raise ValueError("Invalid shrinkage, point budget or quote age")


def _side(value: Any, event: Mapping[str, Any]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    matches = [
        side
        for side in ("home", "away")
        if value in (event.get(f"{side}_team_key"), event.get(f"{side}_team"))
    ]
    return matches[0] if len(matches) == 1 else None


def _valid_quote(
    row: Mapping[str, Any],
    *,
    event_id: str,
    team_key: str,
    start: datetime,
    decision: datetime,
    max_age: float,
) -> tuple[str | None, str | None]:
    if row.get("event_id") != event_id or row.get("scope") != "next_game":
        return None, "event_or_scope_mismatch"
    event = row.get("event")
    if not isinstance(event, Mapping) or _time(event.get("commence_time")) != start:
        return None, "game_time_unverified"
    home, away = event.get("home_team_key"), event.get("away_team_key")
    if (
        not isinstance(home, str)
        or not isinstance(away, str)
        or not home
        or not away
        or home == away
        or team_key not in {home, away}
    ):
        return None, "team_orientation_unverified"
    period_verified = row.get("period_source") == "provider" or (
        row.get("period_source") == "propline_documented_contract"
        and row.get("period_reference") == "https://prop-line.com/docs"
    )
    if row.get("period") != "full_game" or not period_verified:
        return None, "unverified_full_game_period"
    if row.get("line_type") != "main" or row.get("line_type_source") != "provider":
        return None, "unverified_main_line"
    if row.get("market_suspended_at") is not None and row.get("market_suspended_at") != "":
        return None, "market_suspended"
    if quote_pricing_semantics(row)[0] != "quoted_single_leg":
        return None, "unverified_single_leg_pricing"
    if row.get("odds_format_source") not in ("provider", "propline_documented_default"):
        return None, "unverified_odds_format"
    try:
        implied_probability(row.get("price"), str(row.get("odds_format") or ""))
    except ValueError:
        return None, "invalid_price"
    fetched, observed = _time(row.get("quote_fetched_at")), _time(row.get("provider_observed_at"))
    if fetched is None or observed is None or observed > fetched or fetched > decision:
        return None, "invalid_quote_time"
    if (decision - fetched).total_seconds() > max_age or (
        decision - observed
    ).total_seconds() > max_age:
        return None, "stale_quote"
    for key in ("book_updated_at", "last_change_at"):
        if row.get(key) is not None:
            value = _time(row[key])
            if value is None or value > fetched:
                return None, "invalid_quote_time"
    if not isinstance(row.get("bookmaker_key"), str) or not row["bookmaker_key"].strip():
        return None, "missing_bookmaker"
    market = row.get("market_key")
    if market == "spreads":
        return "spread", None
    if market not in ("totals", "team_totals"):
        return None, "unsupported_game_market"
    if row.get("market_team_source") != "provider":
        return None, "game_vs_team_total_unverified"
    market_team = row.get("market_team")
    if market_team is None or market_team == "":
        return ("game_total", None) if market == "totals" else (None, "missing_team_total_team")
    market_side = _side(market_team, event)
    if market_side is None:
        return None, "team_total_identity_unverified"
    if event[f"{market_side}_team_key"] != team_key:
        return None, "other_team_total"
    return "team_total", None


def _pair(rows: list[Mapping[str, Any]], family: str) -> dict[str, Any] | None:
    by_side: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        side = (
            _side(row.get("selection"), row["event"])
            if family == "spread"
            else str(row.get("selection") or "").casefold()
        )
        by_side[side].append(row)
    required = {"home", "away"} if family == "spread" else {"over", "under"}
    if set(by_side) != required:
        return None
    chosen = {}
    for side, quotes in by_side.items():
        signatures = {
            (
                str(row.get("line")),
                str(row["price"]),
                row["odds_format"],
                row["quote_fetched_at"],
                row["provider_observed_at"],
            )
            for row in quotes
        }
        if len(signatures) != 1:
            return None
        chosen[side] = quotes[0]
    if (
        len(
            {
                (row["quote_fetched_at"], row["provider_observed_at"], row["odds_format"])
                for row in chosen.values()
            }
        )
        != 1
    ):
        return None
    points = {side: _number(row.get("line")) for side, row in chosen.items()}
    if any(value is None for value in points.values()):
        return None
    if family == "spread":
        if not math.isclose(points["home"], -points["away"], abs_tol=1e-9, rel_tol=0):
            return None
    elif points["over"] != points["under"] or points["over"] < 0:
        return None
    return {
        "lines": points,
        "snapshot": next(iter(chosen.values()))["quote_fetched_at"],
        "quotes": list(chosen.values()),
    }


def _team_history(
    rows: Sequence[Mapping[str, Any]],
    *,
    team_key: str,
    event_id: str,
    decision: datetime,
    target_season: int | None,
    target_week: int | None,
    current_period_verified: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    samples: list[dict[str, Any]] = []
    rejected = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            rejected.append({"history_row": index, "reason": "invalid_team_history"})
            continue
        occurred, known = _time(row.get("occurred_at")), _time(row.get("known_at"))
        points, game = _number(row.get("points")), row.get("game_id")
        period, period_error = _history_period_identity(
            row, target_season=target_season, target_week=target_week
        )
        period_id = period.get("period_id")
        live = (
            current_period_verified is True
            and isinstance(target_season, int)
            and not isinstance(target_season, bool)
            and isinstance(target_week, int)
            and not isinstance(target_week, bool)
            and period.get("season") == target_season
            and isinstance(period.get("week"), int)
            and 1 <= period["week"] < target_week <= 22
            and period.get("season_type") == "regular"
            and period_id is not None
        )
        if row.get("team_key") != team_key or row.get("period") != "full_game":
            reason = "history_team_or_period_mismatch"
        elif period_error:
            reason = period_error
        elif points is None or points < 0 or not points.is_integer():
            reason = "invalid_reported_team_points"
        elif (
            known is None
            or known > decision
            or (occurred is not None and (occurred >= decision or known < occurred))
        ):
            reason = "unverified_or_future_team_history"
        elif game == event_id or (
            not live and (not isinstance(game, str) or not game or occurred is None)
        ):
            reason = "unverified_team_game"
        else:
            samples.append(
                {
                    "game_id": game if isinstance(game, str) and game else None,
                    "period_id": period_id,
                    "history_period": period,
                    "points": points,
                    "occurred_at": occurred.isoformat() if occurred else None,
                    "known_at": known.isoformat(),
                }
            )
            continue
        rejected.append({"history_row": index, "reason": reason})
    output, conflicts = _deduplicate_history_aliases(
        samples, value_field="points", conflict_reason="conflicting_team_history"
    )
    rejected.extend(conflicts)
    return output, rejected


def estimate_game_market_adjustment(
    rows: Sequence[Mapping[str, Any]],
    team_history: Sequence[Mapping[str, Any]],
    *,
    event_id: str,
    team_key: str,
    kickoff: datetime,
    as_of: datetime,
    baseline_stats: Mapping[str, Any],
    scoring_coefficients: Mapping[str, Any],
    baseline_source: str | None = None,
    player_prop_adjustment_available: bool = False,
    config: GameMarketConfig | None = None,
    target_season: int | None = None,
    target_week: int | None = None,
    current_period_verified: bool = False,
) -> dict[str, Any]:
    """Return a bounded candidate TD-scoring delta, never a calibrated projection.

    History team keys must already be mapped to the exact current event's provider
    key. Team totals require explicit team provenance; game totals require an
    explicitly absent team. The caller must select this OR a player-prop model.
    """
    settings = config or GameMarketConfig()
    start, decision = _time(kickoff), _time(as_of)
    if (
        start is None
        or decision is None
        or not isinstance(event_id, str)
        or not event_id
        or not isinstance(team_key, str)
        or not team_key
        or not isinstance(baseline_stats, Mapping)
        or not isinstance(scoring_coefficients, Mapping)
    ):
        raise ValueError("Exact game/team IDs, aware times and baseline/scoring mappings required")
    result: dict[str, Any] = {
        "available": False,
        "applied": False,
        "model_version": MODEL_VERSION,
        "model_status": "provisional_heuristic_not_empirically_validated",
        "event_id": event_id,
        "team_key": team_key,
        "delta_points": None,
        "rejected": [],
        "components": [],
        "config": asdict(settings),
        "limitations": [
            "Team/game lines are scoring-environment indices, not expected scores",
            "Team points include non-offensive scores; proportional player TD opportunity is a heuristic assumption",
            "Shrinking relative to prior team scoring does not establish incremental information beyond provider forecasts",
            "No player-yardage/PPR allocation, inferred TD counts or nonlinear bonus adjustment",
            "Books are correlated; book count is not independent sample size",
        ],
    }
    if player_prop_adjustment_available:
        result["rejected"].append({"reason": "player_prop_adjustment_takes_precedence"})
        return result
    if decision >= start or baseline_source != "sleeper_api":
        result["rejected"].append(
            {"reason": "game_started" if decision >= start else "baseline_source_unverified"}
        )
        return result
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    orientation: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            result["rejected"].append({"quote": index, "reason": "invalid_game_quote"})
            continue
        family, reason = _valid_quote(
            row,
            event_id=event_id,
            team_key=team_key,
            start=start,
            decision=decision,
            max_age=settings.max_quote_age_seconds,
        )
        if reason:
            result["rejected"].append({"quote": index, "reason": reason})
        else:
            event = row["event"]
            orientation.add((event["home_team_key"], event["away_team_key"]))
            groups[(row["bookmaker_key"], family)].append(row)
    if len(orientation) > 1:
        result["rejected"].append({"reason": "conflicting_event_orientation"})
        return result
    books: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for (book, family), quotes in groups.items():
        pair = _pair(quotes, family)
        if pair is None:
            result["rejected"].append(
                {
                    "bookmaker_key": book,
                    "family": family,
                    "reason": "incomplete_or_conflicting_pair",
                }
            )
        else:
            books[book][family] = pair
    indices = []
    for book, families in sorted(books.items()):
        if "team_total" in families:
            total = families["team_total"]
            index, source, selected_quotes = (
                total["lines"]["over"],
                "direct_team_total",
                total["quotes"],
            )
        elif "game_total" in families and "spread" in families:
            total, spread = families["game_total"], families["spread"]
            if total["snapshot"] != spread["snapshot"]:
                result["rejected"].append(
                    {"bookmaker_key": book, "reason": "noncontemporaneous_total_and_spread"}
                )
                continue
            event = spread["quotes"][0]["event"]
            side = "home" if event["home_team_key"] == team_key else "away"
            index = total["lines"]["over"] / 2 - spread["lines"][side] / 2
            source, selected_quotes = (
                "game_total_and_team_spread",
                total["quotes"] + spread["quotes"],
            )
        else:
            result["rejected"].append(
                {"bookmaker_key": book, "reason": "missing_team_total_or_total_spread_pair"}
            )
            continue
        if not math.isfinite(index) or index < 0:
            result["rejected"].append(
                {"bookmaker_key": book, "reason": "invalid_team_scoring_index"}
            )
            continue
        indices.append(
            {
                "bookmaker_key": book,
                "team_scoring_index": index,
                "source": source,
                "quotes": [deepcopy(dict(row)) for row in selected_quotes],
            }
        )
    if not indices:
        if not result["rejected"]:
            result["rejected"].append({"reason": "no_usable_game_market"})
        return result
    samples, rejected = _team_history(
        team_history,
        team_key=team_key,
        event_id=event_id,
        decision=decision,
        target_season=target_season,
        target_week=target_week,
        current_period_verified=current_period_verified,
    )
    result["rejected"].extend(rejected)
    if len(samples) < settings.min_samples:
        result["rejected"].append(
            {"reason": "insufficient_team_history", "sample_count": len(samples)}
        )
        return result
    try:
        mean = statistics.fmean(row["points"] for row in samples)
        index = statistics.median(row["team_scoring_index"] for row in indices)
        if mean <= 0:
            result["rejected"].append({"reason": "nonpositive_reported_team_mean"})
            return result
        ratio_delta = index / mean - 1
        components = []
        for stat in TD_STATS:
            baseline, coefficient = _number(baseline_stats.get(stat)), _number(
                scoring_coefficients.get(stat)
            )
            if baseline is None or baseline < 0 or coefficient is None:
                continue
            contribution = baseline * coefficient
            delta = contribution * ratio_delta * settings.shrinkage
            if not math.isfinite(contribution) or not math.isfinite(delta):
                raise ArithmeticError
            components.append(
                {
                    "stat": stat,
                    "baseline_stat": baseline,
                    "scoring_coefficient": coefficient,
                    "baseline_td_points": contribution,
                    "uncapped_point_delta": delta,
                }
            )
        if not components:
            result["rejected"].append({"reason": "missing_supported_touchdown_baseline_or_scoring"})
            return result
        absolute = math.fsum(abs(row["uncapped_point_delta"]) for row in components)
        scale = min(1.0, settings.max_points / absolute) if absolute else 1.0
        for row in components:
            row["point_delta"] = row["uncapped_point_delta"] * scale
        delta = math.fsum(row["point_delta"] for row in components)
        if not all(math.isfinite(value) for value in (mean, index, ratio_delta, delta)):
            raise ArithmeticError
    except (OverflowError, ArithmeticError, ValueError):
        result["rejected"].append({"reason": "numeric_overflow"})
        return result
    result.update(
        {
            "available": True,
            "delta_points": delta,
            "components": components,
            "team_scoring_index": index,
            "historical_team_points_mean": mean,
            "ratio_delta": ratio_delta,
            "sample_count": len(samples),
            "sample_ids": sorted(row["sample_id"] for row in samples),
            "book_count": len(indices),
            "independent_book_sample_size": None,
            "book_indices": indices,
            "point_budget_scale": scale,
        }
    )
    return result
