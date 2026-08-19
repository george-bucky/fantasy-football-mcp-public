"""Unit tests for bye week validation and handling across the codebase.

This test module verifies the bye week fixes implemented in:
- fantasy_football_multi_league.py (get_waiver_wire_players, get_draft_rankings)
- src/parsers/yahoo_parsers.py (parse_yahoo_free_agent_players)
- src/services/player_enhancement.py (detect_bye_week)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.parsers.yahoo_parsers import parse_yahoo_free_agent_players
from src.services.player_enhancement import detect_bye_week, enhance_player_with_context


class TestByeWeekValidation:
    """Test bye week validation logic in player_enhancement service."""

    def test_detect_bye_week_valid_match(self):
        """Test detection when player is on bye this week."""
        assert detect_bye_week(7, 7) is True
        assert detect_bye_week("7", 7) is True
        assert detect_bye_week(7.0, 7) is True

    def test_detect_bye_week_valid_no_match(self):
        """Test detection when player is not on bye."""
        assert detect_bye_week(7, 5) is False
        assert detect_bye_week("10", 7) is False
        assert detect_bye_week(14, 1) is False

    def test_detect_bye_week_none_value(self):
        """Test handling of None bye week value."""
        assert detect_bye_week(None, 7) is False
        assert detect_bye_week(None, 1) is False

    def test_detect_bye_week_na_string(self):
        """Test handling of 'N/A' string value."""
        assert detect_bye_week("N/A", 7) is False
        assert detect_bye_week("N/A", 1) is False

    def test_detect_bye_week_empty_string(self):
        """Test handling of empty string value."""
        assert detect_bye_week("", 7) is False
        assert detect_bye_week("", 1) is False

    def test_detect_bye_week_invalid_range_too_low(self):
        """Test validation rejects bye weeks < 1."""
        assert detect_bye_week(0, 0) is False
        assert detect_bye_week(-1, -1) is False
        assert detect_bye_week("-5", 5) is False

    def test_detect_bye_week_invalid_range_too_high(self):
        """Test validation rejects bye weeks > 18."""
        assert detect_bye_week(19, 19) is False
        assert detect_bye_week(25, 25) is False
        assert detect_bye_week("100", 100) is False

    def test_detect_bye_week_invalid_string_format(self):
        """Test handling of non-numeric string values."""
        assert detect_bye_week("invalid", 7) is False
        assert detect_bye_week("week7", 7) is False
        assert detect_bye_week("7.5", 7) is False
        assert detect_bye_week("abc", 1) is False

    def test_detect_bye_week_unexpected_types(self):
        """Test handling of unexpected data types."""
        assert detect_bye_week([], 7) is False
        assert detect_bye_week({}, 7) is False
        # Note: bool(True) == 1, so this actually returns True for week 1
        assert detect_bye_week(True, 1) is True  # True converts to 1
        assert detect_bye_week(True, 2) is False  # True (1) != 2

    def test_detect_bye_week_boundary_values(self):
        """Test boundary values (1 and 18 are valid)."""
        assert detect_bye_week(1, 1) is True
        assert detect_bye_week(18, 18) is True
        assert detect_bye_week("1", 1) is True
        assert detect_bye_week("18", 18) is True


class TestYahooParserByeWeeks:
    """Test bye week extraction in Yahoo API parsers."""

    def test_parse_free_agents_valid_bye_week(self):
        """Test parsing valid bye week data."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Test Player"},
                                            "display_position": "RB",
                                            "editorial_team_abbr": "KC",
                                        }
                                    ],
                                    {"bye_weeks": {"week": "7"}},
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 1
        assert result[0]["bye"] == 7

    def test_parse_free_agents_bye_week_as_int(self):
        """Test parsing bye week when provided as integer."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Test Player"},
                                            "display_position": "WR",
                                            "editorial_team_abbr": "BUF",
                                        }
                                    ],
                                    {"bye_weeks": {"week": 12}},
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 1
        assert result[0]["bye"] == 12

    def test_parse_free_agents_missing_bye_weeks_field(self):
        """Test handling when bye_weeks field is missing."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Test Player"},
                                            "display_position": "QB",
                                            "editorial_team_abbr": "MIA",
                                        }
                                    ],
                                    {"ownership": {"ownership_percentage": 50}},
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 1
        assert result[0]["bye"] is None

    def test_parse_free_agents_malformed_bye_weeks_dict(self):
        """Test handling of malformed bye_weeks dictionary."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Test Player"},
                                            "display_position": "TE",
                                            "editorial_team_abbr": "SF",
                                        }
                                    ],
                                    {"bye_weeks": {"other_key": "value"}},  # Missing 'week'
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 1
        assert result[0]["bye"] is None

    def test_parse_free_agents_bye_week_out_of_range_high(self):
        """Test handling bye week number > 18."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Test Player"},
                                            "display_position": "RB",
                                            "editorial_team_abbr": "DEN",
                                        }
                                    ],
                                    {"bye_weeks": {"week": "99"}},
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 1
        assert result[0]["bye"] is None

    def test_parse_free_agents_bye_week_out_of_range_low(self):
        """Test handling bye week number < 1."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Test Player"},
                                            "display_position": "WR",
                                            "editorial_team_abbr": "LAR",
                                        }
                                    ],
                                    {"bye_weeks": {"week": "0"}},
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 1
        assert result[0]["bye"] is None

    def test_parse_free_agents_bye_week_non_numeric(self):
        """Test handling non-numeric bye week values."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Test Player"},
                                            "display_position": "K",
                                            "editorial_team_abbr": "TB",
                                        }
                                    ],
                                    {"bye_weeks": {"week": "N/A"}},
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 1
        assert result[0]["bye"] is None

    def test_parse_free_agents_bye_week_empty_string(self):
        """Test handling empty string bye week value."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Test Player"},
                                            "display_position": "DEF",
                                            "editorial_team_abbr": "DAL",
                                        }
                                    ],
                                    {"bye_weeks": {"week": ""}},
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 1
        assert result[0]["bye"] is None

    def test_parse_free_agents_bye_weeks_not_dict(self):
        """Test handling when bye_weeks is not a dictionary."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Test Player"},
                                            "display_position": "RB",
                                            "editorial_team_abbr": "ATL",
                                        }
                                    ],
                                    {"bye_weeks": "7"},  # String instead of dict
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 1
        assert result[0]["bye"] is None

    def test_parse_free_agents_multiple_players_mixed_bye_data(self):
        """Test parsing multiple players with mixed bye week data."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Player With Bye"},
                                            "display_position": "QB",
                                            "editorial_team_abbr": "KC",
                                        }
                                    ],
                                    {"bye_weeks": {"week": "7"}},
                                ]
                            },
                            "1": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Player No Bye"},
                                            "display_position": "RB",
                                            "editorial_team_abbr": "BUF",
                                        }
                                    ],
                                    {"ownership": {"ownership_percentage": 80}},
                                ]
                            },
                            "2": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Player Invalid Bye"},
                                            "display_position": "WR",
                                            "editorial_team_abbr": "MIA",
                                        }
                                    ],
                                    {"bye_weeks": {"week": "99"}},
                                ]
                            },
                            "count": 3,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert len(result) == 3
        assert result[0]["bye"] == 7
        assert result[1]["bye"] is None
        assert result[2]["bye"] is None


class TestPlayerEnhancementByeWeeks:
    """Test bye week handling in player enhancement service."""

    @pytest.mark.asyncio
    async def test_enhance_player_on_bye_week(self):
        """Test player enhancement when player is on bye."""
        # Mock player object
        player = MagicMock()
        player.name = "Test Player"
        player.bye = 7
        player.sleeper_id = "test_id"

        # Mock Sleeper API
        mock_sleeper_api = MagicMock()

        result = await enhance_player_with_context(
            player=player,
            current_week=7,
            season=2025,
            sleeper_api=mock_sleeper_api,
        )

        assert result.on_bye is True
        assert result.adjusted_projection == 0.0
        assert result.recommendation_override == "BYE WEEK - DO NOT START"
        assert "ON_BYE" in result.performance_flags
        assert "Week 7" in result.context_message

    @pytest.mark.asyncio
    async def test_enhance_player_not_on_bye(self):
        """Test player enhancement when player is not on bye."""
        player = MagicMock()
        player.name = "Test Player"
        player.bye = 7
        player.sleeper_id = "test_id"

        mock_sleeper_api = MagicMock()

        result = await enhance_player_with_context(
            player=player,
            current_week=5,
            season=2025,
            sleeper_api=mock_sleeper_api,
        )

        assert result.on_bye is False
        assert result.adjusted_projection != 0.0 or result.adjusted_projection is None
        assert "ON_BYE" not in result.performance_flags

    @pytest.mark.asyncio
    async def test_enhance_player_none_bye_value(self):
        """Test enhancement when bye week is None."""
        player = MagicMock()
        player.name = "Test Player"
        player.bye = None
        player.sleeper_id = "test_id"

        mock_sleeper_api = MagicMock()

        result = await enhance_player_with_context(
            player=player,
            current_week=7,
            season=2025,
            sleeper_api=mock_sleeper_api,
        )

        assert result.on_bye is False
        assert "ON_BYE" not in result.performance_flags

    @pytest.mark.asyncio
    async def test_enhance_player_invalid_bye_string(self):
        """Test enhancement with invalid bye week string."""
        player = MagicMock()
        player.name = "Test Player"
        player.bye = "N/A"
        player.sleeper_id = "test_id"

        mock_sleeper_api = MagicMock()

        result = await enhance_player_with_context(
            player=player,
            current_week=7,
            season=2025,
            sleeper_api=mock_sleeper_api,
        )

        assert result.on_bye is False
        assert "ON_BYE" not in result.performance_flags


class TestMainFunctionsByeWeeks:
    """Test bye week handling in main fantasy_football_multi_league.py functions."""

    @pytest.mark.asyncio
    async def test_get_waiver_wire_players_bye_week_extraction(self):
        """Test that get_waiver_wire_players correctly extracts and validates bye weeks.
        
        Invalid or missing current-season API data stays unknown.
        """
        from fantasy_football_multi_league import get_waiver_wire_players
        
        mock_response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Valid Bye Player"},
                                            "display_position": "RB",
                                            "editorial_team_abbr": "KC",
                                            "player_key": "461.p.12345",
                                        }
                                    ],
                                    {"bye_weeks": {"week": "7"}},
                                ]
                            },
                            "1": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Invalid Bye Player"},
                                            "display_position": "WR",
                                            "editorial_team_abbr": "BUF",
                                            "player_key": "461.p.67890",
                                        }
                                    ],
                                    {"bye_weeks": {"week": "99"}},
                                ]
                            },
                            "2": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "No Bye Player"},
                                            "display_position": "QB",
                                            "editorial_team_abbr": "MIA",
                                            "player_key": "461.p.11111",
                                        }
                                    ],
                                ]
                            },
                            "count": 3,
                        }
                    },
                ]
            }
        }

        with patch("fantasy_football_multi_league.yahoo_api_call", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response
            
            result = await get_waiver_wire_players(
                league_key="461.l.61410",
                position="all",
                sort="rank",
                count=30
            )

            assert len(result) == 3
            # Current-season API data wins; stale fallback data is not guessed.
            assert result[0]["bye"] == 7  # KC uses valid API data
            assert result[1]["bye"] is None  # Invalid API value
            assert result[2]["bye"] is None  # No API value

    @pytest.mark.asyncio
    async def test_get_draft_rankings_bye_week_validation(self):
        """Test that get_draft_rankings validates bye weeks correctly.
        
        Invalid current-season API data stays unknown.
        """
        from fantasy_football_multi_league import get_draft_rankings
        
        mock_response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Player 1"},
                                            "display_position": "RB",
                                            "editorial_team_abbr": "KC",
                                        }
                                    ],
                                    {"bye_weeks": {"week": 10}},
                                ]
                            },
                            "1": {
                                "player": [
                                    [
                                        {
                                            "name": {"full": "Player 2"},
                                            "display_position": "WR",
                                            "editorial_team_abbr": "BUF",
                                        }
                                    ],
                                    {"bye_weeks": {"week": "0"}},  # Invalid
                                ]
                            },
                            "count": 2,
                        }
                    },
                ]
            }
        }

        with patch("fantasy_football_multi_league.yahoo_api_call", new_callable=AsyncMock) as mock_api:
            with patch("fantasy_football_multi_league.discover_leagues", new_callable=AsyncMock) as mock_discover:
                mock_api.return_value = mock_response
                mock_discover.return_value = {"461.l.61410": {"name": "Test League"}}
                
                result = await get_draft_rankings(
                    league_key="461.l.61410",
                    position="all",
                    count=50
                )

                assert len(result) == 2
                assert result[0]["bye"] == 10  # Valid API bye week used
                assert result[1]["bye"] is None  # Invalid API value is not guessed
