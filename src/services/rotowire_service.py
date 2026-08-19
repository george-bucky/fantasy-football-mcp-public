"""Credential-free RotoWire NFL RSS news service."""

from __future__ import annotations

import asyncio
import html
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Sequence

import aiohttp


FEED_URL = "https://www.rotowire.com/rss/news.php?sport=NFL"
SOURCE_NAME = "RotoWire NFL RSS"
DEFAULT_TTL_MINUTES = 10
MAX_RESPONSE_BYTES = 1024 * 1024
_HTML_TAG = re.compile(r"<[^>]+>")


class RotowireNewsService:
    """Fetch and filter the public RotoWire NFL RSS feed."""

    def __init__(self) -> None:
        self._cached_items: list[dict[str, str | None]] | None = None
        self._cached_at = 0.0
        self._feed_ttl_minutes = DEFAULT_TTL_MINUTES
        self._lock = asyncio.Lock()

    @staticmethod
    def _clean_text(value: str | None) -> str:
        if not value:
            return ""
        without_tags = _HTML_TAG.sub(" ", value)
        return " ".join(html.unescape(without_tags).split())

    @classmethod
    def _parse_feed(
        cls, payload: bytes
    ) -> tuple[list[dict[str, str | None]], int]:
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise RuntimeError("RotoWire returned malformed RSS XML") from exc

        channel = root.find("channel")
        if channel is None:
            raise RuntimeError("RotoWire returned an invalid RSS feed")

        ttl_text = cls._clean_text(channel.findtext("ttl"))
        try:
            ttl_minutes = max(1, int(ttl_text)) if ttl_text else DEFAULT_TTL_MINUTES
        except ValueError:
            ttl_minutes = DEFAULT_TTL_MINUTES

        items: list[dict[str, str | None]] = []
        for item in channel.findall("item"):
            title = cls._clean_text(item.findtext("title"))
            if not title:
                continue

            player, separator, headline = title.partition(":")
            if not separator:
                player = ""
                headline = title

            items.append(
                {
                    "player": player.strip() or None,
                    "headline": headline.strip(),
                    "summary": cls._clean_text(item.findtext("description")),
                    "published_at": cls._clean_text(item.findtext("pubDate")),
                    "url": cls._clean_text(item.findtext("link")),
                }
            )

        return items, ttl_minutes

    async def _fetch_items(self) -> list[dict[str, str | None]]:
        now = time.monotonic()
        cache_seconds = self._feed_ttl_minutes * 60
        if self._cached_items is not None and now - self._cached_at < cache_seconds:
            return self._cached_items

        async with self._lock:
            now = time.monotonic()
            cache_seconds = self._feed_ttl_minutes * 60
            if self._cached_items is not None and now - self._cached_at < cache_seconds:
                return self._cached_items

            timeout = aiohttp.ClientTimeout(total=15)
            headers = {
                "User-Agent": "fantasy-football-mcp/1.0 (personal RSS reader)"
            }
            try:
                async with aiohttp.ClientSession(
                    timeout=timeout, headers=headers
                ) as session:
                    async with session.get(
                        FEED_URL, allow_redirects=False
                    ) as response:
                        if response.status != 200:
                            raise RuntimeError(
                                f"RotoWire RSS request failed with HTTP {response.status}"
                            )
                        if (
                            response.content_length is not None
                            and response.content_length > MAX_RESPONSE_BYTES
                        ):
                            raise RuntimeError("RotoWire RSS response is too large")
                        payload_parts: list[bytes] = []
                        payload_size = 0
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            payload_size += len(chunk)
                            if payload_size > MAX_RESPONSE_BYTES:
                                raise RuntimeError("RotoWire RSS response is too large")
                            payload_parts.append(chunk)
                        payload = b"".join(payload_parts)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise RuntimeError("RotoWire RSS request failed") from exc

            if len(payload) > MAX_RESPONSE_BYTES:
                raise RuntimeError("RotoWire RSS response is too large")

            items, ttl_minutes = self._parse_feed(payload)
            self._cached_items = items
            self._cached_at = time.monotonic()
            self._feed_ttl_minutes = ttl_minutes
            return items

    async def get_player_news(
        self, players: Sequence[str] | None = None, limit: int = 5
    ) -> dict[str, Any]:
        """Return up to five recent feed items, optionally filtered by player."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
            raise ValueError("limit must be an integer between 1 and 5")

        if players is not None and (
            isinstance(players, (str, bytes))
            or not all(isinstance(player, str) for player in players)
        ):
            raise ValueError("players must be a list of player names")

        items = await self._fetch_items()
        if players:
            requested = {player.strip().casefold() for player in players if player.strip()}
            items = [
                item
                for item in items
                if item["player"] and str(item["player"]).casefold() in requested
            ]

        selected = items[:limit]
        return {
            "status": "success",
            "source": SOURCE_NAME,
            "source_url": FEED_URL,
            "feed_ttl_minutes": self._feed_ttl_minutes,
            "count": len(selected),
            "items": selected,
        }


rotowire_news_service = RotowireNewsService()


async def get_rotowire_player_news(
    players: Sequence[str] | None = None, limit: int = 5
) -> dict[str, Any]:
    """Fetch player news through the shared in-memory service instance."""
    return await rotowire_news_service.get_player_news(players=players, limit=limit)
