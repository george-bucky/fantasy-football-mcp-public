"""Focused tests for context-aware live draft recommendations."""

from unittest.mock import AsyncMock, patch

import pytest

import fantasy_football_multi_league as server


def _settings(
    reception_points=0, *, passing_touchdown_points=4, superflex=False, auction=False
):
    positions = [
        ("QB", 1),
        ("RB", 2),
        ("WR", 2),
        ("TE", 1),
        ("W/R/T", 1),
        ("K", 1),
        ("DEF", 1),
        ("BN", 6),
    ]
    if superflex:
        positions = [("QB", 1), ("RB", 1), ("WR", 1), ("TE", 1), ("Q/W/R/T", 1)]
    return {
        "settings": {
            "is_auction_draft": 1 if auction else 0,
            "roster_positions": {
                str(index): {
                    "roster_position": {
                        "position": position,
                        "count": count,
                    }
                }
                for index, (position, count) in enumerate(positions)
            },
            "stat_modifiers": {
                "stats": {
                    "0": {"stat": {"stat_id": 9, "value": reception_points}},
                    "1": {
                        "stat": {"stat_id": 5, "value": passing_touchdown_points}
                    },
                }
            },
        }
    }


def _stat_categories():
    return {
        "stats": {
            "0": {"stat": {"stat_id": 9, "display_name": "Receptions"}},
            "1": {"stat": {"stat_id": 5, "display_name": "Passing Touchdowns"}},
        }
    }


async def _recommend(
    *,
    roster,
    rankings,
    settings,
    current_pick=5,
    draft_position=5,
    decision_news=None,
):
    available = [{"name": player["name"], "owned_pct": 50} for player in rankings]

    async def yahoo_call(endpoint):
        if endpoint.endswith("/settings"):
            return settings
        if endpoint.endswith("/stat_categories"):
            return _stat_categories()
        if "/roster" in endpoint:
            return {"fantasy_content": {}}
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    with (
        patch.object(server, "get_waiver_wire_players", AsyncMock(return_value=available)),
        patch.object(server, "get_draft_rankings", AsyncMock(return_value=rankings)),
        patch.object(
            server,
            "discover_leagues",
            AsyncMock(
                return_value={
                    "league.test": {
                        "name": "Test League",
                        "num_teams": 10,
                        "scoring_type": "head",
                    }
                }
            ),
        ),
        patch.object(
            server,
            "get_user_team_info",
            AsyncMock(
                return_value={"team_key": "league.test.t.1", "draft_position": draft_position}
            ),
        ),
        patch.object(server, "yahoo_api_call", AsyncMock(side_effect=yahoo_call)),
        patch.object(server, "parse_team_roster", return_value=roster),
        patch.object(
            server,
            "get_decision_news_context",
            AsyncMock(
                return_value={
                    **(
                        decision_news
                        or {"by_player": {}, "sources": [], "warnings": []}
                    ),
                }
            ),
        ),
    ):
        return await server.get_draft_recommendation_simple(
            "league.test", "balanced", 10, current_pick
        )


@pytest.mark.asyncio
async def test_recommendations_use_drafted_roster_and_real_starter_needs():
    roster = [
        {"name": "RB One", "position": "RB"},
        {"name": "RB Two", "position": "RB"},
        {"name": "WR One", "position": "WR"},
        {"name": "WR Two", "position": "WR"},
    ]
    rankings = [
        {"name": "Available RB", "position": "RB", "average_draft_position": 10},
        {"name": "Available QB", "position": "QB", "average_draft_position": 12},
    ]

    result = await _recommend(roster=roster, rankings=rankings, settings=_settings())

    assert result["recommendations"][0]["player"]["name"] == "Available QB"
    assert result["recommendations"][0]["score_breakdown"]["roster_need"] == 18
    assert result["draft_context"]["position_counts"] == {"RB": 2, "WR": 2}
    assert result["draft_context"]["positional_needs"]["QB"]["need"] == "critical"
    assert result["draft_context"]["league"]["roster_slots_source"] == "yahoo"


@pytest.mark.asyncio
async def test_recommendations_apply_ppr_scoring_and_superflex_configuration():
    roster = [
        {"name": "QB One", "position": "QB"},
        {"name": "RB One", "position": "RB"},
        {"name": "WR One", "position": "WR"},
        {"name": "TE One", "position": "TE"},
    ]
    rankings = [
        {"name": "Available RB", "position": "RB", "average_draft_position": 10},
        {"name": "Available WR", "position": "WR", "average_draft_position": 10},
        {"name": "Available QB", "position": "QB", "average_draft_position": 10},
    ]

    result = await _recommend(
        roster=roster,
        rankings=rankings,
        settings=_settings(1, superflex=True),
    )
    picks = {row["player"]["position"]: row for row in result["recommendations"]}

    assert result["draft_context"]["league"]["scoring_format"] == "PPR"
    assert result["draft_context"]["league"]["roster_slots"]["SUPERFLEX"] == 1
    assert picks["WR"]["score_breakdown"]["league_scoring"] == 7
    assert picks["RB"]["score_breakdown"]["league_scoring"] == 4
    assert picks["QB"]["score_breakdown"]["roster_need"] == 12


@pytest.mark.asyncio
async def test_recommendations_attach_attributed_news_without_changing_scores():
    rankings = [
        {"name": "Available QB", "position": "QB", "average_draft_position": 10}
    ]
    news = {
        "by_player": {
            "Available QB": {
                "espn": [
                    {
                        "headline": "QB camp report",
                        "source": "ESPN NFL News API",
                        "team_refs": [
                            {"name": "Test Team", "espn_team_id": "9"}
                        ],
                    }
                ],
                "rotowire": [],
                "espn_athlete_refs": [
                    {"name": "Available QB", "espn_athlete_id": "123"}
                ],
            }
        },
        "sources": ["ESPN NFL News API"],
        "warnings": [],
    }

    result = await _recommend(
        roster=[], rankings=rankings, settings=_settings(), decision_news=news
    )

    recommendation = result["recommendations"][0]
    assert recommendation["news_context"]["espn_athlete_refs"][0][
        "espn_athlete_id"
    ] == "123"
    assert recommendation["news_context"]["espn"][0]["team_refs"][0][
        "espn_team_id"
    ] == "9"
    assert recommendation["score_breakdown"]["base_rank"] == 90
    assert result["decision_evidence"]["news_sources"] == ["ESPN NFL News API"]


def test_snake_timing_uses_current_pick_or_infers_it_from_roster():
    explicit = server._snake_draft_timing(5, drafted_count=0, num_teams=10, draft_slot=5)
    inferred = server._snake_draft_timing(None, drafted_count=2, num_teams=10, draft_slot=5)

    assert explicit == {
        "current_pick": 5,
        "source": "explicit current_pick",
        "num_teams": 10,
        "draft_slot": 5,
        "round": 1,
        "pick_in_round": 5,
        "next_pick": 16,
        "picks_until_next": 10,
        "is_snake_draft": True,
    }
    assert inferred["current_pick"] == 25
    assert inferred["round"] == 3
    assert inferred["next_pick"] == 36


def test_snake_timing_uses_upcoming_pick_when_clock_is_before_team_slot():
    timing = server._snake_draft_timing(12, drafted_count=1, num_teams=10, draft_slot=5)

    assert timing["round"] == 2
    assert timing["next_pick"] == 16
    assert timing["picks_until_next"] == 3


def test_natural_positions_override_selected_bench_and_flex_slots():
    roster_data = {
        "players": {
            "0": {
                "player": [
                    [{"name": {"full": "Bench Back"}}, {"display_position": "RB"}],
                    {"selected_position": [{"position": "BN"}]},
                ]
            },
            "1": {
                "player": [
                    [{"name": {"full": "Flex Receiver"}}, {"display_position": "WR"}],
                    {"selected_position": [{"position": "W/R/T"}]},
                ]
            },
        }
    }
    parsed_roster = [
        {"name": "Bench Back", "position": "BN"},
        {"name": "Flex Receiver", "position": "W/R/T"},
    ]

    assert server._drafted_position_counts(parsed_roster, roster_data) == {"RB": 1, "WR": 1}


def test_flex_need_accounts_for_surplus_players_already_filling_flex():
    needs = server._build_positional_needs(
        {"RB": 1, "WR": 3, "TE": 1},
        {"RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
    )

    assert needs["RB"]["need"] == "critical"
    assert needs["WR"]["need"] == "filled"
    assert needs["TE"]["need"] == "depth"


def test_partial_flex_slots_only_boost_eligible_positions():
    wr_rb_needs = server._build_positional_needs(
        {"RB": 1, "WR": 1, "TE": 1},
        {"RB": 1, "WR": 1, "TE": 1, "W/R": 1},
    )
    wr_te_needs = server._build_positional_needs(
        {"RB": 1, "WR": 1, "TE": 1},
        {"RB": 1, "WR": 1, "TE": 1, "W/T": 1},
    )

    assert wr_rb_needs["RB"]["need"] == "flex"
    assert wr_rb_needs["WR"]["need"] == "flex"
    assert wr_rb_needs["TE"]["need"] == "depth"
    assert wr_te_needs["RB"]["need"] == "depth"
    assert wr_te_needs["WR"]["need"] == "flex"
    assert wr_te_needs["TE"]["need"] == "flex"


def test_six_point_passing_touchdowns_boost_qbs():
    four_point = server._parse_draft_settings(_settings(), _stat_categories())
    six_point = server._parse_draft_settings(
        _settings(passing_touchdown_points=6), _stat_categories()
    )

    assert server._scoring_bonus(
        "QB", four_point["scoring_format"], four_point["passing_touchdown_points"]
    ) == 0
    assert server._scoring_bonus(
        "QB", six_point["scoring_format"], six_point["passing_touchdown_points"]
    ) == 6


@pytest.mark.asyncio
async def test_passing_touchdown_setting_changes_recommendation_score():
    roster = [{"name": "Roster QB", "position": "QB"}]
    rankings = [{"name": "Available QB", "position": "QB", "average_draft_position": 10}]

    four_point = await _recommend(
        roster=roster,
        rankings=rankings,
        settings=_settings(passing_touchdown_points=4),
    )
    six_point = await _recommend(
        roster=roster,
        rankings=rankings,
        settings=_settings(passing_touchdown_points=6),
    )

    assert four_point["recommendations"][0]["score_breakdown"]["league_scoring"] == 0
    assert six_point["recommendations"][0]["score_breakdown"]["league_scoring"] == 6


def test_auction_settings_disable_snake_draft_timing():
    settings = server._parse_draft_settings(_settings(auction=True))
    timing = server._snake_draft_timing(
        5,
        drafted_count=0,
        num_teams=10,
        draft_slot=5,
        is_snake_draft=settings["is_snake_draft"],
    )

    assert settings["draft_type"] == "auction"
    assert timing["is_snake_draft"] is False
    assert "next_pick" not in timing


@pytest.mark.asyncio
async def test_missing_yahoo_context_falls_back_without_losing_recommendations():
    rankings = [{"name": "Player One", "position": "RB", "average_draft_position": 14}]

    with (
        patch.object(
            server,
            "get_waiver_wire_players",
            AsyncMock(return_value=[{"name": "Player One", "owned_pct": 50}]),
        ),
        patch.object(server, "get_draft_rankings", AsyncMock(return_value=rankings)),
        patch.object(server, "discover_leagues", AsyncMock(side_effect=RuntimeError("offline"))),
        patch.object(server, "get_user_team_info", AsyncMock(return_value=None)),
        patch.object(server, "yahoo_api_call", AsyncMock(side_effect=RuntimeError("offline"))),
        patch.object(
            server,
            "get_decision_news_context",
            AsyncMock(
                return_value={"by_player": {}, "sources": [], "warnings": []}
            ),
        ),
    ):
        result = await server.get_draft_recommendation_simple(
            "league.test", "balanced", 10, current_pick=15
        )

    assert result["status"] == "success"
    assert result["recommendations"][0]["player"]["name"] == "Player One"
    assert result["recommendations"][0]["score_breakdown"]["base_rank"] == 86
    assert result["draft_context"]["league"]["roster_slots_source"] == "standard fallback"
    assert result["draft_context"]["roster_available"] is False
    assert all(
        need["recommendation_bonus"] == 0
        for need in result["draft_context"]["positional_needs"].values()
    )
    assert result["draft_context"]["warnings"]
