"""Prepared-board failure isolation and last-known-good snapshot tests."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

import src.services.manual_draft_service as manual
from src.services.manual_draft_service import ManualDraftService

NOW = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
GOTHAM_PROFILE = {
    "profile_id": "gotham-2026",
    "season": 2026,
    "team_count": 12,
    "draft": {"type": "snake", "slot": 11},
    "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "W/R/T": 2, "DEF": 1, "BN": 5},
    "scoring": {
        "passing_yards": 0.04,
        "passing_touchdowns": 4,
        "interceptions": -2,
        "passing_40_yard_touchdowns": 1,
        "fumbles_lost": -2,
        "rushing_yards": 0.1,
        "rushing_touchdowns": 6,
        "receiving_yards": 0.1,
        "receiving_touchdowns": 6,
        "receptions": 0.5,
        "two_point_conversions": 2,
        "rushing_yard_milestones": {"100": 1, "150": 2, "200": 3},
        "receiving_yard_milestones": {"100": 1, "150": 2, "200": 3},
    },
}


def _source(provider: str) -> dict:
    source = {
        "provider": provider,
        "url": f"https://example.invalid/{provider}",
        "fetched_at": NOW.isoformat().replace("+00:00", "Z"),
        "sha256": provider * 8,
        "bytes": 100,
        "served_from_cache": False,
        "cache_ttl_seconds": 3600,
    }
    if provider == "sleeper":
        source["components"] = {
            "players": {
                "fetched_at": NOW.isoformat().replace("+00:00", "Z"),
                "sha256": "players-checksum",
                "bytes": 80,
                "cache_ttl_seconds": 24 * 60 * 60,
            },
            "trending_adds": {
                "fetched_at": NOW.isoformat().replace("+00:00", "Z"),
                "sha256": "adds-checksum",
                "bytes": 10,
                "cache_ttl_seconds": 30 * 60,
            },
            "trending_drops": {
                "fetched_at": NOW.isoformat().replace("+00:00", "Z"),
                "sha256": "drops-checksum",
                "bytes": 10,
                "cache_ttl_seconds": 30 * 60,
            },
        }
    return source


def _result(provider: str, rows: list[dict]) -> manual._ProviderResult:
    return manual._ProviderResult(provider, rows, _source(provider), [])


def _projection_rows() -> list[dict]:
    return [
        {
            "provider_id": "espn-1",
            "name": "A.J. Example",
            "position": "RB",
            "team": "PHI",
            "raw_projection_stats": {
                "rushing_yards": 1_000,
                "rushing_touchdowns": 8,
                "rushing_two_point_conversions": 0,
                "receiving_yards": 300,
                "receiving_touchdowns": 2,
                "receiving_two_point_conversions": 0,
                "receptions": 40,
                "fumbles_lost": 1,
                "_rushing_100_199_games": 4,
                "_rushing_200_plus_games": 1,
                "_receiving_100_199_games": 2,
                "_receiving_200_plus_games": 0,
            },
        },
        {
            "provider_id": "espn-2",
            "name": "Wide Example",
            "position": "WR",
            "team": "BUF",
            "raw_projection_stats": {
                "receiving_yards": 1_100,
                "receiving_touchdowns": 7,
                "receiving_two_point_conversions": 0,
                "receptions": 80,
                "fumbles_lost": 0,
                "_receiving_100_199_games": 5,
                "_receiving_200_plus_games": 0.5,
            },
        },
        {
            "provider_id": "espn-k",
            "name": "Unrostered Kicker",
            "position": "K",
            "team": "NYJ",
            "raw_projection_stats": {},
        },
    ]


def _configure_successful_sources(service: ManualDraftService, *, ecr_failure: bool) -> None:
    service._espn = AsyncMock(return_value=_result("espn", _projection_rows()))
    if ecr_failure:
        service._ecr = AsyncMock(side_effect=manual.ProviderError("ECR offline"))
    else:
        service._ecr = AsyncMock(
            return_value=_result(
                "ecr",
                [
                    {
                        "provider_id": "ecr-1",
                        "name": "AJ Example",
                        "position": "RB",
                        "team": "PHI",
                        "ecr": 10,
                    }
                ],
            )
        )
    service._ffc = AsyncMock(
        return_value=_result(
            "ffc",
            [
                {
                    "provider_id": "ffc-1",
                    "name": "AJ Example",
                    "position": "RB",
                    "team": "PHI",
                    "adp": 12,
                },
                {
                    "provider_id": "ffc-2",
                    "name": "Wide Example",
                    "position": "WR",
                    "team": "BUF",
                    "adp": 20,
                },
            ],
        )
    )
    service._sleeper = AsyncMock(
        return_value=_result(
            "sleeper",
            [
                {
                    "provider_id": "sleeper-1",
                    "name": "AJ Example",
                    "position": "RB",
                    "team": "PHI",
                    "active": True,
                    "status": "Active",
                    "depth_chart_order": 1,
                },
                {
                    "provider_id": "sleeper-2",
                    "name": "Wide Example",
                    "position": "WR",
                    "team": "BUF",
                    "active": True,
                    "status": "Active",
                    "depth_chart_order": 1,
                },
            ],
        )
    )
    history = []
    for position in ("RB", "WR"):
        for index in range(8):
            history.append(
                {
                    "season": 2025,
                    "name": f"Historical {position} {index}",
                    "position": position,
                    "team": "KC",
                    "rushing_yards": 160 if position == "RB" and index < 2 else 0,
                    "receiving_yards": 160 if position == "WR" and index < 2 else 0,
                }
            )
    service._nflverse = AsyncMock(return_value=_result("nflverse", history))


def _fail_all_sources(service: ManualDraftService) -> list[AsyncMock]:
    mocks = []
    for name in ("_espn", "_ecr", "_ffc", "_sleeper", "_nflverse"):
        provider = AsyncMock(side_effect=manual.ProviderError("offline"))
        setattr(service, name, provider)
        mocks.append(provider)
    return mocks


@pytest.mark.asyncio
async def test_one_provider_failure_keeps_a_useful_inspectable_board(tmp_path) -> None:
    service = ManualDraftService(snapshot_dir=tmp_path, now=lambda: NOW)
    _configure_successful_sources(service, ecr_failure=True)

    result = await service.prepare(deepcopy(GOTHAM_PROFILE), preview_limit=10, force_refresh=True)

    assert result["status"] == "success"
    assert result["readiness"] == "ready_with_warnings"
    assert result["board_count"] == 2
    assert all(row["position"] != "K" for row in result["board_preview"])
    assert result["source_coverage"]["ecr"]["available"] is False
    assert any("ecr unavailable" in warning for warning in result["warnings"])
    assert any("never scored as zero" in warning for warning in result["warnings"])
    first = next(row for row in result["board_preview"] if row["name"] == "A.J. Example")
    assert first["projected_points"] is not None
    assert first["replacement_level"] is not None
    assert first["vorp"] is not None
    assert first["ecr"] is None
    assert "ecr" in first["board_score"]["missing"]
    assert first["adp"] == 12
    assert first["sleeper_context"]["provider_id"] == "sleeper-1"
    rushing = next(
        value
        for value in first["milestone_estimates"]
        if value["field"] == "rushing_yard_milestones"
    )
    assert (
        rushing["threshold_methods"]["100"]["method"]
        == "nflverse_historical_split_of_espn_raw_100_199"
    )
    assert (
        rushing["threshold_methods"]["150"]["method"]
        == "nflverse_historical_split_of_espn_raw_100_199"
    )
    assert rushing["threshold_methods"]["200"]["method"].startswith("espn_raw")
    assert rushing["estimated_events"]["100"] + rushing["estimated_events"]["150"] == 4


@pytest.mark.asyncio
async def test_missing_espn_scoring_category_is_reported_as_unsupported(tmp_path) -> None:
    service = ManualDraftService(snapshot_dir=tmp_path, now=lambda: NOW)
    _configure_successful_sources(service, ecr_failure=False)
    projections = _projection_rows()
    for row in projections:
        row["raw_projection_stats"].pop("fumbles_lost", None)
    service._espn = AsyncMock(return_value=_result("espn", projections))

    result = await service.prepare(deepcopy(GOTHAM_PROFILE), force_refresh=True)

    assert "fumbles_lost" in result["unsupported_scoring_fields"]
    assert any(
        "did not supply scoring field fumbles_lost" in warning for warning in result["warnings"]
    )


@pytest.mark.asyncio
async def test_snapshot_reloads_after_restart_and_warns_when_stale_sources_fail(tmp_path) -> None:
    writer = ManualDraftService(snapshot_dir=tmp_path, now=lambda: NOW)
    _configure_successful_sources(writer, ecr_failure=False)
    prepared = await writer.prepare(deepcopy(GOTHAM_PROFILE), force_refresh=True)

    fresh_reader = ManualDraftService(snapshot_dir=tmp_path, now=lambda: NOW + timedelta(hours=1))
    fresh_failures = _fail_all_sources(fresh_reader)
    fresh = await fresh_reader.prepare(deepcopy(GOTHAM_PROFILE))
    assert fresh["snapshot_reused"] is True
    assert fresh["snapshot_id"] == prepared["snapshot_id"]
    assert fresh["snapshot_checksum"] == prepared["snapshot_checksum"]
    assert fresh["board_preview"] == prepared["board_preview"]
    assert fresh["readiness"] == "ready_with_warnings"
    assert any("sleeper source evidence is stale" in warning for warning in fresh["warnings"])
    assert fresh["sources"]["sleeper"]["freshness"]["components"]["players"]["is_stale"] is False
    assert (
        fresh["sources"]["sleeper"]["freshness"]["components"]["trending_adds"]["is_stale"] is True
    )
    assert all(mock.await_count == 0 for mock in fresh_failures)

    stale_reader = ManualDraftService(snapshot_dir=tmp_path, now=lambda: NOW + timedelta(hours=7))
    stale_failures = _fail_all_sources(stale_reader)
    stale = await stale_reader.prepare(deepcopy(GOTHAM_PROFILE))
    assert stale["snapshot_reused"] is True
    assert stale["snapshot_checksum"] == prepared["snapshot_checksum"]
    assert stale["sources"]["espn"]["freshness"]["is_stale"] is True
    assert stale["sources"]["ecr"]["freshness"]["is_stale"] is True
    assert any("last-known-good" in warning for warning in stale["warnings"])
    assert all(mock.await_count == 1 for mock in stale_failures)


@pytest.mark.asyncio
async def test_tampered_snapshot_is_not_presented_as_last_known_good(tmp_path) -> None:
    writer = ManualDraftService(snapshot_dir=tmp_path, now=lambda: NOW)
    _configure_successful_sources(writer, ecr_failure=False)
    await writer.prepare(deepcopy(GOTHAM_PROFILE), force_refresh=True)

    snapshot_path = tmp_path / "gotham-2026.json"
    snapshot_path.write_text(snapshot_path.read_text().replace("A.J. Example", "Tampered"))

    reader = ManualDraftService(snapshot_dir=tmp_path, now=lambda: NOW + timedelta(hours=7))
    _fail_all_sources(reader)
    result = await reader.prepare(deepcopy(GOTHAM_PROFILE), force_refresh=True)

    assert result["status"] == "error"
    assert result["readiness"] == "not_ready"
    assert result["board_count"] == 0


@pytest.mark.asyncio
async def test_espn_failure_still_returns_secondary_source_freshness(tmp_path) -> None:
    service = ManualDraftService(snapshot_dir=tmp_path, now=lambda: NOW)
    _configure_successful_sources(service, ecr_failure=False)
    service._espn = AsyncMock(side_effect=manual.ProviderError("ESPN offline"))

    result = await service.prepare(deepcopy(GOTHAM_PROFILE), force_refresh=True)

    assert result["status"] == "error"
    assert result["readiness"] == "not_ready"
    assert result["source_coverage"]["ecr"] is True
    assert result["sources"]["ecr"]["freshness"]["is_stale"] is False
    assert (
        result["sources"]["sleeper"]["freshness"]["components"]["trending_adds"][
            "cache_ttl_seconds"
        ]
        == 30 * 60
    )
