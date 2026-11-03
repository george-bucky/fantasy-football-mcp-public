"""Bounded NWS forecast evidence; no player projections or weather coefficients.

The caller supplies an independently verified, game-specific venue binding. This
adapter does not geocode stadium names, guess roof status, or fetch observations.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import aiohttp

API_ORIGIN = "https://api.weather.gov"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_PERIODS = 200
_HOURLY_PATH = re.compile(r"/gridpoints/[A-Z]{3}/-?\d+,-?\d+/forecast/hourly\Z")
_WIND = re.compile(r"(\d+(?:\.\d+)?)(?:\s+to\s+(\d+(?:\.\d+)?))?\s+(mph|km/h|m/s|knots|kts)\Z")


class WeatherEvidenceError(ValueError):
    """A fixed, public error code, never provider response text."""


@dataclass(frozen=True)
class VenueContext:
    """Verified schedule/venue input, not a stadium-name lookup result.

    ``exposure`` is exposed, sheltered, or unknown. Sheltered includes a
    verified closed roof. A retractable roof without current verification is
    unknown, not sheltered or exposed. ``verified_at`` timestamps that evidence.
    """

    game_id: str
    stadium_id: str
    latitude: float
    longitude: float
    exposure: str
    source: str
    verified_at: datetime
    verified: bool = False


def _utc(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise WeatherEvidenceError("invalid_timestamp") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WeatherEvidenceError("invalid_timestamp")
    return value.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        normalized = float(value)
    except (OverflowError, ValueError):
        return None
    return normalized if math.isfinite(normalized) else None


def _json(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or len(payload) > MAX_RESPONSE_BYTES:
        raise WeatherEvidenceError("response_size_invalid")
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeError):
        raise WeatherEvidenceError("invalid_response") from None
    if not isinstance(value, dict):
        raise WeatherEvidenceError("invalid_response")
    return value


def _hourly_url(value: Any) -> str:
    if not isinstance(value, str):
        raise WeatherEvidenceError("hourly_endpoint_missing")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.weather.gov"
        or parsed.query
        or parsed.fragment
        or not _HOURLY_PATH.fullmatch(parsed.path)
    ):
        raise WeatherEvidenceError("unsafe_hourly_endpoint")
    return value


def _inside_polygon(geometry: Any, longitude: float, latitude: float) -> bool:
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        return False
    rings = geometry.get("coordinates")
    if not isinstance(rings, list) or not rings:
        return False

    def contains(ring: Any) -> bool:
        if not isinstance(ring, list) or not 4 <= len(ring) <= 100:
            return False
        points = []
        for point in ring:
            if not isinstance(point, list) or len(point) < 2:
                return False
            x, y = _number(point[0]), _number(point[1])
            if x is None or y is None:
                return False
            points.append((x, y))
        if points[0] != points[-1]:
            return False
        result = False
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            # Include boundary points without dividing by zero on horizontal edges.
            cross = (longitude - x1) * (y2 - y1) - (latitude - y1) * (x2 - x1)
            if (
                abs(cross) < 1e-10
                and min(x1, x2) <= longitude <= max(x1, x2)
                and min(y1, y2) <= latitude <= max(y1, y2)
            ):
                return True
            if (y1 > latitude) != (y2 > latitude):
                if longitude < (x2 - x1) * (latitude - y1) / (y2 - y1) + x1:
                    result = not result
        return result

    return contains(rings[0]) and not any(contains(ring) for ring in rings[1:])


def _wind_speed(value: Any) -> dict[str, float] | None:
    factors = {"mph": 0.44704, "km/h": 1 / 3.6, "m/s": 1.0, "knots": 0.514444, "kts": 0.514444}
    if isinstance(value, str):
        if value.strip().casefold() == "calm":
            return {"minimum": 0.0, "maximum": 0.0}
        match = _WIND.fullmatch(value.strip())
        if not match:
            return None
        low, high = _number(float(match[1])), _number(float(match[2] or match[1]))
        if low is None or high is None:
            return None
        factor = factors[match[3]]
    elif isinstance(value, dict):
        low = high = _number(value.get("value"))
        factor = {"wmoUnit:km_h-1": 1 / 3.6, "wmoUnit:m_s-1": 1.0, "wmoUnit:mi_h-1": 0.44704}.get(
            value.get("unitCode")
        )
        if low is None or factor is None:
            return None
    else:
        return None
    if low < 0 or high < low:
        return None
    return {"minimum": round(low * factor, 5), "maximum": round(high * factor, 5)}


def _period(value: dict[str, Any]) -> dict[str, Any]:
    start, end = _utc(value.get("startTime")), _utc(value.get("endTime"))
    if not timedelta(0) < end - start <= timedelta(hours=1):
        raise WeatherEvidenceError("invalid_period")
    temperature = value.get("temperature")
    unit = value.get("temperatureUnit")
    if isinstance(temperature, dict):
        unit = {"wmoUnit:degC": "C", "wmoUnit:degF": "F"}.get(temperature.get("unitCode"))
        temperature = temperature.get("value")
    temperature = _number(temperature)
    celsius = (
        temperature
        if unit == "C"
        else ((temperature - 32) * 5 / 9 if unit == "F" and temperature is not None else None)
    )
    precipitation = value.get("probabilityOfPrecipitation")
    probability = (
        _number(precipitation.get("value"))
        if isinstance(precipitation, dict) and precipitation.get("unitCode") == "wmoUnit:percent"
        else None
    )
    if probability is not None and not 0 <= probability <= 100:
        probability = None
    celsius = _number(celsius)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "temperature_c": round(celsius, 4) if celsius is not None else None,
        "sustained_wind_m_s": _wind_speed(value.get("windSpeed")),
        "gust_wind_m_s": _wind_speed(value.get("windGust")),
        "precipitation_probability": probability / 100 if probability is not None else None,
        # NWS hourly point forecasts do not promise precipitation amounts.
        "precipitation_amount_mm": None,
        "summary": (
            value.get("shortForecast") if isinstance(value.get("shortForecast"), str) else None
        ),
    }


class WeatherEvidenceService:
    """Fetch two fixed-origin NWS documents under one bounded request budget."""

    def __init__(
        self,
        *,
        fetcher: Callable[[str], Awaitable[bytes]] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        game_hours: int = 3,
        cache_seconds: int = 300,
        max_forecast_age_seconds: int = 7200,
        max_venue_age_seconds: int = 86400,
        total_timeout_seconds: float = 8.0,
    ) -> None:
        if (
            not 1 <= game_hours <= 6
            or min(
                cache_seconds,
                max_forecast_age_seconds,
                max_venue_age_seconds,
                total_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("Invalid weather evidence bounds")
        self._fetcher = fetcher or self._download
        self._now = now
        self.game_hours = game_hours
        self.cache_seconds = cache_seconds
        self.max_forecast_age_seconds = max_forecast_age_seconds
        self.max_venue_age_seconds = max_venue_age_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self._cache: OrderedDict[tuple[Any, ...], tuple[datetime, dict[str, Any]]] = OrderedDict()

    @staticmethod
    async def _download(url: str) -> bytes:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.weather.gov"
            or parsed.query
            or parsed.fragment
            or not (
                _HOURLY_PATH.fullmatch(parsed.path)
                or re.fullmatch(r"/points/-?\d+\.\d{4},-?\d+\.\d{4}", parsed.path)
            )
        ):
            raise WeatherEvidenceError("unsafe_provider_endpoint")
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(
            timeout=timeout,
            trust_env=True,
            headers={
                "User-Agent": "fantasy-football-mcp/weekly-weather",
                "Accept": "application/geo+json",
            },
        ) as session:
            async with session.get(url, allow_redirects=False) as response:
                if response.status != 200:
                    raise WeatherEvidenceError("provider_unavailable")
                if (
                    response.content_length is not None
                    and response.content_length > MAX_RESPONSE_BYTES
                ):
                    raise WeatherEvidenceError("response_size_invalid")
                payload = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    payload.extend(chunk)
                    if len(payload) > MAX_RESPONSE_BYTES:
                        raise WeatherEvidenceError("response_size_invalid")
                return bytes(payload)

    async def get_evidence(
        self, *, game_id: str, kickoff: datetime, venue: VenueContext
    ) -> dict[str, Any]:
        now = _utc(self._now())
        result: dict[str, Any] = {
            "status": "unavailable",
            "available": False,
            "applied": False,
            "influence": "forecast_evidence_only",
            "game_id": game_id,
            "forecast_periods": [],
            "projection_delta": None,
            "warnings": [],
        }
        try:
            kickoff = _utc(kickoff)
            verified_at = _utc(venue.verified_at)
            if (
                not game_id
                or venue.game_id != game_id
                or not venue.verified
                or not venue.stadium_id
                or not venue.source.strip()
            ):
                raise WeatherEvidenceError("venue_binding_unverified")
            lat, lon = _number(venue.latitude), _number(venue.longitude)
            if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise WeatherEvidenceError("invalid_coordinates")
            if (
                verified_at > now
                or (now - verified_at).total_seconds() > self.max_venue_age_seconds
            ):
                raise WeatherEvidenceError("venue_evidence_stale")
            result["venue"] = {
                "stadium_id": venue.stadium_id,
                "latitude": lat,
                "longitude": lon,
                "exposure": venue.exposure,
                "source": venue.source,
                "verified_at": verified_at.isoformat(),
            }

            def current_context_time() -> datetime:
                current = _utc(self._now())
                if kickoff <= current:
                    raise WeatherEvidenceError("game_already_started")
                if current < now:
                    raise WeatherEvidenceError("clock_moved_backwards")
                if (
                    verified_at > current
                    or (current - verified_at).total_seconds() > self.max_venue_age_seconds
                ):
                    raise WeatherEvidenceError("venue_evidence_stale")
                return current

            current_context_time()
            if venue.exposure == "sheltered":
                result.update(status="not_applicable", reason="verified_sheltered_venue")
                return result
            if venue.exposure != "exposed":
                raise WeatherEvidenceError("roof_exposure_unknown")
            end = kickoff + timedelta(hours=self.game_hours)
            result["window"] = {"start": kickoff.isoformat(), "end": end.isoformat()}
            key = (
                game_id,
                kickoff.isoformat(),
                lat,
                lon,
                venue.stadium_id,
                venue.exposure,
                venue.source,
                verified_at.isoformat(),
            )
            cached = self._cache.get(key)
            current = current_context_time()
            if cached is not None and cached[0] > current:
                source = cached[1]["source"]
                if _utc(source["issued_at"]) > current or _utc(source["fetched_at"]) > current:
                    raise WeatherEvidenceError("cached_evidence_from_future")
                self._cache.move_to_end(key)
                return copy.deepcopy(cached[1])
            async with asyncio.timeout(self.total_timeout_seconds):
                points_url = f"{API_ORIGIN}/points/{lat:.4f},{lon:.4f}"
                points = _json(await self._fetcher(points_url))
                geometry = points.get("geometry", {})
                coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
                if (
                    not isinstance(coordinates, list)
                    or len(coordinates) != 2
                    or geometry.get("type") != "Point"
                    or any(_number(x) is None for x in coordinates)
                    or abs(coordinates[0] - lon) > 0.00011
                    or abs(coordinates[1] - lat) > 0.00011
                ):
                    raise WeatherEvidenceError("point_location_mismatch")
                properties = points.get("properties")
                if not isinstance(properties, dict):
                    raise WeatherEvidenceError("invalid_point_response")
                hourly_url = _hourly_url(properties.get("forecastHourly"))
                payload = await self._fetcher(hourly_url)
                forecast = _json(payload)
            if not _inside_polygon(forecast.get("geometry"), lon, lat):
                raise WeatherEvidenceError("forecast_location_unverified")
            properties = forecast.get("properties", {})
            if not isinstance(properties, dict):
                raise WeatherEvidenceError("invalid_forecast_response")
            issued_at = _utc(properties.get("updateTime") or properties.get("updated"))
            fetched_at = current_context_time()
            if (
                issued_at > fetched_at
                or (fetched_at - issued_at).total_seconds() > self.max_forecast_age_seconds
            ):
                raise WeatherEvidenceError("forecast_stale_or_future")
            raw_periods = properties.get("periods")
            if (
                not isinstance(raw_periods, list)
                or not raw_periods
                or len(raw_periods) > MAX_PERIODS
            ):
                raise WeatherEvidenceError("invalid_periods")
            periods = []
            for raw in raw_periods:
                if not isinstance(raw, dict):
                    raise WeatherEvidenceError("invalid_period")
                normalized = _period(raw)
                if _utc(normalized["end"]) > kickoff and _utc(normalized["start"]) < end:
                    periods.append(normalized)
            periods.sort(key=lambda value: value["start"])
            cursor = kickoff
            for period in periods:
                start, finish = _utc(period["start"]), _utc(period["end"])
                if start > cursor or (start < cursor and cursor != kickoff):
                    raise WeatherEvidenceError("forecast_window_incomplete_or_ambiguous")
                cursor = min(finish, end)
            if cursor < end:
                raise WeatherEvidenceError("forecast_window_incomplete_or_ambiguous")
            missing = sorted(
                {
                    field
                    for period in periods
                    for field in (
                        "temperature_c",
                        "sustained_wind_m_s",
                        "precipitation_probability",
                    )
                    if period[field] is None
                }
            )
            if all(
                period[field] is None
                for period in periods
                for field in ("temperature_c", "sustained_wind_m_s", "precipitation_probability")
            ):
                raise WeatherEvidenceError("forecast_values_unavailable")
            assessed_at = current_context_time()
            if (assessed_at - issued_at).total_seconds() > self.max_forecast_age_seconds:
                raise WeatherEvidenceError("forecast_stale_or_future")
            result.update(
                status="partial" if missing else "available",
                available=True,
                forecast_periods=periods,
                warnings=[f"Missing forecast field: {field}" for field in missing],
                source={
                    "provider": "NWS",
                    "kind": "forecast",
                    "points_url": points_url,
                    "forecast_url": hourly_url,
                    "issued_at": issued_at.isoformat(),
                    "generated_at": properties.get("generatedAt"),
                    "fetched_at": fetched_at.isoformat(),
                    "assessed_at": assessed_at.isoformat(),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
            )
            expiry = min(
                fetched_at + timedelta(seconds=self.cache_seconds),
                issued_at + timedelta(seconds=self.max_forecast_age_seconds),
                verified_at + timedelta(seconds=self.max_venue_age_seconds),
                kickoff,
            )
            self._cache[key] = (expiry, copy.deepcopy(result))
            self._cache.move_to_end(key)
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
            return result
        except WeatherEvidenceError as exc:
            result["reason"] = str(exc)
        except (TimeoutError, OSError, aiohttp.ClientError):
            result["reason"] = "provider_timeout_or_unavailable"
        except (TypeError, AttributeError, ValueError):
            result["reason"] = "invalid_weather_input_or_response"
        return result
