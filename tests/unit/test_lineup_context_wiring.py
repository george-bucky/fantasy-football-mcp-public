"""Caller-level context binding tests use synthetic Yahoo responses only."""

from unittest.mock import AsyncMock, patch

import pytest

from lineup_optimizer import Player, lineup_optimizer
from src.handlers import matchup_handlers, roster_handlers
from src.parsers.yahoo_parsers import parse_team_roster

LEAGUE = "461.l.1"
TEAM = "461.l.1.t.1"


def settings(*, league=LEAGUE):
    return {
        "fantasy_content": {
            "league": [
                [
                    {"league_key": league},
                    {"league_id": "1"},
                    {"num_teams": 12},
                    {"scoring_type": "head"},
                    {"season": 2026},
                    {"current_week": 5},
                ],
                {
                    "settings": {
                        "scoring_type": "head",
                        "roster_positions": [
                            {"roster_position": {"position": "QB", "count": 1}},
                            {"roster_position": {"position": "WR", "count": 2}},
                            {"roster_position": {"position": "BN", "count": 6}},
                        ],
                        "stat_modifiers": {
                            "stats": {"0": {"stat": {"stat_id": "10", "value": "0.5"}}, "count": 1}
                        },
                    }
                },
            ]
        }
    }


def roster(*, week=5, editable=0, team=TEAM):
    return {
        "fantasy_content": {
            "team": [
                [{"team_key": team}],
                {
                    "roster": {
                        "coverage_type": "week",
                        "week": week,
                        "is_editable": editable,
                        "0": {
                            "players": {
                                "0": {
                                    "player": [
                                        [
                                            {"player_key": "461.p.1"},
                                            {"name": {"full": "Exact QB"}},
                                            {"display_position": "QB"},
                                            {"editorial_team_abbr": "BUF"},
                                        ],
                                        {"selected_position": [{"position": "QB"}]},
                                    ]
                                },
                                "count": 1,
                            }
                        },
                    }
                },
            ]
        }
    }


def test_authoritative_slots_preserve_empty_required_positions():
    slots, warnings = matchup_handlers._authoritative_roster_slots(settings(), LEAGUE)
    assert slots == {"QB": 1, "WR": 2}
    assert warnings == []


@pytest.mark.parametrize("kind", ["wrong_league", "truncated", "missing", "unresolved"])
def test_incomplete_or_cross_league_slots_do_not_claim_authority(kind):
    value = settings(league="461.l.2") if kind == "wrong_league" else settings()
    positions = value["fantasy_content"]["league"][1]["settings"]["roster_positions"]
    if kind == "truncated":
        value["fantasy_content"]["league"][1]["settings"]["roster_positions"] = {
            "0": positions[0],
            "count": 3,
        }
    elif kind == "missing":
        value = {}
    elif kind == "unresolved":
        positions[0]["roster_position"]["is_starting_position"] = "maybe"
    slots, warnings = matchup_handlers._authoritative_roster_slots(value, LEAGUE)
    assert slots is None
    assert "unverified" in warnings[0]


@pytest.mark.parametrize("value", [True, 0, 19, 1.5, "current", "1.5"])
def test_requested_week_is_validated(value):
    with pytest.raises(ValueError):
        matchup_handlers._requested_roster_week(value)


async def test_raw_roster_preserves_exact_player_key_into_optimizer():
    parsed = parse_team_roster(roster())
    assert parsed[0]["player_key"] == "461.p.1"
    players = await lineup_optimizer.parse_yahoo_roster(roster())
    assert players[0].player_key == "461.p.1"
    assert players[0].lineup_locked is None


def test_only_exact_week_noneditable_roster_proves_global_locks():
    players = [Player(name="QB", position="QB", team="BUF")]
    assert (
        matchup_handlers._apply_roster_lock_context(roster(), players, team_key=TEAM, target_week=5)
        == []
    )
    assert players[0].lineup_locked is True


@pytest.mark.parametrize(
    "value", [roster(week=4), roster(editable=1), roster(team="461.l.1.t.2"), {}]
)
def test_unknown_or_editable_roster_never_claims_individual_unlock(value):
    player = Player(name="QB", position="QB", team="BUF")
    warnings = matchup_handlers._apply_roster_lock_context(
        value, [player], team_key=TEAM, target_week=5
    )
    assert player.lineup_locked is None
    assert "unverified" in warnings[0]


def test_duplicate_name_selection_evidence_uses_solver_key():
    players = [
        Player(name="Same", position="QB", team="BUF"),
        Player(name="Same", position="WR", team="BUF"),
    ]
    optimization = {
        "strategy_summary": {"assignment_audit": {"evidence_keys": {"0": "Same|1", "1": "Same|2"}}},
        "player_evidence": {"Same|1": {"score": 1}, "Same|2": {"score": 2}},
    }
    assert matchup_handlers._selection_evidence(
        optimization, players, players[1], fallback_key="Same"
    ) == {"score": 2}


async def test_explicit_roster_week_is_requested_even_for_basic_view():
    call = AsyncMock(return_value={})
    with (
        patch.object(roster_handlers, "yahoo_api_call", call),
        patch.object(roster_handlers, "parse_team_roster", return_value=[]),
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": TEAM})
        ),
    ):
        await roster_handlers.handle_ff_get_roster(
            {"league_key": LEAGUE, "team_key": TEAM, "week": 4, "data_level": "basic"}
        )
    call.assert_awaited_once_with(f"team/{TEAM}/roster;week=4")


async def test_public_lineup_passes_verified_slots_and_preserves_empty_slots():
    players = [
        Player(name="QB", position="QB", team="BUF", roster_position="QB", yahoo_projection=20)
    ]
    calls = []

    async def api(endpoint):
        calls.append(endpoint)
        return roster(editable=1) if "/roster" in endpoint else settings()

    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value=TEAM)),
        patch.object(matchup_handlers, "yahoo_api_call", api),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(
            lineup_optimizer, "enhance_with_external_data", AsyncMock(return_value=players)
        ),
        patch.object(
            matchup_handlers,
            "get_decision_news_context",
            AsyncMock(return_value={"by_player": {}, "sources": [], "warnings": []}),
        ),
    ):
        result = await matchup_handlers.handle_ff_build_lineup({"league_key": LEAGUE, "week": 5})
    assert f"team/{TEAM}/roster;week=5" in calls
    assert (
        result["analysis"]["strategy_evidence"]["assignment_audit"]["required_slots_source"]
        == "league_settings"
    )
    assert len(result["errors"]) == 2
    assert all("WR" in error for error in result["errors"])


@pytest.mark.parametrize("value", [roster(week=4), roster(team="461.l.1.t.2")])
def test_explicit_roster_response_mismatch_fails_closed(value):
    with pytest.raises(ValueError):
        matchup_handlers._verify_roster_response(value, team_key=TEAM, requested_week=5)


def test_missing_roster_binding_is_unknown_not_verified():
    warnings = matchup_handlers._verify_roster_response({}, team_key=TEAM, requested_week=5)
    assert len(warnings) == 2


async def test_roster_week_mismatch_is_not_presented_as_requested_week():
    with patch.object(roster_handlers, "yahoo_api_call", AsyncMock(return_value=roster(week=4))):
        result = await roster_handlers.handle_ff_get_roster(
            {"league_key": LEAGUE, "team_key": TEAM, "week": 5}
        )
    assert result["status"] == "error"
    assert "requested week" in result["error"]


async def test_default_lineup_rejects_roster_from_prior_week_before_enhancement():
    players = [Player(name="QB", position="QB", team="BUF", roster_position="QB")]
    enhance = AsyncMock(return_value=players)

    async def api(endpoint):
        return roster(week=4) if "/roster" in endpoint else settings()

    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value=TEAM)),
        patch.object(matchup_handlers, "yahoo_api_call", api),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(lineup_optimizer, "enhance_with_external_data", enhance),
    ):
        result = await matchup_handlers.handle_ff_build_lineup({"league_key": LEAGUE})
    assert result["status"] == "error"
    assert "requested week" in result["error"]
    enhance.assert_not_awaited()


async def test_default_enhanced_roster_rejects_prior_week_after_current_context_resolves():
    players = [Player(name="QB", position="QB", team="BUF", roster_position="QB")]
    enhance = AsyncMock(return_value=players)

    async def api(endpoint):
        return roster(week=4) if "/roster" in endpoint else settings()

    with (
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": TEAM})
        ),
        patch.object(roster_handlers, "yahoo_api_call", api),
        patch.object(
            roster_handlers,
            "parse_team_roster",
            return_value=[{"name": "QB", "position": "QB", "team": "BUF"}],
        ),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(lineup_optimizer, "enhance_with_external_data", enhance),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {
                "league_key": LEAGUE,
                "team_key": TEAM,
                "data_level": "full",
                "include_weekly_context": True,
            }
        )
    assert result["status"] == "error"
    assert "requested week" in result["error"]
    enhance.assert_not_awaited()


def test_unknown_requested_and_current_week_remains_explicitly_unverified():
    warnings = matchup_handlers._verify_roster_response(
        roster(), team_key=TEAM, requested_week=None
    )
    assert any("week unverified" in warning.lower() for warning in warnings)


async def test_explicit_wrong_league_discards_scoring_and_period_before_enhancement():
    wrong_settings = settings(league="461.l.2")
    wrong_settings["fantasy_content"]["league"][1]["settings"]["stat_modifiers"]["stats"]["0"][
        "stat"
    ]["display_name"] = "receptions"
    players = [Player(name="QB", position="QB", team="BUF", roster_position="QB")]
    enhance = AsyncMock(return_value=players)

    async def api(endpoint):
        return roster(editable=1) if "/roster" in endpoint else wrong_settings

    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value=TEAM)),
        patch.object(matchup_handlers, "yahoo_api_call", api),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(lineup_optimizer, "enhance_with_external_data", enhance),
    ):
        result = await matchup_handlers.handle_ff_build_lineup({"league_key": LEAGUE})
    assert "does not match the requested league_key" in result["error"]
    assert "optimal_lineup" not in result
    assert players[0].scoring_format_source != "yahoo_settings"
    enhance.assert_not_awaited()


@pytest.mark.parametrize("field", ["game_key", "game_id"])
async def test_explicit_wrong_game_categories_do_not_supply_reception_scoring(field):
    categories = {
        "fantasy_content": {
            "game": [
                [{field: "999"}],
                {
                    "stat_categories": {
                        "stats": [{"stat": {"stat_id": "10", "display_name": "receptions"}}]
                    }
                },
            ]
        }
    }

    async def api(endpoint):
        return categories if "stat_categories" in endpoint else settings()

    with pytest.raises(ValueError, match="stat categories"):
        await matchup_handlers._get_lineup_context(LEAGUE, api_call=api)


@pytest.mark.parametrize("payload", [{}, {"league_key": None, "game_key": None}])
async def test_absent_context_binding_keeps_unknown_fallback(payload):
    context = await matchup_handlers._get_lineup_context(
        LEAGUE, api_call=AsyncMock(return_value=payload)
    )
    assert context["scoring_format_source"] == "fallback_default_ppr"
    assert context["canonical_scoring_basis"] == "unknown"
    assert context["season"] is None
    assert context["current_week"] is None


def _projected_players():
    return [
        Player(
            name="Exact QB",
            player_key="461.p.1",
            position="QB",
            team="BUF",
            roster_position="QB",
            yahoo_projection=20,
            sleeper_projection_half_ppr=10,
            sleeper_projection_source="sleeper_api",
            projection_context={"source_provenance": {"yahoo": {"snapshot": "synthetic"}}},
        ),
        Player(
            name="Bench QB",
            player_key="461.p.2",
            position="QB",
            team="NYJ",
            roster_position="BN",
            yahoo_projection=10,
            sleeper_projection_half_ppr=8,
            sleeper_projection_source="sleeper_api",
        ),
    ]


async def _context_api(endpoint):
    if "/roster" in endpoint:
        return roster(editable=1)
    if "stat_categories" in endpoint:
        return {
            "fantasy_content": {
                "game": [
                    [{"game_key": "461"}],
                    {
                        "stat_categories": {
                            "stats": [{"stat": {"stat_id": "10", "display_name": "receptions"}}]
                        }
                    },
                ]
            }
        }
    return settings()


async def test_roster_and_lineup_share_canonical_points_and_actual_selection_utility():
    lineup_players = _projected_players()
    roster_players = _projected_players()
    contexts = []

    async def enhance(players, *, week=None, season=None):
        contexts.append((week, season, [dict(p.projection_context) for p in players]))
        return players

    with (
        patch.object(matchup_handlers, "get_user_team_key", AsyncMock(return_value=TEAM)),
        patch.object(matchup_handlers, "yahoo_api_call", _context_api),
        patch.object(
            lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=lineup_players)
        ),
        patch.object(lineup_optimizer, "enhance_with_external_data", enhance),
        patch.object(
            matchup_handlers,
            "get_decision_news_context",
            AsyncMock(return_value={"by_player": {}, "sources": [], "warnings": []}),
        ),
    ):
        lineup = await matchup_handlers.handle_ff_build_lineup({"league_key": LEAGUE})
    raw = [
        {
            "name": p.name,
            "position": p.position,
            "team": p.team,
            "yahoo_projection": p.yahoo_projection,
        }
        for p in roster_players
    ]
    with (
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": TEAM})
        ),
        patch.object(roster_handlers, "yahoo_api_call", _context_api),
        patch.object(roster_handlers, "parse_team_roster", return_value=raw),
        patch.object(
            lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=roster_players)
        ),
        patch.object(lineup_optimizer, "enhance_with_external_data", enhance),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {"league_key": LEAGUE, "team_key": TEAM, "data_level": "full"}
        )
    starter = lineup["optimal_lineup"]["QB"]
    same_player = result["all_players"][0]
    assert starter["expected_points"] == same_player["expected_points"] == 10
    assert same_player["expected_points_if_available"] == 10
    assert same_player["roster_analysis"]["projected_points"] == 10
    assert result["overall_analysis"]["total_projected_points"] == 18
    assert (
        result["overall_analysis"]["projection_scope"]
        == "entire_roster_including_bench_not_selected_lineup"
    )
    assessment = starter["selection_evidence"]["projection_assessment"]
    assert starter["projection_assessment"] is assessment
    assert starter["selection_score"] == assessment["strategy_utility"]
    assert starter["selection_score"] == lineup_players[0].projection_assessment["strategy_utility"]
    assert lineup["bench"][0]["projection_assessment"]["identity"]["player_id"] == "461.p.2"
    assert len(contexts) == 2
    assert all(week == 5 and season == 2026 for week, season, _ in contexts)
    assert contexts[0][2][0]["source_provenance"] == {"yahoo": {"snapshot": "synthetic"}}
    assert contexts[0][2][0].get("as_of") is None
    assert all(p.scoring_format == "half-ppr" for p in roster_players + lineup_players)


async def test_enhanced_roster_fetches_context_once_without_weekly_report():
    players = _projected_players()
    api = AsyncMock(side_effect=_context_api)
    with (
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": TEAM})
        ),
        patch.object(roster_handlers, "yahoo_api_call", api),
        patch.object(
            roster_handlers,
            "parse_team_roster",
            return_value=[{"name": "Exact QB", "position": "QB", "team": "BUF"}],
        ),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(
            lineup_optimizer, "enhance_with_external_data", AsyncMock(return_value=players)
        ),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {"league_key": LEAGUE, "team_key": TEAM, "data_level": "full"}
        )
    endpoints = [call.args[0] for call in api.await_args_list]
    assert endpoints.count(f"league/{LEAGUE}/settings") == 1
    assert endpoints.count("game/461/stat_categories") == 1
    assert "weekly_player_context" not in result
    assert result["all_players"][0]["projection_assessment"]["identity"]["week"] == 5


async def test_projection_output_disabled_hides_new_and_existing_forecast_values():
    players = _projected_players()
    players[0].adjusted_projection = 99
    raw = [
        {
            "name": p.name,
            "position": p.position,
            "team": p.team,
            "yahoo_projection": p.yahoo_projection,
        }
        for p in players
    ]
    with (
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": TEAM})
        ),
        patch.object(roster_handlers, "yahoo_api_call", _context_api),
        patch.object(roster_handlers, "parse_team_roster", return_value=raw),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(
            lineup_optimizer, "enhance_with_external_data", AsyncMock(return_value=players)
        ),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {
                "league_key": LEAGUE,
                "team_key": TEAM,
                "data_level": "full",
                "include_projections": False,
            }
        )
    for entry in result["all_players"]:
        assert "projection_assessment" not in entry
        assert "expected_points" not in entry
        assert "selection_score" not in entry
        assert all(
            entry[key] is None
            for key in (
                "yahoo_projection",
                "sleeper_projection",
                "floor_projection",
                "ceiling_projection",
                "adjusted_projection",
            )
        )
        assert entry["roster_analysis"]["projected_points"] is None
    assert all("yahoo_projection" not in p for p in result["roster"])
    assert result["overall_analysis"]["total_projected_points"] is None


def test_projection_binding_preserves_source_provenance_and_leaves_unknown_time_unknown():
    player = _projected_players()[0]
    source = dict(player.projection_context["source_provenance"])
    year, week = matchup_handlers._bind_projection_request([player], {}, None)
    assert (year, week) == (None, None)
    assert player.projection_context["source_provenance"] == source
    assert player.projection_context.get("as_of") is None


async def test_bye_display_does_not_destroy_source_values_or_hide_projection_semantics():
    players = _projected_players()
    players[0].on_bye = True
    raw = [{"name": p.name, "position": p.position, "team": p.team} for p in players]
    with (
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": TEAM})
        ),
        patch.object(roster_handlers, "yahoo_api_call", _context_api),
        patch.object(roster_handlers, "parse_team_roster", return_value=raw),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(
            lineup_optimizer, "enhance_with_external_data", AsyncMock(return_value=players)
        ),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {"league_key": LEAGUE, "team_key": TEAM, "data_level": "full"}
        )
    entry = result["all_players"][0]
    assert entry["yahoo_projection"] == 0
    assert players[0].yahoo_projection == 20
    assert players[0].sleeper_projection_half_ppr == 10
    assert entry["projection_assessment"]["raw_provider_values"]["yahoo"] == 20
    assert entry["projection_semantics"] == "conditional_on_availability"
    assert entry["eligibility"]["eligible"] is False
    assert entry["selection_score"] is None
    assert entry["expected_points_if_available"] == 10
    assert entry["roster_analysis"]["projected_points"] == 0
    assert result["overall_analysis"]["total_projected_points"] == 8


@pytest.mark.parametrize("all_unknown", [False, True])
async def test_missing_roster_estimates_have_explicit_partial_coverage_not_fake_zero(all_unknown):
    players = _projected_players()
    players[1].yahoo_projection = 0
    players[1].sleeper_projection_half_ppr = 0
    if all_unknown:
        players[0].yahoo_projection = 0
        players[0].sleeper_projection_half_ppr = 0
    with (
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": TEAM})
        ),
        patch.object(roster_handlers, "yahoo_api_call", _context_api),
        patch.object(
            roster_handlers,
            "parse_team_roster",
            return_value=[
                {"name": p.name, "position": p.position, "team": p.team} for p in players
            ],
        ),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(
            lineup_optimizer, "enhance_with_external_data", AsyncMock(return_value=players)
        ),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {"league_key": LEAGUE, "team_key": TEAM, "data_level": "full"}
        )
    summary = result["overall_analysis"]
    assert summary["total_projected_points"] is None
    assert summary["projection_coverage"]["complete"] is False
    assert summary["projection_coverage"]["known"] == (0 if all_unknown else 1)
    assert summary["projection_coverage"]["missing"] == (2 if all_unknown else 1)
    assert summary["known_projected_points_total"] == (None if all_unknown else 10)


@pytest.mark.parametrize(
    "view",
    [
        {"data_level": "standard"},
        {"data_level": "full", "include_external_data": False},
    ],
)
async def test_known_bye_is_not_masked_by_external_output_toggle(view):
    players = _projected_players()
    players[0].on_bye = True
    with (
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": TEAM})
        ),
        patch.object(roster_handlers, "yahoo_api_call", _context_api),
        patch.object(
            roster_handlers,
            "parse_team_roster",
            return_value=[
                {"name": p.name, "position": p.position, "team": p.team} for p in players
            ],
        ),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(
            lineup_optimizer, "enhance_with_external_data", AsyncMock(return_value=players)
        ),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {"league_key": LEAGUE, "team_key": TEAM, **view}
        )
    entry = result["all_players"][0]
    assert entry["on_bye"] is True
    assert entry["yahoo_projection"] == 0
    assert entry["projection_assessment"]["raw_provider_values"]["yahoo"] == 20
    assert entry["eligibility"]["eligible"] is False
    assert entry["selection_score"] is None
    assert players[0].yahoo_projection == 20
    assert result["all_players"][1]["on_bye"] is None


@pytest.mark.parametrize(
    "view",
    [
        {"data_level": "standard"},
        {"data_level": "full", "include_external_data": False},
    ],
)
async def test_external_disabled_has_no_forecast_or_yahoo_fallback(view):
    from types import SimpleNamespace

    players = _projected_players()
    original = players[0]
    original.sleeper_injury_status = "OUT"
    original.sleeper_depth_chart_order = 1
    original.target_share = 50
    original.snap_count_pct = 90
    original.trending_score = 75
    original.performance_flags = ["BREAKOUT_CANDIDATE", "TRENDING_UP"]
    original.recent_performance_data = SimpleNamespace(weeks_data=[{"points": 100}])
    original.projection_context["source_provenance"]["sleeper"] = {"snapshot": "external"}
    enhance = AsyncMock(return_value=players)
    with (
        patch.object(
            roster_handlers, "get_user_team_info", AsyncMock(return_value={"team_key": TEAM})
        ),
        patch.object(roster_handlers, "yahoo_api_call", _context_api),
        patch.object(
            roster_handlers,
            "parse_team_roster",
            return_value=[
                {"name": p.name, "position": p.position, "team": p.team} for p in players
            ],
        ),
        patch.object(lineup_optimizer, "parse_yahoo_roster", AsyncMock(return_value=players)),
        patch.object(lineup_optimizer, "enhance_with_external_data", enhance),
    ):
        result = await roster_handlers.handle_ff_get_roster(
            {"league_key": LEAGUE, "team_key": TEAM, **view}
        )
    entry = result["all_players"][0]
    assessment = entry["projection_assessment"]
    assert entry["expected_points_if_available"] is None
    # Neutral utility remains distinct from an unavailable point forecast.
    assert entry["selection_score"] == 0
    assert entry["eligibility"]["eligible"] is True
    assert assessment["effective_source_weights"] == {}
    assert "yahoo" not in assessment["configured_source_weights"]
    assert assessment["raw_provider_values"]["sleeper"] is None
    assert assessment["raw_source_values"]["sleeper"] is None
    assert "recent_avg" not in assessment["raw_source_values"]
    assert assessment["supporting_evidence"]["recent_actuals"]["status"] == "disabled_by_request"
    assert assessment["missing_sources"]["sleeper"] == "disabled_by_request"
    assert "recent_avg" not in assessment["missing_sources"]
    assert assessment["strategy_trace"]["utility_source_values"] == {}
    assert "yahoo" not in assessment["strategy_trace"]["utility_source_weights"]
    assert assessment["strategy_trace"]["role_multiplier"] == 1
    assert assessment["strategy_trace"]["availability_multiplier"] == 1
    assert set(assessment["source_provenance"]) <= {"yahoo"}
    assert result["analysis_context"]["data_sources"] == ["Yahoo"]
    assert entry["sleeper_projection"] is None
    assert original.sleeper_projection_half_ppr == 10
    assert original.sleeper_injury_status == "OUT"
    assert original.performance_flags == ["BREAKOUT_CANDIDATE", "TRENDING_UP"]
    assert original.projection_context["source_provenance"]["sleeper"] == {"snapshot": "external"}
    enhance.assert_not_awaited()
