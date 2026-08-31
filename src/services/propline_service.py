"""Bounded, read-only PropLine sportsbook odds integration."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp

from src.utils.constants import NFL_TEAMS

BASE_URL = "https://api.prop-line.com/v1"
ALLOWED_HOST = "api.prop-line.com"
SPORT = "football_nfl"
PROVIDER = "propline"
REQUEST_TIMEOUT_SECONDS = 5
OVERALL_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 16
MAX_CONCURRENCY = 4
MAX_RESULTS = 500
CACHE_SIZE = 128
EVENT_TTL_SECONDS = 60
FUTURES_TTL_SECONDS = 60 * 60

TEAM_MARKETS = ("h2h", "spreads", "totals")
PLAYER_MARKETS = (
    "player_pass_yds",
    "player_pass_tds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
    "player_anytime_td",
)
NEXT_GAME_MARKETS = frozenset((*TEAM_MARKETS, *PLAYER_MARKETS))
_KEY_RE = re.compile(r"^[a-z0-9_]+$")
_PLAYER_TEAM_SUFFIX_RE = re.compile(r"\s*\([A-Za-z]{2,4}\)\s*$")

SPORTSBOOK_ODDS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "players": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 100},
            "minItems": 1,
            "maxItems": 10,
        },
        "teams": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 100},
            "minItems": 1,
            "maxItems": 10,
        },
        "scope": {
            "type": "string",
            "enum": ["auto", "season", "next_game"],
            "default": "auto",
        },
        "markets": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
                "pattern": "^[a-z0-9_]+$",
            },
            "minItems": 1,
            "maxItems": 10,
            "uniqueItems": True,
        },
        "bookmakers": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
                "pattern": "^[a-z0-9_]+$",
            },
            "minItems": 1,
            "maxItems": 10,
            "uniqueItems": True,
        },
    },
    "anyOf": [{"required": ["players"]}, {"required": ["teams"]}],
}


@dataclass
class ProviderFailure(Exception):
    code: str
    message: str
    stage: str
    http_status: int | None = None
    retry_after_seconds: int | None = None
    quota: dict[str, Any] | None = None

    def envelope(self) -> dict[str, Any]:
        output: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
        }
        if self.http_status is not None:
            output["http_status"] = self.http_status
        if self.retry_after_seconds is not None:
            output["retry_after_seconds"] = self.retry_after_seconds
        return output


@dataclass
class CacheEntry:
    payload: Any
    stored_at: float
    fetched_at: str
    ttl_seconds: int
    quota: dict[str, Any]


@dataclass
class Component:
    source_id: str
    kind: str
    payload: Any
    fetched_at: str
    served_from_cache: bool
    cache_age_seconds: float
    cache_ttl_seconds: int
    quota: dict[str, Any]
    event_id: str | None = None

    def source(self) -> dict[str, Any]:
        output: dict[str, Any] = {
            "id": self.source_id,
            "kind": self.kind,
            "fetched_at": self.fetched_at,
            "served_from_cache": self.served_from_cache,
            "cache_age_seconds": round(self.cache_age_seconds, 3),
            "cache_ttl_seconds": self.cache_ttl_seconds,
        }
        if self.event_id is not None:
            output["event_id"] = self.event_id
        return output


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def _normalized_player(value: str) -> str:
    return _normalized(_PLAYER_TEAM_SUFFIX_RE.sub("", value))


def _team_aliases() -> dict[str, frozenset[str]]:
    aliases: dict[str, frozenset[str]] = {}
    for abbreviation, info in NFL_TEAMS.items():
        name = str(info["name"])
        full_key = name.casefold().replace(" ", "_")
        short_key = name.casefold().split()[-1]
        provider_keys = frozenset({full_key, short_key})
        aliases[_normalized(abbreviation)] = provider_keys
        aliases[_normalized(name)] = provider_keys
        aliases[_normalized(full_key)] = provider_keys
        aliases[short_key] = provider_keys
    aliases.update(
        {
            "jacksonville jaguars": frozenset({"jaguars", "jacksonville_jaguars"}),
            "jags": frozenset({"jaguars", "jacksonville_jaguars"}),
            "washington": frozenset({"commanders", "washington_commanders"}),
            "niners": frozenset({"49ers", "san_francisco_49ers"}),
        }
    )
    return aliases


TEAM_ALIASES = _team_aliases()


class PropLineService:
    """Fetch, cache, normalize, and match PropLine NFL odds."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utc_now,
        session_factory: Callable[..., Any] = aiohttp.ClientSession,
    ) -> None:
        self._monotonic = monotonic
        self._now = now
        self._session_factory = session_factory
        self._cache: OrderedDict[tuple[Any, ...], CacheEntry] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._request_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def clear_cache(self) -> None:
        async with self._cache_lock:
            self._cache.clear()

    @staticmethod
    def _validate_names(value: Any, field: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not 1 <= len(value) <= 10:
            raise ProviderFailure(
                "invalid_request", f"{field} must contain between 1 and 10 names", "validation"
            )
        output: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > 100:
                raise ProviderFailure(
                    "invalid_request",
                    f"Each {field} value must be a non-empty string of at most 100 characters",
                    "validation",
                )
            cleaned = item.strip()
            marker = _normalized(cleaned)
            if marker not in seen:
                seen.add(marker)
                output.append(cleaned)
        return output

    @staticmethod
    def _validate_keys(value: Any, field: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not 1 <= len(value) <= 10:
            raise ProviderFailure(
                "invalid_request", f"{field} must contain between 1 and 10 keys", "validation"
            )
        output: list[str] = []
        for item in value:
            if (
                not isinstance(item, str)
                or not item
                or len(item) > 64
                or _KEY_RE.fullmatch(item) is None
            ):
                raise ProviderFailure(
                    "invalid_request",
                    f"Each {field} key must match ^[a-z0-9_]+$ and be at most 64 characters",
                    "validation",
                )
            if item in output:
                raise ProviderFailure(
                    "invalid_request", f"{field} keys must be unique", "validation"
                )
            output.append(item)
        return output

    def _validate(
        self,
        players: Any,
        teams: Any,
        scope: Any,
        markets: Any,
        bookmakers: Any,
    ) -> tuple[list[str], list[str], str, list[str], list[str]]:
        player_names = self._validate_names(players, "players")
        team_names = self._validate_names(teams, "teams")
        if not player_names and not team_names:
            raise ProviderFailure(
                "invalid_request", "At least one player or team is required", "validation"
            )
        if scope not in {"auto", "season", "next_game"}:
            raise ProviderFailure(
                "invalid_request", "scope must be auto, season, or next_game", "validation"
            )
        market_keys = self._validate_keys(markets, "markets")
        bookmaker_keys = self._validate_keys(bookmakers, "bookmakers")
        if scope == "auto" and market_keys:
            raise ProviderFailure(
                "invalid_request", "Custom markets are not allowed with auto scope", "validation"
            )
        if scope == "next_game" and not set(market_keys).issubset(NEXT_GAME_MARKETS):
            raise ProviderFailure(
                "invalid_request",
                "next_game markets must be supported team or player markets",
                "validation",
            )
        return player_names, team_names, scope, market_keys, bookmaker_keys

    @staticmethod
    def _cache_key(
        endpoint: str,
        kind: str,
        markets: Sequence[str],
        bookmakers: Sequence[str],
    ) -> tuple[Any, ...]:
        if kind == "events":
            markets = ()
            bookmakers = ()
        elif kind == "futures":
            markets = ()
        return (endpoint, SPORT, tuple(sorted(markets)), tuple(sorted(bookmakers)))

    async def _cache_get(
        self,
        key: tuple[Any, ...],
        *,
        source_id: str,
        kind: str,
        event_id: str | None,
    ) -> Component | None:
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            age = max(0.0, self._monotonic() - entry.stored_at)
            if age >= entry.ttl_seconds:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return Component(
                source_id=source_id,
                kind=kind,
                event_id=event_id,
                payload=copy.deepcopy(entry.payload),
                fetched_at=entry.fetched_at,
                served_from_cache=True,
                cache_age_seconds=age,
                cache_ttl_seconds=entry.ttl_seconds,
                quota=copy.deepcopy(entry.quota),
            )

    async def _cache_put(
        self,
        key: tuple[Any, ...],
        component: Component,
    ) -> None:
        async with self._cache_lock:
            self._cache[key] = CacheEntry(
                payload=copy.deepcopy(component.payload),
                stored_at=self._monotonic(),
                fetched_at=component.fetched_at,
                ttl_seconds=component.cache_ttl_seconds,
                quota=copy.deepcopy(component.quota),
            )
            self._cache.move_to_end(key)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)

    def _quota(self, headers: Any, fetched_at: str) -> dict[str, Any]:
        def integer(*names: str) -> int | None:
            for name in names:
                value = headers.get(name)
                if value is not None:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None
            return None

        return {
            "as_of": fetched_at,
            "limit": integer("X-Daily-Limit", "X-RateLimit-Limit"),
            "remaining": integer("X-Daily-Remaining", "X-RateLimit-Remaining"),
            "reset": headers.get("X-Daily-Reset") or headers.get("X-RateLimit-Reset"),
        }

    @staticmethod
    def _retry_after(headers: Any) -> int | None:
        try:
            return max(0, int(headers.get("Retry-After")))
        except (TypeError, ValueError):
            return None

    async def _request_json(
        self,
        session: Any,
        endpoint: str,
        params: dict[str, str],
        *,
        stage: str,
    ) -> tuple[Any, str, dict[str, Any]]:
        url = f"{BASE_URL}{endpoint}"
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != ALLOWED_HOST
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ProviderFailure("invalid_request", "Unsafe PropLine request URL", stage)
        try:
            async with session.get(url, params=params or None, allow_redirects=False) as response:
                fetched_at = _iso_now(self._now())
                quota = self._quota(response.headers, fetched_at)
                status = int(response.status)
                if 300 <= status < 400:
                    raise ProviderFailure(
                        "invalid_response",
                        "PropLine redirects are not accepted",
                        stage,
                        http_status=status,
                        quota=quota,
                    )
                if status == 401:
                    raise ProviderFailure(
                        "invalid_credentials",
                        "PropLine rejected the configured API key",
                        stage,
                        http_status=status,
                        quota=quota,
                    )
                if status == 403:
                    raise ProviderFailure(
                        "access_denied",
                        "PropLine denied access to this resource",
                        stage,
                        http_status=status,
                        quota=quota,
                    )
                if status == 429:
                    raise ProviderFailure(
                        "rate_limited",
                        "PropLine rate limit reached",
                        stage,
                        http_status=status,
                        retry_after_seconds=self._retry_after(response.headers),
                        quota=quota,
                    )
                if status < 200 or status >= 300:
                    raise ProviderFailure(
                        "provider_error",
                        "PropLine request failed",
                        stage,
                        http_status=status,
                        quota=quota,
                    )
                content_length = getattr(response, "content_length", None)
                if content_length is not None and content_length > MAX_RESPONSE_BYTES:
                    raise ProviderFailure(
                        "invalid_response", "PropLine response exceeded 2 MiB", stage
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ProviderFailure(
                            "invalid_response", "PropLine response exceeded 2 MiB", stage
                        )
                    chunks.append(chunk)
        except ProviderFailure:
            raise
        except asyncio.TimeoutError as exc:
            raise ProviderFailure("provider_timeout", "PropLine request timed out", stage) from exc
        except aiohttp.ClientError as exc:
            raise ProviderFailure("provider_error", "PropLine request failed", stage) from exc

        try:
            payload = json.loads(b"".join(chunks))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderFailure(
                "invalid_response", "PropLine returned malformed JSON", stage
            ) from exc
        if not isinstance(payload, (dict, list)):
            raise ProviderFailure(
                "invalid_response", "PropLine returned an invalid response shape", stage
            )
        return payload, fetched_at, quota

    async def _component(
        self,
        session: Any,
        *,
        endpoint: str,
        params: dict[str, str],
        markets: Sequence[str],
        bookmakers: Sequence[str],
        source_id: str,
        kind: str,
        ttl_seconds: int,
        event_id: str | None = None,
    ) -> Component:
        key = self._cache_key(endpoint, kind, markets, bookmakers)
        cached = await self._cache_get(key, source_id=source_id, kind=kind, event_id=event_id)
        if cached is not None:
            return cached
        async with self._request_semaphore:
            cached = await self._cache_get(key, source_id=source_id, kind=kind, event_id=event_id)
            if cached is not None:
                return cached
            payload, fetched_at, quota = await self._request_json(
                session, endpoint, params, stage=source_id
            )
            component = Component(
                source_id=source_id,
                kind=kind,
                event_id=event_id,
                payload=payload,
                fetched_at=fetched_at,
                served_from_cache=False,
                cache_age_seconds=0.0,
                cache_ttl_seconds=ttl_seconds,
                quota=quota,
            )
            self._validate_component_shape(component)
            await self._cache_put(key, component)
            return component

    def _validate_component_shape(self, component: Component) -> None:
        if component.kind == "events":
            self._events(component.payload)
            return
        containers = self._unwrap_odds(component.payload)
        required = "markets" if component.kind == "futures" else "bookmakers"
        if any(not isinstance(container.get(required), list) for container in containers):
            raise ProviderFailure(
                "invalid_response",
                f"PropLine returned an invalid {component.kind} response",
                component.source_id,
            )

    async def _run_rolling(
        self,
        factories: Sequence[Callable[[], Awaitable[Component]]],
        *,
        component_sink: list[Component] | None = None,
        failure_sink: list[ProviderFailure] | None = None,
    ) -> tuple[list[Component], list[ProviderFailure], bool]:
        pending = deque(enumerate(factories))
        active: dict[asyncio.Task[Component], int] = {}
        outcomes: list[tuple[int, Component | ProviderFailure]] = []
        halted = False

        def record(ordinal: int, outcome: Component | ProviderFailure) -> None:
            outcomes.append((ordinal, outcome))

        def launch() -> None:
            while pending and len(active) < MAX_CONCURRENCY and not halted:
                ordinal, factory = pending.popleft()
                active[asyncio.create_task(factory())] = ordinal

        def flush() -> tuple[list[Component], list[ProviderFailure]]:
            completed: list[Component] = []
            failures: list[ProviderFailure] = []
            # Planned request order is the stable tie-break for concurrent outcomes.
            for _, outcome in sorted(outcomes, key=lambda item: item[0]):
                if isinstance(outcome, Component):
                    completed.append(outcome)
                    if component_sink is not None:
                        component_sink.append(outcome)
                else:
                    failures.append(outcome)
                    if failure_sink is not None:
                        failure_sink.append(outcome)
            return completed, failures

        launch()
        try:
            while active:
                done, still_active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                batch_failures: list[ProviderFailure] = []
                for task in sorted(done, key=active.__getitem__):
                    ordinal = active.pop(task)
                    try:
                        record(ordinal, task.result())
                    except ProviderFailure as exc:
                        record(ordinal, exc)
                        batch_failures.append(exc)
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        failure = ProviderFailure(
                            "provider_error", "PropLine request failed", "request"
                        )
                        record(ordinal, failure)
                        batch_failures.append(failure)
                active = {task: active[task] for task in still_active}
                if any(failure.code == "rate_limited" for failure in batch_failures):
                    halted = True
                    for task in active:
                        task.cancel()
                    if active:
                        ordered_active = sorted(active, key=active.__getitem__)
                        cancelled_results = await asyncio.gather(
                            *ordered_active, return_exceptions=True
                        )
                        for task, result in zip(ordered_active, cancelled_results):
                            if isinstance(result, Component):
                                record(active[task], result)
                            elif isinstance(result, ProviderFailure):
                                record(active[task], result)
                    active.clear()
                    pending.clear()
                    break
                launch()
        except BaseException:
            for task in active:
                task.cancel()
            if active:
                ordered_active = sorted(active, key=active.__getitem__)
                cancelled_results = await asyncio.gather(*ordered_active, return_exceptions=True)
                for task, result in zip(ordered_active, cancelled_results):
                    if isinstance(result, Component):
                        record(active[task], result)
                    elif isinstance(result, ProviderFailure):
                        record(active[task], result)
            flush()
            raise
        completed, failures = flush()
        return completed, failures, halted

    @staticmethod
    def _list_payload(payload: Any, keys: Sequence[str]) -> list[dict[str, Any]]:
        candidate = payload
        if isinstance(candidate, dict) and "data" in candidate:
            candidate = candidate["data"]
        if isinstance(candidate, dict):
            for key in keys:
                if isinstance(candidate.get(key), list):
                    candidate = candidate[key]
                    break
        if not isinstance(candidate, list):
            raise ProviderFailure(
                "invalid_response", "PropLine returned an invalid response shape", "normalize"
            )
        if any(not isinstance(item, dict) for item in candidate):
            raise ProviderFailure(
                "invalid_response", "PropLine returned an invalid response shape", "normalize"
            )
        return candidate

    def _events(self, payload: Any) -> list[dict[str, Any]]:
        return self._list_payload(payload, ("events", "results"))

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _event_id(event: dict[str, Any]) -> str | None:
        value = event.get("id") or event.get("event_id") or event.get("key")
        return str(value) if value not in (None, "") else None

    @staticmethod
    def _event_team(event: dict[str, Any], side: str) -> tuple[str | None, str | None]:
        key = event.get(f"{side}_team_key")
        display = event.get(f"{side}_team") or event.get(f"{side}_team_name")
        if isinstance(event.get(side), dict):
            nested = event[side]
            key = key or nested.get("key") or nested.get("id")
            display = display or nested.get("name")
        return (
            str(key) if key not in (None, "") else None,
            str(display) if display not in (None, "") else None,
        )

    def _event_matches_team(self, event: dict[str, Any], query: str) -> bool:
        normalized_query = _normalized(query)
        wanted_keys = TEAM_ALIASES.get(normalized_query, frozenset({query.casefold()}))
        for side in ("home", "away"):
            provider_key, display = self._event_team(event, side)
            if provider_key is not None:
                if provider_key.casefold() in wanted_keys:
                    return True
                continue
            if display is not None and _normalized(display) == normalized_query:
                return True
        return False

    @staticmethod
    def _unwrap_odds(payload: Any) -> list[dict[str, Any]]:
        candidate = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(candidate, list):
            if any(not isinstance(item, dict) for item in candidate):
                raise ProviderFailure(
                    "invalid_response",
                    "PropLine returned an invalid odds response",
                    "normalize",
                )
            return candidate
        if isinstance(candidate, dict):
            return [candidate]
        raise ProviderFailure(
            "invalid_response", "PropLine returned an invalid odds response", "normalize"
        )

    def _rows(self, component: Component, *, scope: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        containers = self._unwrap_odds(component.payload)
        for container in containers:
            event_id = self._event_id(container) or component.event_id or "futures"
            home_key, home_name = self._event_team(container, "home")
            away_key, away_name = self._event_team(container, "away")
            if scope == "season":
                futures_markets = container.get("markets")
                if not isinstance(futures_markets, list):
                    raise ProviderFailure(
                        "invalid_response",
                        "PropLine returned an invalid futures response",
                        "normalize",
                    )
                bookmakers = [
                    {
                        "key": market.get("bookmaker"),
                        "title": market.get("bookmaker_title"),
                        "last_update": market.get("last_update"),
                        "book_updated_at": market.get("book_updated_at"),
                        "markets": [market],
                    }
                    for market in futures_markets
                    if isinstance(market, dict)
                ]
            else:
                bookmakers = container.get("bookmakers")
                if not isinstance(bookmakers, list):
                    bookmakers = container.get("books")
                if not isinstance(bookmakers, list):
                    raise ProviderFailure(
                        "invalid_response",
                        "PropLine returned an invalid odds response",
                        "normalize",
                    )
            for book in bookmakers:
                if not isinstance(book, dict):
                    continue
                book_key = book.get("key") or book.get("bookmaker_key") or book.get("id")
                markets = book.get("markets")
                if not isinstance(markets, list):
                    continue
                for market in markets:
                    if not isinstance(market, dict):
                        continue
                    market_key = market.get("key") or market.get("market_key")
                    if not isinstance(market_key, str) or not market_key:
                        continue
                    outcomes = market.get("outcomes")
                    if not isinstance(outcomes, list):
                        continue
                    for outcome in outcomes:
                        if not isinstance(outcome, dict):
                            continue
                        selection = outcome.get("name") or outcome.get("selection")
                        subject = outcome.get("description") or outcome.get("subject") or selection
                        if not isinstance(selection, str) or not isinstance(subject, str):
                            continue
                        provider_entity_id = (
                            outcome.get("player_id")
                            or outcome.get("entity_id")
                            or outcome.get("participant_id")
                        )
                        row: dict[str, Any] = {
                            "source_id": component.source_id,
                            "event_id": str(event_id),
                            "scope": scope,
                            "event": {
                                "id": str(event_id),
                                "home_team_key": home_key,
                                "home_team": home_name,
                                "away_team_key": away_key,
                                "away_team": away_name,
                                "commence_time": container.get("commence_time"),
                                "title": container.get("title") or container.get("name"),
                            },
                            "bookmaker_key": str(book_key or ""),
                            "bookmaker": book.get("title") or book.get("name") or book_key,
                            "market_key": market_key,
                            "market_description": market.get("description") or market.get("title"),
                            "selection": selection,
                            "subject": subject,
                            "period": market.get("period")
                            or outcome.get("period")
                            or ("season" if scope == "season" else "full_game"),
                            "provider_observed_at": market.get("last_update")
                            or book.get("last_update")
                            or container.get("last_update"),
                            "book_updated_at": outcome.get("book_updated_at")
                            or book.get("book_updated_at"),
                            "last_change_at": outcome.get("last_change_at")
                            or outcome.get("last_update"),
                            "provider_entity_id": (
                                str(provider_entity_id)
                                if provider_entity_id not in (None, "")
                                else None
                            ),
                            "subject_normalized": _normalized_player(subject),
                        }
                        line = outcome.get("point", outcome.get("line"))
                        if line is not None:
                            row["line"] = line
                        if outcome.get("price") is not None:
                            row["price"] = outcome["price"]
                        rows.append(row)
        return rows

    @staticmethod
    def _selected_rows(
        rows: Sequence[dict[str, Any]],
        markets: Sequence[str],
        bookmakers: Sequence[str],
    ) -> list[dict[str, Any]]:
        market_set = set(markets)
        book_set = set(bookmakers)
        return [
            row
            for row in rows
            if (not market_set or row["market_key"] in market_set)
            and (not book_set or row["bookmaker_key"] in book_set)
        ]

    @staticmethod
    def _public_result(
        row: dict[str, Any], query: str, entity_type: str, matched_name: str
    ) -> dict[str, Any]:
        output = {
            key: value
            for key, value in row.items()
            if key != "subject_normalized" and value is not None
        }
        output.update({"query": query, "entity_type": entity_type, "matched_name": matched_name})
        return output

    def _match_player(
        self,
        query: str,
        rows: Sequence[dict[str, Any]],
        markets: Sequence[str],
        bookmakers: Sequence[str],
        *,
        explicit_filters: bool,
        across_futures: bool = False,
    ) -> tuple[list[dict[str, Any]], str | None]:
        wanted = _normalized_player(query)
        matching = [row for row in rows if row["subject_normalized"] == wanted]
        identities = {
            (
                None if across_futures else row["event_id"],
                (
                    ("id", row["provider_entity_id"])
                    if row.get("provider_entity_id")
                    else ("subject", row["subject_normalized"])
                ),
            )
            for row in matching
        }
        if len(identities) > 1:
            return [], "ambiguous"
        if not matching:
            if not rows:
                return [], "no_market"
            if markets and not any(row["market_key"] in set(markets) for row in rows):
                return [], "no_market"
            return [], "not_found"
        selected = self._selected_rows(matching, markets, bookmakers)
        if not selected:
            return [], "filtered_out" if explicit_filters else "no_market"
        return [self._public_result(row, query, "player", row["subject"]) for row in selected], None

    def _match_team(
        self,
        query: str,
        event_rows: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
        markets: Sequence[str],
        bookmakers: Sequence[str],
        *,
        explicit_filters: bool,
    ) -> tuple[list[dict[str, Any]], str | None]:
        matching_events = [item for item in event_rows if self._event_matches_team(item[0], query)]
        if not matching_events:
            return [], "not_found"
        rows = [row for _, item_rows in matching_events for row in item_rows]
        selected = self._selected_rows(rows, markets, bookmakers)
        if not selected:
            return [], "filtered_out" if explicit_filters else "no_market"
        display = query
        first_event = matching_events[0][0]
        normalized_query = _normalized(query)
        wanted_keys = TEAM_ALIASES.get(normalized_query, frozenset({query.casefold()}))
        for side in ("home", "away"):
            provider_key, candidate = self._event_team(first_event, side)
            stable_match = provider_key is not None and provider_key.casefold() in wanted_keys
            display_match = (
                provider_key is None
                and candidate is not None
                and _normalized(candidate) == normalized_query
            )
            if (stable_match or display_match) and candidate:
                display = candidate
                break
        return [self._public_result(row, query, "team", display) for row in selected], None

    def _match_futures_team(
        self,
        query: str,
        rows: Sequence[dict[str, Any]],
        markets: Sequence[str],
        bookmakers: Sequence[str],
        *,
        explicit_filters: bool,
    ) -> tuple[list[dict[str, Any]], str | None]:
        normalized_query = _normalized(query)
        wanted_keys = TEAM_ALIASES.get(normalized_query, frozenset({query.casefold()}))
        matching: list[dict[str, Any]] = []
        for row in rows:
            subject_keys = TEAM_ALIASES.get(_normalized(row["subject"]))
            if subject_keys is not None:
                if wanted_keys.intersection(subject_keys):
                    matching.append(row)
            elif row["subject_normalized"] == _normalized_player(query):
                matching.append(row)

        identities = {
            (
                ("id", row["provider_entity_id"])
                if row.get("provider_entity_id")
                else ("subject", row["subject_normalized"])
            )
            for row in matching
        }
        if len(identities) > 1:
            return [], "ambiguous"
        if not matching:
            if not rows:
                return [], "no_market"
            if markets and not any(row["market_key"] in set(markets) for row in rows):
                return [], "no_market"
            return [], "not_found"
        selected = self._selected_rows(matching, markets, bookmakers)
        if not selected:
            return [], "filtered_out" if explicit_filters else "no_market"
        return [self._public_result(row, query, "team", row["subject"]) for row in selected], None

    def _quota_output(
        self, components: Sequence[Component], failures: Sequence[ProviderFailure]
    ) -> dict[str, Any]:
        live: list[dict[str, Any]] = [
            component.quota for component in components if not component.served_from_cache
        ]
        live.extend(failure.quota for failure in failures if failure.quota is not None)
        if live:
            source = "live"
            known_remaining = [item for item in live if item.get("remaining") is not None]
            if known_remaining:
                lowest = min(item["remaining"] for item in known_remaining)
                candidates = [item for item in known_remaining if item["remaining"] == lowest]
            else:
                candidates = live
            selected = max(candidates, key=lambda item: item.get("as_of") or "")
        else:
            cached = [component.quota for component in components]
            selected = max(cached, key=lambda item: item.get("as_of") or "", default=None)
            if selected is None:
                selected = {
                    "as_of": _iso_now(self._now()),
                    "limit": None,
                    "remaining": None,
                    "reset": None,
                }
                source = "live"
            else:
                source = "cache"
        return {"source": source, **selected}

    @staticmethod
    def _primary_failure(failures: Sequence[ProviderFailure]) -> ProviderFailure:
        # Rate limiting stops new work; otherwise the earliest planned failure wins.
        return next(
            (failure for failure in failures if failure.code == "rate_limited"),
            failures[0],
        )

    def _base_response(self, scope: Any) -> dict[str, Any]:
        return {
            "status": "error",
            "provider": PROVIDER,
            "served_at": _iso_now(self._now()),
            "scope_requested": scope if isinstance(scope, str) else "auto",
            "sources": [],
            "results": [],
            "unmatched": [],
            "warnings": [],
            "quota": {
                "source": "live",
                "as_of": _iso_now(self._now()),
                "limit": None,
                "remaining": None,
                "reset": None,
            },
        }

    async def get_sportsbook_odds(
        self,
        *,
        players: Any = None,
        teams: Any = None,
        scope: Any = "auto",
        markets: Any = None,
        bookmakers: Any = None,
        player_context: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Return normalized PropLine odds for requested NFL players or teams."""
        response = self._base_response(scope)
        try:
            player_names, team_names, scope, market_keys, bookmaker_keys = self._validate(
                players, teams, scope, markets, bookmakers
            )
        except ProviderFailure as exc:
            response["error"] = exc.envelope()
            return response

        response["scope_requested"] = scope
        api_key = os.getenv("PROPLINE_API_KEY", "").strip()
        if not api_key:
            failure = ProviderFailure(
                "not_configured", "PROPLINE_API_KEY is not configured", "configuration"
            )
            response["error"] = failure.envelope()
            return response

        components: list[Component] = []
        failures: list[ProviderFailure] = []
        event_cap_truncated = False
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
            async with asyncio.timeout(OVERALL_TIMEOUT_SECONDS):
                async with self._session_factory(
                    timeout=timeout, headers={"X-API-Key": api_key}
                ) as session:
                    initial: list[Callable[[], Awaitable[Component]]] = []
                    if scope in {"auto", "season"}:
                        futures_params = (
                            {"bookmakers": ",".join(bookmaker_keys)} if bookmaker_keys else {}
                        )
                        initial.append(
                            lambda: self._component(
                                session,
                                endpoint=f"/sports/{SPORT}/futures",
                                params=futures_params,
                                markets=market_keys,
                                bookmakers=bookmaker_keys,
                                source_id="futures",
                                kind="futures",
                                ttl_seconds=FUTURES_TTL_SECONDS,
                            )
                        )
                    if scope in {"auto", "next_game"}:
                        initial.append(
                            lambda: self._component(
                                session,
                                endpoint=f"/sports/{SPORT}/events",
                                params={},
                                markets=market_keys,
                                bookmakers=bookmaker_keys,
                                source_id="events",
                                kind="events",
                                ttl_seconds=EVENT_TTL_SECONDS,
                            )
                        )
                    first_components, _, halted = await self._run_rolling(
                        initial,
                        component_sink=components,
                        failure_sink=failures,
                    )

                    events_component = next(
                        (component for component in first_components if component.kind == "events"),
                        None,
                    )
                    if events_component is not None and not halted:
                        try:
                            events = self._events(events_component.payload)
                        except ProviderFailure as exc:
                            components.remove(events_component)
                            failures.append(exc)
                            events = []
                        now = self._now().astimezone(timezone.utc)
                        upcoming = [
                            event
                            for event in events
                            if (parsed := self._parse_time(event.get("commence_time"))) is not None
                            and parsed > now
                            and self._event_id(event) is not None
                        ]
                        upcoming.sort(
                            key=lambda event: self._parse_time(event.get("commence_time"))
                            or datetime.max.replace(tzinfo=timezone.utc)
                        )
                        event_cap_truncated = len(upcoming) > MAX_EVENTS
                        retained = upcoming[:MAX_EVENTS]
                        player_team_names = [
                            player_context[player]["team"]
                            for player in player_names
                            if player_context
                            and player in player_context
                            and player_context[player].get("team")
                        ]
                        unrestricted_player = any(
                            not player_context
                            or player not in player_context
                            or not player_context[player].get("team")
                            for player in player_names
                        )
                        eligible = (
                            retained
                            if unrestricted_player
                            else [
                                event
                                for event in retained
                                if any(
                                    self._event_matches_team(event, team)
                                    for team in [*team_names, *player_team_names]
                                )
                            ]
                        )
                        default_markets = [
                            *(TEAM_MARKETS if team_names else ()),
                            *(PLAYER_MARKETS if player_names else ()),
                        ]
                        selected_markets = market_keys or default_markets
                        event_factories: list[Callable[[], Awaitable[Component]]] = []
                        for event in eligible:
                            event_id = self._event_id(event)
                            if event_id is None:
                                continue
                            encoded = quote(event_id, safe="")
                            params = {"markets": ",".join(selected_markets)}
                            if bookmaker_keys:
                                params["bookmakers"] = ",".join(bookmaker_keys)

                            async def fetch_event(
                                event_id: str = event_id,
                                encoded: str = encoded,
                                params: dict[str, str] = params,
                            ) -> Component:
                                return await self._component(
                                    session,
                                    endpoint=f"/sports/{SPORT}/events/{encoded}/odds",
                                    params=params,
                                    markets=selected_markets,
                                    bookmakers=bookmaker_keys,
                                    source_id=f"event:{event_id}",
                                    kind="event_odds",
                                    ttl_seconds=EVENT_TTL_SECONDS,
                                    event_id=event_id,
                                )

                            event_factories.append(fetch_event)
                        await self._run_rolling(
                            event_factories,
                            component_sink=components,
                            failure_sink=failures,
                        )
        except asyncio.TimeoutError:
            failures.append(
                ProviderFailure("provider_timeout", "PropLine request timed out", "overall")
            )
        except aiohttp.ClientError:
            failures.append(ProviderFailure("provider_error", "PropLine request failed", "session"))
        except Exception:
            failures.append(ProviderFailure("provider_error", "PropLine request failed", "session"))

        valid_components: list[Component] = []
        futures_rows: list[dict[str, Any]] = []
        event_rows_by_id: dict[str, list[dict[str, Any]]] = {}
        events_by_id: dict[str, dict[str, Any]] = {}
        for component in components:
            try:
                if component.kind == "futures":
                    futures_rows.extend(self._rows(component, scope="season"))
                    valid_components.append(component)
                elif component.kind == "events":
                    for event in self._events(component.payload):
                        event_id = self._event_id(event)
                        if event_id:
                            events_by_id[event_id] = event
                    valid_components.append(component)
                elif component.kind == "event_odds":
                    event_rows_by_id.setdefault(component.event_id or "", []).extend(
                        self._rows(component, scope="next_game")
                    )
                    valid_components.append(component)
            except ProviderFailure as exc:
                failures.append(exc)
        components = valid_components

        results: list[dict[str, Any]] = []
        unmatched: list[dict[str, str]] = []
        selected_futures = market_keys if scope == "season" else []
        game_rows = [row for rows in event_rows_by_id.values() for row in rows]

        def combine_reason(reasons: Sequence[str | None]) -> str | None:
            present = [reason for reason in reasons if reason]
            for candidate in ("ambiguous", "filtered_out", "no_market", "truncated"):
                if candidate in present:
                    return candidate
            return present[0] if present else None

        for player in player_names:
            matched: list[dict[str, Any]] = []
            reasons: list[str | None] = []
            if scope in {"auto", "season"}:
                season_matches, season_reason = self._match_player(
                    player,
                    futures_rows,
                    selected_futures,
                    bookmaker_keys,
                    explicit_filters=bool(market_keys or bookmaker_keys),
                    across_futures=True,
                )
                matched.extend(season_matches)
                reasons.append(season_reason)
            if scope in {"auto", "next_game"}:
                player_game_rows = game_rows
                if (
                    player_context
                    and player in player_context
                    and player_context[player].get("team")
                ):
                    player_game_rows = [
                        row
                        for event_id, rows in event_rows_by_id.items()
                        if event_id in events_by_id
                        and self._event_matches_team(
                            events_by_id[event_id], player_context[player]["team"]
                        )
                        for row in rows
                    ]
                game_matches, game_reason = self._match_player(
                    player,
                    player_game_rows,
                    market_keys or list(PLAYER_MARKETS),
                    bookmaker_keys,
                    explicit_filters=bool(market_keys or bookmaker_keys),
                )
                matched.extend(game_matches)
                reasons.append(game_reason)
            reason = None if matched else combine_reason(reasons)
            results.extend(matched)
            if reason:
                if reason == "not_found" and event_cap_truncated and scope != "season":
                    reason = "truncated"
                unmatched.append({"query": player, "entity_type": "player", "reason": reason})

        event_pairs = [
            (event, event_rows_by_id.get(event_id, []))
            for event_id, event in events_by_id.items()
            if event_id in event_rows_by_id
        ]
        for team in team_names:
            matched = []
            reasons = []
            if scope in {"auto", "season"}:
                season_matches, season_reason = self._match_futures_team(
                    team,
                    futures_rows,
                    selected_futures,
                    bookmaker_keys,
                    explicit_filters=bool(market_keys or bookmaker_keys),
                )
                matched.extend(season_matches)
                reasons.append(season_reason)
            if scope in {"auto", "next_game"}:
                game_matches, game_reason = self._match_team(
                    team,
                    event_pairs,
                    market_keys or list(TEAM_MARKETS),
                    bookmaker_keys,
                    explicit_filters=bool(market_keys or bookmaker_keys),
                )
                matched.extend(game_matches)
                reasons.append(game_reason)
            reason = None if matched else combine_reason(reasons)
            results.extend(matched)
            if reason:
                if reason == "not_found" and event_cap_truncated and scope != "season":
                    reason = "truncated"
                unmatched.append({"query": team, "entity_type": "team", "reason": reason})

        results.sort(
            key=lambda row: (
                row.get("query", ""),
                row.get("event_id", ""),
                row.get("bookmaker_key", ""),
                row.get("market_key", ""),
                row.get("selection", ""),
                str(row.get("line", "")),
            )
        )
        result_truncated = len(results) > MAX_RESULTS
        if result_truncated:
            removed_queries = {row["query"] for row in results[MAX_RESULTS:]}
            results = results[:MAX_RESULTS]
            retained_queries = {row["query"] for row in results}
            for query in sorted(removed_queries - retained_queries):
                entity_type = "player" if query in player_names else "team"
                unmatched.append(
                    {"query": query, "entity_type": entity_type, "reason": "truncated"}
                )

        warnings: list[str] = []
        if event_cap_truncated:
            warnings.append("Only the first 16 upcoming events were scanned")
        if result_truncated:
            warnings.append("Results were truncated to 500 rows")
        if failures:
            warnings.append("One or more PropLine responses could not be completed")

        response.update(
            {
                "sources": [component.source() for component in components],
                "results": results,
                "unmatched": unmatched,
                "warnings": warnings,
                "quota": self._quota_output(components, failures),
            }
        )
        if components:
            response["status"] = (
                "partial" if failures or event_cap_truncated or result_truncated else "ok"
            )
            if failures:
                response["error"] = self._primary_failure(failures).envelope()
        else:
            response["status"] = "error"
            if failures:
                response["error"] = self._primary_failure(failures).envelope()
            else:
                response["error"] = ProviderFailure(
                    "provider_error", "No PropLine response completed", "request"
                ).envelope()
        return response


propline_service = PropLineService()


async def get_sportsbook_odds(
    *,
    players: Any = None,
    teams: Any = None,
    scope: Any = "auto",
    markets: Any = None,
    bookmakers: Any = None,
    player_context: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Fetch sportsbook odds through the shared PropLine service instance."""
    return await propline_service.get_sportsbook_odds(
        players=players,
        teams=teams,
        scope=scope,
        markets=markets,
        bookmakers=bookmakers,
        player_context=player_context,
    )


__all__ = [
    "PropLineService",
    "SPORTSBOOK_ODDS_INPUT_SCHEMA",
    "get_sportsbook_odds",
    "propline_service",
]
