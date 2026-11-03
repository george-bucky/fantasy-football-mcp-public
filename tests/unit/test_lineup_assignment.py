"""Selection correctness checks use synthetic data and no provider requests."""

import itertools
import random
from types import SimpleNamespace

import pytest

from lineup_optimizer import (
    LineupOptimizer,
    Player,
    _eligible_for_slot,
    _optimal_assignment,
    _recent_actual_points,
    _strategy_score,
)
from src.services.player_enhancement import calculate_recent_avg


def player(name, position, projection, slot="BN", **kwargs):
    fields = {
        "sleeper_projection_ppr": projection,
        "sleeper_projection_source": "sleeper_api",
        "projection_context": {
            "sleeper_projection_present": projection != 0,
            "sleeper_projection_scoring_format": "ppr",
        },
    }
    fields.update(kwargs)
    return Player(
        name=name,
        position=position,
        team="BUF",
        yahoo_projection=projection,
        roster_position=slot,
        **fields,
    )


async def test_global_assignment_avoids_overlapping_flex_greedy_failure():
    players = [player("WR", "WR", 20, "W/R"), player("RB", "RB", 19), player("TE", "TE", 1, "W/T")]
    result = await LineupOptimizer().optimize_lineup_smart(players)
    assert result["starters"]["W/R"].name == "RB"
    assert result["starters"]["W/T"].name == "WR"
    assert result["strategy_summary"]["assignment_audit"]["selected_total_score"] == 39


@pytest.mark.parametrize("status", ["O", "OUT", "IR", "INACTIVE", "PUP", "SUSPENDED"])
async def test_unavailable_only_player_is_not_recommended(status):
    result = await LineupOptimizer().optimize_lineup_smart(
        [player("Unavailable", "QB", 30, "QB", status=status)]
    )
    assert result["starters"] == {}
    assert result["recommendations"] == []
    assert "Unfilled required slot QB" in result["errors"][0]


async def test_bye_and_reserve_players_never_replace_available_candidate():
    players = [
        player("Bye", "QB", 50, "QB", on_bye=True),
        player("Reserve", "QB", 60, "IR"),
        player("Available", "QB", 10),
    ]
    result = await LineupOptimizer().optimize_lineup_smart(players)
    assert result["starters"]["QB"].name == "Available"


async def test_authoritative_slots_include_empty_positions():
    result = await LineupOptimizer().optimize_lineup_smart(
        [player("Quarterback", "QB", 20, "QB")], roster_slots={"QB": 1, "WR": 2, "BN": 5}
    )
    assert list(result["starters"]) == ["QB"]
    assert len(result["errors"]) == 2
    assert all("WR" in error for error in result["errors"])
    assert (
        result["strategy_summary"]["assignment_audit"]["required_slots_source"] == "league_settings"
    )


async def test_locked_starter_and_locked_bench_are_fixed():
    players = [
        player("Locked starter", "QB", 1, "QB", lineup_locked=True),
        player("Better bench", "QB", 20),
        player("Locked bench", "WR", 50, lineup_locked=True),
        player("Available WR", "WR", 10),
    ]
    result = await LineupOptimizer().optimize_lineup_smart(players, roster_slots={"QB": 1, "WR": 1})
    assert result["starters"]["QB"].name == "Locked starter"
    assert result["starters"]["WR"].name == "Available WR"
    assert result["recommendations"][0].startswith("Locked ")
    assert not result["strategy_summary"]["assignment_audit"]["lock_status_verified"]


async def test_unavailable_locked_starter_is_reported_as_unchangeable_not_start_action():
    result = await LineupOptimizer().optimize_lineup_smart(
        [
            player("Locked out", "QB", 20, "QB", status="O", lineup_locked=True),
            player("Healthy", "QB", 15),
        ]
    )
    assert result["starters"]["QB"].name == "Locked out"
    assert result["recommendations"] == ["Locked Locked out at QB; no replacement allowed"]
    assert "Locked unavailable" in result["errors"][0]


async def test_duplicate_names_keep_separate_evidence():
    result = await LineupOptimizer().optimize_lineup_smart(
        [
            player("Same Name", "RB", 10, "RB", player_key="nfl.p.1"),
            player("Same Name", "WR", 20, "WR", player_key="nfl.p.2"),
        ]
    )
    assert set(result["player_evidence"]) == {"Same Name|nfl.p.1", "Same Name|nfl.p.2"}
    assert len(result["starters"]) == 2


async def test_duplicate_stable_identity_is_rejected_even_with_different_names():
    result = await LineupOptimizer().optimize_lineup_smart(
        [
            player("Name One", "RB", 10, "RB", player_key="nfl.p.1"),
            player("Name Two", "RB", 20, player_key="nfl.p.1"),
        ]
    )
    assert result["status"] == "error"
    assert "Duplicate player identities" in result["errors"][0]


def test_zero_and_negative_recent_games_have_same_mean_in_both_paths():
    points = [-2, 0, 8]
    value = player("Actuals", "QB", 10)
    value.recent_performance_data = SimpleNamespace(weeks_data=[{"points": x} for x in points])
    assert _recent_actual_points(value) == points
    assert calculate_recent_avg([{"pts_ppr": x} for x in points]) == 2


async def test_recent_negative_only_game_remains_eligible():
    value = player("Negative", "QB", 0, "QB")
    value.recent_performance_data = SimpleNamespace(weeks_data=[{"points": -2}])
    result = await LineupOptimizer().optimize_lineup_smart([value])
    assert result["starters"]["QB"] is value
    assert result["strategy_summary"]["assignment_audit"]["selected_total_score"] == -2


def test_custom_scoring_omits_ppr_actuals_and_derived_flags():
    value = player(
        "Custom",
        "QB",
        10,
        scoring_format_source="fallback_custom_ppr",
        sleeper_projection_source="sleeper_api",
        sleeper_projection_ppr=100,
        performance_flags=["BREAKOUT_CANDIDATE"],
    )
    value.recent_performance_data = SimpleNamespace(weeks_data=[{"points": 100}])
    score, evidence = _strategy_score(value, "balanced")
    assert score == 0
    assert evidence["projection_assessment"]["baseline_expected_points"] is None
    assert any("incompatible" in x for x in evidence["fallbacks"])


def test_nonfinite_actuals_are_missing_not_nan_averages():
    assert calculate_recent_avg([{"pts_ppr": float("nan")}, {"pts_ppr": 2}]) == 2


def test_exact_assignment_matches_bruteforce_on_varied_small_rosters():
    rng = random.Random(23)
    for _ in range(25):
        players = [
            player(str(i), rng.choice(["RB", "WR", "TE"]), rng.randint(-3, 30)) for i in range(5)
        ]
        slots = list(enumerate(rng.choices(["W/R", "W/T", "FLEX", "TE"], k=3)))
        scores = {id(p): p.yahoo_projection for p in players}
        actual = _optimal_assignment(slots, players, scores, {})
        best = (0, 0)
        for choice in itertools.product([None, *players], repeat=3):
            present = [p for p in choice if p is not None]
            if len({id(p) for p in present}) != len(present):
                continue
            if any(
                p is not None and not _eligible_for_slot(p, slot)
                for p, (_, slot) in zip(choice, slots)
            ):
                continue
            best = max(best, (len(present), sum(scores[id(p)] for p in present)))
        assert (len(actual), sum(scores[id(p)] for p in actual.values())) == best


async def test_rounded_tiebreak_cannot_consume_unique_eligible_player():
    wr = player("Receiver", "WR", 20.04, "W/R")
    rb = player("Runner", "RB", 20)
    te = player("Tight end", "TE", 1, "W/T")
    for value, percentile in [(wr, 100), (rb, 20), (te, 30)]:
        value.weekly_matchup_evidence = {
            "available": True,
            "percentile": percentile,
            "schedule": {"status": "matched"},
            "tie_break_audit": [],
        }
    result = await LineupOptimizer().optimize_lineup_smart([wr, rb, te], use_matchup_evidence=True)
    assert result["starters"]["W/R"] is rb
    assert result["starters"]["W/T"] is wr
    assert result["strategy_summary"]["assignment_audit"]["selected_total_score"] == 40.04


async def test_parser_preserves_verified_lock_and_identity():
    values = await LineupOptimizer().parse_yahoo_roster(
        {
            "roster": [
                {
                    "name": "ID",
                    "position": "QB",
                    "team": "BUF",
                    "player_key": "nfl.p.1",
                    "lineup_locked": True,
                },
                {"name": "Unknown lock", "position": "QB", "team": "BUF", "lineup_locked": "true"},
            ]
        }
    )
    assert values[0].player_key == "nfl.p.1"
    assert values[0].lineup_locked is True
    assert values[1].lineup_locked is None


async def test_fractional_completion_rounding_never_drops_feasible_slots():
    values = [
        player("WR", "WR", 20.16),
        player("TE best", "TE", 22.39),
        player("RB", "RB", 6.6),
        player("TE low", "TE", 7.07),
        player("TE other", "TE", 10.59),
    ]
    result = await LineupOptimizer().optimize_lineup_smart(
        values, roster_slots={"W/R": 1, "RB": 1, "TE": 1}
    )
    assert len(result["starters"]) == 3
    assert result["errors"] == []
    assert result["strategy_summary"]["assignment_audit"]["selected_total_score"] == pytest.approx(
        49.15
    )


@pytest.mark.parametrize("bad", ["bad", " ", [], {}, True, None, float("nan"), float("inf")])
def test_invalid_actuals_remain_missing_instead_of_becoming_zero(bad):
    value = player("Actuals", "QB", 10)
    value.recent_performance_data = SimpleNamespace(weeks_data=[{"points": bad}, {"points": 0}])
    assert _recent_actual_points(value) == [0]


async def test_full_selector_fractional_assignments_match_exact_solver():
    import math

    rng = random.Random(177)
    for _ in range(50):
        values = [
            player(str(i), rng.choice(["RB", "WR", "TE"]), round(rng.uniform(1, 30), 2))
            for i in range(5)
        ]
        slot_names = rng.sample(["W/R", "W/T", "RB", "TE", "WR"], 3)
        slots = list(enumerate(slot_names))
        scores = {id(p): _strategy_score(p, "balanced")[0] for p in values}
        exact = _optimal_assignment(slots, values, scores, {})
        result = await LineupOptimizer().optimize_lineup_smart(
            values, roster_slots=dict.fromkeys(slot_names, 1)
        )
        assert len(result["starters"]) == len(exact)
        assert math.fsum(scores[id(p)] for p in result["starters"].values()) == pytest.approx(
            math.fsum(scores[id(p)] for p in exact.values())
        )
