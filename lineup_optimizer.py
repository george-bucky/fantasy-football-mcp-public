from __future__ import annotations

"""Lightweight fallback lineup optimizer.

The original optimizer attempted deep projections and external data pulls but was
fragile against Yahoo payload changes.  This replacement keeps the same public
API so existing callers keep working, while delivering deterministic, best-effort
results based purely on the roster data already returned by the legacy layer.
"""

import logging
import math
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.services.projection_assessment import assess_projection
from src.services.rookie_intelligence import rookie_identity_key, rookie_identity_token

logger = logging.getLogger(__name__)


BENCH_SLOTS = {
    "BN",
    "BENCH",
    "IR",
    "IR+",
    "IRL",
    "IRR",
    "DNR",
    "NA",
    "N/A",
    "COVID-19",
    "COVID",
}

# Match confidence scores for different Sleeper matching methods
MATCH_CONFIDENCE = {
    "exact": 1.0,
    "normalized": 0.9,
    "variant": 0.8,
    "token_subset": 0.6,
    "fuzzy": 0.4,
    "failed": 0.0,
    "api": 0.9,  # Default for successful API matches
}

# Penalty factors for mismatches
MISMATCH_PENALTY = 0.5


@dataclass
class MatchAnalytics:
    """Analytics for tracking match quality and success rates."""

    total_players: int = 0
    matched_players: int = 0
    exact_matches: int = 0
    normalized_matches: int = 0
    variant_matches: int = 0
    token_subset_matches: int = 0
    fuzzy_matches: int = 0
    failed_matches: int = 0
    position_mismatches: int = 0
    team_mismatches: int = 0
    avg_match_confidence: float = 0.0

    def add_match(self, match_method: str, confidence: float):
        """Record a match attempt."""
        self.total_players += 1

        if not match_method or match_method == "failed":
            self.failed_matches += 1
            return

        self.matched_players += 1

        # Count match types
        base_method = match_method.split("_")[0]
        if base_method == "exact":
            self.exact_matches += 1
        elif base_method == "normalized":
            self.normalized_matches += 1
        elif base_method == "variant":
            self.variant_matches += 1
        elif base_method == "token":
            self.token_subset_matches += 1
        elif base_method == "fuzzy":
            self.fuzzy_matches += 1

        # Count mismatches
        if "_pos_mismatch" in match_method:
            self.position_mismatches += 1
        if "_team_mismatch" in match_method:
            self.team_mismatches += 1

        # Update average confidence
        if self.matched_players > 0:
            total_confidence = self.avg_match_confidence * (self.matched_players - 1) + confidence
            self.avg_match_confidence = total_confidence / self.matched_players

    def get_success_rate(self) -> float:
        """Get overall match success rate."""
        return self.matched_players / self.total_players if self.total_players > 0 else 0.0

    def get_quality_distribution(self) -> Dict[str, float]:
        """Get distribution of match quality."""
        if self.matched_players == 0:
            return {}

        return {
            "exact": self.exact_matches / self.matched_players,
            "normalized": self.normalized_matches / self.matched_players,
            "variant": self.variant_matches / self.matched_players,
            "token_subset": self.token_subset_matches / self.matched_players,
            "fuzzy": self.fuzzy_matches / self.matched_players,
        }


def _coerce_float(value: Any) -> float:
    try:
        if value is None or isinstance(value, bool):
            return 0.0
        if isinstance(value, str) and not value.strip():
            return 0.0
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _normalize_position(raw: Any) -> str:
    if not raw:
        return "BN"
    if isinstance(raw, dict):
        if "position" in raw:
            return str(raw.get("position", "BN")).upper()
        for val in raw.values():
            if isinstance(val, dict) and "position" in val:
                return str(val.get("position", "BN")).upper()
    return str(raw).upper()


def _calculate_match_confidence(match_method: str) -> float:
    """Calculate confidence score for Sleeper match quality."""
    if not match_method:
        return 0.0

    # Extract base method and check for mismatches
    base_method = match_method.split("_")[0]
    has_mismatch = "_mismatch" in match_method

    # Get base confidence
    confidence = MATCH_CONFIDENCE.get(base_method, 0.0)

    # Apply mismatch penalty
    if has_mismatch:
        confidence *= MISMATCH_PENALTY

    return confidence


def _calculate_dynamic_weights(
    yahoo_proj: float, sleeper_proj: float, match_confidence: float
) -> Dict[str, float]:
    """Calculate dynamic projection weights based on data quality and match confidence."""

    # Base weights from CLAUDE.md strategy
    base_yahoo_weight = 0.40
    base_sleeper_weight = 0.40

    # Adjust Sleeper weight based on match confidence
    adjusted_sleeper_weight = base_sleeper_weight * match_confidence

    # Compensate Yahoo weight to maintain total projection weight at 0.8
    target_total = base_yahoo_weight + base_sleeper_weight
    adjusted_yahoo_weight = target_total - adjusted_sleeper_weight

    # Ensure weights don't exceed reasonable bounds
    adjusted_yahoo_weight = max(0.1, min(0.7, adjusted_yahoo_weight))
    adjusted_sleeper_weight = max(0.0, min(0.7, adjusted_sleeper_weight))

    # Normalize to target total
    total_weight = adjusted_yahoo_weight + adjusted_sleeper_weight
    if total_weight > 0:
        scale_factor = target_total / total_weight
        adjusted_yahoo_weight *= scale_factor
        adjusted_sleeper_weight *= scale_factor

    return {
        "yahoo": adjusted_yahoo_weight,
        "sleeper": adjusted_sleeper_weight,
        "match_confidence": match_confidence,
        "other": 0.20,  # matchup, trending, momentum remain constant
    }


@dataclass
class Player:
    """Simple player model that mirrors the attributes used by our callers."""

    name: str
    position: str
    team: str
    opponent: str = ""
    status: str = "OK"
    yahoo_projection: float = 0.0
    sleeper_projection: float = 0.0
    sleeper_projection_std: float = 0.0
    sleeper_projection_ppr: float = 0.0
    sleeper_projection_half_ppr: float = 0.0
    sleeper_id: str = ""
    sleeper_status: str = ""
    sleeper_injury_status: str = ""
    sleeper_match_method: str = ""
    player_tier: str = "starter"
    matchup_score: int = 50
    matchup_description: str = "No matchup context"
    trending_score: int = 0
    injury_status: str = "Healthy"
    injury_probability: float = 0.0
    ownership_pct: float = 0.0
    recent_performance: List[float] = field(default_factory=list)
    season_avg: float = 0.0
    target_share: float = 0.0
    snap_count_pct: float = 0.0
    weather_impact: str = "Unknown"
    vegas_total: float = 0.0
    team_implied_total: float = 0.0
    spread: float = 0.0
    defense_rank_allowed: str = "Unknown"
    value: float = 0.0
    value_score: float = 0.0
    floor_projection: float = 0.0
    ceiling_projection: float = 0.0
    consistency_score: float = 0.0
    risk_level: str = "medium"
    composite_score: float = 0.0
    # New expert advice fields
    expert_tier: str = ""
    expert_recommendation: str = ""
    expert_confidence: int = 0
    expert_advice: str = ""
    search_rank: int = 500
    # Match analytics
    match_confidence: float = 0.0
    match_analytics: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)
    # Enhancement layer fields (bye weeks, recent stats, performance flags)
    bye: Any = "N/A"  # Bye week number (from Yahoo API)
    on_bye: bool = False  # Is player on bye this week?
    recent_performance_data: Any = None  # RecentPerformance object from enhancement
    performance_flags: List[str] = field(default_factory=list)  # ["BREAKOUT", "TRENDING_UP", etc]
    enhancement_context: str = ""  # Human-readable context message
    adjusted_projection: float = 0.0  # Projection adjusted based on recent performance
    # Appended to preserve positional compatibility for the original Player fields.
    roster_position: str = ""
    sleeper_projection_source: str = ""
    sleeper_depth_chart_order: int = 0
    scoring_format: str = "ppr"
    scoring_format_source: str = "fallback_default_ppr"
    weekly_matchup_evidence: Dict[str, Any] = field(default_factory=dict)
    player_key: str = ""
    lineup_locked: Optional[bool] = None  # Only a verified provider lock, never inferred here.
    projection_context: Dict[str, Any] = field(default_factory=dict)
    projection_assessment: Dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        return bool(self.name and self.team)


_STRATEGY_WEIGHTS = {
    "balanced": {"sleeper": 0.80, "recent_avg": 0.20},
    "conservative": {
        "sleeper": 0.50,
        "recent_avg": 0.20,
        "recent_floor": 0.30,
    },
    "aggressive": {
        "sleeper": 0.50,
        "recent_avg": 0.15,
        "recent_ceiling": 0.35,
    },
}

_FLEX_ELIGIBILITY = {
    "FLEX": {"RB", "WR", "TE"},
    "W/R/T": {"RB", "WR", "TE"},
    "W/R": {"WR", "RB"},
    "W/T": {"WR", "TE"},
    "R/T": {"RB", "TE"},
    "Q/W/R/T": {"QB", "RB", "WR", "TE"},
    "SUPERFLEX": {"QB", "RB", "WR", "TE"},
    "OP": {"QB", "RB", "WR", "TE"},
}

_NEWS_RISK_TERMS = (
    "ruled out",
    "will not play",
    "won't play",
    "not expected to play",
    "unlikely to play",
    "not cleared to play",
    "did not practice",
    "limited practice",
    "doubtful",
    "questionable",
    "injury concern",
    "reduced role",
    "fewer snaps",
    "demoted",
)
_NEWS_POSITIVE_TERMS = (
    "full practice",
    "cleared to play",
    "expected to play",
    "starting role",
    "expanded role",
    "more touches",
)


def _finite_number(value: Any) -> Optional[float]:
    """Accept numeric measurements, preserving missingness and rejecting overflow."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _projection_number(value: Any) -> float:
    """Read an optional provider point value without hiding invalid numbers."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    if isinstance(value, bool):
        raise ValueError("Invalid projection number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Invalid projection number") from None
    if not math.isfinite(number):
        raise ValueError("Nonfinite projection number")
    return number


def _projection_sum(rows: List[Dict[str, Any]], field_name: str) -> float:
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Invalid projection rows")
    try:
        total = math.fsum(_projection_number(row.get(field_name)) for row in rows)
    except OverflowError:
        raise ValueError("Nonfinite projection aggregate") from None
    if not math.isfinite(total):
        raise ValueError("Nonfinite projection aggregate")
    return total


def _projection_warning(player: Player, message: str) -> None:
    context = dict(player.projection_context) if isinstance(player.projection_context, dict) else {}
    previous = context.get("projection_input_warnings")
    warnings = list(previous) if isinstance(previous, list) else []
    if message not in warnings:
        warnings.append(message)
    context["projection_input_warnings"] = warnings
    player.projection_context = context


def _finite_legacy_projection_fields(player: Player) -> None:
    """Keep legacy display fields JSON-safe; zero is an unavailable placeholder."""
    fields = (
        "yahoo_projection",
        "sleeper_projection",
        "sleeper_projection_std",
        "sleeper_projection_ppr",
        "sleeper_projection_half_ppr",
        "composite_score",
        "floor_projection",
        "ceiling_projection",
        "adjusted_projection",
    )
    for field_name in fields:
        if _finite_number(getattr(player, field_name)) is None:
            setattr(player, field_name, 0.0)
            if field_name.startswith("sleeper_projection"):
                player.sleeper_projection_source = "invalid_projection"
            _projection_warning(
                player, f"{field_name} unavailable: nonfinite or invalid arithmetic"
            )


def _recent_actual_points(player: Player) -> List[float]:
    recent = player.recent_performance_data
    weeks_data = getattr(recent, "weeks_data", None)
    if not isinstance(weeks_data, list):
        return []

    points: List[float] = []
    for week in weeks_data:
        if not isinstance(week, dict):
            continue
        value = week.get("points")
        parsed = _finite_number(value)
        if parsed is not None:
            points.append(parsed)
    return points


def _sleeper_projection_for_format(player: Player) -> float:
    scoring_format = player.scoring_format.lower().replace("-", "_")
    if scoring_format == "standard":
        return player.sleeper_projection_std
    if scoring_format == "half_ppr":
        return player.sleeper_projection_half_ppr
    if scoring_format == "ppr":
        return player.sleeper_projection_ppr
    return 0.0


def _sleeper_projection_explicitly_present(player: Player) -> bool:
    context = player.projection_context if isinstance(player.projection_context, dict) else {}
    return context.get("sleeper_projection_present") is True and context.get(
        "sleeper_projection_scoring_format"
    ) == player.scoring_format.lower().replace("-", "_")


def _availability_multiplier(player: Player, strategy: str) -> tuple[float, List[str]]:
    statuses = {
        str(value).strip().upper()
        for value in (
            player.status,
            player.injury_status,
            player.sleeper_status,
            player.sleeper_injury_status,
        )
        if str(value or "").strip()
    }
    if player.on_bye or "ON_BYE" in player.performance_flags:
        return 0.0, ["Bye week"]
    unavailable = statuses & {"O", "OUT", "IR", "IR+", "INACTIVE", "PUP", "SUSPENDED"}
    if unavailable:
        return 0.0, [f"Unavailable status: {', '.join(sorted(unavailable))}"]
    doubtful = statuses & {"D", "DOUBTFUL"}
    if doubtful:
        factor = 0.45 if strategy == "conservative" else 0.60
        return factor, [f"Doubtful status: {', '.join(sorted(doubtful))}"]
    questionable = statuses & {"Q", "QUESTIONABLE"}
    if questionable:
        factor = {"balanced": 0.88, "conservative": 0.78, "aggressive": 0.94}[strategy]
        return factor, [f"Questionable status: {', '.join(sorted(questionable))}"]
    return 1.0, []


def _role_multiplier(
    player: Player, strategy: str, *, include_recent_flags: bool = True
) -> tuple[float, List[str]]:
    multiplier = 1.0
    inputs: List[str] = []
    flags = (
        set(player.performance_flags)
        if include_recent_flags and player.scoring_format_source != "fallback_custom_ppr"
        else set()
    )

    flag_adjustments = {
        "balanced": {
            "CONSISTENT": 0.03,
            "TRENDING_UP": 0.04,
            "BREAKOUT_CANDIDATE": 0.04,
            "DECLINING_ROLE": -0.08,
            "TRENDING_DOWN": -0.05,
        },
        "conservative": {
            "CONSISTENT": 0.07,
            "DECLINING_ROLE": -0.14,
            "TRENDING_DOWN": -0.08,
        },
        "aggressive": {
            "HIGH_CEILING": 0.10,
            "BREAKOUT_CANDIDATE": 0.08,
            "TRENDING_UP": 0.06,
            "DECLINING_ROLE": -0.05,
        },
    }
    applied_flags = sorted(flags & flag_adjustments[strategy].keys())
    if applied_flags:
        multiplier += sum(flag_adjustments[strategy][flag] for flag in applied_flags)
        inputs.append(f"Sleeper recent-performance flags: {', '.join(applied_flags)}")

    if player.sleeper_depth_chart_order > 0:
        order = player.sleeper_depth_chart_order
        if order == 1:
            multiplier += {"balanced": 0.03, "conservative": 0.05, "aggressive": 0.02}[strategy]
        elif order >= 3:
            multiplier -= {"balanced": 0.05, "conservative": 0.10, "aggressive": 0.03}[strategy]
        inputs.append(f"Sleeper depth-chart order: {order}")

    if 0 < player.snap_count_pct <= 100:
        multiplier += (player.snap_count_pct - 60.0) / 1000.0
        inputs.append(f"Snap share: {player.snap_count_pct:g}%")
    if 0 < player.target_share <= 100:
        multiplier += (player.target_share - 15.0) / 1000.0
        inputs.append(f"Target share: {player.target_share:g}%")
    if player.trending_score not in (0, 50):
        direction = "adds" if player.trending_score > 50 else "drops"
        adjustment = 0.02 if direction == "adds" else -0.02
        if strategy == "aggressive":
            adjustment *= 1.5
        multiplier += adjustment
        inputs.append(f"Sleeper trending {direction}")

    return max(0.0, multiplier), inputs


def _news_signals(news_context: Dict[str, Any]) -> List[Dict[str, str]]:
    signals: List[Dict[str, str]] = []
    for source_key in ("espn", "rotowire"):
        for item in news_context.get(source_key, []):
            if not isinstance(item, dict):
                continue
            headline = str(item.get("headline") or "")
            text = f"{headline} {item.get('summary') or ''}".casefold()
            signal = ""
            if any(term in text for term in _NEWS_RISK_TERMS):
                signal = "availability_or_role_risk"
            elif any(term in text for term in _NEWS_POSITIVE_TERMS):
                signal = "availability_or_role_positive"
            if signal:
                signals.append(
                    {
                        "signal": signal,
                        "source": str(item.get("source") or source_key.upper()),
                        "headline": headline,
                    }
                )
    return signals


def _strategy_components(
    player: Player,
    strategy: str,
    news_context: Optional[Dict[str, Any]] = None,
) -> tuple[float, Dict[str, Any]]:
    compatible_scoring = (
        player.scoring_format_source != "fallback_custom_ppr"
        and player.scoring_format.lower().replace("-", "_") in {"standard", "half_ppr", "ppr"}
    )
    recent_points = _recent_actual_points(player) if compatible_scoring else []
    recent_avg = (
        math.fsum(value / len(recent_points) for value in recent_points) if recent_points else 0.0
    )
    available_values: Dict[str, float] = {}
    inputs: List[str] = []
    fallbacks: List[str] = []

    context = player.projection_context if isinstance(player.projection_context, dict) else {}
    sleeper_projection = _finite_number(_sleeper_projection_for_format(player))
    if player.sleeper_projection_source == "sleeper_api" and compatible_scoring:
        if sleeper_projection is not None and (
            _sleeper_projection_explicitly_present(player)
            or ("sleeper_projection_present" not in context and sleeper_projection > 0)
        ):
            available_values["sleeper"] = sleeper_projection
            inputs.append(f"Sleeper real {player.scoring_format} projection")
        else:
            fallbacks.append(f"Sleeper real {player.scoring_format} projection unavailable")
    elif player.sleeper_projection_source:
        fallbacks.append(
            f"Sleeper projection omitted: {player.sleeper_projection_source} is not a real projection"
        )
    else:
        fallbacks.append("Sleeper real projection unavailable")

    if recent_points:
        available_values.update(
            {
                "recent_avg": recent_avg,
                "recent_floor": min(recent_points),
                "recent_ceiling": max(recent_points),
            }
        )
        inputs.append(f"Sleeper recent actuals ({len(recent_points)} weeks)")
    else:
        fallbacks.append("Sleeper recent actuals unavailable")

    if player.scoring_format_source == "yahoo_settings":
        inputs.append(f"Yahoo league scoring format: {player.scoring_format}")
    elif player.scoring_format_source == "fallback_custom_ppr":
        fallbacks.append("Custom scoring: incompatible Sleeper/PPR inputs omitted")
    else:
        fallbacks.append("Yahoo scoring format unavailable; PPR fallback used")

    provenance = context.get("source_provenance")
    recent_sources = ("recent_avg", "recent_floor", "recent_ceiling")
    recent_provenance_supplied = isinstance(provenance, dict) and any(
        source in provenance for source in recent_sources
    )
    if isinstance(provenance, dict) and provenance:
        # All recent summaries derive from the same observations. They cannot
        # override that cohort's provenance independently to reintroduce a
        # rejected average through its minimum, maximum, or role flags.
        checked_provenance = dict(provenance)
        supplied = [provenance[source] for source in recent_sources if source in provenance]
        if supplied:
            if any(meta != supplied[0] for meta in supplied[1:]):
                for source in recent_sources:
                    if source in available_values:
                        available_values.pop(source)
                        fallbacks.append(
                            f"{source} omitted: inconsistent_recent_actuals_provenance"
                        )
            else:
                for source in recent_sources:
                    checked_provenance[source] = supplied[0]
        # Apply common gates before baseline or utility consumes attributed inputs.
        checked = assess_projection(
            available_values,
            {source: 1.0 for source in available_values},
            **_assessment_request(player),
            source_provenance=checked_provenance,
        )
        for source in list(available_values):
            if source not in checked["effective_source_weights"]:
                available_values.pop(source)
                fallbacks.append(f"{source} omitted: {checked['missing_sources'][source]}")
    if "sleeper" not in available_values:
        inputs = [item for item in inputs if not item.startswith("Sleeper real ")]
    if "recent_avg" not in available_values:
        inputs = [item for item in inputs if not item.startswith("Sleeper recent actuals ")]
    weights = _STRATEGY_WEIGHTS[strategy]
    used_weight = math.fsum(weights[key] for key in weights if key in available_values)
    expected_score = (
        math.fsum(
            (weights[key] / used_weight) * available_values[key]
            for key in weights
            if key in available_values
        )
        if used_weight
        else 0.0
    )

    availability, health_flags = _availability_multiplier(player, strategy)
    recent_provenance_allowed = not (
        recent_provenance_supplied and "recent_avg" not in available_values
    )
    role, role_inputs = _role_multiplier(
        player, strategy, include_recent_flags=recent_provenance_allowed
    )
    inputs.extend(role_inputs)
    if not role_inputs:
        fallbacks.append("Roster/role evidence unavailable")

    news_context = news_context or {}
    news_signals = _news_signals(news_context)
    if news_context.get("espn") or news_context.get("rotowire"):
        inputs.append("Attributed ESPN/RotoWire news (qualitative only)")
    else:
        fallbacks.append("ESPN/RotoWire player evidence unavailable")

    evidence_groups = sum(
        (
            "sleeper" in available_values,
            "recent_avg" in available_values,
            bool(role_inputs),
            bool(news_context.get("espn") or news_context.get("rotowire")),
        )
    )
    confidence = "high" if evidence_groups >= 4 else "medium" if evidence_groups >= 2 else "low"
    if health_flags or any(
        signal["signal"] == "availability_or_role_risk" for signal in news_signals
    ):
        confidence = {"high": "medium", "medium": "low", "low": "low"}[confidence]

    strategy_score = -1.0 if availability == 0 else expected_score * availability * role
    return strategy_score, {
        "strategy_score": round(strategy_score, 3),
        "inputs_used": inputs,
        "fallbacks": fallbacks,
        "health_flags": health_flags,
        "news_signals": news_signals,
        "confidence": confidence,
        "opponent_aware": False,
        "news_scoring_note": (
            "Attributed news can flag qualitative risk or confidence; headlines are not converted to points."
        ),
        "_projection_inputs": {
            "available_values": available_values,
            "strategy_base_utility": expected_score,
            "availability_multiplier": availability,
            "role_multiplier": role,
        },
    }


def _assessment_request(player: Player) -> Dict[str, Any]:
    context = player.projection_context if isinstance(player.projection_context, dict) else {}
    basis = (
        "custom"
        if player.scoring_format_source == "fallback_custom_ppr"
        else (
            player.scoring_format.replace("-", "_")
            if player.scoring_format_source == "yahoo_settings"
            else "unknown"
        )
    )
    return {
        "player_id": player.player_key or player.sleeper_id or "",
        "scoring_basis": basis,
        "season": (
            context["season"]
            if type(context.get("season")) is int and 2000 <= context["season"] <= 2100
            else None
        ),
        "week": (
            context["week"]
            if type(context.get("week")) is int and 1 <= context["week"] <= 30
            else None
        ),
        "game_id": context.get("game_id"),
        "as_of": context.get("as_of"),
        "kickoff": context.get("kickoff"),
    }


def assess_player_projection(
    player: Player,
    strategy: str = "balanced",
    news_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Shared canonical projection and separate legacy strategy-utility assessment.

    Fresh verified market inputs may supply a bounded provisional correction;
    weather effects still require their own verified applicability/model.
    Unknown request periods remain unknown, and legacy weighting stays labeled.
    """
    aliases = {"floor": "conservative", "ceiling": "aggressive"}
    strategy_used = aliases.get(str(strategy).lower(), str(strategy).lower())
    if strategy_used not in _STRATEGY_WEIGHTS:
        strategy_used = "balanced"
    _, evidence = _strategy_components(player, strategy_used, news_context)
    components = evidence.pop("_projection_inputs")
    available = components["available_values"]
    context = player.projection_context if isinstance(player.projection_context, dict) else {}
    request = _assessment_request(player)
    scoring_basis = request["scoring_basis"]
    identity = request["player_id"]
    # Sleeper alone supplies player point forecasts. Yahoo values are retained
    # for comparison, and recent actuals support the separate utility policy.
    baseline_weights = {"sleeper": 1.0}
    values = {source: available.get(source) for source in baseline_weights}
    # Preserve valid numeric provider values even if provenance excludes them
    # from the weighted baseline; availability/missingness is separately stated.
    raw_values = {
        "yahoo": _finite_number(player.yahoo_projection),
        "sleeper": _finite_number(_sleeper_projection_for_format(player)),
    }
    availability = components["availability_multiplier"]
    role = components["role_multiplier"]
    constraints = list(evidence["health_flags"]) if availability == 0 else []
    slot = (player.roster_position or player.position).upper()
    if slot in BENCH_SLOTS - {"BN", "BENCH"}:
        constraints.append("Reserve roster slot is not eligible for selection")
    if player.lineup_locked is True and slot in BENCH_SLOTS:
        constraints.append("Locked bench player cannot enter lineup")
    provenance = context.get("source_provenance")
    if not isinstance(provenance, dict):
        provenance = None
    from src.services.weekly_projection_runtime import weekly_context_adjustments

    adjustments, policy, market_estimate, context_estimate = weekly_context_adjustments(
        context, request
    )
    strategy_weights = _STRATEGY_WEIGHTS[strategy_used]
    available_weight = math.fsum(
        weight for source, weight in strategy_weights.items() if source in available
    )
    effective_utility_weights = {
        source: weight / available_weight
        for source, weight in strategy_weights.items()
        if source in available and available_weight > 0
    }
    assessment = assess_projection(
        values,
        baseline_weights,
        **request,
        strategy_base_utility=components["strategy_base_utility"],
        strategy_projection_weight=effective_utility_weights.get("sleeper", 0.0),
        utility_multiplier=availability * role,
        eligible=availability > 0 and not constraints,
        constraints=constraints,
        source_provenance=provenance,
        adjustments=adjustments,
        policy=policy,
        uncertainty={"status": "not_calibrated", "evidence_confidence": evidence["confidence"]},
    )
    assessment["market_estimate"] = market_estimate
    assessment["context_estimate"] = context_estimate
    assessment["market_input_status"] = context.get(
        "market_input_status",
        {"status": "unavailable", "reason": "No live current-game market inputs collected"},
    )
    assessment["raw_provider_values"] = raw_values
    assessment["baseline_source_policy"] = {
        "sources": ["sleeper"],
        "comparison_only_sources": ["yahoo"],
        "status": "sleeper_primary_provider_forecast_not_calibrated",
    }
    assessment["supporting_evidence"] = {
        "recent_actuals": {
            "average": available.get("recent_avg"),
            "minimum": available.get("recent_floor"),
            "maximum": available.get("recent_ceiling"),
            "role": "legacy_strategy_utility_only_not_provider_point_forecast",
        },
    }
    if assessment["baseline_expected_points"] is None:
        assessment["limitations"].append(
            "Sleeper point forecast unavailable; Yahoo is comparison only; "
            "recent actuals can inform legacy utility only"
        )
    assessment["strategy"] = strategy_used
    adjusted_utility_values = dict(available)
    if "sleeper" in adjusted_utility_values:
        adjusted_utility_values["sleeper"] = assessment["final_expected_points"]
    assessment["strategy_trace"].update(
        availability_multiplier=availability,
        role_multiplier=role,
        utility_source_weights=dict(_STRATEGY_WEIGHTS[strategy_used]),
        effective_utility_source_weights=effective_utility_weights,
        raw_utility_source_values=dict(available),
        utility_source_values=adjusted_utility_values,
    )
    assessment["limitations"].extend(evidence["fallbacks"])
    assessment["limitations"].append(
        "Canonical scoring class only; custom bonus/stat-rule equivalence not verified"
    )
    if not identity:
        assessment["limitations"].append("Stable player identity unavailable")
    if request["season"] is None or request["week"] is None:
        assessment["limitations"].append("Projection period unverified")
    if scoring_basis == "unknown":
        assessment["limitations"].append("League scoring unverified; PPR fallback is provisional")
    warning_values = context.get("projection_input_warnings")
    if isinstance(warning_values, list):
        assessment["limitations"].extend(str(value) for value in warning_values)
    if context.get("enrichment_unavailable_reason"):
        assessment["limitations"].append(str(context["enrichment_unavailable_reason"]))
    if context.get("historical_enrichment"):
        assessment["limitations"].append(
            "Historical enrichment does not establish immutable pregame forecast or status snapshots"
        )
    invalid_forecast = _finite_number(_sleeper_projection_for_format(player)) is None
    if (invalid_forecast and not available) or (
        assessment["eligibility"]["eligible"] and assessment["strategy_utility"] is None
    ):
        assessment["eligibility"] = {
            "eligible": False,
            "constraints": ["No finite projection utility available"],
        }
        assessment["strategy_utility"] = None
    evidence["strategy_score"] = (
        round(assessment["strategy_utility"], 3)
        if assessment["strategy_utility"] is not None
        else None
    )
    assessment["decision_evidence"] = evidence
    return assessment


def _strategy_score(
    player: Player,
    strategy: str,
    news_context: Optional[Dict[str, Any]] = None,
) -> tuple[float, Dict[str, Any]]:
    assessment = assess_player_projection(player, strategy, news_context)
    score = assessment["strategy_utility"]
    score = score if score is not None else -1.0  # Exclusion sentinel, not a projection.
    evidence = dict(assessment["decision_evidence"])
    evidence["strategy_score"] = round(score, 3)
    evidence["projection_assessment"] = assessment
    player.projection_assessment = assessment
    return score, evidence


def _natural_positions(player: Player) -> set[str]:
    raw = player.position.upper().replace("D/ST", "DEF").replace("DST", "DEF")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _eligible_for_slot(player: Player, slot: str) -> bool:
    normalized_slot = slot.upper().replace("D/ST", "DEF").replace("DST", "DEF")
    positions = _natural_positions(player)
    eligible = _FLEX_ELIGIBILITY.get(normalized_slot)
    return bool(positions & eligible) if eligible else normalized_slot in positions


def _slot_label(slot: str) -> str:
    return {
        "W/R/T": "FLEX",
        "Q/W/R/T": "SUPERFLEX",
        "OP": "SUPERFLEX",
        "D/ST": "DEF",
        "DST": "DEF",
    }.get(slot.upper(), slot.upper())


def _optimal_assignment(
    slots: Sequence[tuple[int, str]],
    players: Sequence[Player],
    scores: Dict[int, float],
    fixed: Dict[int, Player],
) -> Dict[int, Player]:
    """Maximum-cardinality, maximum-score bipartite matching using residual paths."""
    result = dict(fixed)
    used = {id(player) for player in fixed.values()}
    remaining_slots = [(index, slot) for index, slot in slots if index not in fixed]
    candidates = [player for player in players if id(player) not in used]
    source = 0
    player_offset = 1 + len(remaining_slots)
    sink = player_offset + len(candidates)
    graph = [[] for _ in range(sink + 1)]

    def edge(start: int, end: int, cost: float):
        forward = [end, len(graph[end]), 1, cost]
        reverse = [start, len(graph[start]), 0, -cost]
        graph[start].append(forward)
        graph[end].append(reverse)
        return forward

    assignments = []
    for slot_index, (original_index, slot) in enumerate(remaining_slots, start=1):
        edge(source, slot_index, 0.0)
        for player_index, player in enumerate(candidates, start=player_offset):
            if _eligible_for_slot(player, slot):
                assignments.append(
                    (original_index, player, edge(slot_index, player_index, -scores[id(player)]))
                )
    for player_index in range(player_offset, sink):
        edge(player_index, sink, 0.0)
    while True:
        distances = [float("inf")] * len(graph)
        previous = [None] * len(graph)
        distances[source] = 0.0
        for _ in range(len(graph) - 1):
            changed = False
            for start, edges in enumerate(graph):
                for edge_index, item in enumerate(edges):
                    end, _, capacity, cost = item
                    value = distances[start] + cost
                    if capacity and value < distances[end] - 1e-12:
                        distances[end] = value
                        previous[end] = (start, edge_index)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            start, edge_index = previous[node]
            item = graph[start][edge_index]
            item[2] = 0
            graph[node][item[1]][2] = 1
            node = start
    for index, player, item in assignments:
        if item[2] == 0:
            result[index] = player
    return result


class LineupOptimizer:
    """Best-effort lineup helper that works entirely offline."""

    def __init__(self) -> None:
        pass

    async def parse_yahoo_roster(self, roster_payload: Dict[str, Any]) -> List[Player]:
        """Convert a roster payload into Player objects.

        Supports both the simplified JSON returned by ``ff_get_roster`` and the
        raw Yahoo payload by delegating to ``parse_team_roster`` when needed.
        """

        entries: List[Dict[str, Any]] = []
        if isinstance(roster_payload, dict):
            roster_obj = roster_payload.get("roster")
            if isinstance(roster_obj, list):
                entries = roster_obj
            else:
                # Fallback: try using the legacy parser for raw Yahoo data
                try:
                    from fantasy_football_multi_league import parse_team_roster  # type: ignore

                    entries = parse_team_roster(roster_payload)
                except Exception:
                    entries = []
        players: List[Player] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or entry.get("full_name") or "").strip()
            if not name:
                continue
            team = str(
                entry.get("team")
                or entry.get("editorial_team_abbr")
                or entry.get("team_abbr")
                or entry.get("team_abbreviation")
                or ""
            ).strip()
            roster_position = _normalize_position(
                entry.get("selected_position")
                or entry.get("roster_position")
                or entry.get("position")
                or "BN"
            )
            position = _normalize_position(
                entry.get("display_position")
                or entry.get("eligible_position")
                or entry.get("position")
                or roster_position
            )
            player = Player(
                name=name,
                position=position,
                team=team,
                roster_position=roster_position,
                player_key=str(entry.get("player_key") or entry.get("player_id") or ""),
                projection_context=(
                    dict(entry["projection_context"])
                    if isinstance(entry.get("projection_context"), dict)
                    else {}
                ),
                lineup_locked=(
                    entry.get("lineup_locked")
                    if isinstance(entry.get("lineup_locked"), bool)
                    else None
                ),
                opponent=str(entry.get("opponent") or entry.get("opponent_abbr") or ""),
                status=str(entry.get("status") or "OK"),
                yahoo_projection=_coerce_float(
                    entry.get("yahoo_projection") or entry.get("projection")
                ),
                sleeper_projection=_coerce_float(entry.get("sleeper_projection")),
                sleeper_projection_std=_coerce_float(entry.get("sleeper_projection_std")),
                sleeper_projection_ppr=_coerce_float(entry.get("sleeper_projection_ppr")),
                sleeper_projection_half_ppr=_coerce_float(entry.get("sleeper_projection_half_ppr")),
                sleeper_projection_source=str(entry.get("sleeper_projection_source") or ""),
                sleeper_id=str(entry.get("sleeper_id") or ""),
                sleeper_status=str(entry.get("sleeper_status") or ""),
                sleeper_injury_status=str(entry.get("sleeper_injury_status") or ""),
                sleeper_depth_chart_order=_coerce_int(entry.get("sleeper_depth_chart_order")),
                scoring_format=str(entry.get("scoring_format") or "ppr"),
                scoring_format_source=str(
                    entry.get("scoring_format_source") or "fallback_default_ppr"
                ),
                sleeper_match_method=str(entry.get("sleeper_match_method") or ""),
                player_tier=str(entry.get("player_tier") or "starter"),
                matchup_score=_coerce_int(entry.get("matchup_score"), default=50),
                matchup_description=str(entry.get("matchup_description") or "No matchup context"),
                trending_score=_coerce_int(entry.get("trending_score"), default=0),
                injury_status=str(entry.get("injury_status") or "Healthy"),
                injury_probability=_coerce_float(entry.get("injury_probability")),
                ownership_pct=_coerce_float(entry.get("ownership_pct")),
                season_avg=_coerce_float(entry.get("season_avg")),
                target_share=_coerce_float(entry.get("target_share")),
                snap_count_pct=_coerce_float(entry.get("snap_count_pct")),
                weather_impact=str(entry.get("weather_impact") or "Unknown"),
                vegas_total=_coerce_float(entry.get("vegas_total")),
                team_implied_total=_coerce_float(entry.get("team_implied_total")),
                spread=_coerce_float(entry.get("spread")),
                defense_rank_allowed=str(entry.get("def_rank_vs_pos") or "Unknown"),
                value=_coerce_float(entry.get("value") or entry.get("value_score")),
                value_score=_coerce_float(entry.get("value_score")),
                floor_projection=_coerce_float(entry.get("floor_projection")),
                ceiling_projection=_coerce_float(entry.get("ceiling_projection")),
                consistency_score=_coerce_float(entry.get("consistency_score")),
                risk_level=str(entry.get("risk_level") or "medium"),
                composite_score=_coerce_float(entry.get("composite_score")),
                bye=entry.get("bye", "N/A"),  # Extract bye week from Yahoo data
                raw=entry,
            )
            players.append(player)
        return players

    async def enhance_with_external_data(
        self,
        players: Sequence[Player],
        *,
        week: Optional[int] = None,
        season: Optional[int] = None,
    ) -> List[Player]:
        """Enhance players with Sleeper data including rankings, advice, and matchup analysis."""

        enhanced: List[Player] = []
        match_analytics = MatchAnalytics()

        try:
            from sleeper_api import sleeper_client

            # Get current season and week once for all players
            from sleeper_api import get_current_season, get_current_week

            live_season = await get_current_season()
            live_week = await get_current_week()
            context_seasons = {
                p.projection_context.get("season")
                for p in players
                if isinstance(p.projection_context, dict)
                and type(p.projection_context.get("season")) is int
                and 2000 <= p.projection_context["season"] <= 2100
            }
            context_weeks = {
                p.projection_context.get("week")
                for p in players
                if isinstance(p.projection_context, dict)
                and type(p.projection_context.get("week")) is int
                and 1 <= p.projection_context["week"] <= 30
            }
            current_season = (
                season
                if season is not None
                else (next(iter(context_seasons)) if len(context_seasons) == 1 else live_season)
            )
            current_week = (
                week
                if week is not None
                else (
                    next(iter(context_weeks))
                    if len(context_weeks) == 1
                    else live_week if current_season == live_season else None
                )
            )
            inconsistent = (
                len(context_seasons) > 1
                or len(context_weeks) > 1
                or (context_seasons and context_seasons != {current_season})
                or (context_weeks and context_weeks != {current_week})
            )
            if (
                inconsistent
                or type(current_season) is not int
                or not 2000 <= current_season <= 2100
                or type(current_week) is not int
                or not 1 <= current_week <= 30
            ):
                # Never substitute this season's live week for a different/unknown request period.
                return [
                    replace(
                        p,
                        projection_context={
                            **p.projection_context,
                            "enrichment_unavailable_reason": "Requested enrichment period is unverified or inconsistent",
                        },
                    )
                    for p in players
                ]
            historical_period = current_season < live_season or (
                current_season == live_season and current_week < live_week
            )
            try:
                sleeper_players = await sleeper_client.get_all_players()
            except Exception:
                sleeper_players = {}

            for player in players:
                # Create a copy to avoid modifying the original
                enhanced_player = Player(
                    name=player.name,
                    position=player.position,
                    team=player.team,
                    roster_position=player.roster_position,
                    opponent=player.opponent,
                    status=player.status,
                    yahoo_projection=player.yahoo_projection,
                    sleeper_projection=player.sleeper_projection,
                    sleeper_projection_std=player.sleeper_projection_std,
                    sleeper_projection_ppr=player.sleeper_projection_ppr,
                    sleeper_projection_half_ppr=player.sleeper_projection_half_ppr,
                    sleeper_projection_source=player.sleeper_projection_source,
                    sleeper_id=player.sleeper_id,
                    sleeper_status=player.sleeper_status,
                    sleeper_injury_status=player.sleeper_injury_status,
                    sleeper_depth_chart_order=player.sleeper_depth_chart_order,
                    scoring_format=player.scoring_format,
                    scoring_format_source=player.scoring_format_source,
                    weekly_matchup_evidence=player.weekly_matchup_evidence.copy(),
                    sleeper_match_method=player.sleeper_match_method,
                    player_tier=player.player_tier,
                    matchup_score=player.matchup_score,
                    matchup_description=player.matchup_description,
                    trending_score=player.trending_score,
                    injury_status=player.injury_status,
                    injury_probability=player.injury_probability,
                    ownership_pct=player.ownership_pct,
                    recent_performance=player.recent_performance.copy(),
                    season_avg=player.season_avg,
                    target_share=player.target_share,
                    snap_count_pct=player.snap_count_pct,
                    weather_impact=player.weather_impact,
                    vegas_total=player.vegas_total,
                    team_implied_total=player.team_implied_total,
                    spread=player.spread,
                    defense_rank_allowed=player.defense_rank_allowed,
                    value=player.value,
                    value_score=player.value_score,
                    floor_projection=player.floor_projection,
                    ceiling_projection=player.ceiling_projection,
                    consistency_score=player.consistency_score,
                    risk_level=player.risk_level,
                    composite_score=player.composite_score,
                    raw=player.raw.copy(),
                    bye=player.bye,
                    on_bye=player.on_bye,
                    recent_performance_data=player.recent_performance_data,
                    performance_flags=player.performance_flags.copy(),
                    enhancement_context=player.enhancement_context,
                    adjusted_projection=player.adjusted_projection,
                    player_key=player.player_key,
                    lineup_locked=player.lineup_locked,
                    projection_context=dict(player.projection_context),
                )

                # A failed refresh cannot present a previous period as current.
                enhanced_player.raw.pop("weekly_projection", None)
                enhanced_player.projection_context.pop("sleeper_projection_present", None)
                enhanced_player.projection_context.pop("sleeper_projection_scoring_format", None)
                enhanced_player.sleeper_projection_source = ""
                for field_name in (
                    "sleeper_projection",
                    "sleeper_projection_std",
                    "sleeper_projection_ppr",
                    "sleeper_projection_half_ppr",
                ):
                    setattr(enhanced_player, field_name, 0.0)
                enhanced_player.recent_performance_data = None
                enhanced_player.recent_performance = []
                enhanced_player.performance_flags = []
                enhanced_player.adjusted_projection = 0.0
                enhanced_player.enhancement_context = ""
                _finite_legacy_projection_fields(enhanced_player)
                use_week = current_week
                if historical_period:
                    enhanced_player.projection_context["historical_enrichment"] = True
                logger.debug(
                    "enhance_with_external_data: player=%s original_bye=%r requested_week=%s api_current_week=%s use_week=%s",
                    player.name,
                    player.bye,
                    week,
                    current_week,
                    use_week,
                )

                try:
                    # Get Sleeper player mapping and basic data
                    sleeper_id = await sleeper_client.map_yahoo_to_sleeper(
                        player.name, position=player.position, team=player.team
                    )

                    if sleeper_id:
                        enhanced_player.sleeper_id = sleeper_id
                        enhanced_player.sleeper_match_method = "api"
                        enhanced_player.bye = player.bye
                        sleeper_player = sleeper_players.get(str(sleeper_id), {})
                        if not historical_period:
                            enhanced_player.sleeper_status = str(sleeper_player.get("status") or "")
                            enhanced_player.sleeper_injury_status = str(
                                sleeper_player.get("injury_status") or ""
                            )
                            enhanced_player.sleeper_depth_chart_order = _coerce_int(
                                sleeper_player.get("depth_chart_order")
                            )

                        # Fetch projections for this player
                        try:
                            projections = await sleeper_client.get_projections(
                                current_season, use_week
                            )
                            if sleeper_id in projections:
                                proj_data = projections[sleeper_id]
                                projection_source = str(proj_data.get("projection_source") or "")
                                enhanced_player.sleeper_projection_source = projection_source
                                if projection_source != "sleeper_api":
                                    raise ValueError(
                                        f"Unsupported Sleeper projection source: {projection_source or 'unknown'}"
                                    )
                                stats = proj_data.get("projected_stats", {})
                                fields = {
                                    "pts": "sleeper_projection",
                                    "pts_std": "sleeper_projection_std",
                                    "pts_ppr": "sleeper_projection_ppr",
                                    "pts_half_ppr": "sleeper_projection_half_ppr",
                                }
                                present = set()
                                if isinstance(stats, list):
                                    totals = {key: _projection_sum(stats, key) for key in fields}
                                    present = {
                                        key
                                        for key in fields
                                        if stats
                                        and all(
                                            isinstance(row, dict)
                                            and row.get(key) is not None
                                            and row.get(key) != ""
                                            for row in stats
                                        )
                                    }
                                elif isinstance(stats, dict):
                                    totals = {}
                                    for key in fields:
                                        raw = stats[key] if key in stats else proj_data.get(key)
                                        totals[key] = _projection_number(raw)
                                        if raw is not None and raw != "":
                                            present.add(key)
                                else:
                                    raise ValueError("Invalid Sleeper projected stats")
                                for key, field_name in fields.items():
                                    setattr(enhanced_player, field_name, totals[key])
                                scoring_format = enhanced_player.scoring_format.lower().replace(
                                    "-", "_"
                                )
                                selected_field = {
                                    "standard": "pts_std",
                                    "ppr": "pts_ppr",
                                    "half_ppr": "pts_half_ppr",
                                }.get(scoring_format)
                                enhanced_player.projection_context.update(
                                    sleeper_projection_present=selected_field in present,
                                    sleeper_projection_scoring_format=scoring_format,
                                )
                                from copy import deepcopy

                                enhanced_player.raw["weekly_projection"] = deepcopy(proj_data)
                                if proj_data.get("opponent"):
                                    enhanced_player.opponent = str(proj_data["opponent"])
                        except Exception:
                            # Reject the entire malformed aggregate, including cached format fields.
                            enhanced_player.raw.pop("weekly_projection", None)
                            enhanced_player.projection_context.pop(
                                "sleeper_projection_present", None
                            )
                            enhanced_player.projection_context.pop(
                                "sleeper_projection_scoring_format", None
                            )
                            for projection_field in (
                                "sleeper_projection",
                                "sleeper_projection_std",
                                "sleeper_projection_ppr",
                                "sleeper_projection_half_ppr",
                            ):
                                setattr(enhanced_player, projection_field, 0.0)
                            if enhanced_player.sleeper_projection_source in ("", "sleeper_api"):
                                enhanced_player.sleeper_projection_source = "invalid_projection"
                            _projection_warning(
                                enhanced_player,
                                "Sleeper projection unavailable: invalid, unsupported, or nonfinite aggregate",
                            )

                        # Get expert advice for this player
                        advice = (
                            await sleeper_client.get_expert_advice(
                                player.name,
                                week=use_week,
                                scoring_format=(
                                    enhanced_player.scoring_format
                                    if enhanced_player.scoring_format_source == "yahoo_settings"
                                    else "unknown"
                                ),
                            )
                            if not historical_period
                            else {}
                        )
                        if advice and advice.get("confidence", 0) > 0:
                            enhanced_player.expert_tier = advice.get("tier", "starter")
                            enhanced_player.expert_recommendation = advice.get(
                                "recommendation", "Start"
                            )
                            enhanced_player.expert_confidence = advice.get("confidence", 50)
                            enhanced_player.expert_advice = advice.get(
                                "advice", "No advice available"
                            )
                            enhanced_player.search_rank = advice.get("search_rank", 500)
                            enhanced_player.matchup_description = advice.get(
                                "advice", "No advice available"
                            )

                            # Convert confidence to matchup score (0-100 -> 0-100)
                            enhanced_player.matchup_score = advice.get("confidence", 50)

                            # Set risk level based on tier and confidence
                            confidence = advice.get("confidence", 50)
                            if confidence >= 70:
                                enhanced_player.risk_level = "low"
                            elif confidence >= 50:
                                enhanced_player.risk_level = "medium"
                            else:
                                enhanced_player.risk_level = "high"

                        if not historical_period:
                            # Try to get trending data
                            try:
                                trending_adds = await sleeper_client.get_trending_players(
                                    "nfl", "add", hours=24
                                )
                                trending_drops = await sleeper_client.get_trending_players(
                                    "nfl", "drop", hours=24
                                )

                                # Check if this player is trending
                                trending_add_ids = [p.get("player_id") for p in trending_adds]
                                trending_drop_ids = [p.get("player_id") for p in trending_drops]

                                if sleeper_id in trending_add_ids:
                                    enhanced_player.trending_score = 75  # Trending up
                                elif sleeper_id in trending_drop_ids:
                                    enhanced_player.trending_score = 25  # Trending down
                                else:
                                    enhanced_player.trending_score = 50  # Neutral
                            except Exception:
                                enhanced_player.trending_score = 50  # Default if trending fails

                    # ===== ENHANCEMENT LAYER: Bye weeks & recent stats context =====
                    try:
                        from src.services.player_enhancement import enhance_player_with_context

                        enhancement = await enhance_player_with_context(
                            enhanced_player,
                            current_week=use_week,
                            season=current_season,
                            sleeper_api=sleeper_client,
                        )

                        # Apply bye week override
                        if enhancement.on_bye:
                            # Availability excludes a bye player. Preserve the provider
                            # forecasts for audit rather than rewriting source evidence.
                            enhanced_player.expert_recommendation = (
                                enhancement.recommendation_override
                            )
                            enhanced_player.risk_level = "n/a"
                            enhanced_player.player_tier = "bye"

                        # Store enhancement data on player
                        enhanced_player.on_bye = enhancement.on_bye
                        enhanced_player.recent_performance_data = enhancement.recent_performance
                        enhanced_player.performance_flags = enhancement.performance_flags
                        enhanced_player.enhancement_context = enhancement.context_message

                        # Use adjusted projection if available
                        if enhancement.adjusted_projection is not None and not enhancement.on_bye:
                            enhanced_player.adjusted_projection = enhancement.adjusted_projection
                        else:
                            enhanced_player.adjusted_projection = enhanced_player.sleeper_projection

                    except Exception:
                        # If enhancement fails, continue with original data
                        logger.exception("Player enhancement failed for %s", player.name)
                        enhanced_player.on_bye = False
                        enhanced_player.recent_performance_data = None
                        enhanced_player.performance_flags = []
                        enhanced_player.enhancement_context = "Enhancement unavailable"
                        enhanced_player.adjusted_projection = enhanced_player.sleeper_projection

                except Exception:
                    # If Sleeper lookup fails, keep original data
                    enhanced_player.sleeper_match_method = "failed"

                # Populate derived metrics with dynamic weighting
                match_confidence = _calculate_match_confidence(enhanced_player.sleeper_match_method)
                weights = _calculate_dynamic_weights(
                    enhanced_player.yahoo_projection,
                    enhanced_player.sleeper_projection,
                    match_confidence,
                )

                # Track match analytics
                match_analytics.add_match(enhanced_player.sleeper_match_method, match_confidence)

                # Populate player match analytics fields
                enhanced_player.match_confidence = match_confidence
                enhanced_player.match_analytics = {
                    "method": enhanced_player.sleeper_match_method,
                    "confidence": match_confidence,
                    "has_mismatch": "_mismatch" in (enhanced_player.sleeper_match_method or ""),
                    "weights_used": weights,
                }

                # Calculate weighted composite score
                if enhanced_player.composite_score == 0.0:
                    yahoo_component = enhanced_player.yahoo_projection * weights["yahoo"]
                    sleeper_component = enhanced_player.sleeper_projection * weights["sleeper"]
                    enhanced_player.composite_score = yahoo_component + sleeper_component

                    # Add debugging info to raw data for analysis
                    enhanced_player.raw["weighting_info"] = {
                        "match_confidence": match_confidence,
                        "yahoo_weight": weights["yahoo"],
                        "sleeper_weight": weights["sleeper"],
                        "yahoo_component": yahoo_component,
                        "sleeper_component": sleeper_component,
                    }
                if enhanced_player.floor_projection == 0.0:
                    enhanced_player.floor_projection = max(
                        enhanced_player.composite_score * 0.75, 0.0
                    )
                if enhanced_player.ceiling_projection == 0.0:
                    enhanced_player.ceiling_projection = max(
                        enhanced_player.composite_score * 1.25, enhanced_player.floor_projection
                    )
                if enhanced_player.matchup_description == "No matchup context":
                    enhanced_player.matchup_description = f"Week {use_week} outlook"
                if not enhanced_player.matchup_score:
                    enhanced_player.matchup_score = 50

                _finite_legacy_projection_fields(enhanced_player)
                enhanced.append(enhanced_player)

            # Add analytics summary to the first player's raw data for debugging
            if enhanced:
                enhanced[0].raw["session_analytics"] = {
                    "total_players": match_analytics.total_players,
                    "success_rate": match_analytics.get_success_rate(),
                    "avg_confidence": match_analytics.avg_match_confidence,
                    "quality_distribution": match_analytics.get_quality_distribution(),
                    "mismatches": {
                        "position": match_analytics.position_mismatches,
                        "team": match_analytics.team_mismatches,
                    },
                }

        except ImportError:
            # If Sleeper API not available, fall back to basic enhancement
            for player in players:
                if player.composite_score == 0.0:
                    # Use simple fallback without dynamic weighting
                    match_confidence = _calculate_match_confidence(player.sleeper_match_method)
                    if match_confidence > 0.5 and player.sleeper_projection:
                        # Trust existing Sleeper data if match confidence is good
                        weights = _calculate_dynamic_weights(
                            player.yahoo_projection, player.sleeper_projection, match_confidence
                        )
                        yahoo_component = player.yahoo_projection * weights["yahoo"]
                        sleeper_component = player.sleeper_projection * weights["sleeper"]
                        player.composite_score = yahoo_component + sleeper_component
                    else:
                        # Fall back to Yahoo only or simple average
                        player.composite_score = (
                            player.yahoo_projection or player.sleeper_projection or 0.0
                        )
                if player.floor_projection == 0.0:
                    player.floor_projection = max(player.composite_score * 0.75, 0.0)
                if player.ceiling_projection == 0.0:
                    player.ceiling_projection = max(
                        player.composite_score * 1.25, player.floor_projection
                    )
                if player.matchup_description == "No matchup context":
                    player.matchup_description = f"Week {week or 'current'} outlook"
                if not player.matchup_score:
                    player.matchup_score = 50
                _finite_legacy_projection_fields(player)
                enhanced.append(player)

        return enhanced

    async def optimize_lineup_smart(
        self,
        players: Sequence[Player],
        strategy: str = "balanced",
        week: Optional[int] = None,
        use_llm: bool = False,
        decision_news: Optional[Dict[str, Dict[str, Any]]] = None,
        rookie_intelligence: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
        use_matchup_evidence: bool = False,
        roster_slots: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Return a deterministic, evidence-labeled starter/bench split."""

        aliases = {"floor": "conservative", "ceiling": "aggressive"}
        requested_strategy = str(strategy or "balanced").lower()
        strategy_used = aliases.get(requested_strategy, requested_strategy)
        strategy_fallback = None
        if strategy_used not in _STRATEGY_WEIGHTS:
            strategy_fallback = f"Unknown strategy '{strategy}'; balanced used"
            strategy_used = "balanced"

        decision_news = decision_news or {}
        rookie_intelligence = rookie_intelligence or {}
        stable_ids = [
            f"yahoo:{p.player_key}" if p.player_key else f"sleeper:{p.sleeper_id}"
            for p in players
            if p.player_key or p.sleeper_id
        ]
        if len(stable_ids) != len(set(stable_ids)):
            return {"status": "error", "errors": ["Duplicate player identities in roster"]}
        preferred_keys = {
            id(player): (
                rookie_identity_token(player.name, player.position)
                if rookie_intelligence or use_matchup_evidence
                else player.name
            )
            for player in players
        }
        key_counts = Counter(preferred_keys.values())
        evidence_keys = {}
        for index, player in enumerate(players):
            preferred = preferred_keys[id(player)]
            if key_counts[preferred] == 1:
                evidence_keys[id(player)] = preferred
            else:
                stable_id = player.player_key or player.sleeper_id
                evidence_keys[id(player)] = f"{preferred}|{stable_id or 'roster:' + str(index)}"
        if len(set(evidence_keys.values())) != len(players):
            return {"status": "error", "errors": ["Duplicate player identities in roster"]}

        def evidence_key(player: Player) -> str:
            return evidence_keys[id(player)]

        scores: Dict[int, float] = {}
        player_evidence: Dict[str, Dict[str, Any]] = {}
        for player in players:
            score, evidence = _strategy_score(
                player,
                strategy_used,
                decision_news.get(player.name),
            )
            scores[id(player)] = score
            rookie_outlook = rookie_intelligence.get(
                rookie_identity_key(player.name, player.position)
            )
            if rookie_outlook:
                evidence["rookie_intelligence"] = rookie_outlook
                if rookie_outlook.get("status") == "matched":
                    evidence["inputs_used"].append(
                        "Reviewed rookie-year PPR outlook (near-tie context only)"
                    )
                else:
                    evidence["fallbacks"].extend(rookie_outlook.get("warnings", []))
            if use_matchup_evidence:
                evidence["weekly_matchup_evidence"] = player.weekly_matchup_evidence
                if player.weekly_matchup_evidence.get("available"):
                    evidence["inputs_used"].append(
                        "nflverse current-week opponent and defensive points allowed"
                    )
                else:
                    reason = player.weekly_matchup_evidence.get("unavailable_reason")
                    evidence["fallbacks"].append(
                        f"Weekly matchup evidence unavailable: {reason or 'unknown'}"
                    )
            player_evidence[evidence_key(player)] = evidence

        if roster_slots is None:
            active_slots = [
                (index, (player.roster_position or player.position).upper())
                for index, player in enumerate(players)
                if (player.roster_position or player.position).upper() not in BENCH_SLOTS
            ]
        else:
            active_slots = []
            for slot, count in roster_slots.items():
                if (
                    not isinstance(slot, str)
                    or not isinstance(count, int)
                    or isinstance(count, bool)
                    or count < 0
                ):
                    return {"status": "error", "errors": ["Invalid authoritative roster slots"]}
                normalized = _normalize_position(slot)
                if normalized not in BENCH_SLOTS:
                    for _ in range(count):
                        active_slots.append((len(active_slots), normalized))
        unavailable_reserve_slots = BENCH_SLOTS - {"BN", "BENCH"}
        candidates = [
            player
            for player in players
            if (player.roster_position or player.position).upper() not in unavailable_reserve_slots
            and _availability_multiplier(player, strategy_used)[0] > 0
            and player.projection_assessment.get("eligibility", {}).get("eligible", True)
            and not (
                use_matchup_evidence
                and player.weekly_matchup_evidence.get("schedule", {}).get("status") == "bye"
            )
            and player.lineup_locked is not True
        ]
        selection_errors = []
        selected_by_index: Dict[int, Player] = {}
        for player in players:
            if player.lineup_locked is not True:
                continue
            current_slot = (player.roster_position or player.position).upper()
            if current_slot in BENCH_SLOTS:
                continue  # A locked bench player cannot enter the lineup.
            matches = [
                index
                for index, slot in active_slots
                if slot == current_slot and index not in selected_by_index
            ]
            if not matches or not _eligible_for_slot(player, current_slot):
                return {
                    "status": "error",
                    "errors": ["Locked starter cannot be reconciled with required slots"],
                }
            selected_by_index[matches[0]] = player
            if _availability_multiplier(player, strategy_used)[0] == 0:
                selection_errors.append(
                    f"Locked unavailable player {player.name} cannot be replaced"
                )
        selected_ids = {id(player) for player in selected_by_index.values()}
        initial_assignment = _optimal_assignment(
            active_slots, candidates, scores, selected_by_index
        )
        target_filled = len(initial_assignment)
        target_score = math.fsum(scores[id(player)] for player in initial_assignment.values())
        assignment_order = sorted(
            active_slots,
            key=lambda item: (len(_FLEX_ELIGIBILITY.get(item[1], {item[1]})), item[0]),
        )
        processed_slots = set(selected_by_index)
        matchup_tiebreaks: list[dict[str, Any]] = []
        rookie_tiebreaks: list[dict[str, Any]] = []
        for index, slot in assignment_order:
            if index in selected_by_index:
                continue
            remaining_slots = [
                (i, value)
                for i, value in active_slots
                if i not in processed_slots or i in selected_by_index
            ]
            eligible = []
            for player in candidates:
                if id(player) in selected_ids or not _eligible_for_slot(player, slot):
                    continue
                forced = {**selected_by_index, index: player}
                completion = _optimal_assignment(remaining_slots, candidates, scores, forced)
                total = math.fsum(scores[id(value)] for value in completion.values())
                if len(completion) == target_filled and round(total, 1) == round(target_score, 1):
                    eligible.append(player)
            processed_slots.add(index)
            exact_completion = _optimal_assignment(
                remaining_slots, candidates, scores, selected_by_index
            )
            selected = exact_completion.get(index)
            if selected is None:
                continue
            # Floating-point comparisons must never turn an exact feasible
            # completion into an unfilled slot. Tie alternatives still require
            # the global rounding guard above; this is the solver's baseline.
            if not any(candidate is selected for candidate in eligible):
                eligible.append(selected)
            best_score = scores[id(selected)]
            best_evidence = player_evidence[evidence_key(selected)]
            best_weekly_sources = {
                source
                for source, available in (
                    (
                        "sleeper_projection",
                        _sleeper_projection_for_format(selected) > 0
                        and selected.sleeper_projection_source == "sleeper_api",
                    ),
                    ("recent_actuals", bool(_recent_actual_points(selected))),
                )
                if available
            }
            best_has_availability_risk = (
                bool(best_evidence["health_flags"])
                or any(
                    signal.get("signal") == "availability_or_role_risk"
                    for signal in best_evidence["news_signals"]
                )
                or (
                    use_matchup_evidence
                    and selected.weekly_matchup_evidence.get("schedule", {}).get("status") == "bye"
                )
            )
            safe_near_ties = []
            if not best_has_availability_risk and best_score > 0 and best_weekly_sources:
                safe_near_ties = [
                    player
                    for player in eligible
                    if not player_evidence[evidence_key(player)]["health_flags"]
                    and not (
                        use_matchup_evidence
                        and player.weekly_matchup_evidence.get("schedule", {}).get("status")
                        == "bye"
                    )
                    and not any(
                        signal.get("signal") == "availability_or_role_risk"
                        for signal in player_evidence[evidence_key(player)]["news_signals"]
                    )
                    and scores[id(player)] > 0
                    and bool(
                        best_weekly_sources
                        & {
                            source
                            for source, available in (
                                (
                                    "sleeper_projection",
                                    _sleeper_projection_for_format(player) > 0
                                    and player.sleeper_projection_source == "sleeper_api",
                                ),
                                ("recent_actuals", bool(_recent_actual_points(player))),
                            )
                            if available
                        }
                    )
                    and round(scores[id(player)], 1) == round(best_score, 1)
                ]
            matchup_resolved = False
            if use_matchup_evidence and safe_near_ties:
                sourced = [
                    player
                    for player in safe_near_ties
                    if player.weekly_matchup_evidence.get("available")
                    and isinstance(player.weekly_matchup_evidence.get("percentile"), (int, float))
                ]
                if selected in sourced and len(sourced) >= 2:
                    matchup_choice = max(
                        sourced,
                        key=lambda player: float(player.weekly_matchup_evidence["percentile"]),
                    )
                    runner_up = max(
                        (player for player in sourced if player is not matchup_choice),
                        key=lambda player: float(player.weekly_matchup_evidence["percentile"]),
                    )
                    matchup_gap = float(
                        matchup_choice.weekly_matchup_evidence["percentile"]
                    ) - float(runner_up.weekly_matchup_evidence["percentile"])
                    if matchup_gap >= 12.5:
                        previous_selected = selected
                        audit = {
                            "slot": _slot_label(slot),
                            "selected": matchup_choice.name,
                            "over": runner_up.name,
                            "rounded_weekly_score": round(best_score, 1),
                            "percentile_gap": round(matchup_gap, 3),
                            "threshold": 12.5,
                            "selection_changed": matchup_choice is not previous_selected,
                            "numeric_scores_changed": False,
                        }
                        matchup_tiebreaks.append(audit)
                        matchup_choice.weekly_matchup_evidence["applied"] = True
                        matchup_choice.weekly_matchup_evidence["tie_break_audit"].append(audit)
                        selected = matchup_choice
                        matchup_resolved = True
            if not matchup_resolved and safe_near_ties:
                near_tied_rookies = [
                    player
                    for player in safe_near_ties
                    if rookie_intelligence.get(
                        rookie_identity_key(player.name, player.position), {}
                    ).get("status")
                    == "matched"
                ]
                if near_tied_rookies:
                    rookie_choice = min(
                        near_tied_rookies,
                        key=lambda player: rookie_intelligence[
                            rookie_identity_key(player.name, player.position)
                        ]["base_rank"],
                    )
                    if rookie_choice is not selected:
                        rookie_tiebreaks.append(
                            {
                                "slot": _slot_label(slot),
                                "selected": rookie_choice.name,
                                "over": selected.name,
                                "rounded_weekly_score": round(best_score, 1),
                                "rookie_base_rank": rookie_intelligence[
                                    rookie_identity_key(rookie_choice.name, rookie_choice.position)
                                ]["base_rank"],
                                "note": (
                                    "Season-long rookie outlook broke a rounded weekly-score tie; "
                                    "numeric weekly scores and health evidence were not changed."
                                ),
                            }
                        )
                        player_evidence[evidence_key(rookie_choice)][
                            "rookie_tiebreak_applied"
                        ] = True
                        selected = rookie_choice
            selected_ids.add(id(selected))
            selected_by_index[index] = selected

        label_totals: Dict[str, int] = {}
        for _, slot in active_slots:
            label = _slot_label(slot)
            label_totals[label] = label_totals.get(label, 0) + 1
        label_seen: Dict[str, int] = {}
        starters: Dict[str, Player] = {}
        for index, slot in active_slots:
            label = _slot_label(slot)
            label_seen[label] = label_seen.get(label, 0) + 1
            output_label = f"{label}{label_seen[label]}" if label_totals[label] > 1 else label
            selected = selected_by_index.get(index)
            if selected is None:
                selection_errors.append(
                    f"Unfilled required slot {output_label}: no available eligible player"
                )
                continue
            starters[output_label] = selected

        bench = [player for player in players if id(player) not in selected_ids]

        recommendations = [
            (
                f"Locked {p.name} at {pos}; no replacement allowed"
                if p.lineup_locked is True
                else f"Start {p.name} at {pos}"
            )
            for pos, p in starters.items()
        ]
        all_inputs = sorted(
            {value for evidence in player_evidence.values() for value in evidence["inputs_used"]}
        )
        all_fallbacks = sorted(
            {value for evidence in player_evidence.values() for value in evidence["fallbacks"]}
        )
        if strategy_fallback:
            all_fallbacks.append(strategy_fallback)
        data_quality = {
            "total_players": len(players),
            "valid_players": sum(1 for p in players if p.is_valid()),
            "players_with_projections": sum(
                1
                for p in players
                if {"yahoo", "sleeper"}
                & p.projection_assessment.get("effective_source_weights", {}).keys()
            ),
            "players_with_matchup_data": sum(
                1
                for p in players
                if (
                    p.weekly_matchup_evidence.get("schedule", {}).get("status") == "matched"
                    if use_matchup_evidence
                    else p.matchup_description and p.matchup_description != "No matchup context"
                )
            ),
            "players_with_sleeper_match": sum(
                1 for p in players if p.sleeper_id and p.sleeper_match_method not in ["failed", ""]
            ),
            "avg_match_confidence": (
                sum(p.match_confidence for p in players) / len(players) if players else 0
            ),
            "high_confidence_matches": sum(1 for p in players if p.match_confidence >= 0.8),
            "low_confidence_matches": sum(1 for p in players if 0 < p.match_confidence < 0.6),
        }

        result = {
            "status": "success",
            "strategy_used": strategy_used,
            "strategy_requested": strategy,
            "week": week or "current",
            "starters": starters,
            "bench": bench,
            "recommendations": recommendations,
            "errors": selection_errors,
            "data_quality": data_quality,
            "player_evidence": player_evidence,
            "strategy_summary": {
                "inputs_used": all_inputs,
                "fallbacks": all_fallbacks,
                "opponent_aware": bool(matchup_tiebreaks),
                "assignment_audit": {
                    "objective": (
                        "maximum filled slots, then total strategy score; "
                        "documented rounded-score tie policies"
                    ),
                    "optimal_total_score": target_score,
                    "selected_total_score": math.fsum(scores[id(p)] for p in starters.values()),
                    "rounding_precision": 1,
                    "required_slots_source": (
                        "league_settings"
                        if roster_slots is not None
                        else "occupied_roster_positions"
                    ),
                    "lock_status_verified": all(p.lineup_locked is not None for p in players),
                    "evidence_keys": {
                        str(index): evidence_key(p) for index, p in enumerate(players)
                    },
                },
                "note": (
                    "Selection uses Yahoo plus provenance-gated Sleeper evidence. "
                    "Attributed news affects qualitative confidence/risk only."
                ),
            },
        }
        if use_matchup_evidence:
            result["strategy_summary"]["weekly_matchup_evidence"] = {
                "enabled": True,
                "available_players": sum(
                    1 for player in players if player.weekly_matchup_evidence.get("available")
                ),
                "applied": bool(matchup_tiebreaks),
                "numeric_scores_changed": False,
                "tie_break_audit": matchup_tiebreaks,
            }
        if rookie_intelligence:
            result["strategy_summary"]["rookie_intelligence"] = {
                "role": "rounded weekly-score tie break only",
                "tiebreaks": rookie_tiebreaks,
                "numeric_scores_changed": False,
                "opponent_aware": False,
                "note": "Season-long first-year PPR outlook is not a weekly projection.",
            }
        return result


lineup_optimizer = LineupOptimizer()

__all__ = ["Player", "LineupOptimizer", "lineup_optimizer", "assess_player_projection"]
