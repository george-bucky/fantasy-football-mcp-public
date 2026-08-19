"""Unit tests for credential-free Sleeper helpers."""

from unittest.mock import AsyncMock

import pytest

from sleeper_api import SleeperAPI


@pytest.mark.asyncio
async def test_position_rankings_preserve_sleeper_player_id(monkeypatch):
    api = SleeperAPI()
    monkeypatch.setattr(
        api,
        "get_all_players",
        AsyncMock(
            return_value={
                "1234": {
                    "player_id": "1234",
                    "full_name": "Test Quarterback",
                    "team": "BUF",
                    "position": "QB",
                    "active": True,
                    "search_rank": 1,
                }
            }
        ),
    )

    rankings = await api.get_position_rankings("QB")

    assert rankings[0]["player_id"] == "1234"
