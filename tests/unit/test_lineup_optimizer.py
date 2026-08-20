"""Unit tests for lineup_optimizer.py - Lineup optimization logic."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from lineup_optimizer import (
    BENCH_SLOTS,
    MATCH_CONFIDENCE,
    LineupOptimizer,
    MatchAnalytics,
    Player,
    _calculate_match_confidence,
    _coerce_float,
    _coerce_int,
    _normalize_position,
)
from src.services.rookie_intelligence import rookie_identity_key, rookie_identity_token


class TestUtilityFunctions:
    """Test utility helper functions."""

    def test_coerce_float_valid_number(self):
        """Test coercing valid numbers to float."""
        assert _coerce_float(42) == 42.0
        assert _coerce_float(3.14) == 3.14
        assert _coerce_float("10.5") == 10.5
        assert _coerce_float("100") == 100.0

    def test_coerce_float_invalid(self):
        """Test coercing invalid values returns 0.0."""
        assert _coerce_float("abc") == 0.0
        assert _coerce_float(None) == 0.0
        assert _coerce_float("") == 0.0
        assert _coerce_float({}) == 0.0

    def test_coerce_int_valid_number(self):
        """Test coercing valid numbers to int."""
        assert _coerce_int(42) == 42
        assert _coerce_int(3.14) == 3
        assert _coerce_int("10") == 10
        assert _coerce_int(99.9) == 99

    def test_coerce_int_invalid(self):
        """Test coercing invalid values returns default."""
        assert _coerce_int("abc") == 0
        assert _coerce_int("abc", default=5) == 5
        assert _coerce_int(None) == 0
        assert _coerce_int(None, default=-1) == -1

    def test_normalize_position_valid(self):
        """Test normalizing valid position values."""
        assert _normalize_position("QB") == "QB"
        assert _normalize_position("RB") == "RB"
        assert _normalize_position("WR") == "WR"
        assert _normalize_position("TE") == "TE"
        assert _normalize_position("K") == "K"
        assert _normalize_position("DEF") == "DEF"

    def test_normalize_position_variations(self):
        """Test normalizing position variations."""
        # normalize_position just uppercases, doesn't transform positions
        assert _normalize_position("D/ST") == "D/ST"
        assert _normalize_position("dst") == "DST"
        assert _normalize_position("ir") == "IR"
        assert _normalize_position("qb") == "QB"

    def test_normalize_position_dict(self):
        """Test normalizing position from dict structure."""
        assert _normalize_position({"position": "QB"}) == "QB"
        assert _normalize_position({"0": {"position": "RB"}}) == "RB"

    def test_normalize_position_list(self):
        """Test normalizing position from list structure."""
        # Lists are converted to string and uppercased
        assert _normalize_position([{"position": "WR"}]) == "[{'POSITION': 'WR'}]"

    def test_normalize_position_invalid(self):
        """Test normalizing invalid position returns BN or converts to string."""
        assert _normalize_position(None) == "BN"  # None/empty returns BN
        assert _normalize_position("") == "BN"  # Empty returns BN
        assert _normalize_position(123) == "123"  # Numbers converted to string

    def test_calculate_match_confidence(self):
        """Test match confidence calculation."""
        assert _calculate_match_confidence("exact") == 1.0
        assert _calculate_match_confidence("normalized") == 0.9
        assert _calculate_match_confidence("fuzzy") == 0.4
        assert _calculate_match_confidence("failed") == 0.0
        assert _calculate_match_confidence("exact_pos_mismatch") == 0.5  # 1.0 * 0.5 penalty
        assert _calculate_match_confidence("normalized_team_mismatch") == 0.45  # 0.9 * 0.5 penalty


class TestMatchAnalytics:
    """Test match analytics tracking."""

    def test_match_analytics_initialization(self):
        """Test analytics starts with zero counts."""
        analytics = MatchAnalytics()
        assert analytics.total_players == 0
        assert analytics.matched_players == 0
        assert analytics.failed_matches == 0

    def test_add_match_exact(self):
        """Test adding exact match."""
        analytics = MatchAnalytics()
        analytics.add_match("exact", 1.0)

        assert analytics.total_players == 1
        assert analytics.matched_players == 1
        assert analytics.exact_matches == 1
        assert analytics.avg_match_confidence == 1.0

    def test_add_match_failed(self):
        """Test adding failed match."""
        analytics = MatchAnalytics()
        analytics.add_match("failed", 0.0)

        assert analytics.total_players == 1
        assert analytics.matched_players == 0
        assert analytics.failed_matches == 1

    def test_add_match_with_mismatches(self):
        """Test adding match with position/team mismatches."""
        analytics = MatchAnalytics()
        analytics.add_match("exact_pos_mismatch", 0.5)

        assert analytics.position_mismatches == 1
        assert analytics.exact_matches == 1

        analytics.add_match("normalized_team_mismatch", 0.45)
        assert analytics.team_mismatches == 1

    def test_get_success_rate(self):
        """Test calculating success rate."""
        analytics = MatchAnalytics()
        assert analytics.get_success_rate() == 0.0  # No players

        analytics.add_match("exact", 1.0)
        analytics.add_match("exact", 1.0)
        analytics.add_match("failed", 0.0)
        assert analytics.get_success_rate() == 2 / 3  # 2 matched out of 3

    def test_average_confidence_calculation(self):
        """Test average confidence across multiple matches."""
        analytics = MatchAnalytics()
        analytics.add_match("exact", 1.0)
        analytics.add_match("normalized", 0.9)
        analytics.add_match("fuzzy", 0.4)

        expected_avg = (1.0 + 0.9 + 0.4) / 3
        assert abs(analytics.avg_match_confidence - expected_avg) < 0.01


class TestPlayer:
    """Test Player dataclass."""

    def test_player_creation(self):
        """Test creating a basic player."""
        player = Player(
            name="Josh Allen",
            position="QB",
            team="BUF",
            yahoo_projection=24.5,
        )

        assert player.name == "Josh Allen"
        assert player.position == "QB"
        assert player.team == "BUF"
        assert player.yahoo_projection == 24.5
        assert player.status == "OK"  # Default value

    def test_player_is_valid(self):
        """Test player validity check."""
        valid_player = Player(name="Josh Allen", position="QB", team="BUF")
        assert valid_player.is_valid()

        invalid_player = Player(name="", position="QB", team="BUF")
        assert not invalid_player.is_valid()

        invalid_player2 = Player(name="Josh Allen", position="QB", team="")
        assert not invalid_player2.is_valid()

    def test_player_default_values(self):
        """Test player default field values."""
        player = Player(name="Test Player", position="RB", team="KC")

        assert player.opponent == ""
        assert player.yahoo_projection == 0.0
        assert player.sleeper_projection == 0.0
        assert player.matchup_score == 50
        assert player.injury_probability == 0.0
        assert player.recent_performance == []
        assert player.composite_score == 0.0


@pytest.mark.asyncio
async def test_rookie_outlook_only_breaks_a_rounded_healthy_weekly_tie():
    veteran = Player(
        name="Veteran QB",
        position="QB",
        team="BUF",
        roster_position="QB",
        yahoo_projection=20.04,
    )
    rookie = Player(
        name="Rookie QB",
        position="QB",
        team="NYJ",
        roster_position="BN",
        yahoo_projection=20.0,
    )
    outlook = {
        rookie_identity_key("Rookie QB", "QB"): {
            "status": "matched",
            "base_rank": 2,
            "rookie_year_ppr": {"p10": 100, "p50": 180, "p90": 240},
        }
    }

    result = await LineupOptimizer().optimize_lineup_smart(
        [veteran, rookie], rookie_intelligence=outlook
    )

    assert result["starters"]["QB"].name == "Rookie QB"
    assert result["strategy_summary"]["rookie_intelligence"]["numeric_scores_changed"] is False
    assert result["strategy_summary"]["rookie_intelligence"]["opponent_aware"] is False
    assert (
        result["player_evidence"][rookie_identity_token("Rookie QB", "QB")][
            "rookie_tiebreak_applied"
        ]
        is True
    )


@pytest.mark.asyncio
async def test_rookie_outlook_never_overrides_clear_weekly_or_health_evidence():
    veteran = Player(
        name="Veteran QB",
        position="QB",
        team="BUF",
        roster_position="QB",
        yahoo_projection=20.2,
    )
    rookie = Player(
        name="Rookie QB",
        position="QB",
        team="NYJ",
        roster_position="BN",
        yahoo_projection=20.0,
        status="O",
    )
    outlook = {rookie_identity_key("Rookie QB", "QB"): {"status": "matched", "base_rank": 1}}

    result = await LineupOptimizer().optimize_lineup_smart(
        [veteran, rookie], rookie_intelligence=outlook
    )

    assert result["starters"]["QB"].name == "Veteran QB"
    assert result["strategy_summary"]["rookie_intelligence"]["tiebreaks"] == []


@pytest.mark.asyncio
async def test_rookie_outlook_cannot_break_zero_or_incomparable_weekly_evidence_ties():
    veteran = Player(
        name="Veteran QB",
        position="QB",
        team="BUF",
        roster_position="QB",
        yahoo_projection=20.0,
    )
    rookie = Player(
        name="Rookie QB",
        position="QB",
        team="NYJ",
        roster_position="BN",
        recent_performance_data=SimpleNamespace(weeks_data=[{"points": 20.0}]),
    )
    outlook = {rookie_identity_key("Rookie QB", "QB"): {"status": "matched", "base_rank": 1}}

    incomparable = await LineupOptimizer().optimize_lineup_smart(
        [veteran, rookie], rookie_intelligence=outlook
    )
    veteran.yahoo_projection = 0.0
    rookie.recent_performance_data = None
    zero_evidence = await LineupOptimizer().optimize_lineup_smart(
        [veteran, rookie], rookie_intelligence=outlook
    )

    assert incomparable["starters"]["QB"].name == "Veteran QB"
    assert incomparable["strategy_summary"]["rookie_intelligence"]["tiebreaks"] == []
    assert zero_evidence["starters"]["QB"].name == "Veteran QB"
    assert zero_evidence["strategy_summary"]["rookie_intelligence"]["tiebreaks"] == []


@pytest.mark.asyncio
async def test_same_name_different_positions_keep_distinct_lineup_evidence():
    running_back = Player(
        name="Same Name",
        position="RB",
        team="BUF",
        roster_position="FLEX",
        yahoo_projection=20.0,
    )
    receiver = Player(
        name="Same Name",
        position="WR",
        team="NYJ",
        roster_position="BN",
        yahoo_projection=20.0,
    )
    outlook = {
        rookie_identity_key("Same Name", "RB"): {"status": "matched", "base_rank": 20},
        rookie_identity_key("Same Name", "WR"): {"status": "matched", "base_rank": 1},
    }

    result = await LineupOptimizer().optimize_lineup_smart(
        [running_back, receiver], rookie_intelligence=outlook
    )

    assert result["starters"]["FLEX"].position == "WR"
    assert (
        result["player_evidence"][rookie_identity_token("Same Name", "RB")]["rookie_intelligence"][
            "base_rank"
        ]
        == 20
    )
    assert (
        result["player_evidence"][rookie_identity_token("Same Name", "WR")]["rookie_intelligence"][
            "base_rank"
        ]
        == 1
    )


class TestLineupOptimizer:
    """Test LineupOptimizer functionality."""

    @pytest.mark.asyncio
    async def test_parse_yahoo_roster_basic(self):
        """Test parsing basic roster payload."""
        optimizer = LineupOptimizer()
        roster_payload = {
            "roster": [
                {
                    "name": "Josh Allen",
                    "position": "QB",
                    "team": "BUF",
                    "status": "OK",
                },
                {
                    "name": "Christian McCaffrey",
                    "position": "RB",
                    "team": "SF",
                    "status": "O",
                },
            ]
        }

        players = await optimizer.parse_yahoo_roster(roster_payload)

        assert len(players) == 2
        assert players[0].name == "Josh Allen"
        assert players[0].position == "QB"
        assert players[0].team == "BUF"

        assert players[1].name == "Christian McCaffrey"
        assert players[1].position == "RB"
        assert players[1].status == "O"

    @pytest.mark.asyncio
    async def test_parse_yahoo_roster_empty(self):
        """Test parsing empty roster."""
        optimizer = LineupOptimizer()
        roster_payload = {"roster": []}

        players = await optimizer.parse_yahoo_roster(roster_payload)
        assert players == []

    @pytest.mark.asyncio
    async def test_parse_yahoo_roster_filters_invalid(self):
        """Test that invalid players are filtered out."""
        optimizer = LineupOptimizer()
        roster_payload = {
            "roster": [
                {"name": "Valid Player", "position": "QB", "team": "BUF"},
                {"name": "", "position": "RB", "team": "KC"},  # No name
                {"position": "WR", "team": "LAR"},  # No name
            ]
        }

        players = await optimizer.parse_yahoo_roster(roster_payload)
        assert len(players) == 1
        assert players[0].name == "Valid Player"

    @pytest.mark.asyncio
    async def test_parse_yahoo_roster_normalizes_positions(self):
        """Test that positions are uppercased during parsing."""
        optimizer = LineupOptimizer()
        roster_payload = {
            "roster": [
                {"name": "DEF Player", "position": "d/st", "team": "SF"},
                {"name": "Bench Player", "position": "bn", "team": "KC"},
            ]
        }

        players = await optimizer.parse_yahoo_roster(roster_payload)

        assert players[0].position == "D/ST"  # Uppercased
        assert players[1].position == "BN"  # Uppercased

    @pytest.mark.asyncio
    async def test_parse_yahoo_roster_handles_malformed_data(self):
        """Test graceful handling of malformed roster data."""
        optimizer = LineupOptimizer()
        malformed_payloads = [
            {},  # Empty dict
            {"roster": None},  # None roster
            {"roster": "not a list"},  # String roster
            {"roster": [None, "string", 123]},  # Invalid entries
        ]

        for payload in malformed_payloads:
            players = await optimizer.parse_yahoo_roster(payload)
            assert players == []

    @pytest.mark.asyncio
    async def test_parse_yahoo_roster_preserves_natural_and_selected_positions(self):
        optimizer = LineupOptimizer()

        players = await optimizer.parse_yahoo_roster(
            {
                "roster": [
                    {
                        "name": "Bench Receiver",
                        "position": "BN",
                        "display_position": "WR",
                        "team": "BUF",
                    }
                ]
            }
        )

        assert players[0].position == "WR"
        assert players[0].roster_position == "BN"

    @pytest.mark.asyncio
    async def test_strategies_choose_different_players_from_trustworthy_evidence(self):
        def recent(*points):
            return SimpleNamespace(
                weeks_data=[
                    {"week": index + 1, "points": point} for index, point in enumerate(points)
                ]
            )

        players = [
            Player(
                "Best Overall",
                "WR",
                "BUF",
                roster_position="WR",
                yahoo_projection=12.0,
                sleeper_projection=12.0,
                sleeper_projection_ppr=12.0,
                sleeper_projection_source="sleeper_api",
                recent_performance_data=recent(10.0, 12.0, 11.0),
            ),
            Player(
                "Safe Floor",
                "WR",
                "KC",
                roster_position="BN",
                yahoo_projection=11.4,
                sleeper_projection=11.3,
                sleeper_projection_ppr=11.3,
                sleeper_projection_source="sleeper_api",
                recent_performance_data=recent(11.2, 11.4, 11.3),
                performance_flags=["CONSISTENT"],
            ),
            Player(
                "High Upside",
                "WR",
                "DET",
                roster_position="BN",
                yahoo_projection=11.5,
                sleeper_projection=11.6,
                sleeper_projection_ppr=11.6,
                sleeper_projection_source="sleeper_api",
                recent_performance_data=recent(5.0, 8.0, 20.0),
                performance_flags=["HIGH_CEILING"],
            ),
        ]
        optimizer = LineupOptimizer()

        results = {
            strategy: await optimizer.optimize_lineup_smart(players, strategy)
            for strategy in ("balanced", "conservative", "aggressive")
        }

        assert results["balanced"]["starters"]["WR"].name == "Best Overall"
        assert results["conservative"]["starters"]["WR"].name == "Safe Floor"
        assert results["aggressive"]["starters"]["WR"].name == "High Upside"
        assert all(
            result["strategy_summary"]["opponent_aware"] is False for result in results.values()
        )

    @pytest.mark.asyncio
    async def test_balanced_uses_only_provenance_gated_sleeper_projection(self):
        ranking_fallback = Player(
            "Ranking Fallback",
            "RB",
            "BUF",
            roster_position="RB",
            yahoo_projection=12.0,
            sleeper_projection=30.0,
            sleeper_projection_source="fallback_ranking",
        )
        real_projection = Player(
            "Real Projection",
            "RB",
            "KC",
            roster_position="BN",
            yahoo_projection=11.5,
            sleeper_projection=15.0,
            sleeper_projection_ppr=15.0,
            sleeper_projection_source="sleeper_api",
        )

        result = await LineupOptimizer().optimize_lineup_smart(
            [ranking_fallback, real_projection], "balanced"
        )

        assert result["starters"]["RB"].name == "Real Projection"
        fallback_evidence = result["player_evidence"]["Ranking Fallback"]
        assert not any(
            value.startswith("Sleeper real") for value in fallback_evidence["inputs_used"]
        )
        assert (
            "Sleeper projection omitted: fallback_ranking is not a real projection"
            in fallback_evidence["fallbacks"]
        )

    @pytest.mark.asyncio
    async def test_enhancement_carries_real_projection_provenance_and_omits_fallback(self):
        players = [
            Player(
                "Real Player",
                "RB",
                "BUF",
                roster_position="RB",
                scoring_format="standard",
                scoring_format_source="yahoo_settings",
            ),
            Player(
                "Fallback Player",
                "RB",
                "KC",
                roster_position="BN",
                scoring_format="standard",
                scoring_format_source="yahoo_settings",
            ),
        ]
        projections = {
            "real": {
                "pts": 13.0,
                "projection_source": "sleeper_api",
            },
            "fallback": {
                "pts": 30.0,
                "projection_source": "fallback_ranking",
            },
        }

        with (
            patch("sleeper_api.get_current_season", AsyncMock(return_value=2026)),
            patch("sleeper_api.get_current_week", AsyncMock(return_value=4)),
            patch(
                "sleeper_api.sleeper_client.get_all_players",
                AsyncMock(
                    return_value={
                        "real": {"status": "Active", "depth_chart_order": 1},
                        "fallback": {
                            "status": "Active",
                            "injury_status": "Questionable",
                            "depth_chart_order": 2,
                        },
                    }
                ),
            ),
            patch(
                "sleeper_api.sleeper_client.map_yahoo_to_sleeper",
                AsyncMock(side_effect=["real", "fallback"]),
            ),
            patch(
                "sleeper_api.sleeper_client.get_projections",
                AsyncMock(return_value=projections),
            ),
            patch(
                "sleeper_api.sleeper_client.get_expert_advice",
                AsyncMock(return_value={}),
            ),
            patch(
                "sleeper_api.sleeper_client.get_trending_players",
                AsyncMock(
                    side_effect=[
                        [{"player_id": "real"}],
                        [],
                        [],
                        [{"player_id": "fallback"}],
                    ]
                ),
            ),
            patch(
                "sleeper_api.sleeper_client.get_player_stats",
                AsyncMock(
                    side_effect=lambda season, week: {
                        "real": {
                            "pts": {1: 8.0, 2: 10.0, 3: 14.0}[week],
                            "pts_ppr": 100.0,
                        },
                        "fallback": {"pts": 12.0, "pts_ppr": 100.0},
                    }
                ),
            ),
        ):
            enhanced = await LineupOptimizer().enhance_with_external_data(players, week=4)

        assert enhanced[0].sleeper_projection == 13.0
        assert enhanced[0].sleeper_projection_source == "sleeper_api"
        assert enhanced[0].sleeper_status == "Active"
        assert enhanced[0].sleeper_depth_chart_order == 1
        assert enhanced[0].trending_score == 75
        assert len(enhanced[0].recent_performance_data.weeks_data) == 3
        assert [week["points"] for week in enhanced[0].recent_performance_data.weeks_data] == [
            14.0,
            10.0,
            8.0,
        ]
        assert enhanced[0].recent_performance_data.trend == "improving"
        assert "TRENDING_UP" in enhanced[0].performance_flags
        assert enhanced[1].sleeper_projection == 0.0
        assert enhanced[1].sleeper_projection_source == "fallback_ranking"
        assert enhanced[1].sleeper_injury_status == "Questionable"
        assert enhanced[1].sleeper_depth_chart_order == 2
        assert enhanced[1].trending_score == 25

        optimizer = LineupOptimizer()
        sourced_result = await optimizer.optimize_lineup_smart(enhanced, "conservative")
        assert sourced_result["starters"]["RB"].name == "Real Player"
        real_evidence = sourced_result["player_evidence"]["Real Player"]
        assert "Sleeper recent actuals (3 weeks)" in real_evidence["inputs_used"]
        assert "Sleeper depth-chart order: 1" in real_evidence["inputs_used"]
        assert "Sleeper trending adds" in real_evidence["inputs_used"]
        assert sourced_result["player_evidence"]["Fallback Player"]["health_flags"] == [
            "Questionable status: QUESTIONABLE"
        ]

        for player in enhanced:
            player.sleeper_injury_status = ""
            player.sleeper_depth_chart_order = 0
            player.trending_score = 50
        neutral_result = await optimizer.optimize_lineup_smart(enhanced, "conservative")
        assert neutral_result["starters"]["RB"].name == "Fallback Player"

    @pytest.mark.asyncio
    async def test_news_flags_risk_without_becoming_numeric_projection(self):
        recent = SimpleNamespace(
            weeks_data=[
                {"week": 1, "points": 10.0},
                {"week": 2, "points": 11.0},
            ]
        )
        player = Player(
            "News Player",
            "RB",
            "BUF",
            roster_position="RB",
            yahoo_projection=11.0,
            sleeper_projection=11.0,
            sleeper_projection_ppr=11.0,
            sleeper_projection_source="sleeper_api",
            recent_performance_data=recent,
            performance_flags=["CONSISTENT"],
        )
        optimizer = LineupOptimizer()

        without_news = await optimizer.optimize_lineup_smart([player], "balanced")
        with_news = await optimizer.optimize_lineup_smart(
            [player],
            "balanced",
            decision_news={
                "News Player": {
                    "espn": [],
                    "rotowire": [
                        {
                            "headline": "Not expected to play",
                            "summary": "Availability remains uncertain.",
                            "source": "RotoWire NFL RSS",
                        }
                    ],
                }
            },
        )

        without_evidence = without_news["player_evidence"]["News Player"]
        with_evidence = with_news["player_evidence"]["News Player"]
        assert with_evidence["strategy_score"] == without_evidence["strategy_score"]
        assert with_evidence["confidence"] == "medium"
        assert with_evidence["news_signals"] == [
            {
                "signal": "availability_or_role_risk",
                "source": "RotoWire NFL RSS",
                "headline": "Not expected to play",
            }
        ]
        assert "headlines are not converted to points" in with_evidence["news_scoring_note"]

    @pytest.mark.asyncio
    async def test_missing_data_fallback_prefers_healthy_player_over_out_player(self):
        out_player = Player(
            "Out Starter",
            "RB",
            "BUF",
            roster_position="RB",
            status="O",
        )
        healthy_player = Player(
            "Healthy Bench",
            "RB",
            "KC",
            roster_position="BN",
        )

        result = await LineupOptimizer().optimize_lineup_smart(
            [out_player, healthy_player], "conservative"
        )

        assert result["starters"]["RB"].name == "Healthy Bench"
        assert result["player_evidence"]["Out Starter"]["health_flags"] == ["Unavailable status: O"]
        evidence = result["player_evidence"]["Healthy Bench"]
        assert evidence["strategy_score"] == 0.0
        assert evidence["fallbacks"] == [
            "Yahoo projection unavailable",
            "Sleeper real projection unavailable",
            "Sleeper recent actuals unavailable",
            "Yahoo scoring format unavailable; PPR fallback used",
            "Roster/role evidence unavailable",
            "ESPN/RotoWire player evidence unavailable",
        ]


class TestBenchSlots:
    """Test bench slot definitions."""

    def test_bench_slots_contain_expected_values(self):
        """Test that BENCH_SLOTS contains expected values."""
        assert "BN" in BENCH_SLOTS
        assert "BENCH" in BENCH_SLOTS
        assert "IR" in BENCH_SLOTS
        assert "IR+" in BENCH_SLOTS
        assert "NA" in BENCH_SLOTS

    def test_bench_slots_excludes_active_positions(self):
        """Test that active positions are not in BENCH_SLOTS."""
        assert "QB" not in BENCH_SLOTS
        assert "RB" not in BENCH_SLOTS
        assert "WR" not in BENCH_SLOTS
        assert "TE" not in BENCH_SLOTS
        assert "FLEX" not in BENCH_SLOTS


class TestMatchConfidenceScores:
    """Test match confidence score definitions."""

    def test_match_confidence_exact_highest(self):
        """Test that exact matches have highest confidence."""
        assert MATCH_CONFIDENCE["exact"] == 1.0
        assert MATCH_CONFIDENCE["exact"] >= MATCH_CONFIDENCE["normalized"]
        assert MATCH_CONFIDENCE["exact"] >= MATCH_CONFIDENCE["fuzzy"]

    def test_match_confidence_decreasing_order(self):
        """Test that confidence decreases with match quality."""
        assert MATCH_CONFIDENCE["exact"] > MATCH_CONFIDENCE["normalized"]
        assert MATCH_CONFIDENCE["normalized"] > MATCH_CONFIDENCE["variant"]
        assert MATCH_CONFIDENCE["variant"] > MATCH_CONFIDENCE["token_subset"]
        assert MATCH_CONFIDENCE["token_subset"] > MATCH_CONFIDENCE["fuzzy"]
        assert MATCH_CONFIDENCE["fuzzy"] > MATCH_CONFIDENCE["failed"]

    def test_match_confidence_failed_is_zero(self):
        """Test that failed matches have zero confidence."""
        assert MATCH_CONFIDENCE["failed"] == 0.0
