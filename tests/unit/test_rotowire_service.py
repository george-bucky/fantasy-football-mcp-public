"""Offline tests for the RotoWire NFL RSS service."""

from unittest.mock import Mock

import pytest

from src.services import rotowire_service
from src.services.rotowire_service import RotowireNewsService


FEED_URL = "https://www.rotowire.com/rss/news.php?sport=NFL"
RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>RotoWire NFL News</title>
    <ttl>10</ttl>
    <item>
      <title>Josh Allen: Full participant Wednesday</title>
      <description>Allen practiced without limitations.</description>
      <link>https://www.rotowire.com/football/player/josh-allen-12483</link>
      <guid>josh-allen-1</guid>
      <pubDate>Wed, 19 Aug 2026 16:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Lamar Jackson: Returns to practice</title>
      <description>Jackson returned after a rest day.</description>
      <link>https://www.rotowire.com/football/player/lamar-jackson-12561</link>
      <guid>lamar-jackson-1</guid>
      <pubDate>Wed, 19 Aug 2026 15:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class FakeResponse:
    """Small aiohttp response double supporting common read styles."""

    def __init__(self, payload=RSS, status=200, content_length=None):
        self.payload = payload
        self.status = status
        self.reason = "Service Unavailable" if status >= 400 else "OK"
        self.content_length = len(payload) if content_length is None else content_length
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def __await__(self):
        async def return_self():
            return self

        return return_self().__await__()

    async def read(self):
        return self.payload

    async def text(self):
        return self.payload.decode("utf-8")

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
    monkeypatch.setattr(rotowire_service.aiohttp, "ClientSession", session_factory)
    return session_factory


@pytest.mark.asyncio
async def test_get_player_news_parses_and_attributes_feed(monkeypatch):
    install_response(monkeypatch, FakeResponse())

    result = await RotowireNewsService().get_player_news()

    assert result["source"] == "RotoWire NFL RSS"
    assert result["source_url"] == FEED_URL
    assert result["feed_ttl_minutes"] == 10
    assert result["count"] == 2
    assert result["items"][0] == {
        "player": "Josh Allen",
        "headline": "Full participant Wednesday",
        "summary": "Allen practiced without limitations.",
        "published_at": "Wed, 19 Aug 2026 16:00:00 GMT",
        "url": "https://www.rotowire.com/football/player/josh-allen-12483",
    }


@pytest.mark.asyncio
async def test_get_player_news_filters_players_case_insensitively(monkeypatch):
    install_response(monkeypatch, FakeResponse())

    result = await RotowireNewsService().get_player_news(players=["lAmAr JaCkSoN"])

    assert result["count"] == 1
    assert result["items"][0]["player"] == "Lamar Jackson"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 6])
async def test_get_player_news_rejects_limit_outside_one_to_five(limit):
    with pytest.raises(ValueError, match="1.*5"):
        await RotowireNewsService().get_player_news(limit=limit)


@pytest.mark.asyncio
async def test_get_player_news_reuses_cached_feed(monkeypatch):
    session_factory = install_response(monkeypatch, FakeResponse())
    service = RotowireNewsService()

    first = await service.get_player_news(limit=1)
    second = await service.get_player_news(limit=2)

    assert first["count"] == 1
    assert second["count"] == 2
    assert session_factory.call_count == 1


@pytest.mark.asyncio
async def test_get_player_news_reports_http_failure(monkeypatch):
    install_response(monkeypatch, FakeResponse(status=503))

    with pytest.raises(RuntimeError, match="503"):
        await RotowireNewsService().get_player_news()


@pytest.mark.asyncio
async def test_get_player_news_rejects_malformed_xml(monkeypatch):
    install_response(monkeypatch, FakeResponse(payload=b"<rss><channel>"))

    with pytest.raises(RuntimeError, match="(?i)(malformed|invalid|parse)"):
        await RotowireNewsService().get_player_news()


@pytest.mark.asyncio
async def test_get_player_news_rejects_oversized_payload(monkeypatch):
    oversized = b"x" * (1024 * 1024 + 1)
    install_response(monkeypatch, FakeResponse(payload=oversized))

    with pytest.raises(RuntimeError, match="(?i)(too large|size|limit)"):
        await RotowireNewsService().get_player_news()


@pytest.mark.asyncio
async def test_get_player_news_rejects_chunked_oversize_without_length(monkeypatch):
    response = FakeResponse(payload=b"x" * (1024 * 1024 + 1))
    response.content_length = None
    install_response(monkeypatch, response)

    with pytest.raises(RuntimeError, match="(?i)(too large|size|limit)"):
        await RotowireNewsService().get_player_news()


@pytest.mark.asyncio
async def test_get_player_news_disables_redirects(monkeypatch):
    session = FakeSession(FakeResponse(status=302))
    session.get = Mock(wraps=session.get)
    monkeypatch.setattr(
        rotowire_service.aiohttp,
        "ClientSession",
        Mock(return_value=session),
    )

    with pytest.raises(RuntimeError, match="302"):
        await RotowireNewsService().get_player_news()

    assert session.get.call_args.kwargs["allow_redirects"] is False
