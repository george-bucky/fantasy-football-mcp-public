"""Integration tests for MCP tool flows - end-to-end testing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLeagueToolsIntegration:
    """Integration tests for league-related MCP tools."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_get_leagues_full_flow(self, mock_env_vars, mock_yahoo_league_response):
        """Test full flow of getting leagues."""
        from src.handlers.league_handlers import handle_ff_get_leagues

        # Mock the discover_leagues function
        mock_leagues = {
            "461.l.900001": {
                "key": "461.l.900001",
                "name": "Example League 1",
                "num_teams": 10,
                "current_week": 1,
                "scoring_type": "head2head",
            }
        }

        with patch(
            "src.handlers.league_handlers.discover_leagues", AsyncMock(return_value=mock_leagues)
        ):
            result = await handle_ff_get_leagues({})

            assert "total_leagues" in result
            assert result["total_leagues"] == 1
            assert "leagues" in result
            assert len(result["leagues"]) == 1
            assert result["leagues"][0]["name"] == "Example League 1"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_get_league_info_full_flow(self, mock_env_vars, mock_yahoo_league_response):
        """Test full flow of getting league info."""
        from src.handlers.league_handlers import handle_ff_get_league_info

        mock_leagues = {
            "461.l.900001": {
                "key": "461.l.900001",
                "name": "Example League 1",
                "season": "2025",
                "num_teams": 10,
                "current_week": 1,
                "scoring_type": "head2head",
                "is_finished": False,
            }
        }

        mock_team_info = {
            "team_name": "BreesusChr1st",
            "team_key": "461.l.900001.t.1",
            "draft_position": 3,
        }

        with (
            patch(
                "src.handlers.league_handlers.discover_leagues",
                AsyncMock(return_value=mock_leagues),
            ),
            patch(
                "src.handlers.league_handlers.get_user_team_info",
                AsyncMock(return_value=mock_team_info),
            ),
            patch(
                "src.handlers.league_handlers.yahoo_api_call",
                AsyncMock(return_value={}),
            ),
        ):
            result = await handle_ff_get_league_info({"league_key": "461.l.900001"})

            assert result["league"] == "Example League 1"
            assert result["key"] == "461.l.900001"
            assert result["season"] == "2025"
            assert result["your_team"]["name"] == "BreesusChr1st"


class TestRosterToolsIntegration:
    """Integration tests for roster-related tools."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_parse_roster_to_optimizer_flow(self, mock_yahoo_roster_response):
        """Test flow from roster parsing to lineup optimizer."""
        from lineup_optimizer import LineupOptimizer
        from src.parsers.yahoo_parsers import parse_team_roster

        # Step 1: Parse Yahoo roster
        parsed_roster = parse_team_roster(mock_yahoo_roster_response)
        assert len(parsed_roster) == 3

        # Step 2: Feed to optimizer
        optimizer = LineupOptimizer()
        roster_payload = {"roster": parsed_roster}
        players = await optimizer.parse_yahoo_roster(roster_payload)

        assert len(players) == 3
        assert all(player.is_valid() for player in players)
        assert players[0].name == "Josh Allen"
        assert players[0].position == "QB"


class TestAdminToolsIntegration:
    """Integration tests for admin tools."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_token_refresh_and_api_status_flow(
        self, mock_env_vars, mock_rate_limiter, mock_response_cache
    ):
        """Test flow of refreshing token and checking API status."""
        from src.handlers.admin_handlers import (
            handle_ff_get_api_status,
            handle_ff_refresh_token,
        )

        # Step 1: Refresh token
        mock_refresh = AsyncMock(
            return_value={
                "status": "success",
                "expires_in": 3600,
                "expires_in_hours": 1.0,
            }
        )

        with patch("src.handlers.admin_handlers.refresh_yahoo_token", mock_refresh):
            refresh_result = await handle_ff_refresh_token({})
            assert refresh_result["status"] == "success"

        # Step 2: Check API status after refresh
        with (
            patch("src.handlers.admin_handlers.rate_limiter", mock_rate_limiter),
            patch("src.handlers.admin_handlers.response_cache", mock_response_cache),
        ):
            status_result = await handle_ff_get_api_status({})

            assert "rate_limit" in status_result
            assert "cache" in status_result
            assert status_result["rate_limit"]["requests_remaining"] > 0


class TestDataTransformationPipeline:
    """Integration tests for data transformation pipeline."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_yahoo_response_to_player_objects(
        self, mock_yahoo_roster_response, mock_yahoo_free_agents_response
    ):
        """Test complete pipeline from Yahoo API to Player objects."""
        from lineup_optimizer import LineupOptimizer
        from src.parsers.yahoo_parsers import (
            parse_team_roster,
            parse_yahoo_free_agent_players,
        )

        # Step 1: Parse roster
        roster = parse_team_roster(mock_yahoo_roster_response)
        assert len(roster) == 3

        # Step 2: Parse free agents
        free_agents = parse_yahoo_free_agent_players(mock_yahoo_free_agents_response)
        assert len(free_agents) == 2

        # Step 3: Convert to Player objects
        optimizer = LineupOptimizer()
        roster_players = await optimizer.parse_yahoo_roster({"roster": roster})
        assert len(roster_players) == 3
        assert all(isinstance(p.yahoo_projection, float) for p in roster_players)

        # Verify player attributes are properly set
        qb = next((p for p in roster_players if p.position == "QB"), None)
        assert qb is not None
        assert qb.name == "Josh Allen"
        assert qb.team == "BUF"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_error_recovery_in_pipeline(self):
        """Test that pipeline gracefully handles errors."""
        from lineup_optimizer import LineupOptimizer
        from src.parsers.yahoo_parsers import parse_team_roster

        # Malformed data at various stages
        malformed_responses = [
            {},  # Empty
            {"fantasy_content": {}},  # Missing team
            {"fantasy_content": {"team": "not_a_list"}},  # Wrong type
        ]

        optimizer = LineupOptimizer()

        for response in malformed_responses:
            # Should not raise, just return empty
            parsed = parse_team_roster(response)
            assert parsed == []

            # Optimizer should handle empty roster
            players = await optimizer.parse_yahoo_roster({"roster": parsed})
            assert players == []


class TestCachingBehavior:
    """Integration tests for caching behavior."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_api_call_with_cache_hit(
        self, mock_env_vars, mock_rate_limiter, mock_response_cache
    ):
        """Test that cache hits avoid API calls."""
        from src.api.yahoo_client import yahoo_api_call

        cached_data = {"cached": "response"}
        mock_response_cache.get = AsyncMock(return_value=cached_data)

        with (
            patch("src.api.yahoo_client.rate_limiter", mock_rate_limiter),
            patch("src.api.yahoo_client.response_cache", mock_response_cache),
        ):
            result = await yahoo_api_call("test/endpoint")

            assert result == cached_data
            # Verify rate limiter was NOT called (cache hit)
            mock_rate_limiter.acquire.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_api_call_with_cache_miss(
        self, mock_env_vars, mock_rate_limiter, mock_response_cache
    ):
        """Test that cache misses trigger API calls."""
        from src.api.yahoo_client import yahoo_api_call

        mock_response_cache.get = AsyncMock(return_value=None)  # Cache miss

        # Create proper async context manager classes
        class MockResponse:
            def __init__(self):
                self.status = 200

            async def json(self):
                return {"api": "data"}

        class MockGetContext:
            async def __aenter__(self):
                return MockResponse()

            async def __aexit__(self, *args):
                return None

        class MockSession:
            def get(self, *args, **kwargs):
                return MockGetContext()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

        with (
            patch("src.api.yahoo_client.rate_limiter", mock_rate_limiter),
            patch("src.api.yahoo_client.response_cache", mock_response_cache),
            patch("aiohttp.TCPConnector"),
            patch("aiohttp.ClientSession", return_value=MockSession()),
        ):
            result = await yahoo_api_call("test/endpoint")

            assert result == {"api": "data"}
            # Verify rate limiter WAS called (cache miss)
            mock_rate_limiter.acquire.assert_called_once()
            # Verify cache was updated
            mock_response_cache.set.assert_called_once()
