from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from src.services.nflverse_matchups import (
    CANONICAL_TEAMS,
    MatchupEvidenceError,
    ScheduleGame,
    SourceMetadata,
    WeeklyMatchupEvidenceService,
    calculate_strength,
    canonical_scoring_basis,
    canonical_team,
    parse_schedule,
    parse_stats,
    validate_target_week,
)


NOW = datetime(2026, 10, 20, 16, tzinfo=timezone.utc)
TEAMS = sorted(CANONICAL_TEAMS)
PAIRS = list(zip(TEAMS[::2], TEAMS[1::2]))
SCHEDULE_FIELDS = [
    "game_id",
    "season",
    "game_type",
    "week",
    "gameday",
    "gametime",
    "home_team",
    "away_team",
    "result",
]
STATS_FIELDS = [
    "game_id",
    "player_id",
    "season",
    "week",
    "season_type",
    "team",
    "opponent_team",
    "position",
    "fantasy_points",
    "fantasy_points_ppr",
    "receptions",
]


def _csv(fields, rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _schedule(weeks: int = 4, *, target_week: int | None = None, target_future=True):
    games = []
    for week in range(1, weeks + 1):
        for index, (home, away) in enumerate(PAIRS):
            kickoff = NOW - timedelta(days=(weeks - week + 1) * 7)
            if target_week == week:
                kickoff = NOW + timedelta(days=2) if target_future else NOW - timedelta(hours=1)
            games.append(
                ScheduleGame(
                    game_id=f"2026_{week:02d}_{index:02d}",
                    season=2026,
                    week=week,
                    home_team=home,
                    away_team=away,
                    kickoff=kickoff,
                    completed=target_week != week,
                )
            )
    return games


def _stats_rows(weeks: int = 4):
    rows = []
    for week in range(1, weeks + 1):
        for index, (home, away) in enumerate(PAIRS):
            game_id = f"2026_{week:02d}_{index:02d}"
            for offense, defense in ((home, away), (away, home)):
                prefix = f"{game_id}_{offense}"
                rows.extend(
                    [
                        {
                            "game_id": game_id,
                            "player_id": f"{prefix}_qb1",
                            "season": 2026,
                            "week": week,
                            "season_type": "REG",
                            "team": offense,
                            "opponent_team": defense,
                            "position": "QB",
                            "fantasy_points": 10,
                            "fantasy_points_ppr": 10,
                            "receptions": 0,
                        },
                        {
                            "game_id": game_id,
                            "player_id": f"{prefix}_rb1",
                            "season": 2026,
                            "week": week,
                            "season_type": "REG",
                            "team": offense,
                            "opponent_team": defense,
                            "position": "RB",
                            "fantasy_points": 5,
                            "fantasy_points_ppr": 7,
                            "receptions": 2,
                        },
                    ]
                )
    return rows


def _stats_text(rows=None):
    return _csv(STATS_FIELDS, rows or _stats_rows())


def _metadata(url="fixture", version="v1"):
    return SourceMetadata(url, version, NOW)


def test_schedule_aliases_and_strict_target_week_validation():
    rows = []
    for index, (home, away) in enumerate(PAIRS):
        rows.append(
            {
                "game_id": f"g{index}",
                "season": 2026,
                "game_type": "REG",
                "week": 5,
                "gameday": "2026-10-11",
                "gametime": "13:00",
                "home_team": {"JAX": "JAC", "LA": "LAR", "WAS": "WSH"}.get(home, home),
                "away_team": {"JAX": "JAC", "LA": "LAR", "WAS": "WSH"}.get(away, away),
                "result": "7",
            }
        )
    games = parse_schedule(_csv(SCHEDULE_FIELDS, rows), season=2026)
    validate_target_week(games, 5)

    assert {team for game in games for team in (game.home_team, game.away_team)} == set(TEAMS)
    assert canonical_team("JAC") == "JAX"
    assert canonical_team("LAR") == "LA"
    assert canonical_team("WSH") == "WAS"

    duplicate = [*games, ScheduleGame("extra", 2026, 5, games[0].home_team, "BUF", NOW)]
    with pytest.raises(MatchupEvidenceError, match="appears twice"):
        validate_target_week(duplicate, 5)


def test_schedule_rejects_duplicate_ids_and_incomplete_team_reconciliation():
    base = {
        "game_id": "same",
        "season": 2026,
        "game_type": "REG",
        "week": 1,
        "gameday": "2026-09-10",
        "gametime": "20:00",
        "home_team": "ARI",
        "away_team": "ATL",
        "result": "7",
    }
    with pytest.raises(MatchupEvidenceError, match="unique and nonblank"):
        parse_schedule(_csv(SCHEDULE_FIELDS, [base, base]), season=2026)
    with pytest.raises(MatchupEvidenceError, match="all 32"):
        parse_schedule(_csv(SCHEDULE_FIELDS, [base]), season=2026)


def test_strength_sums_backup_qbs_and_rb_committees_and_keeps_zero_te_games():
    rows = _stats_rows()
    first = rows[0]
    rows.extend(
        [
            {
                **first,
                "player_id": "backup-qb",
                "fantasy_points": 7,
                "fantasy_points_ppr": 7,
            },
            {
                **rows[1],
                "player_id": "committee-rb",
                "fantasy_points": 3,
                "fantasy_points_ppr": 4,
                "receptions": 1,
            },
        ]
    )
    result = calculate_strength(
        _stats_text(rows),
        season=2026,
        cutoff_week=4,
        schedule=_schedule(),
        scoring_basis="ppr",
        now=NOW,
    )
    opponent = first["opponent_team"]

    assert result[(opponent, "QB")]["points_allowed_per_game"] == 11.75
    assert result[(opponent, "RB")]["points_allowed_per_game"] == 8.0
    assert result[(opponent, "TE")]["points_allowed_per_game"] == 0.0
    assert result[(opponent, "TE")]["rank"] == 16.5
    assert result[(opponent, "TE")]["percentile"] == 50.0


def test_strength_scoring_labels_four_game_boundary_and_target_week_leakage():
    rows = _stats_rows()
    rows.append(
        {
            **rows[0],
            "game_id": "future-unknown",
            "player_id": "future-player",
            "week": 5,
            "team": "JAC",
            "opponent_team": "LAR",
        }
    )
    assert canonical_scoring_basis("std") == "standard"
    assert canonical_scoring_basis("half-ppr") == "half_ppr"
    assert canonical_scoring_basis("PPR") == "ppr"
    incomplete_schedule = _schedule()
    incomplete_schedule[0] = replace(incomplete_schedule[0], completed=False)
    with pytest.raises(MatchupEvidenceError, match="incomplete"):
        calculate_strength(
            _stats_text(rows),
            season=2026,
            cutoff_week=4,
            schedule=incomplete_schedule,
            scoring_basis="standard",
            now=NOW,
        )
    assert (
        calculate_strength(
            _stats_text(rows),
            season=2026,
            cutoff_week=3,
            schedule=_schedule(),
            scoring_basis="half-ppr",
            now=NOW,
        )
        == {}
    )
    result = calculate_strength(
        _stats_text(rows),
        season=2026,
        cutoff_week=4,
        schedule=_schedule(),
        scoring_basis="half-ppr",
        now=NOW,
    )
    assert result[(PAIRS[0][1], "RB")]["points_allowed_per_game"] == 6.0


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate",
        "orphan",
        "direction",
        "week",
        "future_week_mismatch",
        "ppr",
        "nan",
        "infinity",
    ],
)
def test_stats_fail_closed_for_invalid_or_incomplete_rows(failure):
    rows = _stats_rows()
    if failure == "duplicate":
        rows.append(dict(rows[0]))
    elif failure == "orphan":
        rows[0]["game_id"] = "orphan"
    elif failure == "direction":
        rows[0]["opponent_team"] = "BUF"
    elif failure == "week":
        rows[0]["week"] = 2
    elif failure == "future_week_mismatch":
        rows[0]["week"] = 5
    elif failure == "ppr":
        rows[0]["fantasy_points_ppr"] = 99
    elif failure == "nan":
        rows[0]["fantasy_points"] = "nan"
    else:
        rows[0]["receptions"] = "inf"

    with pytest.raises(MatchupEvidenceError):
        calculate_strength(
            _stats_text(rows),
            season=2026,
            cutoff_week=4,
            schedule=_schedule(),
            scoring_basis="ppr",
            now=NOW,
        )


def test_strength_rejects_missing_offense_and_31_of_32_defenses():
    rows = _stats_rows()
    missing_direction = [
        row
        for row in rows
        if not (row["game_id"] == "2026_01_00" and row["team"] == PAIRS[0][0])
    ]
    with pytest.raises(MatchupEvidenceError, match="Both offenses"):
        calculate_strength(
            _stats_text(missing_direction),
            season=2026,
            cutoff_week=4,
            schedule=_schedule(),
            scoring_basis="standard",
            now=NOW,
        )

    only_thirty = [game for game in _schedule() if "WAS" not in (game.home_team, game.away_team)]
    included_ids = {game.game_id for game in only_thirty}
    only_thirty_rows = [row for row in rows if row["game_id"] in included_ids]
    with pytest.raises(MatchupEvidenceError, match="all 32"):
        calculate_strength(
            _stats_text(only_thirty_rows),
            season=2026,
            cutoff_week=4,
            schedule=only_thirty,
            scoring_basis="standard",
            now=NOW,
        )


@pytest.mark.asyncio
async def test_bye_and_custom_scoring_return_schedule_only_evidence():
    service = WeeklyMatchupEvidenceService()
    schedule = _schedule(weeks=1, target_week=1)
    bye_team = schedule[0].home_team
    schedule = schedule[1:]
    service._validated = AsyncMock(return_value=(schedule, _metadata()))

    result = await service.get_evidence(
        [
            {"team": bye_team, "position": "QB"},
            {"team": schedule[0].home_team, "position": "QB"},
        ],
        season=2026,
        target_week=1,
        cutoff_week=0,
        scoring_basis="custom",
        now=NOW,
    )

    assert result["players"][0]["schedule"]["status"] == "bye"
    assert result["players"][1]["schedule"]["status"] == "matched"
    assert result["players"][1]["strength"]["status"] == "source_unavailable"
    assert result["players"][1]["available"] is False
    assert service._validated.await_count == 1


@pytest.mark.asyncio
async def test_future_kickoff_guard_and_already_started_game():
    service = WeeklyMatchupEvidenceService()
    schedule = _schedule(weeks=5, target_week=5, target_future=False)
    stats = parse_stats(_stats_text(), season=2026)
    service._validated = AsyncMock(
        side_effect=[(schedule, _metadata("schedule")), (stats, _metadata("stats"))]
    )
    team = schedule[-1].home_team

    result = await service.get_evidence(
        [{"team": team, "position": "QB"}],
        season=2026,
        target_week=5,
        cutoff_week=4,
        scoring_basis="standard",
        now=NOW,
    )

    evidence = result["players"][0]
    assert evidence["schedule"]["status"] == "matched"
    assert evidence["strength"]["status"] == "available"
    assert evidence["available"] is False
    assert evidence["unavailable_reason"] == "game_already_started"


@pytest.mark.asyncio
async def test_cache_never_serves_expired_data_after_upstream_failure():
    service = WeeklyMatchupEvidenceService()
    service._download = AsyncMock(
        side_effect=[("value", _metadata(version="one")), RuntimeError("offline")]
    )
    value, _ = await service._validated(
        season=2026,
        url="fixture",
        ttl=timedelta(seconds=-1),
        validator=lambda text: text,
    )
    assert value == "value"
    with pytest.raises(RuntimeError, match="offline"):
        await service._validated(
            season=2026,
            url="fixture",
            ttl=timedelta(minutes=1),
            validator=lambda text: text,
        )


@pytest.mark.asyncio
async def test_invalid_download_is_not_cached():
    service = WeeklyMatchupEvidenceService()
    service._download = AsyncMock(return_value=("bad", _metadata()))
    with pytest.raises(MatchupEvidenceError, match="invalid"):
        await service._validated(
            season=2026,
            url="fixture",
            ttl=timedelta(minutes=1),
            validator=lambda text: (_ for _ in ()).throw(MatchupEvidenceError("invalid")),
        )
    assert service._cache == {}
    assert service._current == {}
