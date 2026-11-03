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
    StatsRow,
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
    "weekday",
    "roof",
    "surface",
    "home_rest",
    "away_rest",
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
    "player_display_name",
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
                            "player_display_name": f"Fixture QB {prefix}",
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
                            "player_display_name": f"Fixture RB {prefix}",
                        },
                    ]
                )
    return rows


def _stats_text(rows=None):
    return _csv(STATS_FIELDS, rows or _stats_rows())


def _metadata(url="fixture", version="v1"):
    return SourceMetadata(url, version, NOW)


def _environment_schedule(season: int, weeks: int, *, target_week: int | None = None):
    games = []
    for week in range(1, weeks + 1):
        for index, (home, away) in enumerate(PAIRS):
            kickoff = datetime(season, 9, min(week * 7, 28), 0, tzinfo=timezone.utc)
            completed = True
            if target_week == week:
                kickoff = NOW + timedelta(days=2, hours=8)
                completed = False
            games.append(
                ScheduleGame(
                    game_id=f"{season}_{week:02d}_{index:02d}",
                    season=season,
                    week=week,
                    home_team=home,
                    away_team=away,
                    kickoff=kickoff,
                    completed=completed,
                    weekday="Thursday",
                    roof="closed",
                    surface="fieldturf",
                    home_rest=7,
                    away_rest=7,
                )
            )
    return games


def _player_stat(game: ScheduleGame, points: float, *, player_id: str = "player-1"):
    return StatsRow(
        game_id=game.game_id,
        player_id=player_id,
        season=game.season,
        week=game.week,
        team=game.home_team,
        opponent=game.away_team,
        position="WR",
        standard_points=points,
        receptions=4,
        ppr_points=points + 4,
        player_display_name="Amon-Ra St. Brown",
    )


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
                "weekday": "Sunday",
                "roof": "outdoors",
                "surface": "grass",
                "home_rest": "7",
                "away_rest": "7",
            }
        )
    games = parse_schedule(_csv(SCHEDULE_FIELDS, rows), season=2026)
    validate_target_week(games, 5)

    assert {team for game in games for team in (game.home_team, game.away_team)} == set(TEAMS)
    assert canonical_team("JAC") == "JAX"
    assert canonical_team("LAR") == "LA"
    assert canonical_team("WSH") == "WAS"
    assert games[0].weekday == "Sunday"
    assert games[0].roof == "outdoors"
    assert games[0].surface == "grass"
    assert games[0].home_rest == 7

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


@pytest.mark.asyncio
async def test_player_environment_context_is_opt_in_and_does_not_fetch_history_by_default():
    service = WeeklyMatchupEvidenceService()
    schedule = _environment_schedule(2026, 1, target_week=1)
    service._validated = AsyncMock(return_value=(schedule, _metadata("schedule")))

    result = await service.get_evidence(
        [{"name": "Amon-Ra St. Brown", "team": schedule[0].home_team, "position": "WR"}],
        season=2026,
        target_week=1,
        cutoff_week=0,
        scoring_basis="ppr",
        now=NOW,
    )

    assert "player_environment_context" not in result["players"][0]
    assert service._validated.await_count == 1


@pytest.mark.asyncio
async def test_player_environment_context_exact_identity_similarity_and_provenance():
    service = WeeklyMatchupEvidenceService()
    current = _environment_schedule(2026, 1, target_week=1)
    historical = {
        2024: _environment_schedule(2024, 1),
        2025: _environment_schedule(2025, 2),
    }
    points = iter((10.0, 12.0, 14.0))
    stats = {
        history_season: [
            _player_stat(game, next(points))
            for game in games
            if game.home_team == current[0].home_team
        ]
        for history_season, games in historical.items()
    }

    async def validated(*, season, url, ttl, validator, cache_namespace="default"):
        del ttl, validator, cache_namespace
        if url.endswith("games.csv"):
            return {
                "games": {**historical, 2026: current},
                "errors": {},
            }, _metadata("schedule", f"schedule-{season}")
        return stats[season], _metadata(url, f"stats-{season}")

    service._validated = AsyncMock(side_effect=validated)
    result = await service.get_evidence(
        [
            {
                "name": "Amon Ra St Brown",
                "team": current[0].home_team,
                "position": "WR",
                "nflverse_player_id": "player-1",
            },
            {
                "name": "Amon Ra St Brown",
                "team": current[0].home_team,
                "position": "WR",
            },
            {
                "name": "Amon Ra St Brown",
                "team": current[0].home_team,
                "position": "WR",
                "nflverse_player_id": "wrong-player-id",
            },
        ],
        season=2026,
        target_week=1,
        cutoff_week=0,
        scoring_basis="standard",
        now=NOW,
        include_player_context=True,
    )

    context = result["players"][0]["player_environment_context"]
    assert context["status"] == "available"
    assert context["applied"] is False
    assert context["identity"] == {
        "status": "verified",
        "verified": True,
        "confidence": "high",
        "match_method": "provided_id_exact_name_position",
        "nflverse_player_id": "player-1",
    }
    assert context["current_environment"]["venue_type"] == "indoor"
    assert context["current_environment"]["kickoff_window"] == "night"
    assert context["history"]["requested_seasons"] == [2024, 2025, 2026]
    assert context["history"]["included_seasons"] == [2024, 2025]
    assert context["history"]["all_stat_rows_count"] == 3
    assert context["history"]["all_stat_row_average_points"] == 12.0
    assert context["history"]["comparable_stat_rows_count"] == 3
    assert context["history"]["comparable_stat_row_average_points"] == 12.0
    assert context["history"]["comparable_stat_row_median_points"] == 12.0
    assert context["history"]["difference_from_all_stat_row_average"] == 0.0
    assert context["history"]["effective_sample_size"] == 3.0
    assert [game["season"] for game in context["history"]["comparable_games"]] == [
        2025,
        2025,
        2024,
    ]
    assert all(
        game["similarity_score"] == 1.0
        for game in context["history"]["comparable_games"]
    )
    assert [source["season"] for source in context["provenance"]["player_stats"]] == [
        2024,
        2025,
    ]
    assert [source["season"] for source in context["provenance"]["schedule"]] == [
        2024,
        2025,
        2026,
    ]
    assert context["confidence"] == "low"
    assert context["evidence_quality"]["recency"]["status"] == "recent"
    assert context["analysis_semantics"]["mode"] == "descriptive_only"
    assert (
        context["analysis_semantics"]["projection_residual_status"]
        == "unavailable_no_historical_pregame_projection"
    )
    assert "missing row is unknown coverage" in context["history"]["coverage_semantics"]
    unverified = result["players"][1]["player_environment_context"]
    assert unverified["status"] == "partial"
    assert unverified["identity"]["status"] == "name_position_only"
    assert unverified["identity"]["verified"] is False
    assert unverified["identity"]["confidence"] == "low"
    assert unverified["confidence"] == "low"
    assert "Identity is unverified" in unverified["warnings"][0]
    rejected_id = result["players"][2]["player_environment_context"]
    assert rejected_id["status"] == "identity_unavailable"
    assert rejected_id["identity"]["status"] == "unmatched"
    assert rejected_id["identity"]["nflverse_player_id"] is None
    assert service._validated.await_count == 3
    assert sum(
        call.kwargs["url"].endswith("games.csv")
        for call in service._validated.await_args_list
    ) == 1
    assert not any(
        call.kwargs["season"] == 2026 and "stats_player_week" in call.kwargs["url"]
        for call in service._validated.await_args_list
    )


@pytest.mark.asyncio
async def test_player_environment_context_requires_three_games_for_aggregates():
    service = WeeklyMatchupEvidenceService()
    current = _environment_schedule(2026, 1, target_week=1)
    history_2025 = _environment_schedule(2025, 2)
    stats_2025 = [
        _player_stat(game, points)
        for game, points in zip(
            [game for game in history_2025 if game.home_team == current[0].home_team],
            (8.0, 18.0),
        )
    ]

    async def validated(*, season, url, ttl, validator, cache_namespace="default"):
        del ttl, validator, cache_namespace
        if url.endswith("games.csv"):
            return {
                "games": {2025: history_2025, 2026: current},
                "errors": {2024: "fixture unavailable"},
            }, _metadata("schedule")
        return stats_2025, _metadata(url)

    service._validated = AsyncMock(side_effect=validated)
    result = await service.get_evidence(
        [{"name": "Amon-Ra St. Brown", "team": current[0].home_team, "position": "WR"}],
        season=2026,
        target_week=1,
        cutoff_week=0,
        scoring_basis="standard",
        now=NOW,
        include_player_context=True,
    )

    context = result["players"][0]["player_environment_context"]
    assert context["status"] == "insufficient_history"
    assert context["history"]["all_stat_rows_count"] == 2
    assert context["history"]["all_stat_row_average_points"] is None
    assert context["history"]["comparable_stat_rows_count"] == 2
    assert context["history"]["comparable_stat_row_average_points"] is None
    assert context["history"]["comparable_stat_row_median_points"] is None
    assert len(context["history"]["comparable_games"]) == 2
    assert context["identity"]["status"] == "name_position_only"
    assert context["identity"]["verified"] is False
    assert context["confidence"] == "none"
    assert context["warnings"][0] == "2024 schedule source unavailable: fixture unavailable"
    assert "Identity is unverified" in context["warnings"][1]


@pytest.mark.asyncio
async def test_player_environment_context_fails_closed_for_ambiguous_identity():
    service = WeeklyMatchupEvidenceService()
    current = _environment_schedule(2026, 1, target_week=1)
    history_2025 = _environment_schedule(2025, 1)
    player_game = next(game for game in history_2025 if game.home_team == current[0].home_team)
    ambiguous_stats = [
        _player_stat(player_game, 10.0, player_id="first"),
        _player_stat(player_game, 10.0, player_id="second"),
    ]

    async def validated(*, season, url, ttl, validator, cache_namespace="default"):
        del ttl, validator, cache_namespace
        if url.endswith("games.csv"):
            return {
                "games": {2025: history_2025, 2026: current},
                "errors": {2024: "fixture unavailable"},
            }, _metadata("schedule")
        return ambiguous_stats, _metadata(url)

    service._validated = AsyncMock(side_effect=validated)
    result = await service.get_evidence(
        [{"name": "Amon-Ra St. Brown", "team": current[0].home_team, "position": "WR"}],
        season=2026,
        target_week=1,
        cutoff_week=0,
        scoring_basis="ppr",
        now=NOW,
        include_player_context=True,
    )

    context = result["players"][0]["player_environment_context"]
    assert context["status"] == "identity_ambiguous"
    assert context["identity"]["status"] == "ambiguous"
    assert context["identity"]["nflverse_player_id"] is None
    assert context["history"]["all_stat_row_average_points"] is None


@pytest.mark.asyncio
async def test_player_environment_context_reports_unsupported_scoring_without_history_fetches():
    service = WeeklyMatchupEvidenceService()
    current = _environment_schedule(2026, 1, target_week=1)
    service._validated = AsyncMock(
        return_value=(
            {"games": {2026: current}, "errors": {}},
            _metadata("schedule"),
        )
    )

    result = await service.get_evidence(
        [{"name": "Amon-Ra St. Brown", "team": current[0].home_team, "position": "WR"}],
        season=2026,
        target_week=1,
        cutoff_week=0,
        scoring_basis="custom",
        now=NOW,
        include_player_context=True,
    )

    context = result["players"][0]["player_environment_context"]
    assert context["status"] == "unsupported_scoring_basis"
    assert context["current_environment"]["venue_type"] == "indoor"
    assert context["applied"] is False
    assert service._validated.await_count == 1


@pytest.mark.asyncio
async def test_player_environment_context_reports_source_unavailable_without_guessing_identity():
    service = WeeklyMatchupEvidenceService()
    current = _environment_schedule(2026, 1, target_week=1)

    async def validated(*, season, url, ttl, validator, cache_namespace="default"):
        del season, ttl, validator, cache_namespace
        assert url.endswith("games.csv")
        return {
            "games": {2026: current},
            "errors": {2024: "2024 unavailable", 2025: "2025 unavailable"},
        }, _metadata("schedule")

    service._validated = AsyncMock(side_effect=validated)
    result = await service.get_evidence(
        [{"name": "Amon-Ra St. Brown", "team": current[0].home_team, "position": "WR"}],
        season=2026,
        target_week=1,
        cutoff_week=0,
        scoring_basis="ppr",
        now=NOW,
        include_player_context=True,
    )

    context = result["players"][0]["player_environment_context"]
    assert context["status"] == "source_unavailable"
    assert context["identity"]["status"] == "unmatched"
    assert context["identity"]["nflverse_player_id"] is None
    assert len(context["warnings"]) == 3
