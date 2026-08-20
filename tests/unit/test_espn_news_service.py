"""Offline tests for the ESPN NFL JSON news service."""

import json
from unittest.mock import Mock

import pytest

from src.services import espn_news_service
from src.services.espn_news_service import EspnNewsService


NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
RESPONSE = {
    "articles": [
        {
            "id": 1,
            "headline": "Josh Allen returns to practice",
            "description": "The Bills quarterback practiced without limitations.",
            "published": "2026-08-20T14:00:00Z",
            "byline": "ESPN staff",
            "premium": False,
            "links": {"web": {"href": "https://www.espn.com/nfl/story/1"}},
            "categories": [
                {
                    "id": 99999,
                    "type": "athlete",
                    "sportId": 28,
                    "athleteId": 3918298,
                    "description": "Josh Allen",
                    "athlete": {"id": 3918298, "description": "Josh Allen"},
                },
                {
                    "id": 88888,
                    "type": "team",
                    "sportId": 28,
                    "teamId": 2,
                    "description": "Buffalo Bills",
                    "team": {
                        "id": 2,
                        "description": "Buffalo Bills",
                        "abbreviation": "BUF",
                    },
                },
                {
                    "type": "team",
                    "sportId": 10,
                    "teamId": 10,
                    "description": "New York Yankees",
                },
            ],
        },
        {
            "id": 2,
            "headline": "Fantasy football draft guide",
            "description": "Rankings, tiers and analysis for draft season.",
            "published": "2026-08-20T13:00:00Z",
            "byline": "Fantasy staff",
            "premium": True,
            "links": {"web": {"href": "https://www.espn.com/fantasy/story/2"}},
            "categories": [{"type": "league", "description": "Fantasy NFL"}],
        },
    ]
}
PAYLOAD = json.dumps(RESPONSE).encode()


class FakeResponse:
    def __init__(self, payload=PAYLOAD, status=200, content_length=None):
        self.payload = payload
        self.status = status
        self.content_length = len(payload) if content_length is None else content_length
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def iter_chunked(self, _size):
        yield self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get(self, *_args, **_kwargs):
        return self.response


def install_response(monkeypatch, response):
    session_factory = Mock(side_effect=lambda *_args, **_kwargs: FakeSession(response))
    monkeypatch.setattr(espn_news_service.aiohttp, "ClientSession", session_factory)
    return session_factory


@pytest.mark.asyncio
async def test_get_nfl_news_parses_and_attributes_response(monkeypatch):
    install_response(monkeypatch, FakeResponse())

    result = await EspnNewsService().get_nfl_news()

    assert result["source"] == "ESPN NFL News API"
    assert result["source_url"] == NEWS_URL
    assert "Community-documented" in result["source_note"]
    assert result["cache_ttl_minutes"] == 10
    assert result["count"] == 2
    assert result["items"][0] == {
        "article_id": "1",
        "players": ["Josh Allen"],
        "athlete_refs": [
            {"name": "Josh Allen", "espn_athlete_id": "3918298"}
        ],
        "teams": ["Buffalo Bills"],
        "team_refs": [
            {
                "name": "Buffalo Bills",
                "espn_team_id": "2",
                "abbreviation": "BUF",
            }
        ],
        "headline": "Josh Allen returns to practice",
        "summary": "The Bills quarterback practiced without limitations.",
        "published_at": "2026-08-20T14:00:00Z",
        "url": "https://www.espn.com/nfl/story/1",
        "byline": "ESPN staff",
        "premium": False,
    }


@pytest.mark.asyncio
async def test_get_nfl_news_filters_by_structured_player(monkeypatch):
    install_response(monkeypatch, FakeResponse())

    result = await EspnNewsService().get_nfl_news(players=["jOsH aLlEn"])

    assert result["count"] == 1
    assert result["items"][0]["players"] == ["Josh Allen"]
    assert result["items"][0]["athlete_refs"][0]["espn_athlete_id"] == "3918298"
    assert result["items"][0]["teams"] == ["Buffalo Bills"]


@pytest.mark.asyncio
async def test_get_nfl_news_normalizes_player_punctuation(monkeypatch):
    response_data = json.loads(PAYLOAD)
    response_data["articles"][0]["categories"][0]["description"] = "A.J. Brown"
    response_data["articles"][0]["headline"] = "Brown returns to practice"
    install_response(monkeypatch, FakeResponse(payload=json.dumps(response_data).encode()))

    result = await EspnNewsService().get_nfl_news(players=["AJ Brown"])

    assert result["count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 11])
async def test_get_nfl_news_rejects_limit_outside_one_to_ten(limit):
    with pytest.raises(ValueError, match="1.*10"):
        await EspnNewsService().get_nfl_news(limit=limit)


@pytest.mark.asyncio
async def test_get_nfl_news_reuses_cached_response(monkeypatch):
    session_factory = install_response(monkeypatch, FakeResponse())
    service = EspnNewsService()

    await service.get_nfl_news(limit=1)
    await service.get_nfl_news(limit=2)

    assert session_factory.call_count == 1


@pytest.mark.asyncio
async def test_get_nfl_news_sorts_newest_first_before_limiting(monkeypatch):
    response_data = json.loads(PAYLOAD)
    response_data["articles"][1]["published"] = "2026-08-20T15:00:00Z"
    install_response(monkeypatch, FakeResponse(payload=json.dumps(response_data).encode()))

    result = await EspnNewsService().get_nfl_news(limit=1)

    assert result["items"][0]["headline"] == "Fantasy football draft guide"


@pytest.mark.asyncio
async def test_get_nfl_news_deduplicates_article_ids(monkeypatch):
    response_data = json.loads(PAYLOAD)
    response_data["articles"].append(dict(response_data["articles"][0]))
    install_response(monkeypatch, FakeResponse(payload=json.dumps(response_data).encode()))

    result = await EspnNewsService().get_nfl_news(limit=10)

    assert result["count"] == 2


@pytest.mark.asyncio
async def test_get_nfl_news_reports_http_failure(monkeypatch):
    install_response(monkeypatch, FakeResponse(status=503))

    with pytest.raises(RuntimeError, match="503"):
        await EspnNewsService().get_nfl_news()


@pytest.mark.asyncio
async def test_get_nfl_news_rejects_malformed_json(monkeypatch):
    install_response(monkeypatch, FakeResponse(payload=b"{"))

    with pytest.raises(RuntimeError, match="malformed JSON"):
        await EspnNewsService().get_nfl_news()


@pytest.mark.asyncio
async def test_get_nfl_news_rejects_invalid_response(monkeypatch):
    install_response(monkeypatch, FakeResponse(payload=b"{}"))

    with pytest.raises(RuntimeError, match="invalid NFL news response"):
        await EspnNewsService().get_nfl_news()


@pytest.mark.asyncio
async def test_get_nfl_news_rejects_oversized_payload(monkeypatch):
    install_response(
        monkeypatch,
        FakeResponse(payload=b"{}", content_length=1024 * 1024 + 1),
    )

    with pytest.raises(RuntimeError, match="too large"):
        await EspnNewsService().get_nfl_news()


@pytest.mark.asyncio
async def test_get_nfl_news_disables_redirects(monkeypatch):
    session = FakeSession(FakeResponse(status=302))
    session.get = Mock(wraps=session.get)
    monkeypatch.setattr(
        espn_news_service.aiohttp,
        "ClientSession",
        Mock(return_value=session),
    )

    with pytest.raises(RuntimeError, match="302"):
        await EspnNewsService().get_nfl_news()

    assert session.get.call_args.kwargs["allow_redirects"] is False
    assert session.get.call_args.kwargs["params"] == {"limit": 50}
