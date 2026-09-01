"""Deterministic offline tests for manual live-draft recommendations."""

import json
import math
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

import fantasy_football_multi_league as legacy_server
import fastmcp_server
import src.services.manual_draft_recommendation_service as recommendation_module
from src.services.manual_draft_recommendation_service import (
    MANUAL_DRAFT_RECOMMENDATION_INPUT_SCHEMA,
    ManualDraftRecommendationService,
    manual_draft_recommendation_service,
)
from src.services.manual_draft_service import manual_draft_service, validate_profile

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


def _player(index: int, position: str, score: float, *, name: str | None = None) -> dict:
    return {
        "player_id": f"espn:{index}",
        "name": name or f"Player {index}",
        "position": position,
        "team": "JAX" if index % 2 else "BUF",
        "base_board_score": score,
        "rank": index,
        "adp": float(index + 5),
        "adp_sd": 4.0,
        "warnings": [],
    }


def _write_snapshot(tmp_path, board: list[dict], *, prepared_at: datetime = NOW) -> dict:
    profile = validate_profile(GOTHAM_PROFILE)
    source_time = prepared_at - timedelta(hours=1)
    body = {
        "schema_version": "1.0.0",
        "profile_id": profile["profile_id"],
        "profile_checksum": profile["profile_checksum"],
        "profile": profile,
        "prepared_at": prepared_at.isoformat().replace("+00:00", "Z"),
        "sources": {
            "espn": {
                "provider": "espn",
                "fetched_at": source_time.isoformat().replace("+00:00", "Z"),
                "cache_ttl_seconds": 6 * 60 * 60,
            }
        },
        "source_coverage": {},
        "unsupported_scoring_fields": [],
        "unsupported_scoring_inputs": {},
        "estimated_scoring_fields": [],
        "quarantined_identities": [],
        "replacement_levels": {},
        "weights": {"projection_value": 0.55, "ecr": 0.25, "adp": 0.15, "availability": 0.05},
        "board": board,
        "warnings": [],
    }
    body["snapshot_id"] = f"manual-draft-{recommendation_module._canonical_checksum(body)[:16]}"
    body["snapshot_checksum"] = recommendation_module._canonical_checksum(body)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "gotham-2026.json").write_text(json.dumps(body), encoding="utf-8")
    return body


def _board(count: int = 60) -> list[dict]:
    positions = ("RB", "WR", "QB", "TE", "DEF")
    return [
        _player(index, positions[(index - 1) % len(positions)], 99.0 - index)
        for index in range(1, count + 1)
    ]


@pytest.mark.asyncio
async def test_entrypoints_share_schema_and_dispatch_without_yahoo() -> None:
    tools = {tool.name: tool for tool in await legacy_server.list_tools()}
    assert tools["ff_get_manual_draft_recommendation"].inputSchema == (
        MANUAL_DRAFT_RECOMMENDATION_INPUT_SCHEMA
    )
    assert fastmcp_server.ff_get_manual_draft_recommendation.parameters == (
        MANUAL_DRAFT_RECOMMENDATION_INPUT_SCHEMA
    )
    expected = {"status": "success", "recommendation": {"name": "Player 11"}}
    recommend = AsyncMock(return_value=expected)
    yahoo = AsyncMock(side_effect=AssertionError("Yahoo must not be called"))
    arguments = {
        "prepared_id": "gotham-2026",
        "current_overall_pick": 11,
        "drafted_players": [f"Player {index}" for index in range(1, 11)],
        "roster": [],
    }
    with (
        patch.object(manual_draft_recommendation_service, "recommend", recommend),
        patch.object(legacy_server, "yahoo_api_call", yahoo),
    ):
        legacy_result = await legacy_server.call_tool(
            "ff_get_manual_draft_recommendation", arguments
        )
        fast_result = await fastmcp_server.ff_get_manual_draft_recommendation.fn(None, **arguments)
    assert json.loads(legacy_result[0].text) == expected
    assert fast_result == expected
    yahoo.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_recommendation_path_never_calls_yahoo_or_preparation_providers(
    tmp_path,
) -> None:
    _write_snapshot(tmp_path, _board())
    yahoo = AsyncMock(side_effect=AssertionError("Yahoo must not be called"))
    provider = AsyncMock(side_effect=AssertionError("Network provider must not be called"))
    arguments = {
        "prepared_id": "gotham-2026",
        "current_overall_pick": 11,
        "drafted_players": [f"Player {index}" for index in range(1, 11)],
        "roster": [],
    }
    with (
        patch.object(manual_draft_recommendation_service, "snapshot_dir", tmp_path),
        patch.object(manual_draft_service, "_request", provider),
        patch.object(legacy_server, "yahoo_api_call", yahoo),
    ):
        result = await legacy_server.call_tool("ff_get_manual_draft_recommendation", arguments)
    assert json.loads(result[0].text)["status"] == "success"
    yahoo.assert_not_awaited()
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_reload_excludes_drafted_and_reports_unknown_or_ambiguous_names(
    tmp_path,
) -> None:
    board = _board()
    board.extend(
        [
            _player(101, "RB", 70, name="Same Name"),
            _player(102, "WR", 69, name="Same Name"),
        ]
    )
    snapshot = _write_snapshot(tmp_path, board)
    drafted = [f"Player {index}" for index in range(1, 10)] + ["Unknown Screenshot Name"]
    service = ManualDraftRecommendationService(snapshot_dir=tmp_path, now=lambda: NOW)
    first = await service.recommend(
        prepared_id=snapshot["snapshot_id"],
        current_overall_pick=11,
        drafted_players=drafted,
        roster=[],
    )
    restarted = ManualDraftRecommendationService(snapshot_dir=tmp_path, now=lambda: NOW)
    second = await restarted.recommend(
        prepared_id="gotham-2026",
        current_overall_pick=11,
        drafted_players=drafted,
        roster=[],
    )
    names = {first["recommendation"]["name"]} | {row["name"] for row in first["alternatives"]}
    assert not names.intersection({f"Player {index}" for index in range(1, 10)})
    assert first["unmatched_inputs"]["drafted_players"][0]["status"] == "unknown"
    stable_fields = ("recommendation", "alternatives", "pick_context", "roster_state")
    assert {field: first[field] for field in stable_fields} == {
        field: second[field] for field in stable_fields
    }

    ambiguous = await restarted.recommend(
        prepared_id="gotham-2026",
        current_overall_pick=11,
        drafted_players=[f"Player {index}" for index in range(1, 10)] + ["Same Name"],
        roster=[],
    )
    assert ambiguous["unmatched_inputs"]["drafted_players"][0]["status"] == "ambiguous"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_pick", "next_pick"),
    [(11, 14), (14, 35)],
)
async def test_snake_turn_and_adp_distribution_survival_are_explicit(
    tmp_path, current_pick, next_pick
) -> None:
    board = _board()
    _write_snapshot(tmp_path, board)
    service = ManualDraftRecommendationService(snapshot_dir=tmp_path, now=lambda: NOW)
    result = await service.recommend(
        prepared_id="gotham-2026",
        current_overall_pick=current_pick,
        drafted_players=[f"Player {index}" for index in range(1, current_pick)],
        roster=[],
        alternative_count=10,
    )
    assert result["pick_context"]["next_user_pick"] == next_pick
    skill_player = next(
        row
        for row in [result["recommendation"], *result["alternatives"]]
        if row["position"] in {"RB", "WR"}
    )
    assert skill_player["adjustments"]["roster_need"] == 13.0
    assert skill_player["adjustments"]["two_flex_construction"] == 2.0
    expected_survival = 0.5 * (
        1 + math.erf((skill_player["adp"] - next_pick) / skill_player["adp_sd"] / math.sqrt(2))
    )
    assert skill_player["next_turn_survival_estimate"] == pytest.approx(
        expected_survival, abs=0.0001
    )
    assert skill_player["adjustments"]["snake_next_turn_risk"] == pytest.approx(
        (1 - expected_survival) * 4, abs=0.001
    )
    assert "DEF" not in result["current_strategy"]


@pytest.mark.asyncio
async def test_resolved_roster_reduces_base_and_both_flex_needs(tmp_path) -> None:
    _write_snapshot(tmp_path, _board())
    service = ManualDraftRecommendationService(snapshot_dir=tmp_path, now=lambda: NOW)
    result = await service.recommend(
        prepared_id="gotham-2026",
        current_overall_pick=35,
        drafted_players=[f"Player {index}" for index in range(1, 35)],
        roster=[
            "Player 1",
            "Player 2",
            "Player 6",
            "Player 7",
            "Player 11",
            "Player 12",
        ],
        alternative_count=10,
    )
    assert result["roster_state"]["base_unfilled"]["RB"] == 0
    assert result["roster_state"]["base_unfilled"]["WR"] == 0
    assert result["roster_state"]["flex_filled"] == 2
    assert result["roster_state"]["flex_unfilled"] == 0
    skill_player = next(
        row
        for row in [result["recommendation"], *result["alternatives"]]
        if row["position"] in {"RB", "WR"}
    )
    assert skill_player["adjustments"]["roster_need"] == 0
    assert skill_player["adjustments"]["two_flex_construction"] == 0


@pytest.mark.asyncio
async def test_optional_evidence_is_capped_and_stale_or_context_only_evidence_cannot_score(
    tmp_path,
) -> None:
    board = _board()
    _write_snapshot(tmp_path, board)
    service = ManualDraftRecommendationService(snapshot_dir=tmp_path, now=lambda: NOW)
    evidence = [
        {
            "player": "Player 11",
            "kind": "news",
            "source": "RotoWire",
            "detail": "Cleared for practice",
            "adjustment": 2,
            "age_seconds": 60,
        },
        {
            "player": "Player 11",
            "kind": "season_long_odds",
            "source": "PropLine",
            "detail": "Comparable season market",
            "adjustment": 2,
            "age_seconds": 60,
        },
        {
            "player": "Player 11",
            "kind": "next_game_prop",
            "source": "PropLine",
            "detail": "Context only",
            "adjustment": 3,
            "age_seconds": 60,
        },
        {
            "player": "Player 11",
            "kind": "news",
            "source": "ESPN",
            "detail": "Stale report",
            "adjustment": -3,
            "age_seconds": 999999,
            "stale": True,
        },
    ]
    result = await service.recommend(
        prepared_id="gotham-2026",
        current_overall_pick=11,
        drafted_players=[f"Player {index}" for index in range(1, 11)],
        roster=[],
        optional_evidence=evidence,
        alternative_count=10,
    )
    candidate = next(
        row
        for row in [result["recommendation"], *result["alternatives"]]
        if row["name"] == "Player 11"
    )
    assert candidate["adjustments"]["optional_cached_evidence"] == 3
    applied = {item["kind"]: item["applied_adjustment"] for item in candidate["optional_evidence"]}
    assert applied["next_game_prop"] == 0
    assert candidate["optional_evidence"][-1]["applied_adjustment"] == 0
    assert any("capped" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_missing_optional_evidence_and_stale_sources_return_immediately_under_five_seconds(
    tmp_path,
) -> None:
    _write_snapshot(tmp_path, _board(250), prepared_at=NOW - timedelta(days=2))
    service = ManualDraftRecommendationService(snapshot_dir=tmp_path, now=lambda: NOW)
    started = time.perf_counter()
    result = await service.recommend(
        prepared_id="gotham-2026",
        current_overall_pick=11,
        drafted_players=[f"Player {index}" for index in range(1, 11)],
        roster=[],
    )
    wall_seconds = time.perf_counter() - started
    assert result["status"] == "success"
    assert wall_seconds < 5
    assert result["timing"]["elapsed_ms"] < 5000
    assert result["source_ages"]["espn"]["is_stale"] is True
    assert any("stale" in warning for warning in result["warnings"])
