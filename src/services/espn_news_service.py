"""Credential-free ESPN NFL JSON news service."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Sequence

import aiohttp


NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
SOURCE_NAME = "ESPN NFL News API"
SOURCE_NOTE = (
    "Community-documented ESPN JSON endpoint; not an official ESPN contract and may change."
)
DEFAULT_TTL_MINUTES = 10
MAX_RESPONSE_BYTES = 1024 * 1024
FETCH_LIMIT = 50


class EspnNewsService:
    """Fetch and filter ESPN's public NFL JSON response."""

    def __init__(self) -> None:
        self._cached_items: list[dict[str, Any]] | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _normalize_search(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    @staticmethod
    def _category_names(article: dict[str, Any], category_type: str) -> list[str]:
        names: list[str] = []
        for category in article.get("categories", []):
            if not isinstance(category, dict) or category.get("type") != category_type:
                continue
            if category.get("sportId") not in (None, 28, "28"):
                continue
            name = category.get("description")
            if isinstance(name, str) and name.strip() and name.strip() not in names:
                names.append(name.strip())
        return names

    @staticmethod
    def _category_refs(
        article: dict[str, Any], category_type: str
    ) -> list[dict[str, str]]:
        id_key = "athleteId" if category_type == "athlete" else "teamId"
        output_id_key = (
            "espn_athlete_id" if category_type == "athlete" else "espn_team_id"
        )
        refs: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for category in article.get("categories", []):
            if not isinstance(category, dict) or category.get("type") != category_type:
                continue
            if category.get("sportId") not in (None, 28, "28"):
                continue
            nested = category.get(category_type)
            nested = nested if isinstance(nested, dict) else {}
            raw_id = category.get(id_key) or nested.get("id")
            name = category.get("description") or nested.get("description")
            if raw_id in (None, "") or not isinstance(name, str) or not name.strip():
                continue
            normalized_id = str(raw_id)
            if normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)
            ref = {"name": name.strip(), output_id_key: normalized_id}
            if category_type == "team" and nested.get("abbreviation"):
                ref["abbreviation"] = str(nested["abbreviation"])
            refs.append(ref)
        return refs

    @staticmethod
    def _published_timestamp(item: dict[str, Any]) -> float:
        try:
            value = str(item["published_at"]).replace("Z", "+00:00")
            return datetime.fromisoformat(value).timestamp()
        except (KeyError, TypeError, ValueError):
            return 0.0

    @classmethod
    def _parse_response(cls, payload: bytes) -> list[dict[str, Any]]:
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("ESPN returned malformed JSON") from exc

        if not isinstance(data, dict) or not isinstance(data.get("articles"), list):
            raise RuntimeError("ESPN returned an invalid NFL news response")

        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for article in data["articles"]:
            if not isinstance(article, dict):
                continue
            headline = article.get("headline")
            if not isinstance(headline, str) or not headline.strip():
                continue

            article_id = str(article.get("id") or "")
            if article_id and article_id in seen_ids:
                continue
            if article_id:
                seen_ids.add(article_id)

            links = article.get("links")
            web_link = links.get("web") if isinstance(links, dict) else None
            url = web_link.get("href") if isinstance(web_link, dict) else None
            athlete_refs = cls._category_refs(article, "athlete")
            team_refs = cls._category_refs(article, "team")
            items.append(
                {
                    "article_id": article_id or None,
                    "players": cls._category_names(article, "athlete"),
                    "athlete_refs": athlete_refs,
                    "teams": cls._category_names(article, "team"),
                    "team_refs": team_refs,
                    "headline": headline.strip(),
                    "summary": str(article.get("description") or "").strip(),
                    "published_at": article.get("published")
                    or article.get("lastModified"),
                    "url": url,
                    "byline": article.get("byline"),
                    "premium": bool(article.get("premium", False)),
                }
            )
        return items

    async def _fetch_items(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if (
            self._cached_items is not None
            and now - self._cached_at < DEFAULT_TTL_MINUTES * 60
        ):
            return self._cached_items

        async with self._lock:
            now = time.monotonic()
            if (
                self._cached_items is not None
                and now - self._cached_at < DEFAULT_TTL_MINUTES * 60
            ):
                return self._cached_items

            timeout = aiohttp.ClientTimeout(total=15)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        NEWS_URL,
                        params={"limit": FETCH_LIMIT},
                        allow_redirects=False,
                    ) as response:
                        if response.status != 200:
                            raise RuntimeError(
                                f"ESPN NFL news request failed with HTTP {response.status}"
                            )
                        if (
                            response.content_length is not None
                            and response.content_length > MAX_RESPONSE_BYTES
                        ):
                            raise RuntimeError("ESPN NFL news response is too large")
                        payload_parts: list[bytes] = []
                        payload_size = 0
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            payload_size += len(chunk)
                            if payload_size > MAX_RESPONSE_BYTES:
                                raise RuntimeError("ESPN NFL news response is too large")
                            payload_parts.append(chunk)
                        payload = b"".join(payload_parts)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise RuntimeError("ESPN NFL news request failed") from exc

            items = self._parse_response(payload)
            self._cached_items = items
            self._cached_at = time.monotonic()
            return items

    async def get_nfl_news(
        self,
        players: Sequence[str] | None = None,
        limit: int = 5,
        *,
        _max_limit: int = 10,
    ) -> dict[str, Any]:
        """Return recent ESPN NFL articles, optionally filtered by player."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _max_limit
        ):
            raise ValueError(f"limit must be an integer between 1 and {_max_limit}")
        if players is not None and (
            isinstance(players, (str, bytes))
            or not all(isinstance(player, str) for player in players)
        ):
            raise ValueError("players must be a list of player names")

        items = await self._fetch_items()
        if players:
            requested = [
                self._normalize_search(player)
                for player in players
                if player.strip()
            ]
            items = [
                item
                for item in items
                if any(
                    player
                    in self._normalize_search(
                        " ".join(
                            [
                                *item["players"],
                                item["headline"],
                                item["summary"],
                            ]
                        )
                    )
                    for player in requested
                )
            ]

        selected = sorted(items, key=self._published_timestamp, reverse=True)[:limit]
        return {
            "status": "success",
            "source": SOURCE_NAME,
            "source_url": NEWS_URL,
            "source_note": SOURCE_NOTE,
            "cache_ttl_minutes": DEFAULT_TTL_MINUTES,
            "count": len(selected),
            "items": selected,
        }


espn_news_service = EspnNewsService()


async def get_espn_nfl_news(
    players: Sequence[str] | None = None, limit: int = 5
) -> dict[str, Any]:
    """Fetch ESPN NFL news through the shared in-memory service instance."""
    return await espn_news_service.get_nfl_news(players=players, limit=limit)


async def get_espn_nfl_news_batch(
    players: Sequence[str] | None = None, limit: int = 50
) -> dict[str, Any]:
    """Internal larger batch used before per-player decision limits are applied."""
    return await espn_news_service.get_nfl_news(
        players=players, limit=limit, _max_limit=50
    )
