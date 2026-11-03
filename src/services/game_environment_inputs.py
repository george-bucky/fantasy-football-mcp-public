"""Live game venue, NWS forecast and prior team-score inputs from public data.

Venue coordinates come from the independently maintained greerreNFL stadium
registry (Google-Earth measurements), NOT an official NFL/nflverse location feed.
The exact nflverse stadium ID joins the registry; names/home teams never geocode
or select a home stadium. Static registry roof labels are deliberately ignored.
"""

from __future__ import annotations

import asyncio
import csv
import io
import math
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from src.services.nflverse_matchups import canonical_team
from src.services.weather_evidence import VenueContext, WeatherEvidenceService

SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
STADIUMS_URL = "https://raw.githubusercontent.com/greerreNFL/stadiums/master/data/stadiums.csv"
TRUSTED_URLS = frozenset({SCHEDULE_URL, STADIUMS_URL})
MAX_BYTES = 8 * 1024 * 1024


def _time(value: Any) -> datetime | None:
    try:
        result = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
        return result.astimezone(timezone.utc) if result.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _kickoff(row: Mapping[str, str]) -> datetime | None:
    try:
        return (
            datetime.fromisoformat(f"{row['gameday']}T{row['gametime']}")
            .replace(tzinfo=ZoneInfo("America/New_York"))
            .astimezone(timezone.utc)
        )
    except (ValueError, KeyError, TypeError):
        return None


def _rows(payload: bytes, required: set[str]) -> list[dict[str, str]]:
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise ValueError("invalid_source_size")
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("source_schema_missing")
    rows = list(reader)
    if len(rows) > 30000:
        raise ValueError("source_rows_exceeded")
    return rows


class GameEnvironmentInputsService:
    """Bounded public fetches; one weather request per unique verified game.

    collect accepts game bindings containing game_id, home_team, away_team,
    kickoff; verifies all against current raw season/week schedule. Returned
    history has exact game/team identity and observed scores, with current fetch
    timestamps; this service does not provide historical as-of guarantees.
    Retractable open/closed schedule labels alone do not prove live roof status.
    """

    def __init__(
        self,
        *,
        fetcher: Callable[..., Any] | None = None,
        weather_service: Any = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        cache_seconds: float = 300,
        timeout_seconds: float = 25,
    ):
        if cache_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError("invalid_collection_bounds")
        self.fetcher = fetcher or self._download
        self.weather = weather_service or WeatherEvidenceService(now=now)
        self.now = now
        self.cache_seconds = cache_seconds
        self.timeout_seconds = timeout_seconds
        self._cache: OrderedDict[str, tuple[datetime, bytes]] = OrderedDict()

    @staticmethod
    async def _download(url: str) -> bytes:
        if url not in TRUSTED_URLS:
            raise ValueError("untrusted_source")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            async with session.get(url, allow_redirects=False) as response:
                if response.status != 200:
                    raise ValueError("public_source_unavailable")
                payload = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    payload.extend(chunk)
                    if len(payload) > MAX_BYTES:
                        raise ValueError("source_size_exceeded")
                return bytes(payload)

    async def _source(self, url: str) -> tuple[bytes, datetime]:
        current = _time(self.now())
        if current is None:
            raise ValueError("invalid_clock")
        cached = self._cache.get(url)
        if cached and 0 <= (current - cached[0]).total_seconds() <= self.cache_seconds:
            return cached[1], cached[0]
        payload = await asyncio.wait_for(self.fetcher(url), timeout=8)
        if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
            raise ValueError("invalid_source_size")
        fetched = _time(self.now())
        if fetched is None:
            raise ValueError("invalid_clock")
        self._cache[url] = (fetched, payload)
        while len(self._cache) > 2:
            self._cache.popitem(last=False)
        return payload, fetched

    async def collect(
        self,
        games: Sequence[Mapping[str, Any]],
        *,
        season: int,
        week: int,
        as_of: datetime | None = None,
        include_weather: bool = True,
    ) -> dict[str, Any]:
        clock = _time(self.now())
        requested = _time(as_of) if as_of is not None else clock
        if (
            clock is None
            or requested is None
            or abs((clock - requested).total_seconds()) > 60
            or type(season) is not int
            or not 2000 <= season <= 2100
            or type(week) is not int
            or not 1 <= week <= 18
            or len(games) > 32
        ):
            raise ValueError("live_period_and_aware_time_required")
        output: dict[str, Any] = {"games": {}, "warnings": [], "as_of": clock.isoformat()}
        if not games:
            return output
        try:
            async with asyncio.timeout(self.timeout_seconds):
                schedule_data, schedule_at = await self._source(SCHEDULE_URL)
                schedule = _rows(
                    schedule_data,
                    {
                        "game_id",
                        "season",
                        "week",
                        "game_type",
                        "home_team",
                        "away_team",
                        "gameday",
                        "gametime",
                        "home_score",
                        "away_score",
                    }
                    | ({"stadium_id", "stadium", "roof"} if include_weather else set()),
                )
                stadium_rows, stadium_at = [], None
                if include_weather:
                    try:
                        stadium_data, stadium_at = await self._source(STADIUMS_URL)
                        stadium_rows = _rows(
                            stadium_data, {"stadium_id", "stadium_name", "lat", "lon", "country"}
                        )
                    except Exception:
                        stadium_rows, stadium_at = [], None
                        output["warnings"].append("stadium_registry_unavailable")
                stadiums: dict[str, list[dict]] = {}
                for row in stadium_rows:
                    stadiums.setdefault(row["stadium_id"], []).append(row)
                current = [
                    row
                    for row in schedule
                    if row.get("season") == str(season)
                    and row.get("week") == str(week)
                    and row.get("game_type") == "REG"
                ]
                sem = asyncio.Semaphore(2)

                async def game_report(binding: Mapping[str, Any]) -> None:
                    gid = str(binding.get("game_id") or "")
                    if not gid:
                        output["warnings"].append("game_id_missing")
                        return
                    report: dict[str, Any] = {
                        "game_id": gid,
                        "available": False,
                        "unavailable_reasons": [],
                        "team_points_history": [],
                        "sources": {
                            "schedule": {"url": SCHEDULE_URL, "fetched_at": schedule_at.isoformat()}
                        },
                    }
                    output["games"][gid] = report
                    matches = [row for row in current if row["game_id"] == gid]
                    if len(matches) != 1:
                        report["unavailable_reasons"].append("schedule_game_missing_or_ambiguous")
                        return
                    row = matches[0]
                    kickoff = _kickoff(row)
                    home, away = canonical_team(row["home_team"]), canonical_team(row["away_team"])
                    if (
                        home is None
                        or away is None
                        or home == away
                        or kickoff is None
                        or kickoff <= clock
                        or kickoff != _time(binding.get("kickoff"))
                        or canonical_team(binding.get("home_team")) != home
                        or canonical_team(binding.get("away_team")) != away
                    ):
                        report["unavailable_reasons"].append("schedule_game_binding_mismatch")
                        return
                    report.update(
                        home_team=home,
                        away_team=away,
                        kickoff=kickoff.isoformat(),
                        season=season,
                        week=week,
                    )
                    history_by_id: dict[str, list[dict]] = {}
                    for past in schedule:
                        if past.get("season") == str(season) and past.get("game_type") == "REG":
                            history_by_id.setdefault(str(past.get("game_id") or ""), []).append(
                                past
                            )
                    for past_id, rows in history_by_id.items():
                        if not past_id or len(rows) != 1:
                            continue
                        past = rows[0]
                        prior = _number(past.get("week"))
                        occurred = _kickoff(past)
                        ph, pa = canonical_team(past["home_team"]), canonical_team(
                            past["away_team"]
                        )
                        hs, aws = _number(past.get("home_score")), _number(past.get("away_score"))
                        if (
                            prior is None
                            or not prior.is_integer()
                            or not 1 <= prior < week
                            or occurred is None
                            or occurred >= clock
                            or ph is None
                            or pa is None
                            or ph == pa
                            or hs is None
                            or aws is None
                            or min(hs, aws) < 0
                            or not hs.is_integer()
                            or not aws.is_integer()
                        ):
                            continue
                        for team, score, opponent in ((ph, hs, pa), (pa, aws, ph)):
                            if team in {home, away}:
                                report["team_points_history"].append(
                                    {
                                        "game_id": past_id,
                                        "team": team,
                                        "opponent": opponent,
                                        "points": score,
                                        "season": season,
                                        "week": int(prior),
                                        "occurred_at": occurred.isoformat(),
                                        "known_at": schedule_at.isoformat(),
                                        "source": SCHEDULE_URL,
                                        "period": "full_game",
                                        "season_type": "regular",
                                        "period_id": f"{season}:regular:{int(prior)}",
                                    }
                                )
                    report["history_available"] = bool(report["team_points_history"])
                    if not include_weather:
                        report.update(
                            available=report["history_available"],
                            input_scope="game_history_only_weather_disabled",
                            weather={"available": False, "reason": "disabled_by_request"},
                        )
                        return
                    sid = str(row.get("stadium_id") or "").strip()
                    venues = stadiums.get(sid, [])
                    if not sid or len(venues) != 1 or stadium_at is None:
                        report["unavailable_reasons"].append(
                            "stadium_id_coordinates_missing_or_ambiguous"
                        )
                        return
                    venue = venues[0]
                    if not str(row.get("stadium") or "").strip() or " ".join(
                        str(row["stadium"]).casefold().split()
                    ) != " ".join(str(venue.get("stadium_name") or "").casefold().split()):
                        report["unavailable_reasons"].append("stadium_name_id_binding_mismatch")
                        return
                    lat, lon = _number(venue.get("lat")), _number(venue.get("lon"))
                    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                        report["unavailable_reasons"].append("stadium_coordinates_invalid")
                        return
                    if venue.get("country", "").strip().casefold() not in {
                        "united states",
                        "usa",
                        "us",
                    }:
                        report["unavailable_reasons"].append("nws_outside_us_coverage")
                        return
                    roof = str(row.get("roof") or "").strip().casefold()
                    # open/closed may be historical/default placeholders for retractable roofs.
                    retractable = any(
                        str(past.get("stadium_id") or "").strip() == sid
                        and str(past.get("roof") or "").strip().casefold() in {"open", "closed"}
                        for past in schedule
                    )
                    exposure = (
                        "unknown"
                        if retractable
                        else {"outdoors": "exposed", "dome": "sheltered"}.get(roof, "unknown")
                    )
                    report["sources"]["coordinates"] = {
                        "url": STADIUMS_URL,
                        "fetched_at": stadium_at.isoformat(),
                        "authority": "independent_google_earth_registry_not_official_nfl",
                        "license": "not_published_or_verified",
                        "provenance_reference": "https://github.com/greerreNFL/stadiums#data-sources",
                    }
                    context = VenueContext(
                        gid,
                        sid,
                        lat,
                        lon,
                        exposure,
                        SCHEDULE_URL + " + " + STADIUMS_URL,
                        min(schedule_at, stadium_at),
                        True,
                    )
                    report["venue"] = {
                        "stadium_id": sid,
                        "latitude": lat,
                        "longitude": lon,
                        "roof": roof or None,
                        "exposure": exposure,
                        "verified": True,
                    }
                    async with sem:
                        try:
                            report["weather"] = await self.weather.get_evidence(
                                game_id=gid, kickoff=kickoff, venue=context
                            )
                            report["available"] = bool(report["weather"].get("available"))
                        except Exception:
                            report["unavailable_reasons"].append("weather_source_unavailable")

                # Conflicting duplicate bindings must not win via task ordering.
                grouped: dict[str, list[Mapping]] = {}
                for binding in games:
                    grouped.setdefault(str(binding.get("game_id") or ""), []).append(binding)
                unique = []
                for gid, bindings in grouped.items():
                    if any(dict(item) != dict(bindings[0]) for item in bindings[1:]):
                        output["games"][gid] = {
                            "game_id": gid,
                            "available": False,
                            "team_points_history": [],
                            "unavailable_reasons": ["conflicting_game_bindings"],
                        }
                    else:
                        unique.append(bindings[0])
                await asyncio.gather(*(game_report(binding) for binding in unique))
        except asyncio.TimeoutError:
            output["warnings"].append("environment_collection_deadline_exceeded")
        except Exception:
            output["warnings"].append("schedule_source_unavailable")
        output["as_of"] = _time(self.now()).isoformat()
        return output
