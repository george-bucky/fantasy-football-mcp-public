"""FastMCP waiver ordering regressions for rookie intelligence."""

from fastmcp_server import _sort_enhanced_waiver_players


def test_veteran_sort_is_preserved_while_only_rookie_slots_reorder():
    players = [
        {
            "name": "Lower Rookie",
            "waiver_priority": 90,
            "rookie_intelligence": {"status": "matched", "base_rank": 20},
        },
        {"name": "Top Veteran", "waiver_priority": 100},
        {
            "name": "Better Rookie",
            "waiver_priority": 70,
            "rookie_intelligence": {"status": "matched", "base_rank": 1},
        },
        {"name": "Other Veteran", "waiver_priority": 80},
    ]

    ordered = _sort_enhanced_waiver_players(players, "rank", rookie_enabled=True)

    assert [player["name"] for player in ordered] == [
        "Top Veteran",
        "Better Rookie",
        "Other Veteran",
        "Lower Rookie",
    ]


def test_zero_rookie_matches_is_order_equivalent_to_normal_sort():
    players = [
        {
            "name": "Lower Veteran",
            "trending_score": 10,
            "rookie_intelligence": {"status": "quarantined"},
        },
        {
            "name": "Higher Veteran",
            "trending_score": 30,
            "rookie_intelligence": {"status": "quarantined"},
        },
    ]
    opt_out = [
        {"name": "Lower Veteran", "trending_score": 10},
        {"name": "Higher Veteran", "trending_score": 30},
    ]

    opted_in_order = _sort_enhanced_waiver_players(players, "trending", rookie_enabled=True)
    opted_out_order = _sort_enhanced_waiver_players(opt_out, "trending")

    assert [player["name"] for player in opted_in_order] == [
        player["name"] for player in opted_out_order
    ]


def test_opt_out_points_and_owned_preserve_original_enhanced_order():
    players = [
        {"name": "First", "points": 1, "owned_pct": 1},
        {"name": "Second", "points": 100, "owned_pct": 100},
    ]

    assert _sort_enhanced_waiver_players(players, "points") == players
    assert _sort_enhanced_waiver_players(players, "owned") == players
