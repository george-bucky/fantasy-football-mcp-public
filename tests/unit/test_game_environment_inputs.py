"""Offline venue/weather binding and score-history tests."""

import csv
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.game_environment_inputs import (
    SCHEDULE_URL,
    STADIUMS_URL,
    GameEnvironmentInputsService,
)

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
START = datetime(2026, 11, 5, 18, tzinfo=timezone.utc)


def csv_bytes(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def schedule_row(**kwargs):
    row = {
        "game_id": "2026_10_BUF_KC",
        "season": "2026",
        "week": "10",
        "game_type": "REG",
        "home_team": "KC",
        "away_team": "BUF",
        "gameday": "2026-11-05",
        "gametime": "13:00",
        "stadium_id": "KAN00",
        "stadium": "Arrowhead Stadium",
        "roof": "outdoors",
        "home_score": "",
        "away_score": "",
    }
    row.update(kwargs)
    return row


def binding():
    return {"game_id": "2026_10_BUF_KC", "home_team": "KC", "away_team": "BUF", "kickoff": START}


def setup(*, schedule=None, venue=None):
    rows = (
        schedule
        if schedule is not None
        else [
            schedule_row(),
            schedule_row(
                game_id="2026_09_KC_BUF",
                week="9",
                gameday="2026-11-01",
                home_team="BUF",
                away_team="KC",
                home_score="0",
                away_score="21",
            ),
        ]
    )
    venues = (
        venue
        if venue is not None
        else [
            {
                "stadium_id": "KAN00",
                "stadium_name": "Arrowhead Stadium",
                "lat": "39.0489",
                "lon": "-94.4839",
                "country": "United States",
                "roof_type": "Dome",
            }
        ]
    )
    fetch = AsyncMock(side_effect=lambda url: csv_bytes(rows if url == SCHEDULE_URL else venues))
    weather = SimpleNamespace(
        get_evidence=AsyncMock(return_value={"available": True, "forecast_periods": []})
    )
    service = GameEnvironmentInputsService(fetcher=fetch, weather_service=weather, now=lambda: NOW)
    return service, fetch, weather


@pytest.mark.asyncio
async def test_exact_id_name_game_binding_weather_dedup_and_zero_history():
    service, fetch, weather = setup()
    output = await service.collect([binding(), binding()], season=2026, week=10)
    report = output["games"][binding()["game_id"]]
    assert report["available"]
    assert fetch.await_count == 2
    assert weather.get_evidence.await_count == 1
    context = weather.get_evidence.call_args.kwargs["venue"]
    assert context.exposure == "exposed"  # ignores static registry's bogus Dome
    assert context.stadium_id == "KAN00"
    assert {row["team"]: row["points"] for row in report["team_points_history"]} == {
        "BUF": 0.0,
        "KC": 21.0,
    }
    assert all(row["known_at"] == NOW.isoformat() for row in report["team_points_history"])
    assert all(row["period"] == "full_game" for row in report["team_points_history"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roof,exposure",
    [("open", "unknown"), ("closed", "unknown"), ("", "unknown"), ("dome", "sheltered")],
)
async def test_retractable_roof_never_defaults_closed(roof, exposure):
    service, _, weather = setup(schedule=[schedule_row(roof=roof)])
    await service.collect([binding()], season=2026, week=10)
    assert weather.get_evidence.call_args.kwargs["venue"].exposure == exposure


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        {"home_team": "BUF", "away_team": "KC"},
        {"kickoff": START + timedelta(hours=1)},
        {"game_id": "wrong"},
    ],
)
async def test_wrong_game_binding_does_not_get_weather(mutation):
    service, _, weather = setup()
    row = binding()
    row.update(mutation)
    result = await service.collect([row], season=2026, week=10)
    assert not result["games"][row["game_id"]]["available"]
    weather.get_evidence.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"stadium_id": "OTHER"}, "stadium_id_coordinates_missing_or_ambiguous"),
        ({"stadium_name": "Different Venue"}, "stadium_name_id_binding_mismatch"),
        ({"lat": "nan"}, "stadium_coordinates_invalid"),
        ({"country": "United Kingdom"}, "nws_outside_us_coverage"),
    ],
)
async def test_bad_or_foreign_venue_is_explicit(changes, reason):
    venue = {
        "stadium_id": "KAN00",
        "stadium_name": "Arrowhead Stadium",
        "lat": "39",
        "lon": "-94",
        "country": "United States",
    }
    venue.update(changes)
    service, _, weather = setup(venue=[venue])
    result = await service.collect([binding()], season=2026, week=10)
    assert reason in result["games"][binding()["game_id"]]["unavailable_reasons"]
    weather.get_evidence.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_excludes_missing_scores_future_current_week_and_duplicates():
    history = schedule_row(
        game_id="old", week="9", gameday="2026-11-01", home_score="7", away_score=""
    )
    future = dict(history, game_id="future", away_score="3", gameday="2026-11-04")
    duplicate = dict(history, game_id="duplicate", away_score="0")
    service, _, _ = setup(schedule=[schedule_row(), history, future, duplicate, duplicate])
    report = (await service.collect([binding()], season=2026, week=10))["games"][
        binding()["game_id"]
    ]
    assert report["team_points_history"] == []


@pytest.mark.asyncio
async def test_cache_keeps_original_times_and_does_not_fetch_again():
    service, fetch, _ = setup()
    first = await service.collect([binding()], season=2026, week=10)
    service.now = lambda: NOW + timedelta(seconds=20)
    second = await service.collect([binding()], season=2026, week=10)
    assert fetch.await_count == 2
    gid = binding()["game_id"]
    assert second["games"][gid]["sources"] == first["games"][gid]["sources"]


@pytest.mark.asyncio
async def test_conflicting_duplicate_bindings_never_win_by_order():
    service, _, weather = setup()
    bad = dict(binding(), away_team="NYJ")
    output = await service.collect([binding(), bad], season=2026, week=10)
    assert output["games"][binding()["game_id"]]["unavailable_reasons"] == [
        "conflicting_game_bindings"
    ]
    weather.get_evidence.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_omits_provider_exception_text_and_keeps_score_history():
    service, fetch, weather = setup()
    original = fetch.side_effect

    async def broken(url):
        if url == STADIUMS_URL:
            raise RuntimeError("private exception payload")
        return original(url)

    fetch.side_effect = broken
    output = await service.collect([binding()], season=2026, week=10)
    assert "stadium_registry_unavailable" in output["warnings"]
    assert "private exception payload" not in str(output)
    assert len(output["games"][binding()["game_id"]]["team_points_history"]) == 2
    weather.get_evidence.assert_not_awaited()


@pytest.mark.asyncio
async def test_known_retractable_history_prevents_using_placeholder_outdoors_as_exposed():
    service, _, weather = setup(
        schedule=[
            schedule_row(),
            schedule_row(
                game_id="prior",
                week="9",
                gameday="2026-11-01",
                roof="closed",
                home_score="21",
                away_score="10",
            ),
        ]
    )
    output = await service.collect([binding()], season=2026, week=10)
    assert weather.get_evidence.call_args.kwargs["venue"].exposure == "unknown"
    assert (
        output["games"][binding()["game_id"]]["sources"]["coordinates"]["license"]
        == "not_published_or_verified"
    )


@pytest.mark.asyncio
async def test_fixed_download_rejects_arbitrary_urls_before_network():
    with pytest.raises(ValueError, match="untrusted_source"):
        await GameEnvironmentInputsService._download("https://example.com/coordinates.csv")


@pytest.mark.asyncio
async def test_weather_disabled_fetches_only_schedule_and_retains_available_history():
    service, fetch, weather = setup()
    output = await service.collect([binding()], season=2026, week=10, include_weather=False)
    fetch.assert_awaited_once_with(SCHEDULE_URL)
    weather.get_evidence.assert_not_awaited()
    report = output["games"][binding()["game_id"]]
    assert report["available"]
    assert report["history_available"]
    assert len(report["team_points_history"]) == 2
    assert report["weather"] == {"available": False, "reason": "disabled_by_request"}
    assert not report.get("venue")
    assert not report["unavailable_reasons"]
    assert "stadium_registry_unavailable" not in output["warnings"]


@pytest.mark.asyncio
async def test_weather_disabled_history_does_not_require_venue_schema():
    rows = [
        schedule_row(),
        schedule_row(
            game_id="old", week="9", gameday="2026-11-01", home_score="0", away_score="10"
        ),
    ]
    for row in rows:
        for key in ("stadium_id", "stadium", "roof"):
            row.pop(key)
    service, fetch, weather = setup(schedule=rows)
    output = await service.collect([binding()], season=2026, week=10, include_weather=False)
    report = output["games"][binding()["game_id"]]
    assert report["history_available"]
    fetch.assert_awaited_once_with(SCHEDULE_URL)
    weather.get_evidence.assert_not_awaited()
