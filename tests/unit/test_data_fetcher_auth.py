"""Tests for yfpy client construction without making network calls."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.agents.data_fetcher import DataFetcherAgent, PROJECT_ROOT


@pytest.mark.asyncio
async def test_yfpy_receives_env_directory_and_supported_credentials():
    agent = object.__new__(DataFetcherAgent)
    agent.settings = SimpleNamespace(
        yahoo_client_id="test-client-id",
        yahoo_client_secret="test-client-secret",
    )

    with patch("src.agents.data_fetcher.YahooFantasySportsQuery") as query_class:
        await agent._initialize_yahoo_client()

    query_class.assert_called_once_with(
        league_id=None,
        game_code="nfl",
        game_id=None,
        yahoo_consumer_key="test-client-id",
        yahoo_consumer_secret="test-client-secret",
        env_file_location=PROJECT_ROOT,
    )
