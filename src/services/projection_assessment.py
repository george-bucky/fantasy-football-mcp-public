"""Pure, versioned projection ledger; policy artifacts are trusted server inputs.

Callers supply the canonical (strategy-independent) baseline weights. Market and
weather point corrections require a separately validated, matching artifact;
current-market estimates may instead use an explicitly labeled performance policy;
normalizing a quote/forecast is never sufficient validation. This module neither
loads artifacts nor claims that the legacy baseline weights are calibrated.
"""

from __future__ import annotations

import copy
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"
_SUPPORTED_EFFECT_BASES = frozenset({"standard", "half_ppr", "ppr"})
_EFFECT_KINDS = frozenset({"market", "environment"})
_EFFECT_SOURCES = _EFFECT_KINDS | {"weather", "sportsbook", "vegas", "propline"}


@dataclass(frozen=True)
class ValidatedAdjustmentPolicy:
    model_id: str
    model_version: str
    scoring_basis: str
    trained_through: datetime
    validated_at: datetime
    validation_reference: str
    validated: bool = False
    validation_kind: str = "unspecified"
    allowed_kinds: frozenset[str] = _EFFECT_KINDS
    max_evidence_age_seconds: float | None = None


@dataclass(frozen=True)
class PerformanceAdjustmentPolicy(ValidatedAdjustmentPolicy):
    """Explicit provisional market estimate; never described as backtest validated.

    Prior performance can fit a distribution without a historical betting archive.
    The caller must still establish identity, period, scoring and fresh prices.
    Caps and shrinkage are safeguards, not empirically calibrated coefficients.
    """

    validation_kind: str = "performance_distribution_estimate"
    allowed_kinds: frozenset[str] = frozenset({"market"})
    max_abs_delta_points: float = 2.0


@dataclass(frozen=True)
class ContextAdjustmentPolicy(ValidatedAdjustmentPolicy):
    """Bounded provisional game/weather rules, with no empirical validation claim."""

    validation_kind: str = "provisional_context_rules"
    allowed_kinds: frozenset[str] = frozenset({"market", "environment"})
    max_abs_delta_points: float = 2.0


@dataclass(frozen=True)
class ProjectionAdjustment:
    adjustment_id: str
    kind: str
    delta_points: float
    model_id: str
    model_version: str
    player_id: str
    game_id: str
    season: int
    week: int
    scoring_basis: str
    source_id: str
    evidence_as_of: datetime
    valid_at: datetime
    estimate_semantics: str
    exposure_verified: bool = False


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _time(value: Any) -> datetime | None:
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _source_freshness_reason(meta: Mapping[str, Any], request_time: datetime | None) -> str | None:
    """Recheck an optional source freshness budget when consuming a saved input."""
    if "max_age_seconds" not in meta:
        return None
    limit = _number(meta["max_age_seconds"])
    if limit is None or limit < 0:
        return "invalid_source_freshness_limit"
    stamps = [meta[key] for key in ("observed_at", "as_of") if key in meta]
    if not stamps or request_time is None:
        return "source_not_verified_as_of_request"
    for stamp in stamps:
        observed = _time(stamp)
        if observed is None or observed > request_time:
            return "source_not_verified_as_of_request"
        if (request_time - observed).total_seconds() > limit:
            return "stale_source_estimate"
    return None


def _json_safe(value: Any) -> Any:
    """Keep valid JSON values unchanged; invalid/nonfinite metadata is null."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return value if _number(value) is not None else None
    if isinstance(value, datetime):
        instant = _time(value)
        return instant.isoformat() if instant else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return None


def _basis(value: str) -> str:
    return str(value).strip().lower().replace("-", "_")


def _policy_reason(
    policy: ValidatedAdjustmentPolicy | None,
    basis: str,
    as_of: datetime | None,
    allow_synthetic_policy: bool,
) -> str | None:
    estimated = isinstance(policy, (PerformanceAdjustmentPolicy, ContextAdjustmentPolicy))
    if policy is None or (not estimated and policy.validated is not True):
        return "no_validated_policy"
    if estimated:
        cap = _number(policy.max_abs_delta_points)
        context_rules = isinstance(policy, ContextAdjustmentPolicy)
        expected_kinds = (
            frozenset({"market", "environment"}) if context_rules else frozenset({"market"})
        )
        expected_validation = (
            "provisional_context_rules" if context_rules else "performance_distribution_estimate"
        )
        if cap is None or cap <= 0 or policy.allowed_kinds != expected_kinds:
            return "invalid_performance_policy_bounds"
        if policy.validation_kind != expected_validation:
            return "unknown_policy_validation"
    if not all((policy.model_id, policy.model_version, policy.validation_reference)):
        return "incomplete_policy_provenance"
    if not estimated and policy.validation_kind not in {"backtest", "synthetic_fixture"}:
        return "unknown_policy_validation"
    if policy.validation_kind == "synthetic_fixture" and not allow_synthetic_policy:
        return "synthetic_policy_not_production_validated"
    age = _number(policy.max_evidence_age_seconds)
    if age is None or age <= 0:
        return "missing_policy_freshness_limit"
    if (
        basis not in _SUPPORTED_EFFECT_BASES
        or _basis(policy.scoring_basis) not in _SUPPORTED_EFFECT_BASES
    ):
        return "unsupported_adjustment_scoring_basis"
    if _basis(policy.scoring_basis) != basis:
        return "policy_scoring_mismatch"
    trained, validated = _time(policy.trained_through), _time(policy.validated_at)
    if as_of is None or trained is None or validated is None:
        return "unverified_policy_time"
    if trained > validated or validated > as_of:
        return "policy_not_available_as_of_request"
    return None


def assess_projection(
    source_values: Mapping[str, float | None],
    source_weights: Mapping[str, float],
    *,
    player_id: str,
    scoring_basis: str,
    season: int | None,
    week: int | None,
    game_id: str | None = None,
    as_of: datetime | None = None,
    kickoff: datetime | None = None,
    strategy_base_utility: float | None = None,
    strategy_projection_weight: float = 1.0,
    utility_multiplier: float = 1.0,
    eligible: bool = True,
    constraints: Sequence[str] = (),
    source_provenance: Mapping[str, Mapping[str, Any]] | None = None,
    adjustments: Sequence[ProjectionAdjustment] = (),
    policy: ValidatedAdjustmentPolicy | None = None,
    uncertainty: Mapping[str, Any] | None = None,
    allow_synthetic_policy: bool = False,
) -> dict[str, Any]:
    """Return a fresh assessment without mutating forecasts or reapplying deltas.

    Baseline sources must be expected-point estimates in the requested scoring
    basis. Quote thresholds and weather observations are not baseline forecasts.
    The caller supplies any strategy-specific pre-multiplier utility separately;
    adjustments enter that blend at the forecast component's normalized weight
    before the risk multiplier. The default weight preserves forecast-only callers. Ineligible
    players retain their counterfactual projection but have no selection utility.
    """
    basis, request_time, game_time = _basis(scoring_basis), _time(as_of), _time(kickoff)
    provenance = copy.deepcopy(dict(source_provenance or {}))
    missing: dict[str, str] = {}
    values, weights = {}, {}
    limits = []
    if basis not in _SUPPORTED_EFFECT_BASES:
        limits.append(
            "Baseline scoring is unresolved or custom; numerical context effects are unsupported"
        )
    for source in dict.fromkeys([*source_values, *source_weights]):
        weight, value = _number(source_weights.get(source)), _number(source_values.get(source))
        raw_meta = provenance.get(source, {})
        meta = raw_meta if isinstance(raw_meta, Mapping) else {}
        reason = None
        if not isinstance(raw_meta, Mapping):
            reason = "invalid_source_provenance"
        elif weight is None or weight <= 0:
            reason = "missing_or_nonpositive_weight"
        elif value is None:
            reason = "missing_or_nonfinite_estimate"
        elif meta.get("scoring_basis") is not None and _basis(meta["scoring_basis"]) != basis:
            reason = "source_scoring_mismatch"
        elif meta.get("season", season) != season or meta.get("week", week) != week:
            reason = "source_period_mismatch"
        elif (
            meta.get("player_id", player_id) != player_id or meta.get("game_id", game_id) != game_id
        ):
            reason = "source_identity_mismatch"
        elif (
            str(meta.get("kind", source)).casefold() in _EFFECT_SOURCES
            or meta.get("estimate_semantics", "expected_value") != "expected_value"
        ):
            # New effects have their own artifact/time/identity gates below.
            reason = "effect_requires_validated_adjustment"
        elif "as_of" in meta and (
            _time(meta["as_of"]) is None
            or request_time is None
            or _time(meta["as_of"]) > request_time
        ):
            reason = "source_not_verified_as_of_request"
        else:
            reason = _source_freshness_reason(meta, request_time)
        if reason:
            missing[source] = reason
        else:
            values[source], weights[source] = value, weight
    weight_scale = max(weights.values(), default=1.0)
    scaled = {}
    for name, weight in weights.items():
        value = weight / weight_scale
        if value > 0:
            scaled[name] = value
        else:
            missing[name] = "source_weight_underflow"
    weight_sum = math.fsum(scaled.values())
    effective = {}
    for name, weight in scaled.items():
        value = weight / weight_sum
        if value > 0:
            effective[name] = value
        else:
            missing[name] = "source_weight_underflow"
    baseline = (
        math.fsum(values[name] * weight for name, weight in effective.items())
        if effective
        else None
    )
    if not effective:
        limits.append("No valid weighted baseline estimate")
    elif len(effective) == 1:
        limits.append("Single-source baseline; missing sources are not corroborating evidence")
    policy_reason = _policy_reason(policy, basis, request_time, allow_synthetic_policy)
    performance_estimate = isinstance(
        policy, (PerformanceAdjustmentPolicy, ContextAdjustmentPolicy)
    )
    if performance_estimate:
        limits.append(
            "Current-game adjustments are provisional estimates/rules; "
            "not backtested against historical odds and may overlap provider forecasts"
        )
    counts = Counter(a.adjustment_id for a in adjustments if isinstance(a, ProjectionAdjustment))
    ledger = []
    accepted = []
    for index, adjustment in enumerate(adjustments):
        if not isinstance(adjustment, ProjectionAdjustment):
            ledger.append(
                {
                    "adjustment_id": f"invalid:{index}",
                    "applied": False,
                    "reason": "invalid_adjustment",
                }
            )
            continue
        delta = _number(adjustment.delta_points)
        evidence_time, valid_time = _time(adjustment.evidence_as_of), _time(adjustment.valid_at)
        reason = policy_reason
        if reason is None:
            if not adjustment.adjustment_id or counts[adjustment.adjustment_id] != 1:
                reason = "duplicate_or_missing_adjustment_id"
            elif baseline is None:
                reason = "missing_baseline"
            elif eligible is not True:
                reason = "player_ineligible"
            elif any(
                type(value) is not int or value <= 0
                for value in (season, week, adjustment.season, adjustment.week)
            ):
                reason = "unverified_request_period"
            elif (
                adjustment.kind not in _EFFECT_KINDS or adjustment.kind not in policy.allowed_kinds
            ):
                reason = "unsupported_adjustment_kind"
            elif (
                adjustment.model_id != policy.model_id
                or adjustment.model_version != policy.model_version
            ):
                reason = "adjustment_model_mismatch"
            elif delta is None:
                reason = "nonfinite_adjustment"
            elif (
                not player_id
                or adjustment.player_id != player_id
                or not game_id
                or adjustment.game_id != game_id
            ):
                reason = "adjustment_identity_mismatch"
            elif (
                adjustment.season != season
                or adjustment.week != week
                or _basis(adjustment.scoring_basis) != basis
            ):
                reason = "adjustment_period_or_scoring_mismatch"
            elif request_time is None or game_time is None or request_time >= game_time:
                reason = "unverified_or_started_game"
            elif evidence_time is None or valid_time != game_time or evidence_time > request_time:
                reason = "evidence_time_mismatch"
            elif (request_time - evidence_time).total_seconds() > policy.max_evidence_age_seconds:
                reason = "stale_adjustment_evidence"
            elif not adjustment.source_id:
                reason = "missing_adjustment_source"
            elif adjustment.kind == "market" and not (
                adjustment.estimate_semantics == "expected_value"
                or (
                    isinstance(policy, ContextAdjustmentPolicy)
                    and adjustment.estimate_semantics == "game_scoring_index"
                )
            ):
                reason = "market_mean_not_established"
            elif adjustment.kind == "environment" and (
                adjustment.estimate_semantics != "forecast"
                or adjustment.exposure_verified is not True
            ):
                reason = "environment_applicability_unverified"
        if reason is None:
            try:
                math.fsum([*accepted, delta])
                math.fsum([baseline, *accepted, delta])
                if (
                    performance_estimate
                    and math.fsum(abs(value) for value in [*accepted, delta])
                    > policy.max_abs_delta_points
                ):
                    reason = "performance_policy_total_cap_exceeded"
            except OverflowError:
                reason = "nonfinite_adjustment_aggregate"
        applied = reason is None
        if applied:
            accepted.append(delta)
        ledger.append(
            {
                "adjustment_id": adjustment.adjustment_id,
                "kind": adjustment.kind,
                "requested_delta_points": delta,
                "applied_delta_points": delta if applied else 0.0,
                "applied": applied,
                "reason": (
                    (policy.validation_kind if performance_estimate else "validated_policy")
                    if applied
                    else reason
                ),
                "model_id": adjustment.model_id,
                "model_version": adjustment.model_version,
                "source_id": adjustment.source_id,
            }
        )
    total_delta = math.fsum(accepted)
    final = math.fsum([baseline, total_delta]) if baseline is not None else None
    utility_base = baseline if strategy_base_utility is None else _number(strategy_base_utility)
    projection_weight = _number(strategy_projection_weight)
    valid_projection_weight = projection_weight is not None and 0 <= projection_weight <= 1
    adjusted_contribution = (
        final * projection_weight if final is not None and valid_projection_weight else None
    )
    weighted_delta = total_delta * projection_weight if valid_projection_weight else None
    before_risk = None
    if valid_projection_weight and utility_base is not None:
        try:
            before_risk = math.fsum([utility_base, weighted_delta])
        except OverflowError:
            pass
    multiplier = _number(utility_multiplier)
    if not valid_projection_weight:
        limits.append("Invalid strategy projection weight")
        utility = None
    elif multiplier is None or multiplier < 0:
        limits.append("Invalid strategy utility multiplier")
        utility = None
    elif eligible is not True or utility_base is None:
        utility = None
    else:
        utility = before_risk * multiplier if before_risk is not None else None
        if utility is None or not math.isfinite(utility):
            utility = None
            limits.append("Nonfinite strategy utility")
    return {
        "schema_version": SCHEMA_VERSION,
        "projection_semantics": "conditional_on_availability",
        "identity": {"player_id": player_id, "game_id": game_id, "season": season, "week": week},
        "scoring_basis": basis,
        "as_of": request_time.isoformat() if request_time else None,
        "raw_source_values": {
            name: value if _number(value) is not None else None
            for name, value in source_values.items()
        },
        "source_provenance": _json_safe(provenance),
        "configured_source_weights": {
            name: value if _number(value) is not None else None
            for name, value in source_weights.items()
        },
        "effective_source_weights": effective,
        "baseline_expected_points": baseline,
        "adjustment_ledger": ledger,
        "total_adjustment_points": total_delta,
        "final_expected_points": final,
        "strategy_utility": utility,
        "strategy_trace": {
            "base_utility": utility_base,
            "multiplier": multiplier,
            "projection_weight": projection_weight,
            "raw_projection_input": baseline,
            "adjusted_projection_input": final,
            "weighted_projection_contribution": adjusted_contribution,
            "weighted_adjustment_points": weighted_delta,
            "weighted_before_risk": before_risk,
        },
        "eligibility": {"eligible": eligible is True, "constraints": list(constraints)},
        "missing_sources": missing,
        "uncertainty": _json_safe(dict(uncertainty or {})),
        "limitations": limits,
        "weighting_status": "legacy_weighting_uncalibrated",
        "adjustment_policy": {
            "status": (
                "estimated_not_backtested"
                if policy_reason is None and performance_estimate
                else (
                    "synthetic_test_only"
                    if policy_reason is None and policy.validation_kind == "synthetic_fixture"
                    else "validated" if policy_reason is None else "not_validated"
                )
            ),
            "reason": policy_reason,
            "model_id": policy.model_id if policy else None,
            "model_version": policy.model_version if policy else None,
            "validation_kind": policy.validation_kind if policy else None,
            "validation_reference": policy.validation_reference if policy else None,
            "max_abs_delta_points": (
                _number(policy.max_abs_delta_points) if performance_estimate else None
            ),
            "cap_semantics": "sum_of_absolute_component_deltas" if performance_estimate else None,
        },
    }
