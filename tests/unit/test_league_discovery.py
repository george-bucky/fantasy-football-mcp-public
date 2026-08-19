"""Tests for current-season Yahoo league discovery."""

import pytest

import fantasy_football_multi_league as server


def yahoo_league_response(*, season="2025"):
    league = {
        "league_key": "461.l.61410",
        "league_id": "61410",
        "name": "Test League",
        "num_teams": 10,
    }
    if season is not None:
        league["season"] = season

    return {
        "fantasy_content": {
            "users": {
                "0": {
                    "user": [
                        {
                            "games": {
                                "0": {
                                    "game": [
                                        {
                                            "leagues": {
                                                "0": {"league": [league]},
                                                "count": 1,
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            }
        }
    }


@pytest.mark.asyncio
async def test_discover_leagues_uses_current_nfl_alias(monkeypatch):
    requested_endpoints = []

    async def fake_yahoo_api_call(endpoint):
        requested_endpoints.append(endpoint)
        return yahoo_league_response()

    monkeypatch.setattr(server, "yahoo_api_call", fake_yahoo_api_call)
    monkeypatch.setattr(server, "LEAGUES_CACHE", {})

    leagues = await server.discover_leagues()

    assert requested_endpoints == ["users;use_login=1/games;game_keys=nfl/leagues"]
    assert leagues["461.l.61410"]["season"] == "2025"


@pytest.mark.asyncio
async def test_discover_leagues_does_not_invent_missing_season(monkeypatch):
    async def fake_yahoo_api_call(_endpoint):
        return yahoo_league_response(season=None)

    monkeypatch.setattr(server, "yahoo_api_call", fake_yahoo_api_call)
    monkeypatch.setattr(server, "LEAGUES_CACHE", {})

    leagues = await server.discover_leagues()

    assert leagues["461.l.61410"]["season"] is None
