"""Synthetic NWS documents only; no credentials, geocoding, or live weather."""

import asyncio
import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.services.weather_evidence import (
    MAX_RESPONSE_BYTES,
    VenueContext,
    WeatherEvidenceService,
)

NOW = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 11, 1, 18, tzinfo=timezone.utc)
VENUE = VenueContext(
    game_id="2026_09_MIA_BUF",
    stadium_id="synthetic-stadium",
    latitude=42.77,
    longitude=-78.79,
    exposure="exposed",
    source="synthetic-verified-schedule-and-roof",
    verified_at=NOW - timedelta(minutes=10),
    verified=True,
)
HOURLY = "https://api.weather.gov/gridpoints/BUF/1,2/forecast/hourly"


def documents():
    points = {
        "geometry": {"type": "Point", "coordinates": [-78.79, 42.77]},
        "properties": {"forecastHourly": HOURLY},
    }
    periods = []
    for index in range(4):
        start = KICKOFF + timedelta(hours=index)
        periods.append(
            {
                "startTime": start.isoformat(),
                "endTime": (start + timedelta(hours=1)).isoformat(),
                "temperature": 50,
                "temperatureUnit": "F",
                "windSpeed": "10 to 15 mph",
                "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 70},
                "shortForecast": "Rain",
            }
        )
    forecast = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-79, 42], [-78, 42], [-78, 43], [-79, 43], [-79, 42]]],
        },
        "properties": {
            "updateTime": (NOW - timedelta(minutes=20)).isoformat(),
            "generatedAt": (NOW - timedelta(minutes=5)).isoformat(),
            "periods": periods,
        },
    }
    return points, forecast


def service(points=None, forecast=None, **kwargs):
    default_points, default_forecast = documents()
    responses = [
        points if points is not None else default_points,
        forecast if forecast is not None else default_forecast,
    ]
    fetch = AsyncMock(side_effect=[json.dumps(value).encode() for value in responses])
    return WeatherEvidenceService(fetcher=fetch, now=lambda: NOW, **kwargs), fetch


async def evidence(adapter, **kwargs):
    return await adapter.get_evidence(game_id=VENUE.game_id, kickoff=KICKOFF, venue=VENUE, **kwargs)


async def test_verified_forecast_has_units_window_and_provenance():
    adapter, fetch = service()
    result = await evidence(adapter)
    assert result["status"] == "available"
    assert result["available"] is True
    assert result["applied"] is False
    assert result["projection_delta"] is None
    assert result["influence"] == "forecast_evidence_only"
    assert len(result["forecast_periods"]) == 3
    period = result["forecast_periods"][0]
    assert period["temperature_c"] == 10
    assert period["sustained_wind_m_s"] == {"minimum": 4.4704, "maximum": 6.7056}
    assert period["precipitation_probability"] == 0.7
    assert period["gust_wind_m_s"] is None
    assert period["precipitation_amount_mm"] is None
    assert result["source"]["kind"] == "forecast"
    assert result["source"]["issued_at"] != result["source"]["generated_at"]
    assert len(result["source"]["sha256"]) == 64
    assert [call.args[0] for call in fetch.await_args_list] == [
        "https://api.weather.gov/points/42.7700,-78.7900",
        HOURLY,
    ]


@pytest.mark.parametrize(
    "exposure,status,reason",
    [
        ("sheltered", "not_applicable", "verified_sheltered_venue"),
        ("unknown", "unavailable", "roof_exposure_unknown"),
        ("retractable", "unavailable", "roof_exposure_unknown"),
    ],
)
async def test_roof_exposure_is_never_guessed(exposure, status, reason):
    adapter, fetch = service()
    result = await adapter.get_evidence(
        game_id=VENUE.game_id, kickoff=KICKOFF, venue=replace(VENUE, exposure=exposure)
    )
    assert result["status"] == status
    assert result["reason"] == reason
    fetch.assert_not_awaited()


@pytest.mark.parametrize(
    "venue",
    [
        replace(VENUE, verified=False),
        replace(VENUE, game_id="other-game"),
        replace(VENUE, source=""),
        replace(VENUE, stadium_id=""),
    ],
)
async def test_unverified_venue_binding_never_fetches(venue):
    adapter, fetch = service()
    result = await adapter.get_evidence(game_id=VENUE.game_id, kickoff=KICKOFF, venue=venue)
    assert result["reason"] == "venue_binding_unverified"
    fetch.assert_not_awaited()


@pytest.mark.parametrize("updated", [NOW + timedelta(seconds=1), NOW - timedelta(hours=3)])
async def test_stale_or_future_forecast_not_treated_as_fair_weather(updated):
    _, forecast = documents()
    forecast["properties"]["updateTime"] = updated.isoformat()
    adapter, _ = service(forecast=forecast)
    result = await evidence(adapter)
    assert result["available"] is False
    assert result["reason"] == "forecast_stale_or_future"
    assert not result["forecast_periods"]


async def test_generation_time_cannot_replace_issue_time():
    _, forecast = documents()
    del forecast["properties"]["updateTime"]
    adapter, _ = service(forecast=forecast)
    assert (await evidence(adapter))["reason"] == "invalid_timestamp"


@pytest.mark.parametrize("change", ["gap", "overlap", "short", "no_periods"])
async def test_whole_game_window_required(change):
    _, forecast = documents()
    periods = forecast["properties"]["periods"]
    if change == "gap":
        periods.pop(1)
    elif change == "overlap":
        periods.insert(1, copy.deepcopy(periods[0]))
    elif change == "short":
        del periods[2:]
    else:
        periods.clear()
    adapter, _ = service(forecast=forecast)
    result = await evidence(adapter)
    assert result["available"] is False
    assert result["reason"] in {"forecast_window_incomplete_or_ambiguous", "invalid_periods"}


async def test_wrong_point_and_forecast_polygon_rejected():
    points, forecast = documents()
    points["geometry"]["coordinates"][0] = -77
    adapter, fetch = service(points=points)
    assert (await evidence(adapter))["reason"] == "point_location_mismatch"
    assert fetch.await_count == 1
    forecast["geometry"]["coordinates"] = [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
    adapter, _ = service(forecast=forecast)
    assert (await evidence(adapter))["reason"] == "forecast_location_unverified"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/gridpoints/BUF/1,2/forecast/hourly",
        "https://api.weather.gov@evil.example/gridpoints/BUF/1,2/forecast/hourly",
        "https://api.weather.gov:443/gridpoints/BUF/1,2/forecast/hourly",
        "http://api.weather.gov/gridpoints/BUF/1,2/forecast/hourly",
        HOURLY + "?redirect=elsewhere",
        "https://api.weather.gov/stations/secret/observations/latest",
    ],
)
async def test_only_fixed_origin_hourly_endpoint_allowed(url):
    points, _ = documents()
    points["properties"]["forecastHourly"] = url
    adapter, fetch = service(points=points)
    assert (await evidence(adapter))["reason"] == "unsafe_hourly_endpoint"
    assert fetch.await_count == 1


async def test_partial_fields_are_unknown_not_zero():
    _, forecast = documents()
    for period in forecast["properties"]["periods"]:
        period["probabilityOfPrecipitation"]["value"] = None
        period["windSpeed"] = "unavailable"
    adapter, _ = service(forecast=forecast)
    result = await evidence(adapter)
    assert result["status"] == "partial"
    assert result["forecast_periods"][0]["sustained_wind_m_s"] is None
    assert result["forecast_periods"][0]["precipitation_probability"] is None
    assert result["warnings"]


async def test_quantitative_temperature_and_wind_units():
    _, forecast = documents()
    for period in forecast["properties"]["periods"]:
        period["temperature"] = {"unitCode": "wmoUnit:degC", "value": -2}
        period["windSpeed"] = {"unitCode": "wmoUnit:km_h-1", "value": 36}
        period["windGust"] = "20 m/s"
    adapter, _ = service(forecast=forecast)
    period = (await evidence(adapter))["forecast_periods"][0]
    assert period["temperature_c"] == -2
    assert period["sustained_wind_m_s"] == {"minimum": 10.0, "maximum": 10.0}
    assert period["gust_wind_m_s"]["maximum"] == 20


async def test_cache_is_defensive_and_never_serves_stale_data():
    clock = [NOW]
    adapter, fetch = service()
    adapter._now = lambda: clock[0]
    first = await evidence(adapter)
    first["forecast_periods"][0]["temperature_c"] = 999
    second = await evidence(adapter)
    assert second["forecast_periods"][0]["temperature_c"] == 10
    assert fetch.await_count == 2
    clock[0] += timedelta(seconds=301)
    fetch.side_effect = OSError("synthetic network issue")
    # Connection failures can contain provider details; callers see only fixed codes.
    result = await evidence(adapter)
    assert result["available"] is False
    assert "999" not in str(result)


async def test_rescheduled_game_does_not_reuse_old_cache():
    adapter, fetch = service()
    await evidence(adapter)
    fetch.side_effect = OSError("no replacement forecast")
    result = await adapter.get_evidence(
        game_id=VENUE.game_id, kickoff=KICKOFF + timedelta(days=1), venue=VENUE
    )
    assert not result["available"]
    assert fetch.await_count == 3


async def test_dst_offset_and_partial_first_hour_cover_real_time():
    _, forecast = documents()
    # 18:00Z ==13:00 EST after the fall-back transition; offsets must compare as instants.
    for period in forecast["properties"]["periods"]:
        for name in ["startTime", "endTime"]:
            period[name] = (
                datetime.fromisoformat(period[name])
                .astimezone(timezone(timedelta(hours=-5)))
                .isoformat()
            )
    adapter, _ = service(forecast=forecast)
    result = await adapter.get_evidence(
        game_id=VENUE.game_id, kickoff=KICKOFF + timedelta(minutes=30), venue=VENUE
    )
    assert result["available"]
    assert len(result["forecast_periods"]) == 4


@pytest.mark.parametrize(
    "venue",
    [
        replace(VENUE, verified_at=NOW - timedelta(days=2)),
        replace(VENUE, verified_at=NOW + timedelta(seconds=1)),
        replace(VENUE, latitude=float("nan")),
        replace(VENUE, longitude=200),
    ],
)
async def test_invalid_or_stale_venue_never_fetches(venue):
    adapter, fetch = service()
    result = await adapter.get_evidence(game_id=VENUE.game_id, kickoff=KICKOFF, venue=venue)
    assert not result["available"]
    fetch.assert_not_awaited()


async def test_started_game_is_not_a_pregame_forecast():
    adapter, fetch = service()
    result = await adapter.get_evidence(game_id=VENUE.game_id, kickoff=NOW, venue=VENUE)
    assert result["reason"] == "game_already_started"
    fetch.assert_not_awaited()


async def test_oversize_and_timeout_are_bounded():
    fetch = AsyncMock(return_value=b"x" * (MAX_RESPONSE_BYTES + 1))
    adapter = WeatherEvidenceService(fetcher=fetch, now=lambda: NOW)
    assert (await evidence(adapter))["reason"] == "response_size_invalid"

    async def slow(_url):
        await asyncio.sleep(1)
        return b"{}"

    adapter = WeatherEvidenceService(fetcher=slow, now=lambda: NOW, total_timeout_seconds=0.01)
    assert (await evidence(adapter))["reason"] == "provider_timeout_or_unavailable"


async def test_transport_does_not_follow_redirects_and_sanitizes_error():
    import aiohttp

    adapter = WeatherEvidenceService(now=lambda: NOW)
    with patch(
        "src.services.weather_evidence.aiohttp.ClientSession",
        side_effect=aiohttp.ClientError("secret-like exception"),
    ):
        result = await evidence(adapter)
    assert result["reason"] == "provider_timeout_or_unavailable"
    assert "secret-like exception" not in str(result)


async def test_forecast_with_no_usable_values_is_unavailable():
    _, forecast = documents()
    for period in forecast["properties"]["periods"]:
        period["temperature"] = None
        period["windSpeed"] = None
        period["probabilityOfPrecipitation"]["value"] = None
    adapter, _ = service(forecast=forecast)
    result = await evidence(adapter)
    assert not result["available"]
    assert result["reason"] == "forecast_values_unavailable"


async def test_naive_kickoff_and_coordinates_not_accepted():
    adapter, fetch = service()
    result = await adapter.get_evidence(
        game_id=VENUE.game_id, kickoff=KICKOFF.replace(tzinfo=None), venue=VENUE
    )
    assert result["reason"] == "invalid_timestamp"
    result = await adapter.get_evidence(
        game_id=VENUE.game_id, kickoff=KICKOFF, venue=replace(VENUE, latitude=True)
    )
    assert result["reason"] == "invalid_coordinates"
    fetch.assert_not_awaited()


async def test_default_transport_validates_origin_before_session():
    from src.services.weather_evidence import WeatherEvidenceError

    with patch("src.services.weather_evidence.aiohttp.ClientSession") as session:
        with pytest.raises(WeatherEvidenceError, match="unsafe_provider_endpoint"):
            await WeatherEvidenceService._download("https://untrusted.example/points/1,2")
    session.assert_not_called()


async def test_default_transport_stream_cap_and_request_options():
    class Response:
        status = 200
        content_length = None
        content = None

        async def __aenter__(self):
            self.content = self
            return self

        async def __aexit__(self, *_args):
            return None

        async def iter_chunked(self, _size):
            yield b"x" * (MAX_RESPONSE_BYTES + 1)

    class Session:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return Response()

    session = Session()
    with patch(
        "src.services.weather_evidence.aiohttp.ClientSession", return_value=session
    ) as factory:
        result = await evidence(WeatherEvidenceService(now=lambda: NOW))
    assert result["reason"] == "response_size_invalid"
    assert factory.call_args.kwargs["trust_env"] is True
    assert "User-Agent" in factory.call_args.kwargs["headers"]
    assert session.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("invalid", [10**400, float("inf"), float("nan")])
async def test_overflowing_or_nonfinite_coordinates_rejected_without_fetch(invalid):
    adapter, fetch = service()
    result = await adapter.get_evidence(
        game_id=VENUE.game_id, kickoff=KICKOFF, venue=replace(VENUE, latitude=invalid)
    )
    assert result["reason"] == "invalid_coordinates"
    fetch.assert_not_awaited()


@pytest.mark.parametrize(
    "wind", ["9" * 400 + " mph", {"unitCode": "wmoUnit:km_h-1", "value": 10**400}]
)
async def test_overflowing_wind_is_unknown_never_infinite(wind):
    _, forecast = documents()
    for period in forecast["properties"]["periods"]:
        period["windSpeed"] = wind
        period["windGust"] = wind
        period["temperature"] = 10**400
        period["probabilityOfPrecipitation"]["value"] = 10**400
    adapter, _ = service(forecast=forecast)
    result = await evidence(adapter)
    assert result["reason"] == "forecast_values_unavailable"
    assert result["available"] is False
    assert not result["forecast_periods"]


async def test_fetch_finishing_after_kickoff_cannot_return_pregame_evidence():
    points, forecast = documents()
    clock = [KICKOFF - timedelta(seconds=1)]
    forecast["properties"]["updateTime"] = (KICKOFF - timedelta(minutes=1)).isoformat()

    async def fetch(url):
        if url == HOURLY:
            clock[0] = KICKOFF + timedelta(seconds=2)
            return json.dumps(forecast).encode()
        return json.dumps(points).encode()

    adapter = WeatherEvidenceService(fetcher=fetch, now=lambda: clock[0])
    result = await adapter.get_evidence(
        game_id=VENUE.game_id,
        kickoff=KICKOFF,
        venue=replace(VENUE, verified_at=KICKOFF - timedelta(minutes=2)),
    )
    assert result["available"] is False
    assert result["reason"] == "game_already_started"
    assert not result["forecast_periods"]


async def test_cached_return_rechecks_current_kickoff_and_source_times():
    adapter, fetch = service()
    await evidence(adapter)
    # Initial call still appears pregame, but the subsequent cache-context check
    # observes kickoff. A cache hit must not bypass that latest context.
    times = iter([KICKOFF - timedelta(seconds=1), KICKOFF])
    adapter._now = lambda: next(times)
    result = await evidence(adapter)
    assert result["reason"] == "game_already_started"
    assert fetch.await_count == 2
    adapter._now = lambda: NOW - timedelta(minutes=10)
    result = await evidence(adapter)
    assert result["reason"] == "cached_evidence_from_future"
