"""Synthetic policy fixtures establish wiring, never empirical validation."""

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.services.projection_assessment import (
    ProjectionAdjustment,
    ValidatedAdjustmentPolicy,
    assess_projection,
)

AS_OF = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
KICKOFF = AS_OF + timedelta(days=2)
POLICY = ValidatedAdjustmentPolicy(
    model_id="synthetic",
    model_version="fixture-v1",
    scoring_basis="half_ppr",
    trained_through=AS_OF - timedelta(days=10),
    validated_at=AS_OF - timedelta(days=1),
    validation_reference="synthetic-tests-only",
    validated=True,
    validation_kind="synthetic_fixture",
    max_evidence_age_seconds=10800,
)
ADJUSTMENT = ProjectionAdjustment(
    adjustment_id="weather:game:player",
    kind="environment",
    delta_points=-2,
    model_id="synthetic",
    model_version="fixture-v1",
    player_id="p1",
    game_id="g1",
    season=2026,
    week=9,
    scoring_basis="half_ppr",
    source_id="synthetic-forecast",
    evidence_as_of=AS_OF - timedelta(hours=1),
    valid_at=KICKOFF,
    estimate_semantics="forecast",
    exposure_verified=True,
)


def assessment(values=None, weights=None, **kwargs):
    args = {
        "player_id": "p1",
        "game_id": "g1",
        "scoring_basis": "half_ppr",
        "season": 2026,
        "week": 9,
        "as_of": AS_OF,
        "kickoff": KICKOFF,
        "allow_synthetic_policy": True,
    }
    args.update(kwargs)
    return assess_projection(
        {"yahoo": 20, "sleeper": 10} if values is None else values,
        {"yahoo": 0.5, "sleeper": 0.5} if weights is None else weights,
        **args,
    )


def test_canonical_baseline_is_separate_from_strategy_utility():
    result = assessment(strategy_base_utility=18, utility_multiplier=0.8)
    assert result["baseline_expected_points"] == 15
    assert result["final_expected_points"] == 15
    assert result["strategy_utility"] == pytest.approx(14.4)
    assert result["weighting_status"] == "legacy_weighting_uncalibrated"
    assert result["schema_version"] == "1.0"


def test_accepted_synthetic_adjustment_changes_points_and_utility_once():
    result = assessment(
        adjustments=[ADJUSTMENT], policy=POLICY, strategy_base_utility=18, utility_multiplier=0.8
    )
    assert result["final_expected_points"] == 13
    assert result["strategy_utility"] == pytest.approx(12.8)
    assert result["adjustment_ledger"][0]["applied"] is True
    assert result["adjustment_policy"]["validation_kind"] == "synthetic_fixture"


@pytest.mark.parametrize(
    "policy,reason",
    [
        (None, "no_validated_policy"),
        (replace(POLICY, validated=False), "no_validated_policy"),
        (replace(POLICY, scoring_basis="ppr"), "policy_scoring_mismatch"),
        (
            replace(POLICY, validated_at=AS_OF + timedelta(hours=1)),
            "policy_not_available_as_of_request",
        ),
        (replace(POLICY, validation_reference=""), "incomplete_policy_provenance"),
    ],
)
def test_invalid_policy_cannot_change_points(policy, reason):
    result = assessment(adjustments=[ADJUSTMENT], policy=policy)
    assert result["final_expected_points"] == 15
    assert result["adjustment_ledger"][0]["reason"] == reason


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"player_id": "another"}, "adjustment_identity_mismatch"),
        ({"game_id": "another"}, "adjustment_identity_mismatch"),
        ({"week": 10}, "adjustment_period_or_scoring_mismatch"),
        ({"scoring_basis": "ppr"}, "adjustment_period_or_scoring_mismatch"),
        ({"evidence_as_of": AS_OF + timedelta(seconds=1)}, "evidence_time_mismatch"),
        ({"valid_at": KICKOFF + timedelta(hours=1)}, "evidence_time_mismatch"),
        ({"exposure_verified": False}, "environment_applicability_unverified"),
        ({"estimate_semantics": "observation"}, "environment_applicability_unverified"),
        ({"model_version": "other"}, "adjustment_model_mismatch"),
        ({"delta_points": float("inf")}, "nonfinite_adjustment"),
    ],
)
def test_invalid_context_cannot_change_points(changes, reason):
    result = assessment(adjustments=[replace(ADJUSTMENT, **changes)], policy=POLICY)
    assert result["final_expected_points"] == 15
    assert result["adjustment_ledger"][0]["reason"] == reason


def test_market_median_is_rejected_and_validated_mean_can_apply():
    market = replace(ADJUSTMENT, kind="market", estimate_semantics="median")
    rejected = assessment(adjustments=[market], policy=POLICY)
    assert rejected["adjustment_ledger"][0]["reason"] == "market_mean_not_established"
    accepted = assessment(
        adjustments=[replace(market, estimate_semantics="expected_value")], policy=POLICY
    )
    assert accepted["final_expected_points"] == 13


def test_unknown_time_and_started_game_do_not_adjust():
    for kwargs in [{"as_of": None}, {"kickoff": None}, {"as_of": KICKOFF}]:
        result = assessment(adjustments=[ADJUSTMENT], policy=POLICY, **kwargs)
        assert result["final_expected_points"] == 15
        assert result["adjustment_ledger"][0]["applied"] is False


def test_duplicate_contribution_ids_are_rejected_not_double_counted():
    result = assessment(adjustments=[ADJUSTMENT, ADJUSTMENT], policy=POLICY)
    assert result["final_expected_points"] == 15
    assert all(
        x["reason"] == "duplicate_or_missing_adjustment_id" for x in result["adjustment_ledger"]
    )


def test_repeat_assessment_does_not_mutate_raw_data_or_accumulate_effects():
    values = {"yahoo": 20, "sleeper": 10}
    weights = {"yahoo": 0.5, "sleeper": 0.5}
    metadata = {"yahoo": {"scoring_basis": "half_ppr", "note": ["original"]}}
    before = copy.deepcopy((values, weights, metadata))
    first = assessment(
        values, weights, source_provenance=metadata, adjustments=[ADJUSTMENT], policy=POLICY
    )
    second = assessment(
        values, weights, source_provenance=metadata, adjustments=[ADJUSTMENT], policy=POLICY
    )
    assert first == second
    first["source_provenance"]["yahoo"]["note"].append("changed output")
    assert (values, weights, metadata) == before


def test_missing_nonfinite_and_bad_weights_remain_explicit():
    result = assessment(
        {"a": 0, "b": -2, "c": float("nan"), "d": 4}, {"a": 1, "b": 1, "c": 1, "d": float("inf")}
    )
    assert result["baseline_expected_points"] == -1
    assert result["effective_source_weights"] == {"a": 0.5, "b": 0.5}
    assert result["missing_sources"] == {
        "c": "missing_or_nonfinite_estimate",
        "d": "missing_or_nonpositive_weight",
    }


def test_market_cannot_bypass_artifact_gate_as_a_baseline_source():
    result = assessment({"yahoo": 10, "market": 100}, {"yahoo": 1, "market": 1})
    assert result["baseline_expected_points"] == 10
    assert result["missing_sources"]["market"] == "effect_requires_validated_adjustment"


def test_wrong_scoring_or_future_baseline_source_is_omitted():
    result = assessment(source_provenance={"yahoo": {"scoring_basis": "ppr"}})
    assert result["baseline_expected_points"] == 10
    future = assessment(source_provenance={"sleeper": {"as_of": AS_OF + timedelta(seconds=1)}})
    assert future["baseline_expected_points"] == 20


def test_ineligible_retains_counterfactual_projection_without_selection_utility():
    result = assessment(
        eligible=False, constraints=["out"], adjustments=[ADJUSTMENT], policy=POLICY
    )
    assert result["baseline_expected_points"] == 15
    assert result["strategy_utility"] is None
    assert result["eligibility"] == {"eligible": False, "constraints": ["out"]}


def test_all_missing_has_no_invented_projection():
    result = assessment({"yahoo": None}, {"yahoo": 1})
    assert result["baseline_expected_points"] is None
    assert result["final_expected_points"] is None
    assert result["strategy_utility"] is None


def test_large_valid_weights_normalize_without_infinity():
    result = assessment({"a": 10, "b": 20}, {"a": 1e308, "b": 1e308})
    assert result["baseline_expected_points"] == 15


def test_nonfinite_strategy_utility_cannot_escape_to_selection():
    result = assessment(utility_multiplier=1e308)
    assert result["strategy_utility"] is None
    assert "Nonfinite strategy utility" in result["limitations"]


def test_synthetic_policy_requires_explicit_test_only_opt_in():
    result = assessment(adjustments=[ADJUSTMENT], policy=POLICY, allow_synthetic_policy=False)
    assert result["final_expected_points"] == 15
    assert result["adjustment_policy"]["reason"] == "synthetic_policy_not_production_validated"
    enabled = assessment(adjustments=[ADJUSTMENT], policy=POLICY)
    assert enabled["adjustment_policy"]["status"] == "synthetic_test_only"


def test_every_output_serializes_strict_json_even_when_inputs_are_invalid():
    import json

    result = assessment(
        {"huge": 10**400, "nan": float("nan"), "valid": 0},
        {"huge": 1, "nan": float("inf"), "valid": 1},
        source_provenance={"valid": {"as_of": AS_OF, "extra": float("nan")}},
        uncertainty={"unknown": float("inf")},
    )
    assert result["raw_source_values"] == {"huge": None, "nan": None, "valid": 0}
    assert result["configured_source_weights"]["nan"] is None
    assert result["uncertainty"]["unknown"] is None
    json.dumps(result, allow_nan=False)


def test_stale_evidence_does_not_adjust_points():
    result = assessment(
        adjustments=[replace(ADJUSTMENT, evidence_as_of=AS_OF - timedelta(days=1))], policy=POLICY
    )
    assert result["final_expected_points"] == 15
    assert result["adjustment_ledger"][0]["reason"] == "stale_adjustment_evidence"


def test_overflowing_adjustment_aggregate_is_rejected():
    first = replace(ADJUSTMENT, adjustment_id="first", delta_points=1e308)
    second = replace(ADJUSTMENT, adjustment_id="second", delta_points=1e308)
    result = assessment({"x": -1e308}, {"x": 1}, adjustments=[first, second], policy=POLICY)
    assert result["final_expected_points"] == 0
    assert result["adjustment_ledger"][1]["reason"] == "nonfinite_adjustment_aggregate"


def test_empty_sources_do_not_invent_a_forecast():
    assert assessment({}, {})["final_expected_points"] is None


def test_unknown_period_stays_null_and_cannot_accept_adjustment():
    result = assessment(season=None, week=None, adjustments=[ADJUSTMENT], policy=POLICY)
    assert result["identity"]["season"] is None
    assert result["identity"]["week"] is None
    assert result["final_expected_points"] == 15
    assert result["adjustment_ledger"][0]["reason"] == "unverified_request_period"


@pytest.mark.parametrize("basis", ["", "unknown", "custom"])
def test_unresolved_or_custom_scoring_cannot_validate_context_effects(basis):
    result = assessment(
        scoring_basis=basis,
        adjustments=[replace(ADJUSTMENT, scoring_basis=basis)],
        policy=replace(POLICY, scoring_basis=basis),
    )
    assert result["baseline_expected_points"] == 15
    assert result["final_expected_points"] == 15
    assert result["adjustment_ledger"][0]["applied"] is False
    assert result["adjustment_policy"]["reason"] == "unsupported_adjustment_scoring_basis"
    assert any("scoring is unresolved or custom" in item for item in result["limitations"])


def test_underflow_source_is_not_counted_as_corroborating_evidence():
    result = assessment({"weak": 1, "dominant": 20}, {"weak": 1e-308, "dominant": 1e308})
    assert result["effective_source_weights"] == {"dominant": 1}
    assert result["baseline_expected_points"] == 20
    assert result["missing_sources"]["weak"] == "source_weight_underflow"
    assert any("Single-source baseline" in item for item in result["limitations"])


def test_post_normalization_underflow_has_no_zero_weight_source():
    result = assessment(
        {"weak": 1, "first": 20, "second": 10},
        {"weak": float.fromhex("0x0.0000000000001p-1022"), "first": 1, "second": 1},
    )
    assert result["effective_source_weights"] == {"first": 0.5, "second": 0.5}
    assert result["missing_sources"]["weak"] == "source_weight_underflow"


def test_performance_policy_applies_without_claiming_historical_backtest():
    from src.services.projection_assessment import PerformanceAdjustmentPolicy

    policy = PerformanceAdjustmentPolicy(
        model_id="performance-market",
        model_version="1",
        scoring_basis="half_ppr",
        trained_through=AS_OF - timedelta(days=7),
        validated_at=AS_OF,
        validation_reference="prior-completed-game-stats:8-observations",
        max_evidence_age_seconds=300,
    )
    adjustment = replace(
        ADJUSTMENT,
        kind="market",
        model_id=policy.model_id,
        model_version="1",
        delta_points=1.5,
        evidence_as_of=AS_OF,
        estimate_semantics="expected_value",
    )
    result = assessment(policy=policy, adjustments=[adjustment])
    assert result["final_expected_points"] == 16.5
    assert result["strategy_utility"] == 16.5
    assert result["adjustment_policy"]["status"] == "estimated_not_backtested"
    assert result["adjustment_ledger"][0]["reason"] == "performance_distribution_estimate"
    assert policy.validated is False
    assert any("may overlap" in limit for limit in result["limitations"])


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"max_abs_delta_points": float("nan")}, "invalid_performance_policy_bounds"),
        (
            {"allowed_kinds": frozenset({"market", "environment"})},
            "invalid_performance_policy_bounds",
        ),
        ({"validation_kind": "backtest"}, "unknown_policy_validation"),
    ],
)
def test_performance_policy_is_separate_and_bounded(change, reason):
    from src.services.projection_assessment import PerformanceAdjustmentPolicy

    policy = PerformanceAdjustmentPolicy(
        model_id="performance-market",
        model_version="1",
        scoring_basis="half_ppr",
        trained_through=AS_OF - timedelta(days=7),
        validated_at=AS_OF,
        validation_reference="prior-stats",
        max_evidence_age_seconds=300,
    )
    policy = replace(policy, **change)
    adjustment = replace(
        ADJUSTMENT,
        kind="market",
        model_id=policy.model_id,
        model_version="1",
        evidence_as_of=AS_OF,
        estimate_semantics="expected_value",
    )
    result = assessment(policy=policy, adjustments=[adjustment])
    assert result["final_expected_points"] == 15
    assert result["adjustment_ledger"][0]["reason"] == reason


def test_performance_cap_covers_all_accepted_adjustments_and_rechecks_freshness():
    from src.services.projection_assessment import PerformanceAdjustmentPolicy

    policy = PerformanceAdjustmentPolicy(
        model_id="performance-market",
        model_version="1",
        scoring_basis="half_ppr",
        trained_through=AS_OF - timedelta(days=7),
        validated_at=AS_OF,
        validation_reference="prior-stats",
        max_evidence_age_seconds=300,
    )
    adjustment = replace(
        ADJUSTMENT,
        kind="market",
        model_id=policy.model_id,
        model_version="1",
        evidence_as_of=AS_OF,
        delta_points=1.5,
        estimate_semantics="expected_value",
    )
    result = assessment(
        policy=policy, adjustments=[adjustment, replace(adjustment, adjustment_id="second")]
    )
    assert result["final_expected_points"] == 16.5
    assert result["adjustment_ledger"][1]["reason"] == "performance_policy_total_cap_exceeded"
    stale = assessment(
        policy=policy,
        adjustments=[replace(adjustment, evidence_as_of=AS_OF - timedelta(minutes=6))],
    )
    assert stale["final_expected_points"] == 15
    assert stale["adjustment_ledger"][0]["reason"] == "stale_adjustment_evidence"


@pytest.mark.parametrize("cap", [float("nan"), float("inf"), 10**400])
def test_invalid_performance_policy_metadata_is_strict_json(cap):
    import json

    from src.services.projection_assessment import PerformanceAdjustmentPolicy

    policy = PerformanceAdjustmentPolicy(
        model_id="performance-market",
        model_version="1",
        scoring_basis="half_ppr",
        trained_through=AS_OF - timedelta(days=7),
        validated_at=AS_OF,
        validation_reference="prior-stats",
        max_evidence_age_seconds=300,
        max_abs_delta_points=cap,
    )
    result = assessment(policy=policy)
    assert result["adjustment_policy"]["max_abs_delta_points"] is None
    json.dumps(result, allow_nan=False)


def test_provisional_context_policy_accepts_disjoint_game_and_weather_estimates():
    from src.services.projection_assessment import ContextAdjustmentPolicy

    policy = ContextAdjustmentPolicy(
        model_id="context",
        model_version="1",
        scoring_basis="half_ppr",
        trained_through=AS_OF,
        validated_at=AS_OF,
        validation_reference="documented-provisional-rules",
        max_evidence_age_seconds=300,
    )
    weather = replace(
        ADJUSTMENT, delta_points=-0.7, model_id="context", model_version="1", evidence_as_of=AS_OF
    )
    game = replace(
        weather,
        adjustment_id="game-index",
        kind="market",
        delta_points=1.3,
        estimate_semantics="game_scoring_index",
    )
    result = assessment(policy=policy, adjustments=[game, weather])
    assert result["final_expected_points"] == pytest.approx(15.6)
    assert all(row["applied"] for row in result["adjustment_ledger"])
    assert result["adjustment_policy"]["status"] == "estimated_not_backtested"
    assert sum(abs(row["applied_delta_points"]) for row in result["adjustment_ledger"]) == 2
    unverified = assessment(policy=policy, adjustments=[replace(weather, exposure_verified=False)])
    assert unverified["final_expected_points"] == 15
    assert unverified["adjustment_ledger"][0]["reason"] == "environment_applicability_unverified"


def test_game_index_cannot_claim_expected_mean_under_distribution_policy():
    from src.services.projection_assessment import PerformanceAdjustmentPolicy

    policy = PerformanceAdjustmentPolicy(
        model_id="distribution",
        model_version="1",
        scoring_basis="half_ppr",
        trained_through=AS_OF,
        validated_at=AS_OF,
        validation_reference="prior-stats",
        max_evidence_age_seconds=300,
    )
    game = replace(
        ADJUSTMENT,
        kind="market",
        model_id="distribution",
        model_version="1",
        evidence_as_of=AS_OF,
        estimate_semantics="game_scoring_index",
    )
    result = assessment(policy=policy, adjustments=[game])
    assert result["final_expected_points"] == 15
    assert result["adjustment_ledger"][0]["reason"] == "market_mean_not_established"
