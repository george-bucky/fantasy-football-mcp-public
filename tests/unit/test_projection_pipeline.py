"""Synthetic shared projection/selection assessment integration checks."""

import copy
import json
from types import SimpleNamespace

import pytest

from lineup_optimizer import (
    LineupOptimizer,
    Player,
    _coerce_float,
    _strategy_score,
    assess_player_projection,
)


def example_player(**overrides):
    fields = {
        "name": "Example",
        "position": "QB",
        "team": "BUF",
        "roster_position": "QB",
        "player_key": "nfl.p.1",
        "yahoo_projection": 20.0,
        "sleeper_projection_ppr": 10.0,
        "sleeper_projection_source": "sleeper_api",
        "scoring_format": "ppr",
        "scoring_format_source": "yahoo_settings",
        "recent_performance_data": SimpleNamespace(weeks_data=[{"points": n} for n in [6, 12, 18]]),
        "projection_context": {"season": 2026, "week": 5},
    }
    fields.update(overrides)
    return Player(**fields)


@pytest.mark.parametrize(
    "strategy,utility", [("balanced", 15.4), ("conservative", 12.7), ("aggressive", 16.6)]
)
def test_canonical_expected_points_are_independent_of_strategy(strategy, utility):
    player = example_player()
    assessment = assess_player_projection(player, strategy)
    score, evidence = _strategy_score(player, strategy)
    assert assessment["baseline_expected_points"] == pytest.approx(16.25)
    assert assessment["final_expected_points"] == pytest.approx(16.25)
    assert assessment["strategy_utility"] == pytest.approx(utility)
    assert score == assessment["strategy_utility"]
    assert evidence["projection_assessment"] == assessment
    assert player.projection_assessment == assessment
    assert assessment["effective_source_weights"] == pytest.approx(
        {"yahoo": 0.625, "sleeper": 0.375}
    )
    assert set(assessment["raw_source_values"]) == {"yahoo", "sleeper"}
    assert "configurable_legacy_heuristic" in assessment["baseline_source_policy"]["status"]
    assert assessment["weighting_status"] == "legacy_weighting_uncalibrated"
    assert assessment["adjustment_policy"]["status"] == "not_validated"
    assert assessment["total_adjustment_points"] == 0


def test_health_and_role_trace_are_utility_not_a_rewritten_provider_forecast():
    player = example_player(status="Q", sleeper_depth_chart_order=1)
    assessment = assess_player_projection(player)
    assert assessment["strategy_utility"] == pytest.approx(15.4 * 0.88 * 1.03)
    assert assessment["baseline_expected_points"] == pytest.approx(16.25)
    assert assessment["strategy_trace"]["availability_multiplier"] == 0.88
    assert assessment["strategy_trace"]["role_multiplier"] == 1.03
    assert player.yahoo_projection == 20
    assert player.sleeper_projection_ppr == 10


def test_assessment_is_idempotent_and_does_not_reuse_legacy_adjusted_projection():
    player = example_player(adjusted_projection=999, composite_score=777)
    forecasts = (
        player.yahoo_projection,
        player.sleeper_projection_ppr,
        player.adjusted_projection,
        player.composite_score,
    )
    context = copy.deepcopy(player.projection_context)
    a = assess_player_projection(player)
    b = assess_player_projection(player)
    assert a == b
    assert forecasts == (
        player.yahoo_projection,
        player.sleeper_projection_ppr,
        player.adjusted_projection,
        player.composite_score,
    )
    assert player.projection_context == context
    assert player.projection_assessment == {}  # Public helper itself is pure.


def test_unknown_identity_period_and_scoring_remain_explicit():
    player = example_player(
        player_key="", projection_context={}, scoring_format_source="fallback_default_ppr"
    )
    assessment = assess_player_projection(player)
    assert assessment["identity"] == {
        "player_id": "",
        "game_id": None,
        "season": None,
        "week": None,
    }
    assert assessment["scoring_basis"] == "unknown"
    assert "Projection period unverified" in assessment["limitations"]
    assert "Stable player identity unavailable" in assessment["limitations"]
    assert any("custom bonus/stat-rule" in x for x in assessment["limitations"])


def test_custom_scoring_does_not_blend_known_incompatible_inputs():
    assessment = assess_player_projection(
        example_player(scoring_format_source="fallback_custom_ppr")
    )
    assert assessment["effective_source_weights"] == {"yahoo": 1.0}
    assert assessment["final_expected_points"] == 20
    assert assessment["scoring_basis"] == "custom"
    assert "sleeper" in assessment["missing_sources"]


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), 10**400, True, "bad"])
async def test_invalid_forecast_never_beats_valid_player_or_leaks_nonfinite_json(bad):
    invalid = example_player(
        yahoo_projection=bad,
        sleeper_projection_ppr=0,
        sleeper_projection_source="",
        recent_performance_data=None,
    )
    valid = example_player(
        name="Valid",
        player_key="nfl.p.2",
        roster_position="BN",
        yahoo_projection=5,
        sleeper_projection_ppr=0,
        sleeper_projection_source="",
        recent_performance_data=None,
    )
    result = await LineupOptimizer().optimize_lineup_smart([invalid, valid])
    assert result["starters"]["QB"] is valid
    assert invalid.projection_assessment["eligibility"]["eligible"] is False
    json.dumps(invalid.projection_assessment, allow_nan=False)


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), "Infinity", "NaN", 10**400, True])
def test_parser_float_coercion_rejects_nonfinite_overflow_and_bool(bad):
    assert _coerce_float(bad) == 0


def test_invalid_yahoo_retains_other_valid_evidence():
    player = example_player(yahoo_projection=float("inf"))
    score, evidence = _strategy_score(player, "balanced")
    assessment = evidence["projection_assessment"]
    assert assessment["effective_source_weights"] == {"sleeper": 1.0}
    assert score == pytest.approx(10.8)
    assert assessment["raw_provider_values"]["yahoo"] is None
    assert player.yahoo_projection == float("inf")
    json.dumps(assessment, allow_nan=False)


def test_provenance_rejection_affects_both_projection_and_actual_selection_utility():
    player = example_player()
    player.projection_context["source_provenance"] = {"yahoo": {"week": 4}}
    score, evidence = _strategy_score(player, "balanced")
    assessment = evidence["projection_assessment"]
    assert score == pytest.approx(10.8)
    assert assessment["final_expected_points"] == pytest.approx(10.0)
    assert "Yahoo projection" not in evidence["inputs_used"]
    assert any("source_period_mismatch" in reason for reason in evidence["fallbacks"])


def test_rejected_recent_provenance_cannot_reenter_through_derived_flags():
    player = example_player(performance_flags=["BREAKOUT_CANDIDATE"])
    player.projection_context["source_provenance"] = {"recent_avg": {"week": 3}}
    assessment = assess_player_projection(player)
    assert assessment["strategy_trace"]["role_multiplier"] == 1
    assert assessment["final_expected_points"] == pytest.approx(16.25)
    assert assessment["strategy_utility"] == pytest.approx(16.25)


@pytest.mark.parametrize("slot,locked", [("IR", None), ("BN", True)])
def test_reserve_and_locked_bench_have_no_selection_utility(slot, locked):
    assessment = assess_player_projection(
        example_player(roster_position=slot, lineup_locked=locked)
    )
    assert assessment["eligibility"]["eligible"] is False
    assert assessment["strategy_utility"] is None
    assert assessment["baseline_expected_points"] == pytest.approx(16.25)


async def test_selected_players_store_exact_assessment_used_by_selector():
    players = [
        example_player(),
        example_player(
            name="Bench", player_key="nfl.p.2", roster_position="BN", yahoo_projection=1
        ),
    ]
    result = await LineupOptimizer().optimize_lineup_smart(players, strategy="aggressive")
    keys = result["strategy_summary"]["assignment_audit"]["evidence_keys"]
    for index, player in enumerate(players):
        evidence = result["player_evidence"][keys[str(index)]]
        assert evidence["projection_assessment"] == player.projection_assessment
        assert evidence["strategy_score"] == round(
            player.projection_assessment["strategy_utility"], 3
        )


async def test_enrichment_uses_verified_league_season_not_live_sleeper_season():
    from unittest.mock import AsyncMock, patch

    import sleeper_api
    from src.services.player_enhancement import EnhancedPlayerData

    player = example_player(projection_context={"season": 2025, "week": 5})
    projections = AsyncMock(return_value={})
    expert = AsyncMock(return_value={})
    trending = AsyncMock(return_value=[])
    enhancement = AsyncMock(return_value=EnhancedPlayerData(False, None, [], None, None, "fixture"))
    with (
        patch("sleeper_api.get_current_season", AsyncMock(return_value=2026)),
        patch("sleeper_api.get_current_week", AsyncMock(return_value=9)),
        patch.object(
            sleeper_api.sleeper_client,
            "get_all_players",
            AsyncMock(return_value={"123": {"status": "Inactive"}}),
        ),
        patch.object(
            sleeper_api.sleeper_client, "map_yahoo_to_sleeper", AsyncMock(return_value="123")
        ),
        patch.object(sleeper_api.sleeper_client, "get_projections", projections),
        patch.object(sleeper_api.sleeper_client, "get_expert_advice", expert),
        patch.object(sleeper_api.sleeper_client, "get_trending_players", trending),
        patch("src.services.player_enhancement.enhance_player_with_context", enhancement),
    ):
        result = await LineupOptimizer().enhance_with_external_data([player], week=5)
    projections.assert_awaited_with(2025, 5)
    assert enhancement.await_args.kwargs["season"] == 2025
    assert enhancement.await_args.kwargs["current_week"] == 5
    assert result[0].sleeper_status != "Inactive"
    assert result[0].projection_context["historical_enrichment"] is True
    expert.assert_not_awaited()
    trending.assert_not_awaited()
    assert player.projection_context == {"season": 2025, "week": 5}


async def test_different_season_without_verified_week_never_uses_live_week():
    from unittest.mock import AsyncMock, patch

    import sleeper_api

    player = example_player(projection_context={"season": 2025})
    metadata = AsyncMock(return_value={})
    with (
        patch("sleeper_api.get_current_season", AsyncMock(return_value=2026)),
        patch("sleeper_api.get_current_week", AsyncMock(return_value=9)),
        patch.object(sleeper_api.sleeper_client, "get_all_players", metadata),
    ):
        result = await LineupOptimizer().enhance_with_external_data([player])
    metadata.assert_not_awaited()
    assert result[0] is not player
    assert "unverified" in result[0].projection_context["enrichment_unavailable_reason"]
    assert "week" not in result[0].projection_context


def test_invalid_request_period_metadata_is_unknown_not_an_invented_period():
    assessment = assess_player_projection(
        example_player(projection_context={"season": True, "week": 100})
    )
    assert assessment["identity"]["season"] is None
    assert assessment["identity"]["week"] is None
    assert "Projection period unverified" in assessment["limitations"]


@pytest.mark.parametrize("strategy", ["conservative", "aggressive"])
@pytest.mark.parametrize(
    "provenance",
    [
        {"recent_avg": {"week": 4}, "recent_floor": {"week": 5}, "recent_ceiling": {"week": 5}},
        {"recent_avg": {"week": 5}, "recent_floor": {"week": 4}},
        {"recent_floor": {"week": 4}},
        {"recent_ceiling": {"week": 4}},
    ],
)
def test_recent_cohort_cannot_reenter_through_independent_extreme_or_role_metadata(
    strategy, provenance
):
    player = example_player(performance_flags=["BREAKOUT_CANDIDATE", "HIGH_CEILING"])
    player.projection_context["source_provenance"] = provenance
    score, evidence = _strategy_score(player, strategy)
    assessment = evidence["projection_assessment"]
    # No current-period recent observation was established. Only the 35/15
    # provider components can drive utility; flags derived from rejected
    # actuals cannot add another bonus.
    assert score == pytest.approx(17)
    assert assessment["baseline_expected_points"] == pytest.approx(16.25)
    assert assessment["strategy_trace"]["role_multiplier"] == 1
    assert set(assessment["strategy_trace"]["utility_source_values"]) == {"yahoo", "sleeper"}
    assert not any("recent actuals" in item for item in evidence["inputs_used"])
    assert not any("recent-performance flags" in item for item in evidence["inputs_used"])
    assert assessment["raw_provider_values"]["yahoo"] == 20


@pytest.mark.parametrize("strategy,utility", [("conservative", 12.7), ("aggressive", 16.6)])
def test_consistent_recent_cohort_provenance_is_shared_by_all_summaries(strategy, utility):
    player = example_player()
    meta = {"week": 5, "season": 2026}
    player.projection_context["source_provenance"] = {
        "recent_avg": dict(meta),
        "recent_floor": dict(meta),
        "recent_ceiling": dict(meta),
    }
    score, evidence = _strategy_score(player, strategy)
    assert score == pytest.approx(utility)
    assert evidence["projection_assessment"]["baseline_expected_points"] == pytest.approx(16.25)


@pytest.mark.parametrize("overflow", ["list", "dict", "legacy_ceiling"])
async def test_enrichment_rejects_overflowing_aggregates_and_keeps_legacy_outputs_json_safe(
    overflow,
):
    from dataclasses import asdict
    from unittest.mock import AsyncMock, patch

    import sleeper_api
    from src.services.player_enhancement import EnhancedPlayerData

    fields = ("pts", "pts_std", "pts_ppr", "pts_half_ppr")
    if overflow == "list":
        stats = [dict.fromkeys(fields, 1e308) for _ in range(3)]
    elif overflow == "dict":
        stats = {field: float("inf") for field in fields}
    else:
        stats = dict.fromkeys(fields, 10)
    player = example_player(composite_score=1.7e308 if overflow == "legacy_ceiling" else 0)
    enhancement = AsyncMock(return_value=EnhancedPlayerData(False, None, [], None, None, "fixture"))
    with (
        patch("sleeper_api.get_current_season", AsyncMock(return_value=2026)),
        patch("sleeper_api.get_current_week", AsyncMock(return_value=5)),
        patch.object(sleeper_api.sleeper_client, "get_all_players", AsyncMock(return_value={})),
        patch.object(
            sleeper_api.sleeper_client, "map_yahoo_to_sleeper", AsyncMock(return_value="123")
        ),
        patch.object(
            sleeper_api.sleeper_client,
            "get_projections",
            AsyncMock(
                return_value={
                    "123": {"projection_source": "sleeper_api", "projected_stats": stats},
                }
            ),
        ),
        patch.object(sleeper_api.sleeper_client, "get_expert_advice", AsyncMock(return_value={})),
        patch.object(
            sleeper_api.sleeper_client, "get_trending_players", AsyncMock(return_value=[])
        ),
        patch("src.services.player_enhancement.enhance_player_with_context", enhancement),
    ):
        result = await LineupOptimizer().enhance_with_external_data([player], week=5)
    enriched = result[0]
    json.dumps(asdict(enriched), allow_nan=False)
    assessment = assess_player_projection(enriched)
    json.dumps(assessment, allow_nan=False)
    if overflow != "legacy_ceiling":
        assert enriched.sleeper_projection_source == "invalid_projection"
        assert all(
            getattr(enriched, name) == 0
            for name in (
                "sleeper_projection",
                "sleeper_projection_std",
                "sleeper_projection_ppr",
                "sleeper_projection_half_ppr",
            )
        )
        assert assessment["effective_source_weights"] == {"yahoo": 1.0}
        assert assessment["baseline_expected_points"] == 20
        assert any("nonfinite aggregate" in warning for warning in assessment["limitations"])
    else:
        assert enriched.ceiling_projection == 0  # Explicitly unavailable, not infinity.
        assert any(
            "ceiling_projection unavailable" in warning for warning in assessment["limitations"]
        )
    assert player.yahoo_projection == 20


async def test_bye_enrichment_preserves_raw_provider_values_but_cannot_select_player():
    from unittest.mock import AsyncMock, patch

    import sleeper_api
    from src.services.player_enhancement import EnhancedPlayerData

    player = example_player()
    enhancement = AsyncMock(
        return_value=EnhancedPlayerData(True, None, ["ON_BYE"], 0, "Bye week", "fixture")
    )
    with (
        patch("sleeper_api.get_current_season", AsyncMock(return_value=2026)),
        patch("sleeper_api.get_current_week", AsyncMock(return_value=5)),
        patch.object(sleeper_api.sleeper_client, "get_all_players", AsyncMock(return_value={})),
        patch.object(
            sleeper_api.sleeper_client, "map_yahoo_to_sleeper", AsyncMock(return_value="123")
        ),
        patch.object(
            sleeper_api.sleeper_client,
            "get_projections",
            AsyncMock(
                return_value={
                    "123": {
                        "projection_source": "sleeper_api",
                        "projected_stats": {
                            "pts": 10,
                            "pts_ppr": 10,
                            "pts_std": 10,
                            "pts_half_ppr": 10,
                        },
                    },
                }
            ),
        ),
        patch.object(sleeper_api.sleeper_client, "get_expert_advice", AsyncMock(return_value={})),
        patch.object(
            sleeper_api.sleeper_client, "get_trending_players", AsyncMock(return_value=[])
        ),
        patch("src.services.player_enhancement.enhance_player_with_context", enhancement),
    ):
        result = await LineupOptimizer().enhance_with_external_data([player], week=5)
    enriched = result[0]
    assert enriched.yahoo_projection == 20
    assert enriched.sleeper_projection_ppr == 10
    assessment = assess_player_projection(enriched)
    assert assessment["raw_source_values"]["yahoo"] == 20
    assert assessment["raw_source_values"]["sleeper"] == 10
    assert assessment["eligibility"]["eligible"] is False
    assert assessment["strategy_utility"] is None
    selection = await LineupOptimizer().optimize_lineup_smart(result)
    assert selection["starters"] == {}


@pytest.mark.parametrize("strategy", ["balanced", "conservative", "aggressive"])
def test_recent_actuals_do_not_change_provider_only_expected_points(strategy):
    low = example_player(recent_performance_data=SimpleNamespace(weeks_data=[{"points": 1}]))
    high = example_player(recent_performance_data=SimpleNamespace(weeks_data=[{"points": 90}]))
    a = assess_player_projection(low, strategy)
    b = assess_player_projection(high, strategy)
    assert a["baseline_expected_points"] == b["baseline_expected_points"] == 16.25
    assert a["final_expected_points"] == b["final_expected_points"] == 16.25
    assert a["strategy_utility"] != b["strategy_utility"]
    assert a["supporting_evidence"]["recent_actuals"]["average"] == 1
    assert b["supporting_evidence"]["recent_actuals"]["average"] == 90


@pytest.mark.parametrize("strategy", ["balanced", "conservative", "aggressive"])
def test_missing_provider_forecasts_never_fall_back_to_recent_actuals_as_expected_points(strategy):
    player = example_player(yahoo_projection=0, sleeper_projection_ppr=0)
    score, evidence = _strategy_score(player, strategy)
    assessment = evidence["projection_assessment"]
    assert assessment["baseline_expected_points"] is None
    assert assessment["final_expected_points"] is None
    assert assessment["effective_source_weights"] == {}
    assert set(assessment["raw_source_values"]) == {"yahoo", "sleeper"}
    assert assessment["strategy_utility"] == score  # Retained legacy utility is explicit.
    assert any(
        "recent actuals can inform legacy utility only" in x for x in assessment["limitations"]
    )


def test_single_provider_point_forecast_renormalizes_without_recent_actuals():
    assessment = assess_player_projection(example_player(sleeper_projection_ppr=0))
    assert assessment["effective_source_weights"] == {"yahoo": 1.0}
    assert assessment["baseline_expected_points"] == 20
    assert assessment["strategy_utility"] != 20
