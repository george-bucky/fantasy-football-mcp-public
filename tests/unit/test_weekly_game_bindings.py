"""Schedule-only exact upcoming-game bindings, with synthetic source snapshots."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from src.services.nflverse_matchups import (
    CANONICAL_TEAMS,
    SCHEDULE_URL,
    MatchupEvidenceError,
    ScheduleGame,
    SourceMetadata,
    WeeklyMatchupEvidenceService,
)

NOW = datetime(2026, 10, 20, 16, tzinfo=timezone.utc)
GAME = ScheduleGame("2026_08_BUF_MIA", 2026, 8, "BUF", "MIA", NOW + timedelta(days=2))
META = SourceMetadata(SCHEDULE_URL, "snapshot-1", NOW)


def source(games):
    service = WeeklyMatchupEvidenceService()
    service._validated = AsyncMock(return_value=(games, META))
    return service


async def test_full_roster_uses_one_cached_schedule_request_and_never_stats_or_history():
    service = source([GAME])
    service._environment_history = AsyncMock(side_effect=AssertionError("No history needed"))
    players = [{"team": "buf", "opponent": "MIA"}, {"team": "MIA", "opponent": "BUF"}] * 12
    rows = await service.get_game_bindings(players, season=2026, target_week=8, now=NOW)
    assert len(rows) == len(players)
    assert all(row["status"] == "matched" for row in rows)
    assert rows[0]["team"] == "BUF"
    assert rows[0]["opponent"] == "MIA"
    assert rows[1]["opponent"] == "BUF"
    assert rows[0]["schedule_game_id"] == GAME.game_id
    assert datetime.fromisoformat(rows[0]["kickoff"]).utcoffset() == timedelta(0)
    assert rows[0]["season"] == 2026 and rows[0]["week"] == 8
    assert rows[0]["provenance"]["schedule"]["version"] == "snapshot-1"
    service._validated.assert_awaited_once()
    kwargs = service._validated.await_args.kwargs
    assert kwargs["url"] == SCHEDULE_URL
    assert kwargs["ttl"] == timedelta(minutes=15)
    service._environment_history.assert_not_awaited()


@pytest.mark.parametrize("team", [None, "", "Unknown", "NYC"])
async def test_unknown_team_is_explicit_and_order_is_preserved(team):
    service = source([GAME])
    result = await service.get_game_bindings(
        [{"team": team}, {"team": "BUF"}], season=2026, target_week=8, now=NOW
    )
    assert result[0]["status"] == "unavailable"
    assert result[0]["reason"] == "unrecognized_nfl_team"
    assert result[1]["status"] == "matched"


@pytest.mark.parametrize("opponent", ["NYJ", "BYE", "unknown"])
async def test_supplied_opponent_must_match_exact_canonical_schedule(opponent):
    row = (
        await source([GAME]).get_game_bindings(
            [{"team": "BUF", "opponent": opponent}], season=2026, target_week=8, now=NOW
        )
    )[0]
    assert row["reason"] == "opponent_mismatch"
    assert row["schedule_game_id"] is None


async def test_aliases_and_blank_optional_opponent_are_accepted():
    game = replace(GAME, home_team="LA", away_team="WAS")
    rows = await source([game]).get_game_bindings(
        [{"team": "LAR", "opponent": "WSH"}, {"team": "WAS", "opponent": "  "}],
        season=2026,
        target_week=8,
        now=NOW,
    )
    assert rows[0]["team"] == "LA" and rows[0]["opponent"] == "WAS"
    assert all(row["status"] == "matched" for row in rows)


@pytest.mark.parametrize(
    "kickoff,completed,reason",
    [
        (None, False, "kickoff_unavailable"),
        (NOW.replace(tzinfo=None), False, "kickoff_unavailable"),
        (NOW, False, "game_already_started"),
        (NOW - timedelta(seconds=1), False, "game_already_started"),
        (NOW + timedelta(days=2), True, "game_already_started"),
        (NOW.replace(year=2028), False, "kickoff_period_mismatch"),
    ],
)
async def test_missing_invalid_or_started_kickoff_is_not_an_upcoming_binding(
    kickoff, completed, reason
):
    row = (
        await source([replace(GAME, kickoff=kickoff, completed=completed)]).get_game_bindings(
            [{"team": "BUF"}], season=2026, target_week=8, now=NOW
        )
    )[0]
    assert row["status"] == "unavailable"
    assert row["reason"] == reason
    assert row["kickoff"] is None


@pytest.mark.parametrize(
    "games",
    [
        [GAME, replace(GAME, game_id="duplicate-team", away_team="NYJ")],
        [GAME, GAME],
        [replace(GAME, season=2025)],
        [replace(GAME, week=True)],
        [replace(GAME, home_team="Unknown")],
        [replace(GAME, home_team="MIA")],
        [replace(GAME, game_id="")],
        [replace(GAME, week=7)],
        [],
    ],
)
async def test_invalid_or_absent_target_schedule_fails_closed(games):
    rows = await source(games).get_game_bindings(
        [{"team": "BUF"}, {"team": "ARI"}], season=2026, target_week=8, now=NOW
    )
    assert all(
        row["status"] == "unavailable" and row["reason"] == "schedule_unavailable_or_invalid"
        for row in rows
    )


async def test_missing_team_in_partial_schedule_is_not_called_a_bye():
    row = (
        await source([GAME]).get_game_bindings(
            [{"team": "ARI"}], season=2026, target_week=8, now=NOW
        )
    )[0]
    assert row["status"] == "unavailable"
    assert row["reason"] == "incomplete_schedule_cannot_establish_bye"


def complete_schedule():
    pairs = list(zip(sorted(CANONICAL_TEAMS)[::2], sorted(CANONICAL_TEAMS)[1::2]))
    games = []
    for week in range(1, 19):
        for index, (home, away) in enumerate(pairs):
            bye_week = 8 if index == 0 else 18
            if week != bye_week:
                games.append(
                    ScheduleGame(
                        f"2026_{week}_{index}", 2026, week, home, away, NOW + timedelta(days=week)
                    )
                )
    return games, pairs[0][0]


async def test_bye_requires_complete_season_and_validated_nonempty_target_week():
    games, bye_team = complete_schedule()
    rows = await source(games).get_game_bindings(
        [
            {"team": bye_team},
            {"team": bye_team, "opponent": "BYE"},
            {"team": bye_team, "opponent": "BUF"},
        ],
        season=2026,
        target_week=8,
        now=NOW,
    )
    assert rows[0]["status"] == rows[1]["status"] == "bye"
    assert rows[0]["reason"] == "bye_week"
    assert rows[0]["schedule_game_id"] is None
    assert rows[2]["status"] == "unavailable" and rows[2]["reason"] == "opponent_mismatch"
    # Equal but insufficient total counts are not proof of full schedule coverage.
    subset = [game for game in games if game.week == 8]
    row = (
        await source(subset).get_game_bindings(
            [{"team": bye_team}], season=2026, target_week=8, now=NOW
        )
    )[0]
    assert row["status"] == "unavailable"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"season": True, "target_week": 8},
        {"season": 2026.0, "target_week": 8},
        {"season": 1999, "target_week": 8},
        {"season": 2026, "target_week": True},
        {"season": 2026, "target_week": 0},
        {"season": 2026, "target_week": 19},
        {"season": 2026, "target_week": 8, "now": NOW.replace(tzinfo=None)},
        {"season": 2026, "target_week": 8, "now": "2026-10-20"},
    ],
)
async def test_invalid_request_period_or_clock_raises_before_fetch(kwargs):
    service = source([GAME])
    with pytest.raises(MatchupEvidenceError):
        await service.get_game_bindings([{"team": "BUF"}], **kwargs)
    service._validated.assert_not_awaited()


async def test_source_failure_is_explicit_without_leaking_provider_text():
    service = source([GAME])
    service._validated.side_effect = RuntimeError("provider-private-error")
    row = (await service.get_game_bindings([{"team": "BUF"}], season=2026, target_week=8, now=NOW))[
        0
    ]
    assert row["reason"] == "schedule_unavailable_or_invalid"
    assert "provider-private-error" not in str(row)


async def test_empty_roster_skips_all_fetches():
    service = source([GAME])
    assert await service.get_game_bindings([], season=2026, target_week=8, now=NOW) == []
    service._validated.assert_not_awaited()


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        SourceMetadata("https://invalid.example", "v", NOW),
        SourceMetadata(SCHEDULE_URL, "", NOW),
        SourceMetadata(SCHEDULE_URL, "v", None),
        SourceMetadata(SCHEDULE_URL, "v", NOW.replace(tzinfo=None)),
    ],
)
async def test_invalid_provenance_is_unavailable_not_a_row_serialization_failure(metadata):
    service = source([GAME])
    service._validated.return_value = ([GAME], metadata)
    row = (await service.get_game_bindings([{"team": "BUF"}], season=2026, target_week=8, now=NOW))[
        0
    ]
    assert row["reason"] == "schedule_unavailable_or_invalid"
    assert row["provenance"]["schedule"] is None
