"""Unit tests for src/parsers/yahoo_parsers.py - Yahoo API response parsing."""

import pytest

from src.parsers.yahoo_parsers import parse_team_roster, parse_yahoo_free_agent_players


class TestParseTeamRoster:
    """Test team roster parsing from Yahoo API responses."""

    def test_parse_roster_basic(self, mock_yahoo_roster_response):
        """Test parsing a basic roster response."""
        result = parse_team_roster(mock_yahoo_roster_response)

        assert len(result) == 3
        assert result[0]["name"] == "Josh Allen"
        assert result[0]["position"] == "QB"
        assert result[0]["team"] == "BUF"
        assert result[0]["status"] == "OK"

        assert result[1]["name"] == "Christian McCaffrey"
        assert result[1]["status"] == "O"

        assert result[2]["name"] == "Cooper Kupp"
        assert result[2]["position"] == "WR"

    def test_parse_roster_empty_response(self):
        """Test parsing when response has no roster data."""
        empty_response = {"fantasy_content": {"team": []}}
        result = parse_team_roster(empty_response)
        assert result == []

    def test_parse_roster_malformed_response(self):
        """Test parsing with malformed response structure."""
        malformed_response = {"fantasy_content": {"team": [{"other_key": "data"}]}}
        result = parse_team_roster(malformed_response)
        assert result == []

    def test_parse_roster_missing_player_data(self):
        """Test parsing when player data is incomplete."""
        response = {
            "fantasy_content": {
                "team": [
                    [{"team_key": "461.l.61410.t.1"}],
                    {
                        "roster": {
                            "0": {
                                "players": {
                                    "0": {
                                        "player": [
                                            [
                                                {
                                                    "name": {"full": "Incomplete Player"},
                                                    # Missing other fields
                                                }
                                            ]
                                        ]
                                    },
                                    "count": 1,
                                }
                            }
                        }
                    },
                ]
            }
        }
        result = parse_team_roster(response)
        assert len(result) == 1
        assert result[0]["name"] == "Incomplete Player"
        assert result[0]["status"] == "OK"  # Default status

    def test_parse_roster_with_selected_position(self):
        """Test that selected_position takes precedence over display_position."""
        response = {
            "fantasy_content": {
                "team": [
                    [{"team_key": "461.l.61410.t.1"}],
                    {
                        "roster": {
                            "0": {
                                "players": {
                                    "0": {
                                        "player": [
                                            [
                                                {
                                                    "name": {"full": "Flex Player"},
                                                    "display_position": "RB",
                                                    "editorial_team_abbr": "KC",
                                                    "player_projected_points": {"total": "13.7"},
                                                }
                                            ],
                                            {"selected_position": [{"position": "FLEX"}]},
                                        ]
                                    },
                                    "count": 1,
                                }
                            }
                        }
                    },
                ]
            }
        }
        result = parse_team_roster(response)
        assert len(result) == 1
        assert result[0]["position"] == "FLEX"  # Should use selected_position
        assert result[0]["display_position"] == "RB"
        assert result[0]["yahoo_projection"] == 13.7

    def test_parse_roster_with_nested_team_structure(self):
        """Test parsing team abbreviation from nested structure."""
        response = {
            "fantasy_content": {
                "team": [
                    [{"team_key": "461.l.61410.t.1"}],
                    {
                        "roster": {
                            "0": {
                                "players": {
                                    "0": {
                                        "player": [
                                            [
                                                {
                                                    "name": {"full": "Nested Team Player"},
                                                    "display_position": "QB",
                                                    "team": {"abbr": "DEN"},
                                                }
                                            ]
                                        ]
                                    },
                                    "count": 1,
                                }
                            }
                        }
                    },
                ]
            }
        }
        result = parse_team_roster(response)
        assert len(result) == 1
        assert result[0]["team"] == "DEN"


class TestParseFreeAgentPlayers:
    """Test free agent/waiver wire player parsing."""

    def test_parse_free_agents_basic(self, mock_yahoo_free_agents_response):
        """Test parsing basic free agent response."""
        result = parse_yahoo_free_agent_players(mock_yahoo_free_agents_response)

        assert len(result) == 2

        # First player
        assert result[0]["name"] == "Available Player"
        assert result[0]["position"] == "RB"
        assert result[0]["team"] == "NYJ"
        assert result[0]["owned_pct"] == 45
        assert result[0]["weekly_change"] == 5

        # Second player (injured)
        assert result[1]["name"] == "Injured Player"
        assert result[1]["injury_status"] == "Q"
        assert result[1]["injury_detail"] == "Questionable"
        assert result[1]["bye"] == 7  # Bye week is now an int from fallback utility
        assert result[1]["weekly_change"] == -8

    def test_parse_free_agents_empty_response(self):
        """Test parsing when no free agents in response."""
        empty_response = {"fantasy_content": {"league": [[{"league_key": "461.l.61410"}]]}}
        result = parse_yahoo_free_agent_players(empty_response)
        assert result == []

    def test_parse_free_agents_missing_name(self):
        """Test that players without names are filtered out."""
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
                                            "player_key": "461.p.12345",
                                            # Missing name field
                                            "display_position": "RB",
                                        }
                                    ]
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert result == []

    def test_parse_free_agents_with_percent_owned(self):
        """Test parsing when percent_owned is at top level."""
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
                                            "editorial_team_abbr": "SF",
                                            "percent_owned": 87.5,
                                        }
                                    ]
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
        assert result[0]["owned_pct"] == 87.5

    def test_parse_free_agents_malformed_players_section(self):
        """Test handling of malformed players section."""
        response = {
            "fantasy_content": {
                "league": [
                    [{"league_key": "461.l.61410"}],
                    {
                        "players": {
                            "0": "not_a_dict",  # Malformed
                            "count": 1,
                        }
                    },
                ]
            }
        }
        result = parse_yahoo_free_agent_players(response)
        assert result == []

    def test_parse_free_agents_ownership_with_zero_values(self):
        """Test parsing ownership data with zero values."""
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
                                            "name": {"full": "Unowned Player"},
                                            "display_position": "K",
                                            "editorial_team_abbr": "TB",
                                        }
                                    ],
                                    {
                                        "ownership": {
                                            "ownership_percentage": 0,
                                            "weekly_change": 0,
                                        }
                                    },
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
        assert result[0]["owned_pct"] == 0
        assert result[0]["weekly_change"] == 0


def _team_metadata_roster(metadata):
    return {
        "fantasy_content": {
            "team": [
                {
                    "roster": {
                        "0": {
                            "players": {
                                "0": {
                                    "player": [
                                        [
                                            {"player_key": "461.p.123"},
                                            {"name": {"full": "Public Test Player"}},
                                            {"display_position": "WR"},
                                            *metadata,
                                        ],
                                        {"selected_position": {"position": "BN"}},
                                        {"player_points": {"total": "99"}},
                                    ]
                                },
                                "count": 1,
                            }
                        }
                    }
                }
            ]
        }
    }


@pytest.mark.parametrize(
    "metadata",
    [
        [{"editorial_team_full_name": "Buffalo Bills"}, {"editorial_team_abbr": "BUF"}],
        [{"editorial_team_abbr": "BUF"}, {"editorial_team_full_name": "Buffalo Bills"}],
        [{"editorial_team_full_name": "Buffalo Bills"}, {"team": {"abbr": "BUF"}}],
        [{"team": {"abbr": "BUF"}}, {"editorial_team_full_name": "Buffalo Bills"}],
        [{"editorial_team_full_name": "Buffalo Bills", "team": {"abbr": "BUF"}}],
        [{"team": {"name": "Buffalo Bills", "abbr": "BUF"}}],
    ],
)
def test_team_abbreviation_wins_across_flat_and_nested_metadata_order(metadata):
    player = parse_team_roster(_team_metadata_roster(metadata))[0]
    assert player["team"] == "BUF"
    assert player["player_key"] == "461.p.123"
    assert player["position"] == "BN"
    assert player["display_position"] == "WR"
    assert "yahoo_projection" not in player  # actual points never become forecasts


def test_team_full_name_without_abbreviation_remains_unknown_to_canonical_matcher():
    from src.services.nflverse_matchups import canonical_team

    player = parse_team_roster(
        _team_metadata_roster(
            [
                {"editorial_team_full_name": "Buffalo Bills"},
                {"editorial_team_abbr": " "},
            ]
        )
    )[0]
    assert player["team"] == "Buffalo Bills"
    assert canonical_team(player["team"]) is None


async def test_flat_yahoo_abbreviation_flows_into_optimizer_and_verified_game_binding():
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock

    from lineup_optimizer import LineupOptimizer
    from src.services.nflverse_matchups import (
        SCHEDULE_URL,
        ScheduleGame,
        SourceMetadata,
        WeeklyMatchupEvidenceService,
    )

    parsed = parse_team_roster(
        _team_metadata_roster(
            [
                {"editorial_team_full_name": "Buffalo Bills"},
                {"editorial_team_abbr": "BUF"},
            ]
        )
    )
    players = await LineupOptimizer().parse_yahoo_roster({"roster": parsed})
    assert len(players) == 1
    assert players[0].team == "BUF"
    assert players[0].player_key == "461.p.123"
    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    service = WeeklyMatchupEvidenceService()
    service._validated = AsyncMock(
        return_value=(
            [
                ScheduleGame("2026_09_BUF_MIA", 2026, 9, "MIA", "BUF", now + timedelta(days=2)),
            ],
            SourceMetadata(SCHEDULE_URL, "synthetic-trusted-fixture", now),
        )
    )
    rows = await service.get_game_bindings(
        [
            {"team": players[0].team, "opponent": "MIA"},
        ],
        season=2026,
        target_week=9,
        now=now,
    )
    assert rows[0]["available"]
    assert rows[0]["status"] == "matched"
    assert rows[0]["team"] == "BUF"
