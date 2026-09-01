"""Deterministic scoring, identity, and value-board tests."""

import pytest

from src.services.manual_draft_service import (
    _availability,
    _milestone_estimates,
    calculate_projected_points,
    calculate_replacement_values,
    exact_match,
    validate_profile,
    weighted_board_score,
)

GOTHAM_PROFILE = {
    "profile_id": "gotham-2026",
    "season": 2026,
    "team_count": 12,
    "draft": {"type": "snake", "slot": 11},
    "roster_slots": {
        "QB": 1,
        "RB": 2,
        "WR": 2,
        "TE": 1,
        "W/R/T": 2,
        "DEF": 1,
        "BN": 5,
    },
    "scoring": {
        "passing_yards": 0.04,
        "passing_touchdowns": 4,
        "interceptions": -2,
        "passing_40_yard_touchdowns": 1,
        "fumbles_lost": -2,
        "rushing_yards": 0.1,
        "rushing_touchdowns": 6,
        "receiving_yards": 0.1,
        "receiving_touchdowns": 6,
        "receptions": 0.5,
        "two_point_conversions": 2,
        "rushing_yard_milestones": {"100": 1, "150": 2, "200": 3},
        "receiving_yard_milestones": {"100": 1, "150": 2, "200": 3},
    },
}


def test_gotham_profile_preserves_custom_roster_and_scoring() -> None:
    profile = validate_profile(GOTHAM_PROFILE)

    assert profile["team_count"] == 12
    assert profile["draft"] == {"type": "snake", "slot": 11}
    assert profile["roster_slots"]["W/R/T"] == 2
    assert profile["roster_slots"]["BN"] == 5
    assert "K" not in profile["roster_slots"]
    assert profile["scoring"]["receptions"] == 0.5
    assert profile["scoring"]["passing_two_point_conversions"] == 2
    assert profile["scoring"]["rushing_yard_milestones"] == {100: 1, 150: 2, 200: 3}
    assert profile["unsupported_scoring_fields"] == []
    assert profile["unsupported_scoring_inputs"] == {}


def test_unsupported_scoring_values_are_preserved_in_profile_identity() -> None:
    first = dict(GOTHAM_PROFILE)
    first["profile_id"] = "unsupported-one"
    first["scoring"] = {**GOTHAM_PROFILE["scoring"], "sacks": 1}
    second = dict(first)
    second["scoring"] = {**GOTHAM_PROFILE["scoring"], "sacks": 2}

    canonical_first = validate_profile(first)
    canonical_second = validate_profile(second)

    assert canonical_first["unsupported_scoring_fields"] == ["sacks"]
    assert canonical_first["unsupported_scoring_inputs"] == {"sacks": 1}
    assert canonical_first["profile_checksum"] != canonical_second["profile_checksum"]


def test_exact_custom_scoring_exposes_every_component() -> None:
    raw_stats = {
        "passing_yards": 300,
        "passing_touchdowns": 2,
        "interceptions": 1,
        "passing_40_yard_touchdowns": 1,
        "fumbles_lost": 1,
        "rushing_yards": 50,
        "rushing_touchdowns": 1,
        "receiving_yards": 80,
        "receiving_touchdowns": 1,
        "receptions": 6,
        "passing_two_point_conversions": 1,
        "rushing_two_point_conversions": 1,
        "receiving_two_point_conversions": 1,
    }
    milestones = {
        "rushing_yard_milestones": {100: 2, 150: 1, 200: 0.25},
        "receiving_yard_milestones": {100: 3, 150: 1.5, 200: 0.5},
    }

    points, breakdown = calculate_projected_points(
        raw_stats, validate_profile(GOTHAM_PROFILE)["scoring"], milestones
    )

    assert points == pytest.approx(63.25)
    assert breakdown["passing_yards"] == 12
    assert breakdown["interceptions"] == -2
    assert breakdown["rushing_yard_milestones_150"] == 2
    assert breakdown["receiving_yard_milestones_200"] == 1.5
    assert sum(breakdown.values()) == pytest.approx(points)


def test_milestone_values_are_exclusive_tier_totals() -> None:
    scoring = validate_profile(GOTHAM_PROFILE)["scoring"]
    raw_stats = {}

    one_100_yard_game, _ = calculate_projected_points(
        raw_stats,
        scoring,
        {"rushing_yard_milestones": {100: 1, 150: 0, 200: 0}},
    )
    one_150_yard_game, _ = calculate_projected_points(
        raw_stats,
        scoring,
        {"rushing_yard_milestones": {100: 0, 150: 1, 200: 0}},
    )
    one_200_yard_game, breakdown = calculate_projected_points(
        raw_stats,
        scoring,
        {"rushing_yard_milestones": {100: 0, 150: 0, 200: 1}},
    )

    assert one_100_yard_game == 1
    assert one_150_yard_game == 2
    assert one_200_yard_game == 3
    assert breakdown["rushing_yard_milestones_100"] == 0
    assert breakdown["rushing_yard_milestones_150"] == 0
    assert breakdown["rushing_yard_milestones_200"] == 3


def test_milestone_history_only_splits_espn_projected_events() -> None:
    profile = validate_profile(GOTHAM_PROFILE)
    player = {
        "name": "No Projected Milestones",
        "position": "RB",
        "team": "BUF",
        "raw_projection_stats": {},
    }
    history = [
        {
            "name": f"Historical Runner {index}",
            "position": "RB",
            "team": "BUF",
            "rushing_yards": 175,
            "receiving_yards": 0,
        }
        for index in range(8)
    ]

    estimates, provenance, _warnings = _milestone_estimates(player, history, profile["scoring"])

    assert estimates["rushing_yard_milestones"] == {100: 0, 150: 0, 200: 0}
    rushing = next(item for item in provenance if item["field"] == "rushing_yard_milestones")
    assert rushing["threshold_methods"]["150"]["historical_150_199_share"] == 1


def test_multiple_flex_slots_change_position_replacement_levels() -> None:
    players = []
    for position, values in {
        "RB": [100, 90, 80, 79, 78, 10],
        "WR": [99, 89, 79, 77, 76, 9],
        "TE": [98, 88, 78, 75, 74, 8],
        "DEF": [20, 19, 18, 1],
    }.items():
        players.extend(
            {"name": f"{position}-{index}", "position": position, "projected_points": value}
            for index, value in enumerate(values)
        )

    levels = calculate_replacement_values(
        players,
        team_count=3,
        roster_slots={"RB": 1, "WR": 1, "TE": 1, "W/R/T": 2, "DEF": 1, "BN": 5},
    )

    assert levels == {"RB": 78, "WR": 76, "TE": 74, "DEF": 18}


def test_exact_identity_matching_quarantines_ambiguity_and_never_fuzzy_guesses() -> None:
    rows = [
        {
            "provider_id": "one",
            "name": "A.J. Brown",
            "position": "WR",
            "team": "PHI",
        },
        {
            "provider_id": "two",
            "name": "AJ Brown",
            "position": "WR",
            "team": "TEN",
        },
    ]

    matched, quarantine = exact_match(
        {"name": "AJ Brown", "position": "WR", "team": "PHI"}, "example", rows
    )
    assert matched == rows[0]
    assert quarantine is None

    matched, quarantine = exact_match(
        {"name": "AJ Brown", "position": "WR", "team": ""}, "example", rows
    )
    assert matched is None
    assert quarantine["reason"] == "ambiguous_normalized_exact_match"
    assert quarantine["candidate_ids"] == ["one", "two"]

    matched, quarantine = exact_match(
        {"name": "A J Browne", "position": "WR", "team": "PHI"}, "example", rows
    )
    assert matched is None
    assert quarantine is None


def test_missing_evidence_is_omitted_and_weights_are_renormalized() -> None:
    result = weighted_board_score(
        {"projection_value": 80, "ecr": 60, "adp": None, "availability": 100}
    )

    assert result["score"] == pytest.approx(75.2941)
    assert result["components"] == {
        "projection_value": 80,
        "ecr": 60,
        "availability": 100,
    }
    assert result["effective_weights"] == pytest.approx(
        {"projection_value": 55 / 85, "ecr": 25 / 85, "availability": 5 / 85},
        abs=1e-6,
    )
    assert result["missing"] == ["adp"]


@pytest.mark.parametrize("injury_status", ["PUP", "Sus", "SUSPENDED"])
def test_sleeper_unavailable_injury_variants_score_zero(injury_status: str) -> None:
    availability = _availability(
        {
            "active": True,
            "status": "Active",
            "injury_status": injury_status,
            "depth_chart_order": 1,
        }
    )

    assert availability is not None
    assert availability[0] == 0
