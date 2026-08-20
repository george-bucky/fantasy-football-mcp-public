"""Tests for batching attributed news evidence for decisions."""

from unittest.mock import AsyncMock, patch

import pytest

from src.services.decision_news_service import get_decision_news_context


@pytest.mark.asyncio
async def test_decision_news_batches_sources_and_preserves_espn_ids():
    espn = {
        "status": "success",
        "source": "ESPN NFL News API",
        "items": [
            {
                "headline": "Josh Allen returns",
                "summary": "Allen practiced fully.",
                "players": ["Josh Allen"],
                "athlete_refs": [
                    {"name": "Josh Allen", "espn_athlete_id": "3918298"}
                ],
                "team_refs": [
                    {"name": "Buffalo Bills", "espn_team_id": "2"}
                ],
            }
        ],
    }
    rotowire = {
        "status": "success",
        "source": "RotoWire NFL RSS",
        "items": [
            {"player": "Josh Allen", "headline": "Full practice", "summary": ""}
        ],
    }
    with (
        patch(
            "src.services.decision_news_service.get_espn_nfl_news_batch",
            AsyncMock(return_value=espn),
        ) as get_espn,
        patch(
            "src.services.decision_news_service.get_rotowire_player_news_batch",
            AsyncMock(return_value=rotowire),
        ) as get_rotowire,
    ):
        result = await get_decision_news_context(["Josh Allen", "Other Player"])

    get_espn.assert_awaited_once_with(
        players=["Josh Allen", "Other Player"], limit=50
    )
    get_rotowire.assert_awaited_once_with(
        players=["Josh Allen", "Other Player"], limit=50
    )
    context = result["by_player"]["Josh Allen"]
    assert context["espn_athlete_refs"] == [
        {"name": "Josh Allen", "espn_athlete_id": "3918298"}
    ]
    assert context["espn"][0]["source"] == "ESPN NFL News API"
    assert context["espn"][0]["team_refs"] == [
        {"name": "Buffalo Bills", "espn_team_id": "2"}
    ]
    assert context["rotowire"][0]["source"] == "RotoWire NFL RSS"
    assert result["by_player"]["Other Player"]["espn"] == []


@pytest.mark.asyncio
async def test_decision_news_fails_sources_independently():
    with (
        patch(
            "src.services.decision_news_service.get_espn_nfl_news_batch",
            AsyncMock(side_effect=RuntimeError("offline")),
        ),
        patch(
            "src.services.decision_news_service.get_rotowire_player_news_batch",
            AsyncMock(
                return_value={
                    "status": "success",
                    "source": "RotoWire NFL RSS",
                    "items": [],
                }
            ),
        ),
    ):
        result = await get_decision_news_context(["Josh Allen"])

    assert result["sources"] == ["RotoWire NFL RSS"]
    assert result["by_player"]["Josh Allen"] == {
        "espn": [],
        "rotowire": [],
        "espn_athlete_refs": [],
    }
    assert result["warnings"] == ["ESPN news unavailable: offline"]


@pytest.mark.asyncio
async def test_decision_news_applies_per_player_limit_after_batch_fetch():
    espn = {
        "status": "success",
        "source": "ESPN NFL News API",
        "items": [
            {
                "headline": headline,
                "summary": "",
                "players": [player],
                "athlete_refs": [],
                "team_refs": [],
            }
            for player, headline in [
                ("Player One", "One story 1"),
                ("Player One", "One story 2"),
                ("Player One", "One story 3"),
                ("Player Two", "Two story 1"),
            ]
        ],
    }
    with (
        patch(
            "src.services.decision_news_service.get_espn_nfl_news_batch",
            AsyncMock(return_value=espn),
        ),
        patch(
            "src.services.decision_news_service.get_rotowire_player_news_batch",
            AsyncMock(
                return_value={
                    "status": "success",
                    "source": "RotoWire NFL RSS",
                    "items": [],
                }
            ),
        ),
    ):
        result = await get_decision_news_context(
            ["Player One", "Player Two"], per_player_limit=1
        )

    assert len(result["by_player"]["Player One"]["espn"]) == 1
    assert len(result["by_player"]["Player Two"]["espn"]) == 1
