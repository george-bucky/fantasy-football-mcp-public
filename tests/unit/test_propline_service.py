"""Deterministic, offline tests for the PropLine sportsbook odds service."""

from __future__ import annotations

import asyncio
import importlib
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock
from urllib.parse import urlparse

import aiohttp
import pytest

from src.services.propline_service import (
    CACHE_SIZE,
    EVENT_TTL_SECONDS,
    FUTURES_TTL_SECONDS,
    MAX_CONCURRENCY,
    MAX_EVENTS,
    MAX_RESPONSE_BYTES,
    MAX_RESULTS,
    PropLineService,
)

propline_service = importlib.import_module("src.services.propline_service")

API_KEY = "unit-test-propline-key"
NOW = datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.elapsed = 100.0
        self.current = NOW

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds
        self.current += timedelta(seconds=seconds)


class TickingClock(Clock):
    def now(self) -> datetime:
        current = self.current
        self.current += timedelta(milliseconds=1)
        return current


class ActivityTracker:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0
        self.cancelled = 0


class FakeResponse:
    def __init__(
        self,
        payload: Any = None,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
        content_length: int | None | object = ...,  # Ellipsis means derive it.
        delay: float = 0.0,
        tracker: ActivityTracker | None = None,
    ) -> None:
        self.raw = (
            json.dumps(payload if payload is not None else {}).encode() if raw is None else raw
        )
        self.status = status
        self.headers = headers or {}
        self.content_length = len(self.raw) if content_length is ... else content_length
        self.content = self
        self.delay = delay
        self.tracker = tracker

    async def __aenter__(self) -> FakeResponse:
        if self.tracker is not None:
            self.tracker.active += 1
            self.tracker.maximum = max(self.tracker.maximum, self.tracker.active)
        return self

    async def __aexit__(self, exc_type, _exc, _traceback) -> None:
        if self.tracker is not None:
            self.tracker.active -= 1
            if exc_type is asyncio.CancelledError:
                self.tracker.cancelled += 1

    async def iter_chunked(self, _size: int):
        if self.delay:
            await asyncio.sleep(self.delay)
        yield self.raw


class FakeSession:
    def __init__(self, routes: dict[str, deque[Any]], factory: SessionFactory) -> None:
        self.routes = routes
        self.factory = factory

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> Any:
        path = urlparse(url).path
        self.factory.calls.append((url, kwargs))
        self.factory.calls_by_path[path] += 1
        if path not in self.routes or not self.routes[path]:
            raise AssertionError(f"Unexpected request: {path}")
        response = self.routes[path].popleft()
        if isinstance(response, BaseException):
            raise response
        return response


class SessionFactory:
    def __init__(self, routes: dict[str, list[Any]]) -> None:
        self.routes = {path: deque(responses) for path, responses in routes.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.calls_by_path: dict[str, int] = defaultdict(int)
        self.session_kwargs: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeSession:
        self.session_kwargs.append(kwargs)
        return FakeSession(self.routes, self)


def event(
    event_id: str,
    *,
    hours: int = 1,
    home_key: str = "buffalo_bills",
    home_name: str = "Buffalo Bills",
    away_key: str = "baltimore_ravens",
    away_name: str = "Baltimore Ravens",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "commence_time": (NOW + timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
        "home_team_key": home_key,
        "home_team": home_name,
        "away_team_key": away_key,
        "away_team": away_name,
    }


def game_odds(
    event_id: str,
    *,
    player: str = "Josh Allen (BUF)",
    player_id: str | None = "player-17",
    market: str = "player_pass_yds",
    book: str = "draftkings",
    outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if outcomes is None:
        outcomes = [
            {
                "name": "Over",
                "description": player,
                "player_id": player_id,
                "point": 275.5,
                "price": -110,
                "last_change_at": "2026-08-31T15:58:00Z",
            }
        ]
    return {
        "id": event_id,
        "commence_time": "2026-08-31T17:00:00Z",
        "home_team_key": "buffalo_bills",
        "home_team": "Buffalo Bills",
        "away_team_key": "baltimore_ravens",
        "away_team": "Baltimore Ravens",
        "bookmakers": [
            {
                "key": book,
                "title": book.title(),
                "last_update": "2026-08-31T15:59:00Z",
                "book_updated_at": "2026-08-31T15:59:30Z",
                "markets": [
                    {
                        "key": market,
                        "description": "Passing yards",
                        "period": "full_game",
                        "outcomes": outcomes,
                    }
                ],
            }
        ],
    }


def futures_odds(
    *,
    subject: str = "Josh Allen",
    player_id: str | None = "player-17",
    market: str = "mvp",
    book: str = "fanduel",
) -> dict[str, Any]:
    return {
        "markets": [
            {
                "key": market,
                "description": "Most Valuable Player",
                "bookmaker": book,
                "bookmaker_title": "FanDuel",
                "last_update": "2026-08-31T15:55:00Z",
                "outcomes": [
                    {
                        "name": subject,
                        "description": subject,
                        "player_id": player_id,
                        "price": 650,
                    }
                ],
            }
        ]
    }


def quota_headers(remaining: int, *, limit: int = 1000) -> dict[str, str]:
    return {
        "X-Daily-Limit": str(limit),
        "X-Daily-Remaining": str(remaining),
        "X-Daily-Reset": "2026-09-01T00:00:00Z",
    }


def make_service(
    routes: dict[str, list[Any]], clock: Clock | None = None
) -> tuple[PropLineService, SessionFactory, Clock]:
    fixed_clock = clock or Clock()
    factory = SessionFactory(routes)
    service = PropLineService(
        monotonic=fixed_clock.monotonic,
        now=fixed_clock.now,
        session_factory=factory,
    )
    return service, factory, fixed_clock


@pytest.fixture(autouse=True)
def configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPLINE_API_KEY", API_KEY)


@pytest.mark.asyncio
async def test_season_normalizes_and_filters_market_and_bookmaker() -> None:
    routes = {
        "/v1/sports/football_nfl/futures": [
            FakeResponse(
                [futures_odds(), futures_odds(subject="Lamar Jackson", book="betmgm")],
                headers=quota_headers(91),
            )
        ]
    }
    service, factory, _ = make_service(routes)

    result = await service.get_sportsbook_odds(
        players=["Josh Allen"], scope="season", markets=["mvp"], bookmakers=["fanduel"]
    )

    assert result["status"] == "ok"
    assert result["quota"] == {
        "source": "live",
        "as_of": "2026-08-31T16:00:00Z",
        "limit": 1000,
        "remaining": 91,
        "reset": "2026-09-01T00:00:00Z",
    }
    assert result["sources"][0]["kind"] == "futures"
    assert len(result["results"]) == 1
    normalized = result["results"][0]
    assert normalized["source_id"] == "futures"
    assert normalized["scope"] == "season"
    assert normalized["bookmaker_key"] == "fanduel"
    assert normalized["market_key"] == "mvp"
    assert normalized["market_description"] == "Most Valuable Player"
    assert normalized["selection"] == normalized["subject"] == "Josh Allen"
    assert normalized["period"] == "season"
    assert normalized["price"] == 650
    assert normalized["provider_entity_id"] == "player-17"
    assert normalized["query"] == normalized["matched_name"] == "Josh Allen"
    assert normalized["entity_type"] == "player"
    assert factory.calls[0][1]["params"] == {"bookmakers": "fanduel"}
    assert factory.calls[0][1]["allow_redirects"] is False


@pytest.mark.asyncio
async def test_season_matches_team_futures_as_team_results() -> None:
    routes = {
        "/v1/sports/football_nfl/futures": [
            FakeResponse(
                [
                    futures_odds(
                        subject="Buffalo Bills",
                        player_id="team-17",
                        market="super_bowl_winner",
                    )
                ]
            )
        ]
    }
    service, _, _ = make_service(routes)

    result = await service.get_sportsbook_odds(teams=["BUF"], scope="season")

    assert result["status"] == "ok"
    assert result["results"][0]["entity_type"] == "team"
    assert result["results"][0]["matched_name"] == "Buffalo Bills"
    assert result["results"][0]["market_key"] == "super_bowl_winner"
    assert result["results"][0]["provider_entity_id"] == "team-17"


@pytest.mark.asyncio
async def test_futures_identity_spans_multiple_legitimate_containers() -> None:
    player_mvp = futures_odds(subject="Josh Allen", player_id="player-17", market="mvp")
    player_mvp["id"] = "award-mvp"
    player_opoy = futures_odds(
        subject="Josh Allen", player_id="player-17", market="offensive_player_of_year"
    )
    player_opoy["id"] = "award-opoy"
    team_super_bowl = futures_odds(
        subject="Buffalo Bills", player_id="team-17", market="super_bowl_winner"
    )
    team_super_bowl["id"] = "championship-super-bowl"
    team_conference = futures_odds(
        subject="Buffalo Bills", player_id="team-17", market="afc_winner"
    )
    team_conference["id"] = "championship-afc"
    routes = {
        "/v1/sports/football_nfl/futures": [
            FakeResponse([player_mvp, player_opoy, team_super_bowl, team_conference])
        ]
    }
    service, _, _ = make_service(routes)

    result = await service.get_sportsbook_odds(
        players=["Josh Allen"], teams=["BUF"], scope="season"
    )

    assert result["status"] == "ok"
    assert result["unmatched"] == []
    player_rows = [row for row in result["results"] if row["entity_type"] == "player"]
    team_rows = [row for row in result["results"] if row["entity_type"] == "team"]
    assert {row["event_id"] for row in player_rows} == {"award-mvp", "award-opoy"}
    assert {row["event_id"] for row in team_rows} == {
        "championship-super-bowl",
        "championship-afc",
    }


@pytest.mark.asyncio
async def test_futures_cache_ignores_locally_applied_market_filter() -> None:
    mvp = futures_odds(subject="Josh Allen", market="mvp", book="fanduel")
    champion = futures_odds(
        subject="Buffalo Bills",
        player_id="team-17",
        market="super_bowl_winner",
        book="fanduel",
    )
    routes = {
        "/v1/sports/football_nfl/futures": [
            FakeResponse([mvp, champion], headers=quota_headers(77))
        ]
    }
    service, factory, _ = make_service(routes)

    first = await service.get_sportsbook_odds(
        players=["Josh Allen"],
        scope="season",
        markets=["mvp"],
        bookmakers=["fanduel"],
    )
    second = await service.get_sportsbook_odds(
        teams=["BUF"],
        scope="season",
        markets=["super_bowl_winner"],
        bookmakers=["fanduel"],
    )

    assert first["status"] == second["status"] == "ok"
    assert factory.calls_by_path["/v1/sports/football_nfl/futures"] == 1
    assert second["sources"][0]["served_from_cache"] is True
    assert second["results"][0]["market_key"] == "super_bowl_winner"
    assert second["quota"]["source"] == "cache"
    assert second["quota"]["remaining"] == 77


@pytest.mark.asyncio
async def test_next_game_sorts_events_combines_queries_and_matches_team_key() -> None:
    events = [
        event("later", hours=3, home_key="miami_dolphins", home_name="Miami Dolphins"),
        event("first", hours=1),
        event("past", hours=-1),
    ]
    first_odds = game_odds("first")
    first_odds["bookmakers"][0]["markets"].append(
        {
            "key": "h2h",
            "description": "Moneyline",
            "outcomes": [{"name": "Buffalo Bills", "description": "Buffalo Bills", "price": -130}],
        }
    )
    routes = {
        "/v1/sports/football_nfl/events": [FakeResponse(events)],
        "/v1/sports/football_nfl/events/first/odds": [FakeResponse(first_odds)],
        "/v1/sports/football_nfl/events/later/odds": [
            FakeResponse(game_odds("later", player="Lamar Jackson", player_id="player-8"))
        ],
    }
    service, factory, _ = make_service(routes)

    result = await service.get_sportsbook_odds(
        players=["Josh Allen"], teams=["BUF"], scope="next_game"
    )

    assert result["status"] == "ok"
    assert {source["event_id"] for source in result["sources"] if "event_id" in source} == {
        "first",
        "later",
    }
    assert {row["entity_type"] for row in result["results"]} == {"player", "team"}
    assert {row["query"] for row in result["results"]} == {"Josh Allen", "BUF"}
    assert factory.calls_by_path["/v1/sports/football_nfl/events"] == 1
    assert sum("/odds" in path for path in factory.calls_by_path) == 2
    assert [urlparse(url).path for url, _ in factory.calls[1:]] == [
        "/v1/sports/football_nfl/events/first/odds",
        "/v1/sports/football_nfl/events/later/odds",
    ]
    params = next(kwargs["params"] for url, kwargs in factory.calls if url.endswith("/first/odds"))
    assert "h2h" in params["markets"]
    assert "player_pass_yds" in params["markets"]


@pytest.mark.asyncio
async def test_events_cache_ignores_filters_not_sent_to_discovery() -> None:
    team_market = game_odds(
        "one",
        market="h2h",
        book="fanduel",
        outcomes=[
            {
                "name": "Buffalo Bills",
                "description": "Buffalo Bills",
                "price": -125,
            }
        ],
    )
    routes = {
        "/v1/sports/football_nfl/events": [FakeResponse([event("one")], headers=quota_headers(80))],
        "/v1/sports/football_nfl/events/one/odds": [
            FakeResponse(game_odds("one"), headers=quota_headers(70)),
            FakeResponse(team_market, headers=quota_headers(60)),
        ],
    }
    service, factory, _ = make_service(routes)

    first = await service.get_sportsbook_odds(
        players=["Josh Allen"],
        scope="next_game",
        markets=["player_pass_yds"],
        bookmakers=["draftkings"],
    )
    second = await service.get_sportsbook_odds(
        teams=["BUF"],
        scope="next_game",
        markets=["h2h"],
        bookmakers=["fanduel"],
    )

    assert first["status"] == second["status"] == "ok"
    assert factory.calls_by_path["/v1/sports/football_nfl/events"] == 1
    assert factory.calls_by_path["/v1/sports/football_nfl/events/one/odds"] == 2
    events_source = next(source for source in second["sources"] if source["id"] == "events")
    assert events_source["served_from_cache"] is True
    assert second["quota"]["source"] == "live"
    assert second["quota"]["remaining"] == 60


@pytest.mark.asyncio
async def test_team_only_query_restricts_event_requests_before_fetching_odds() -> None:
    routes = {
        "/v1/sports/football_nfl/events": [
            FakeResponse(
                [
                    event("bills"),
                    event(
                        "other",
                        home_key="miami_dolphins",
                        home_name="Miami Dolphins",
                        away_key="new_york_jets",
                        away_name="New York Jets",
                    ),
                ]
            )
        ],
        "/v1/sports/football_nfl/events/bills/odds": [FakeResponse(game_odds("bills"))],
    }
    service, factory, _ = make_service(routes)

    result = await service.get_sportsbook_odds(teams=["Buffalo Bills"], scope="next_game")

    assert result["status"] == "ok"
    assert not any("/other/" in url for url, _ in factory.calls)


@pytest.mark.asyncio
async def test_event_id_is_url_encoded_without_changing_the_allowlisted_host() -> None:
    event_id = "../other/path?redirect=evil"
    encoded_path = "/v1/sports/football_nfl/events/..%2Fother%2Fpath%3Fredirect%3Devil/odds"
    routes = {
        "/v1/sports/football_nfl/events": [FakeResponse([event(event_id)])],
        encoded_path: [FakeResponse(game_odds(event_id))],
    }
    service, factory, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="next_game")

    assert result["status"] == "ok"
    odds_url = next(url for url, _ in factory.calls if urlparse(url).path == encoded_path)
    assert urlparse(odds_url).hostname == "api.prop-line.com"


@pytest.mark.asyncio
async def test_player_parenthetical_suffix_matches_and_distinct_identity_is_ambiguous() -> None:
    routes = {
        "/v1/sports/football_nfl/events": [FakeResponse([event("one"), event("two", hours=2)])],
        "/v1/sports/football_nfl/events/one/odds": [
            FakeResponse(game_odds("one", player="Josh Allen (BUF)", player_id="17"))
        ],
        "/v1/sports/football_nfl/events/two/odds": [
            FakeResponse(game_odds("two", player="Josh Allen", player_id="99"))
        ],
    }
    service, _, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="next_game")

    assert result["status"] == "ok"
    assert result["results"] == []
    assert result["unmatched"] == [
        {"query": "Josh Allen", "entity_type": "player", "reason": "ambiguous"}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("odds_payload", "kwargs", "reason"),
    [
        (game_odds("one", player="Lamar Jackson"), {}, "not_found"),
        ({**game_odds("one"), "bookmakers": []}, {}, "no_market"),
        (game_odds("one", book="fanduel"), {"bookmakers": ["draftkings"]}, "filtered_out"),
    ],
)
async def test_structured_unmatched_reasons(
    odds_payload: dict[str, Any], kwargs: dict[str, Any], reason: str
) -> None:
    routes = {
        "/v1/sports/football_nfl/events": [FakeResponse([event("one")])],
        "/v1/sports/football_nfl/events/one/odds": [FakeResponse(odds_payload)],
    }
    service, _, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="next_game", **kwargs)

    assert result["status"] == "ok"
    assert result["unmatched"][0]["reason"] == reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"players": []},
        {"players": [" "]},
        {"players": ["x" * 101]},
        {"players": [str(index) for index in range(11)]},
        {"players": ["Josh Allen"], "scope": "weekly"},
        {"players": ["Josh Allen"], "scope": "auto", "markets": ["mvp"]},
        {"players": ["Josh Allen"], "scope": "next_game", "markets": ["mvp"]},
        {"players": ["Josh Allen"], "scope": "season", "markets": ["Bad-Key"]},
        {"players": ["Josh Allen"], "scope": "season", "markets": ["mvp", "mvp"]},
        {"players": ["Josh Allen"], "bookmakers": ["x" * 65]},
        {"players": ["Josh Allen"], "bookmakers": ["book", "book"]},
    ],
)
async def test_invalid_inputs_are_rejected_before_session_creation(kwargs: dict[str, Any]) -> None:
    factory = Mock(side_effect=AssertionError("network/session must not be created"))
    service = PropLineService(session_factory=factory)

    result = await service.get_sportsbook_odds(**kwargs)

    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_request"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_missing_key_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROPLINE_API_KEY", raising=False)
    factory = Mock(side_effect=AssertionError("network/session must not be created"))

    result = await PropLineService(session_factory=factory).get_sportsbook_odds(
        players=["Josh Allen"], scope="season"
    )

    assert result["status"] == "error"
    assert result["error"] == {
        "code": "not_configured",
        "message": "PROPLINE_API_KEY is not configured",
        "stage": "configuration",
    }
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code", "http_status"),
    [
        (FakeResponse({}, status=302), "invalid_response", 302),
        (FakeResponse({}, status=401), "invalid_credentials", 401),
        (FakeResponse({}, status=403), "access_denied", 403),
        (FakeResponse({}, status=503), "provider_error", 503),
        (FakeResponse(raw=b"not-json"), "invalid_response", None),
        (FakeResponse("scalar"), "invalid_response", None),
        (FakeResponse({}, content_length=MAX_RESPONSE_BYTES + 1), "invalid_response", None),
        (
            FakeResponse(raw=b"x" * (MAX_RESPONSE_BYTES + 1), content_length=None),
            "invalid_response",
            None,
        ),
    ],
)
async def test_stable_provider_error_mapping(
    response: FakeResponse, code: str, http_status: int | None
) -> None:
    routes = {"/v1/sports/football_nfl/futures": [response]}
    service, _, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="season")

    assert result["status"] == "error"
    assert result["error"]["code"] == code
    assert result["error"].get("http_status") == http_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (asyncio.TimeoutError(), "provider_timeout"),
        (aiohttp.ClientConnectionError("offline"), "provider_error"),
    ],
)
async def test_timeout_and_transport_failures_have_stable_errors(
    failure: BaseException, code: str
) -> None:
    routes = {"/v1/sports/football_nfl/futures": [failure]}
    service, _, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="season")

    assert result["status"] == "error"
    assert result["error"]["code"] == code


@pytest.mark.asyncio
async def test_exact_host_allowlist_blocks_request_before_session_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(propline_service, "BASE_URL", "https://evil.example/v1")
    service, factory, _ = make_service({})

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="season")

    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_request"
    assert factory.calls == []


@pytest.mark.asyncio
async def test_event_and_total_request_caps() -> None:
    upcoming = [event(f"e{index:02}", hours=index + 1) for index in range(MAX_EVENTS + 2)]
    routes: dict[str, list[Any]] = {
        "/v1/sports/football_nfl/futures": [FakeResponse([futures_odds()])],
        "/v1/sports/football_nfl/events": [FakeResponse(upcoming)],
    }
    for item in upcoming[:MAX_EVENTS]:
        routes[f"/v1/sports/football_nfl/events/{item['id']}/odds"] = [
            FakeResponse(game_odds(item["id"]))
        ]
    service, factory, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="auto")

    assert len(factory.calls) == MAX_EVENTS + 2
    assert result["status"] == "partial"
    assert "Only the first 16 upcoming events were scanned" in result["warnings"]


@pytest.mark.asyncio
async def test_result_bound_marks_partial() -> None:
    outcomes = [
        {
            "name": f"Selection {index}",
            "description": "Josh Allen",
            "player_id": "player-17",
            "point": index,
            "price": -110,
        }
        for index in range(MAX_RESULTS + 1)
    ]
    routes = {
        "/v1/sports/football_nfl/events": [FakeResponse([event("one")])],
        "/v1/sports/football_nfl/events/one/odds": [
            FakeResponse(game_odds("one", outcomes=outcomes))
        ],
    }
    service, _, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="next_game")

    assert result["status"] == "partial"
    assert len(result["results"]) == MAX_RESULTS
    assert "Results were truncated to 500 rows" in result["warnings"]


@pytest.mark.asyncio
async def test_request_concurrency_never_exceeds_four() -> None:
    tracker = ActivityTracker()
    upcoming = [event(f"e{index}", hours=index + 1) for index in range(8)]
    routes: dict[str, list[Any]] = {"/v1/sports/football_nfl/events": [FakeResponse(upcoming)]}
    for item in upcoming:
        routes[f"/v1/sports/football_nfl/events/{item['id']}/odds"] = [
            FakeResponse(game_odds(item["id"]), delay=0.01, tracker=tracker)
        ]
    service, _, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="next_game")

    assert result["status"] == "ok"
    assert result["unmatched"][0]["reason"] == "ambiguous"
    assert tracker.maximum == MAX_CONCURRENCY


@pytest.mark.asyncio
async def test_cache_ttls_lru_bound_mixed_freshness_and_quota() -> None:
    clock = TickingClock()
    routes = {
        "/v1/sports/football_nfl/futures": [
            FakeResponse([futures_odds()], headers=quota_headers(90))
        ],
        "/v1/sports/football_nfl/events": [
            FakeResponse([event("one")], headers=quota_headers(80)),
            FakeResponse([event("one")], headers=quota_headers(70)),
        ],
        "/v1/sports/football_nfl/events/one/odds": [
            FakeResponse(game_odds("one"), headers=quota_headers(75)),
            FakeResponse(game_odds("one"), headers=quota_headers(65)),
        ],
    }
    service, factory, _ = make_service(routes, clock)

    first = await service.get_sportsbook_odds(players=["Josh Allen"], scope="auto")
    clock.advance(EVENT_TTL_SECONDS + 1)
    second = await service.get_sportsbook_odds(players=["Josh Allen"], scope="auto")
    third = await service.get_sportsbook_odds(players=["Josh Allen"], scope="auto")

    assert first["status"] == second["status"] == third["status"] == "ok"
    assert factory.calls_by_path["/v1/sports/football_nfl/futures"] == 1
    assert factory.calls_by_path["/v1/sports/football_nfl/events"] == 2
    second_sources = {source["id"]: source for source in second["sources"]}
    assert second_sources["futures"]["served_from_cache"] is True
    assert second_sources["events"]["served_from_cache"] is False
    assert second_sources["event:one"]["served_from_cache"] is False
    assert second["quota"]["source"] == "live"
    assert second["quota"]["remaining"] == 65
    assert third["quota"]["source"] == "cache"
    assert third["quota"]["remaining"] == 65
    assert (
        next(source for source in third["sources"] if source["id"] == "futures")[
            "cache_age_seconds"
        ]
        == 61.0
    )
    assert len(service._cache) <= CACHE_SIZE
    assert FUTURES_TTL_SECONDS > EVENT_TTL_SECONDS


@pytest.mark.asyncio
async def test_cache_evicts_least_recently_used_entry_at_128() -> None:
    service, _, _ = make_service({})
    quota = {"as_of": "2026-08-31T16:00:00Z", "limit": 1000, "remaining": 900, "reset": None}
    for index in range(CACHE_SIZE + 1):
        component = propline_service.Component(
            source_id=f"event:e{index}",
            kind="event_odds",
            event_id=f"e{index}",
            payload=game_odds(f"e{index}"),
            fetched_at="2026-08-31T16:00:00Z",
            served_from_cache=False,
            cache_age_seconds=0.0,
            cache_ttl_seconds=EVENT_TTL_SECONDS,
            quota=quota,
        )
        await service._cache_put((f"endpoint-{index}", "football_nfl", (), ()), component)

    assert len(service._cache) == CACHE_SIZE
    assert ("endpoint-0", "football_nfl", (), ()) not in service._cache
    assert (f"endpoint-{CACHE_SIZE}", "football_nfl", (), ()) in service._cache


@pytest.mark.asyncio
async def test_request_and_overall_timeouts_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(propline_service, "OVERALL_TIMEOUT_SECONDS", 0.001)
    routes = {"/v1/sports/football_nfl/futures": [FakeResponse([futures_odds()], delay=0.05)]}
    service, factory, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="season")

    assert result["status"] == "error"
    assert result["error"]["code"] == "provider_timeout"
    assert factory.session_kwargs[0]["timeout"].total == 5


@pytest.mark.asyncio
async def test_first_429_stops_scheduling_cancels_inflight_and_never_retries() -> None:
    tracker = ActivityTracker()
    upcoming = [event(f"e{index}", hours=index + 1) for index in range(8)]
    routes: dict[str, list[Any]] = {
        "/v1/sports/football_nfl/events": [FakeResponse(upcoming)],
        "/v1/sports/football_nfl/events/e0/odds": [
            FakeResponse({}, status=429, headers={"Retry-After": "7", **quota_headers(0)})
        ],
    }
    for item in upcoming[1:]:
        routes[f"/v1/sports/football_nfl/events/{item['id']}/odds"] = [
            FakeResponse(game_odds(item["id"]), delay=1, tracker=tracker)
        ]
    service, factory, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="next_game")

    event_odds_calls = [url for url, _ in factory.calls if url.endswith("/odds")]
    assert result["status"] == "partial"
    assert result["error"] == {
        "code": "rate_limited",
        "message": "PropLine rate limit reached",
        "stage": "event:e0",
        "http_status": 429,
        "retry_after_seconds": 7,
    }
    assert len(event_odds_calls) == MAX_CONCURRENCY
    assert len(set(event_odds_calls)) == len(event_odds_calls)
    assert tracker.cancelled == MAX_CONCURRENCY - 1
    assert result["quota"]["remaining"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_concurrent_failure_precedence_is_deterministic(reverse: bool) -> None:
    service, _, _ = make_service({})
    failures = [
        propline_service.ProviderFailure(
            "rate_limited",
            "PropLine rate limit reached",
            "event:z",
            http_status=429,
            retry_after_seconds=3,
        ),
        propline_service.ProviderFailure(
            "provider_error",
            "PropLine request failed",
            "event:b",
            http_status=503,
        ),
        propline_service.ProviderFailure(
            "rate_limited",
            "PropLine rate limit reached",
            "event:a",
            http_status=429,
            retry_after_seconds=11,
        ),
    ]
    if reverse:
        failures.reverse()
    expected = next(failure for failure in failures if failure.code == "rate_limited")

    for _ in range(12):
        started = 0
        release = asyncio.Event()

        def factory(
            failure: propline_service.ProviderFailure,
            barrier: asyncio.Event = release,
        ):
            async def fail() -> propline_service.Component:
                nonlocal started
                started += 1
                if started == len(failures):
                    barrier.set()
                await barrier.wait()
                raise failure

            return fail

        _, recorded, halted = await service._run_rolling([factory(failure) for failure in failures])
        selected = service._primary_failure(recorded)

        assert halted is True
        assert selected.envelope() == expected.envelope()


@pytest.mark.asyncio
async def test_concurrent_non_rate_limit_failures_use_planned_order() -> None:
    service, _, _ = make_service({})
    release = asyncio.Event()
    started = 0
    failures = [
        propline_service.ProviderFailure(
            "provider_timeout", "PropLine request timed out", "event:first"
        ),
        propline_service.ProviderFailure(
            "invalid_credentials",
            "PropLine rejected the configured API key",
            "event:second",
            http_status=401,
        ),
    ]

    def factory(failure: propline_service.ProviderFailure):
        async def fail() -> propline_service.Component:
            nonlocal started
            started += 1
            if started == len(failures):
                release.set()
            await release.wait()
            raise failure

        return fail

    _, recorded, halted = await service._run_rolling([factory(failure) for failure in failures])

    assert halted is False
    assert service._primary_failure(recorded).envelope() == failures[0].envelope()


@pytest.mark.asyncio
async def test_all_failed_is_error_but_completed_empty_component_is_partial() -> None:
    failed_routes = {"/v1/sports/football_nfl/futures": [FakeResponse({}, status=429)]}
    failed_service, _, _ = make_service(failed_routes)
    failed = await failed_service.get_sportsbook_odds(players=["Josh Allen"], scope="season")

    partial_routes = {
        "/v1/sports/football_nfl/futures": [FakeResponse([futures_odds()])],
        "/v1/sports/football_nfl/events": [FakeResponse({}, status=503)],
    }
    partial_service, _, _ = make_service(partial_routes)
    partial = await partial_service.get_sportsbook_odds(players=["Nobody"], scope="auto")

    assert failed["status"] == "error"
    assert failed["error"]["code"] == "rate_limited"
    assert partial["status"] == "partial"
    assert partial["error"]["code"] == "provider_error"


@pytest.mark.asyncio
async def test_secret_is_only_sent_in_header_and_never_returned() -> None:
    routes = {"/v1/sports/football_nfl/futures": [FakeResponse({}, status=401)]}
    service, factory, _ = make_service(routes)

    result = await service.get_sportsbook_odds(players=["Josh Allen"], scope="season")

    assert factory.session_kwargs[0]["headers"] == {"X-API-Key": API_KEY}
    assert API_KEY not in json.dumps(result)
    assert all(API_KEY not in url for url, _ in factory.calls)
