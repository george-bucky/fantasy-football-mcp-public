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


@pytest.mark.asyncio
async def test_real_projection_is_labeled_with_sleeper_api_provenance(monkeypatch):
    api = SleeperAPI()
    monkeypatch.setattr(
        api,
        "_make_request",
        AsyncMock(return_value={"1234": {"pts": 18.5}}),
    )
    monkeypatch.setattr(
        api,
        "get_all_players",
        AsyncMock(
            return_value={
                "1234": {
                    "first_name": "Test",
                    "last_name": "Quarterback",
                    "team": "BUF",
                    "position": "QB",
                }
            }
        ),
    )

    projections = await api.get_projections(2026, 1)

    assert projections["1234"]["projection_source"] == "sleeper_api"
