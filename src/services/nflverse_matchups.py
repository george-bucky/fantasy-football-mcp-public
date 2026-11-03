"""Source-backed weekly NFL opponent and matchup-strength evidence.

Data is provided by nflverse under CC BY 4.0. The service deliberately keeps
schedule identity separate from derived defensive strength and never serves an
expired cache entry or a partially validated response.
"""

from __future__ import annotations

import asyncio
import csv
import io
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import aiohttp

SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
STATS_URL_TEMPLATE = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.csv"
)
NFLVERSE_ATTRIBUTION = "nflverse data, CC BY 4.0"

CANONICAL_TEAMS = frozenset(
    {
        "ARI",
        "ATL",
        "BAL",
        "BUF",
        "CAR",
        "CHI",
        "CIN",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GB",
        "HOU",
        "IND",
        "JAX",
        "KC",
        "LA",
        "LAC",
        "LV",
        "MIA",
        "MIN",
        "NE",
        "NO",
        "NYG",
        "NYJ",
        "PHI",
        "PIT",
        "SEA",
        "SF",
        "TB",
        "TEN",
        "WAS",
    }
)
TEAM_ALIASES = {
    "JAC": "JAX",
    "JAX": "JAX",
    "LAR": "LA",
    "LA": "LA",
    "WSH": "WAS",
    "WAS": "WAS",
}
SUPPORTED_POSITIONS = ("QB", "RB", "WR", "TE")
SCORING_BASES = frozenset({"standard", "half_ppr", "ppr"})

_SCHEDULE_REQUIRED = {
    "game_id",
    "season",
    "game_type",
    "week",
    "gameday",
    "gametime",
    "home_team",
    "away_team",
    "result",
}
_STATS_REQUIRED = {
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
}


class MatchupEvidenceError(ValueError):
    """Raised when an upstream response cannot support trustworthy evidence."""


def canonical_team(value: Any) -> Optional[str]:
    raw = str(value or "").strip().upper()
    normalized = TEAM_ALIASES.get(raw, raw)
    return normalized if normalized in CANONICAL_TEAMS else None


def canonical_position(value: Any) -> Optional[str]:
    raw = str(value or "").strip().upper()
    if raw == "FB":
        return "RB"
    return raw if raw in SUPPORTED_POSITIONS else None


def canonical_scoring_basis(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    aliases = {"std": "standard", "half": "half_ppr", "halfppr": "half_ppr"}
    return aliases.get(raw, raw)


def _int(value: Any, field: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise MatchupEvidenceError(f"Invalid {field}: {value!r}") from exc


def _float(value: Any, field: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise MatchupEvidenceError(f"Invalid {field}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise MatchupEvidenceError(f"Invalid {field}: {value!r}")
    return parsed


def _optional_int(value: Any, field: str) -> Optional[int]:
    if value is None or not str(value).strip():
        return None
    return _int(value, field)


def _rows(text: str, required: set[str], dataset: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    fields = set(reader.fieldnames or [])
    missing = sorted(required - fields)
    if missing:
        raise MatchupEvidenceError(f"{dataset} missing required fields: {', '.join(missing)}")
    rows = [dict(row) for row in reader]
    if not rows:
        raise MatchupEvidenceError(f"{dataset} returned no rows")
    return rows


def _kickoff(row: dict[str, str]) -> Optional[datetime]:
    day = str(row.get("gameday") or "").strip()
    time_value = str(row.get("gametime") or "").strip()
    if not day or not time_value:
        return None
    try:
        local = datetime.strptime(f"{day} {time_value}", "%Y-%m-%d %H:%M").replace(
            tzinfo=ZoneInfo("America/New_York")
        )
    except ValueError:
        return None
    return local.astimezone(timezone.utc)


@dataclass(frozen=True)
class ScheduleGame:
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    kickoff: Optional[datetime]
    completed: bool = False
    weekday: Optional[str] = None
    roof: Optional[str] = None
    surface: Optional[str] = None
    home_rest: Optional[int] = None
    away_rest: Optional[int] = None


@dataclass(frozen=True)
class StatsRow:
    game_id: str
    player_id: str
    season: int
    week: int
    team: str
    opponent: str
    position: Optional[str]
    standard_points: float
    receptions: float
    ppr_points: float
    player_display_name: Optional[str] = None


@dataclass(frozen=True)
class SourceMetadata:
    source_url: str
    version: str
    fetched_at: datetime


@dataclass
class _CacheEntry:
    value: Any
    metadata: SourceMetadata
    expires_at: datetime


def parse_schedule(text: str, *, season: int) -> list[ScheduleGame]:
    parsed = _rows(text, _SCHEDULE_REQUIRED, "nflverse schedules")
    games: list[ScheduleGame] = []
    game_ids: set[str] = set()
    team_games: dict[str, int] = {team: 0 for team in CANONICAL_TEAMS}
    for row in parsed:
        if _int(row["season"], "schedule season") != season:
            continue
        if str(row["game_type"]).strip().upper() != "REG":
            continue
        game_id = str(row["game_id"] or "").strip()
        if not game_id or game_id in game_ids:
            raise MatchupEvidenceError("Schedule game_id values must be unique and nonblank")
        home = canonical_team(row["home_team"])
        away = canonical_team(row["away_team"])
        if not home or not away or home == away:
            raise MatchupEvidenceError(f"Invalid schedule teams for game {game_id}")
        game_ids.add(game_id)
        team_games[home] += 1
        team_games[away] += 1
        week = _int(row["week"], "schedule week")
        if not 1 <= week <= 18:
            raise MatchupEvidenceError(f"Invalid schedule week: {week}")
        games.append(
            ScheduleGame(
                game_id=game_id,
                season=season,
                week=week,
                home_team=home,
                away_team=away,
                kickoff=_kickoff(row),
                completed=bool(str(row["result"] or "").strip()),
                weekday=str(row.get("weekday") or "").strip() or None,
                roof=str(row.get("roof") or "").strip().lower() or None,
                surface=str(row.get("surface") or "").strip().lower() or None,
                home_rest=_optional_int(row.get("home_rest"), "home_rest"),
                away_rest=_optional_int(row.get("away_rest"), "away_rest"),
            )
        )
    if not games:
        raise MatchupEvidenceError(f"No regular-season schedule rows for {season}")
    counts = set(team_games.values())
    if 0 in counts or len(counts) != 1:
        raise MatchupEvidenceError("Schedule does not reconcile all 32 canonical teams")
    return games


def _parse_schedule_bundle(
    text: str, *, seasons: Sequence[int], required_season: int
) -> dict[str, Any]:
    games: dict[int, list[ScheduleGame]] = {}
    errors: dict[int, str] = {}
    for bundle_season in seasons:
        try:
            games[bundle_season] = parse_schedule(text, season=bundle_season)
        except MatchupEvidenceError as exc:
            errors[bundle_season] = str(exc)
    if required_season not in games:
        reason = errors.get(required_season, "missing from schedule bundle")
        raise MatchupEvidenceError(f"Required {required_season} schedule unavailable: {reason}")
    return {"games": games, "errors": errors}


def validate_target_week(games: Sequence[ScheduleGame], target_week: int) -> None:
    seen: set[str] = set()
    target_games = [game for game in games if game.week == target_week]
    if not target_games:
        raise MatchupEvidenceError(f"Schedule has no games for target week {target_week}")
    for game in target_games:
        for team in (game.home_team, game.away_team):
            if team in seen:
                raise MatchupEvidenceError(f"Team {team} appears twice in target week")
            seen.add(team)


def _completed_games(
    games: Sequence[ScheduleGame], *, cutoff_week: int, now: datetime
) -> list[ScheduleGame]:
    return [
        game
        for game in games
        if game.week <= cutoff_week
        and game.completed
        and game.kickoff is not None
        and game.kickoff < now
    ]


def parse_stats(text: str, *, season: int) -> list[StatsRow]:
    parsed = _rows(text, _STATS_REQUIRED, "nflverse weekly player stats")
    rows: list[StatsRow] = []
    identities: set[tuple[str, str]] = set()
    for row in parsed:
        if _int(row["season"], "stats season") != season:
            continue
        if str(row["season_type"]).strip().upper() != "REG":
            continue
        game_id = str(row["game_id"] or "").strip()
        team = canonical_team(row["team"])
        opponent = canonical_team(row["opponent_team"])
        if not game_id or not team or not opponent or team == opponent:
            raise MatchupEvidenceError("Stats require a valid game and team/opponent direction")
        position = canonical_position(row["position"])
        player_id = str(row["player_id"] or "").strip()
        if position:
            identity = (game_id, player_id)
            if not player_id or identity in identities:
                raise MatchupEvidenceError(
                    "Supported player stats require unique nonblank (game_id, player_id)"
                )
            identities.add(identity)
        standard = _float(row["fantasy_points"], "fantasy_points")
        receptions = _float(row["receptions"], "receptions")
        ppr = _float(row["fantasy_points_ppr"], "fantasy_points_ppr")
        if abs(ppr - (standard + receptions)) > 0.011:
            raise MatchupEvidenceError("PPR points do not reconcile to standard plus receptions")
        week = _int(row["week"], "stats week")
        if not 1 <= week <= 18:
            raise MatchupEvidenceError(f"Invalid stats week: {week}")
        rows.append(
            StatsRow(
                game_id=game_id,
                player_id=player_id,
                season=season,
                week=week,
                team=team,
                opponent=opponent,
                position=position,
                standard_points=standard,
                receptions=receptions,
                ppr_points=ppr,
                player_display_name=(str(row.get("player_display_name") or "").strip() or None),
            )
        )
    if not rows:
        raise MatchupEvidenceError(f"No regular-season weekly stats rows for {season}")
    return rows


def _calculate_strength_rows(
    parsed: Sequence[StatsRow],
    *,
    cutoff_week: int,
    schedule: Sequence[ScheduleGame],
    scoring_basis: str,
    now: datetime,
) -> dict[tuple[str, str], dict[str, Any]]:
    basis = canonical_scoring_basis(scoring_basis)
    if basis not in SCORING_BASES:
        raise MatchupEvidenceError(f"Unsupported scoring basis: {basis or 'unknown'}")
    completed = _completed_games(schedule, cutoff_week=cutoff_week, now=now)
    schedule_by_id = {game.game_id: game for game in completed}
    if not completed:
        return {}

    # Every completed defense-game-position cell starts at zero. This preserves
    # games where, for example, no tight end recorded a fantasy point.
    grid: dict[tuple[str, str, str], float] = {}
    games_by_defense: dict[str, set[str]] = {team: set() for team in CANONICAL_TEAMS}
    directions: dict[str, set[tuple[str, str]]] = {game.game_id: set() for game in completed}
    for game in completed:
        for defense in (game.home_team, game.away_team):
            games_by_defense[defense].add(game.game_id)
            for position in SUPPORTED_POSITIONS:
                grid[(defense, game.game_id, position)] = 0.0

    for row in parsed:
        if row.week > cutoff_week:
            completed_game = schedule_by_id.get(row.game_id)
            if completed_game and row.week != completed_game.week:
                raise MatchupEvidenceError(
                    f"Stats week does not match schedule for game {row.game_id}"
                )
            continue
        if row.game_id not in schedule_by_id:
            raise MatchupEvidenceError(
                f"Stats row references incomplete or unknown game {row.game_id}"
            )
        game = schedule_by_id[row.game_id]
        if row.week != game.week:
            raise MatchupEvidenceError(f"Stats week does not match schedule for game {row.game_id}")
        if {row.team, row.opponent} != {game.home_team, game.away_team}:
            raise MatchupEvidenceError(f"Invalid team/opponent direction for game {row.game_id}")
        directions[row.game_id].add((row.team, row.opponent))
        if not row.position:
            continue
        points = {
            "standard": row.standard_points,
            "half_ppr": row.standard_points + (0.5 * row.receptions),
            "ppr": row.ppr_points,
        }[basis]
        grid[(row.opponent, row.game_id, row.position)] += points

    for game in completed:
        expected = {
            (game.home_team, game.away_team),
            (game.away_team, game.home_team),
        }
        if directions[game.game_id] != expected:
            raise MatchupEvidenceError(
                f"Both offenses are not represented for completed game {game.game_id}"
            )

    if set(team for team, ids in games_by_defense.items() if ids) != set(CANONICAL_TEAMS):
        raise MatchupEvidenceError("Stats do not reconcile all 32 canonical defenses")
    if any(len(ids) < 4 for ids in games_by_defense.values()):
        return {}

    averages: dict[tuple[str, str], float] = {}
    for defense in CANONICAL_TEAMS:
        game_ids = games_by_defense[defense]
        for position in SUPPORTED_POSITIONS:
            total = sum(grid[(defense, game_id, position)] for game_id in game_ids)
            averages[(defense, position)] = total / len(game_ids)

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for position in SUPPORTED_POSITIONS:
        values = [averages[(defense, position)] for defense in CANONICAL_TEAMS]
        for defense in CANONICAL_TEAMS:
            value = averages[(defense, position)]
            greater = sum(candidate > value for candidate in values)
            equal = sum(candidate == value for candidate in values)
            # Descending midrank: rank 1 is the most favorable defense to face.
            rank = 1 + greater + ((equal - 1) / 2)
            percentile = 100 * ((len(values) - rank) / (len(values) - 1))
            result[(defense, position)] = {
                "games_sampled": len(games_by_defense[defense]),
                "points_allowed_per_game": round(value, 3),
                "rank": round(rank, 3),
                "percentile": round(percentile, 3),
            }
    return result


def calculate_strength(
    text: str,
    *,
    season: int,
    cutoff_week: int,
    schedule: Sequence[ScheduleGame],
    scoring_basis: str,
    now: datetime,
) -> dict[tuple[str, str], dict[str, Any]]:
    return _calculate_strength_rows(
        parse_stats(text, season=season),
        cutoff_week=cutoff_week,
        schedule=schedule,
        scoring_basis=scoring_basis,
        now=now,
    )


def _normalized_player_name(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_name = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", ascii_name.casefold()))


def _venue_type(roof: Optional[str]) -> Optional[str]:
    normalized = str(roof or "").strip().lower()
    if normalized in {"dome", "closed"}:
        return "indoor"
    if normalized in {"outdoors", "open"}:
        return "outdoor"
    return None


def _rest_bucket(rest_days: Optional[int]) -> Optional[str]:
    if rest_days is None:
        return None
    if rest_days <= 5:
        return "short"
    if rest_days <= 8:
        return "normal"
    return "long"


def _game_environment(game: ScheduleGame, team: str) -> dict[str, Any]:
    kickoff = game.kickoff
    local_kickoff = kickoff.astimezone(ZoneInfo("America/New_York")) if kickoff else None
    rest_days = game.home_rest if team == game.home_team else game.away_rest
    return {
        "weekday": game.weekday or (local_kickoff.strftime("%A") if local_kickoff else None),
        "kickoff_window": (
            "night"
            if local_kickoff and local_kickoff.hour >= 18
            else "day" if local_kickoff else None
        ),
        "kickoff_window_basis": "America/New_York; night>=18:00",
        "venue_type": _venue_type(game.roof),
        "roof": game.roof,
        "surface": game.surface,
        "home_away": "home" if team == game.home_team else "away",
        "rest_days": rest_days,
    }


_SIMILARITY_WEIGHTS = {
    "venue_type": 3,
    "weekday": 2,
    "kickoff_window": 2,
    "home_away": 1,
    "rest_bucket": 1,
    "surface": 1,
}


def _comparison_values(environment: dict[str, Any]) -> dict[str, Any]:
    return {
        "venue_type": environment.get("venue_type"),
        "weekday": environment.get("weekday"),
        "kickoff_window": environment.get("kickoff_window"),
        "home_away": environment.get("home_away"),
        "rest_bucket": _rest_bucket(environment.get("rest_days")),
        "surface": environment.get("surface"),
    }


def _similarity(
    target: dict[str, Any], candidate: dict[str, Any]
) -> Optional[tuple[float, list[str]]]:
    target_values = _comparison_values(target)
    candidate_values = _comparison_values(candidate)
    if not target_values["venue_type"] or not candidate_values["venue_type"]:
        return None
    comparable = [
        field
        for field in _SIMILARITY_WEIGHTS
        if target_values[field] is not None and candidate_values[field] is not None
    ]
    if len(comparable) < 3:
        return None
    denominator = sum(_SIMILARITY_WEIGHTS[field] for field in comparable)
    matched = [field for field in comparable if target_values[field] == candidate_values[field]]
    score = sum(_SIMILARITY_WEIGHTS[field] for field in matched) / denominator
    return score, matched


def _points(row: StatsRow, scoring_basis: str) -> float:
    return {
        "standard": row.standard_points,
        "half_ppr": row.standard_points + (0.5 * row.receptions),
        "ppr": row.ppr_points,
    }[scoring_basis]


def _source_payload(metadata: SourceMetadata, *, season: Optional[int] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "url": metadata.source_url,
        "version": metadata.version,
        "fetched_at": metadata.fetched_at.isoformat(),
    }
    if season is not None:
        payload["season"] = season
    return payload


def _effective_sample_size(weights: Sequence[float]) -> float:
    if not weights:
        return 0.0
    squared_sum = sum(weight * weight for weight in weights)
    if not squared_sum:
        return 0.0
    return round((sum(weights) ** 2) / squared_sum, 3)


def _recency_payload(
    game_rows: Sequence[dict[str, Any]], target_game: ScheduleGame
) -> dict[str, Any]:
    if not game_rows:
        return {"status": "unavailable", "latest_game": None, "days_old": None}
    latest = max(
        game_rows,
        key=lambda item: (
            item["game"].kickoff or datetime.min.replace(tzinfo=timezone.utc),
            item["row"].season,
            item["row"].week,
        ),
    )
    latest_game = latest["game"]
    days_old: Optional[int] = None
    if target_game.kickoff is not None and latest_game.kickoff is not None:
        days_old = max(0, (target_game.kickoff - latest_game.kickoff).days)
    if latest_game.season == target_game.season:
        status = "current_season"
    elif days_old is not None and days_old <= 450:
        status = "recent"
    else:
        status = "stale"
    return {
        "status": status,
        "latest_game": {
            "game_id": latest_game.game_id,
            "season": latest_game.season,
            "week": latest_game.week,
            "kickoff": latest_game.kickoff.isoformat() if latest_game.kickoff else None,
        },
        "days_old": days_old,
    }


def _evidence_confidence(
    *,
    identity_verified: bool,
    sample_size: int,
    effective_sample_size: float,
    recency_status: str,
    has_source_warnings: bool,
) -> str:
    if sample_size < 3:
        return "none"
    if not identity_verified or has_source_warnings or recency_status == "stale":
        return "low"
    if sample_size >= 12 and effective_sample_size >= 10:
        return "high"
    if sample_size >= 6 and effective_sample_size >= 5:
        return "moderate"
    return "low"


def empty_player_environment_context(status: str, warning: Optional[str] = None) -> dict[str, Any]:
    coverage_semantics = (
        "Counts include nflverse player stat rows only; a missing row is unknown coverage, "
        "not a confirmed appearance or zero-point game."
    )
    return {
        "status": status,
        "applied": False,
        "confidence": "none",
        "identity": {
            "status": "unmatched",
            "verified": False,
            "confidence": "none",
            "match_method": None,
            "nflverse_player_id": None,
        },
        "current_environment": None,
        "history": {
            "requested_seasons": [],
            "included_seasons": [],
            "all_stat_rows_count": 0,
            "all_stat_row_average_points": None,
            "comparable_stat_rows_count": 0,
            "comparable_stat_row_average_points": None,
            "comparable_stat_row_median_points": None,
            "difference_from_all_stat_row_average": None,
            "minimum_aggregate_sample": 3,
            "effective_sample_size": 0.0,
            "coverage_semantics": coverage_semantics,
            "splits": [],
            "comparable_games": [],
        },
        "evidence_quality": {
            "confidence": "none",
            "effective_sample_size": 0.0,
            "recency": {"status": "unavailable", "latest_game": None, "days_old": None},
            "identity_verified": False,
            "source_coverage": "unavailable",
        },
        "analysis_semantics": {
            "mode": "descriptive_only",
            "projection_residual_status": "unavailable_no_historical_pregame_projection",
            "note": (
                "Historical pregame projections are not archived, so these splits describe "
                "past stat rows and do not estimate performance above or below expectation."
            ),
        },
        "provenance": {
            "attribution": NFLVERSE_ATTRIBUTION,
            "schedule": [],
            "player_stats": [],
        },
        "warnings": [warning] if warning else [],
    }


def _build_player_environment_context(
    player: dict[str, Any],
    *,
    target_game: Optional[ScheduleGame],
    target_team: Optional[str],
    scoring_basis: str,
    historical_games: Sequence[ScheduleGame],
    historical_stats: Sequence[StatsRow],
    history_seasons: Sequence[int],
    included_history_seasons: Sequence[int],
    schedule_source: SourceMetadata,
    schedule_sources: Sequence[tuple[int, SourceMetadata]],
    stats_sources: Sequence[tuple[int, SourceMetadata]],
    source_warnings: Sequence[str],
    successful_history_sources: int,
) -> dict[str, Any]:
    schedule_provenance = [
        _source_payload(metadata, season=source_season)
        for source_season, metadata in schedule_sources
    ] or [_source_payload(schedule_source)]
    stats_provenance = [
        _source_payload(metadata, season=source_season) for source_season, metadata in stats_sources
    ]

    def with_scope(context: dict[str, Any]) -> dict[str, Any]:
        context["history"]["requested_seasons"] = list(history_seasons)
        context["history"]["included_seasons"] = list(included_history_seasons)
        context["provenance"]["schedule"] = schedule_provenance
        context["provenance"]["player_stats"] = stats_provenance
        context["evidence_quality"]["source_coverage"] = (
            "partial" if source_warnings else "complete" if stats_sources else "unavailable"
        )
        return context

    if target_team and target_game is None:
        context = empty_player_environment_context("bye")
        return with_scope(context)

    current_environment = (
        _game_environment(target_game, target_team)
        if target_game is not None and target_team is not None
        else None
    )
    if scoring_basis not in SCORING_BASES:
        context = empty_player_environment_context("unsupported_scoring_basis")
        context["current_environment"] = current_environment
        context["provenance"]["schedule"] = schedule_provenance
        context["warnings"].append("Historical points require standard, half-PPR, or PPR scoring")
        return with_scope(context)
    position = canonical_position(player.get("position"))
    name = _normalized_player_name(player.get("name"))
    if not name or not position:
        context = empty_player_environment_context(
            "identity_unavailable",
            "Player name and supported position are required for exact matching",
        )
        context["current_environment"] = current_environment
        context["provenance"]["schedule"] = schedule_provenance
        return with_scope(context)
    if not successful_history_sources:
        context = empty_player_environment_context(
            "source_unavailable", "No validated historical player-stat source was available"
        )
        context["current_environment"] = current_environment
        context["provenance"]["schedule"] = schedule_provenance
        context["warnings"].extend(source_warnings)
        return with_scope(context)

    matching_ids = {
        row.player_id
        for row in historical_stats
        if row.position == position and _normalized_player_name(row.player_display_name) == name
    }
    provided_player_id = str(player.get("nflverse_player_id") or "").strip()
    if provided_player_id:
        if provided_player_id not in matching_ids:
            context = empty_player_environment_context(
                "identity_unavailable",
                "Provided nflverse player ID did not exactly match the player name and position",
            )
            context["current_environment"] = current_environment
            context["provenance"]["schedule"] = schedule_provenance
            context["provenance"]["player_stats"] = [
                _source_payload(metadata, season=source_season)
                for source_season, metadata in stats_sources
            ]
            context["warnings"].extend(source_warnings)
            return with_scope(context)
        player_id = provided_player_id
        identity = {
            "status": "verified",
            "verified": True,
            "confidence": "high",
            "match_method": "provided_id_exact_name_position",
            "nflverse_player_id": player_id,
        }
        identity_warning: Optional[str] = None
    elif not matching_ids:
        context = empty_player_environment_context(
            "identity_unavailable", "No exact nflverse player name and position match was found"
        )
        context["current_environment"] = current_environment
        context["provenance"]["schedule"] = schedule_provenance
        context["provenance"]["player_stats"] = [
            _source_payload(metadata, season=source_season)
            for source_season, metadata in stats_sources
        ]
        context["warnings"].extend(source_warnings)
        return with_scope(context)
    elif len(matching_ids) > 1:
        context = empty_player_environment_context(
            "identity_ambiguous",
            "More than one nflverse player ID matched the exact name and position",
        )
        context["identity"].update(
            {
                "status": "ambiguous",
                "match_method": "unique_normalized_exact_name_position",
            }
        )
        context["current_environment"] = current_environment
        context["provenance"]["schedule"] = schedule_provenance
        context["provenance"]["player_stats"] = [
            _source_payload(metadata, season=source_season)
            for source_season, metadata in stats_sources
        ]
        context["warnings"].extend(source_warnings)
        return with_scope(context)
    else:
        player_id = next(iter(matching_ids))
        identity = {
            "status": "name_position_only",
            "verified": False,
            "confidence": "low",
            "match_method": "unique_normalized_exact_name_position",
            "nflverse_player_id": player_id,
        }
        identity_warning = (
            "Identity is unverified because no nflverse_player_id was supplied; "
            "name-and-position context is descriptive only"
        )
    provenance = {
        "attribution": NFLVERSE_ATTRIBUTION,
        "schedule": schedule_provenance,
        "player_stats": [
            _source_payload(metadata, season=source_season)
            for source_season, metadata in stats_sources
        ],
    }
    if current_environment is None:
        context = empty_player_environment_context("target_environment_unavailable")
        context.update(
            {
                "identity": identity,
                "current_environment": current_environment,
                "provenance": provenance,
                "warnings": [*source_warnings, "Target game environment is unavailable"],
            }
        )
        return with_scope(context)
    target_values = _comparison_values(current_environment)
    if (
        not target_values["venue_type"]
        or sum(value is not None for value in target_values.values()) < 3
    ):
        context = empty_player_environment_context("target_environment_unavailable")
        context.update(
            {
                "identity": identity,
                "current_environment": current_environment,
                "provenance": provenance,
                "warnings": [
                    *source_warnings,
                    "Target environment lacks a known venue type or three comparable factors",
                ],
            }
        )
        return with_scope(context)

    games_by_id = {game.game_id: game for game in historical_games}
    game_rows: list[dict[str, Any]] = []
    for row in historical_stats:
        if row.player_id != player_id:
            continue
        game = games_by_id.get(row.game_id)
        if game is None:
            continue
        environment = _game_environment(game, row.team)
        similarity = _similarity(current_environment, environment)
        game_rows.append(
            {
                "row": row,
                "game": game,
                "environment": environment,
                "points": _points(row, scoring_basis),
                "similarity": similarity,
            }
        )

    all_points = [item["points"] for item in game_rows]
    comparable = [
        item
        for item in game_rows
        if item["similarity"] is not None and item["similarity"][0] >= 0.70
    ]
    comparable.sort(
        key=lambda item: (
            -item["similarity"][0],
            -item["row"].season,
            -item["row"].week,
            item["row"].game_id,
        )
    )
    comparable_points = [item["points"] for item in comparable]
    effective_sample_size = _effective_sample_size([item["similarity"][0] for item in comparable])
    all_average = statistics.fmean(all_points) if len(all_points) >= 3 else None
    comparable_average = (
        statistics.fmean(comparable_points) if len(comparable_points) >= 3 else None
    )

    split_rows: list[dict[str, Any]] = []
    for dimension, target_value in target_values.items():
        if target_value is None:
            split_rows.append(
                {
                    "dimension": dimension,
                    "target_value": None,
                    "stat_rows": 0,
                    "average_points": None,
                    "status": "target_value_unavailable",
                }
            )
            continue
        matching_points = [
            item["points"]
            for item in game_rows
            if _comparison_values(item["environment"])[dimension] == target_value
        ]
        split_rows.append(
            {
                "dimension": dimension,
                "target_value": target_value,
                "stat_rows": len(matching_points),
                "average_points": (
                    round(statistics.fmean(matching_points), 3)
                    if len(matching_points) >= 3
                    else None
                ),
                "status": "available" if len(matching_points) >= 3 else "insufficient_history",
            }
        )

    comparable_payload: list[dict[str, Any]] = []
    for item in comparable[:5]:
        row = item["row"]
        game = item["game"]
        environment = item["environment"]
        opponent = game.away_team if row.team == game.home_team else game.home_team
        comparable_payload.append(
            {
                "game_id": game.game_id,
                "season": row.season,
                "week": row.week,
                "kickoff": game.kickoff.isoformat() if game.kickoff else None,
                "opponent": opponent,
                "home_away": environment["home_away"],
                "weekday": environment["weekday"],
                "kickoff_window": environment["kickoff_window"],
                "roof": environment["roof"],
                "venue_type": environment["venue_type"],
                "surface": environment["surface"],
                "rest_days": environment["rest_days"],
                "fantasy_points": round(item["points"], 3),
                "similarity_score": round(item["similarity"][0], 3),
                "matched_factors": item["similarity"][1],
            }
        )

    recency = _recency_payload(game_rows, target_game)
    identity_verified = bool(identity["verified"])
    confidence = _evidence_confidence(
        identity_verified=identity_verified,
        sample_size=len(comparable),
        effective_sample_size=effective_sample_size,
        recency_status=recency["status"],
        has_source_warnings=bool(source_warnings),
    )
    if not successful_history_sources:
        status = "source_unavailable"
    elif len(comparable) < 3:
        status = "insufficient_history"
    elif source_warnings or not identity_verified:
        status = "partial"
    else:
        status = "available"
    coverage_semantics = (
        "Counts include nflverse player stat rows only; a missing row is unknown coverage, "
        "not a confirmed appearance or zero-point game."
    )
    history = {
        "requested_seasons": list(history_seasons),
        "included_seasons": list(included_history_seasons),
        "all_stat_rows_count": len(all_points),
        "all_stat_row_average_points": round(all_average, 3) if all_average is not None else None,
        "comparable_stat_rows_count": len(comparable),
        "comparable_stat_row_average_points": (
            round(comparable_average, 3) if comparable_average is not None else None
        ),
        "comparable_stat_row_median_points": (
            round(statistics.median(comparable_points), 3) if len(comparable_points) >= 3 else None
        ),
        "difference_from_all_stat_row_average": (
            round(comparable_average - all_average, 3)
            if comparable_average is not None and all_average is not None
            else None
        ),
        "minimum_aggregate_sample": 3,
        "effective_sample_size": effective_sample_size,
        "coverage_semantics": coverage_semantics,
        "splits": split_rows,
        "comparable_games": comparable_payload,
    }
    warnings = list(source_warnings)
    if identity_warning:
        warnings.append(identity_warning)
    return {
        "status": status,
        "applied": False,
        "confidence": confidence,
        "identity": identity,
        "current_environment": current_environment,
        "history": history,
        "evidence_quality": {
            "confidence": confidence,
            "effective_sample_size": effective_sample_size,
            "recency": recency,
            "identity_verified": identity_verified,
            "source_coverage": "partial" if source_warnings else "complete",
        },
        "analysis_semantics": {
            "mode": "descriptive_only",
            "projection_residual_status": "unavailable_no_historical_pregame_projection",
            "note": (
                "Historical pregame projections are not archived, so these splits describe "
                "past stat rows and do not estimate performance above or below expectation."
            ),
        },
        "provenance": provenance,
        "warnings": warnings,
    }


class WeeklyMatchupEvidenceService:
    """Fetch and apply validated nflverse weekly matchup evidence."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, str, str, str], _CacheEntry] = {}
        self._current: dict[tuple[int, str, str], tuple[int, str, str, str]] = {}
        self._lock = asyncio.Lock()

    async def _download(self, url: str) -> tuple[str, SourceMetadata]:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise MatchupEvidenceError(f"nflverse returned HTTP {response.status}")
                text = await response.text()
                fetched = datetime.now(timezone.utc)
                version = (
                    response.headers.get("ETag")
                    or response.headers.get("Last-Modified")
                    or f"fetched:{fetched.isoformat()}"
                )
                return text, SourceMetadata(url, version, fetched)

    async def _validated(
        self,
        *,
        season: int,
        url: str,
        ttl: timedelta,
        validator,
        cache_namespace: str = "default",
    ) -> tuple[Any, SourceMetadata]:
        now = datetime.now(timezone.utc)
        current_key = self._current.get((season, url, cache_namespace))
        if current_key:
            cached = self._cache.get(current_key)
            if cached and cached.expires_at > now:
                return cached.value, cached.metadata
        async with self._lock:
            now = datetime.now(timezone.utc)
            current_key = self._current.get((season, url, cache_namespace))
            if current_key:
                cached = self._cache.get(current_key)
                if cached and cached.expires_at > now:
                    return cached.value, cached.metadata
            text, metadata = await self._download(url)
            value = validator(text)
            key = (season, url, cache_namespace, metadata.version)
            self._cache[key] = _CacheEntry(value, metadata, now + ttl)
            self._current[(season, url, cache_namespace)] = key
            return value, metadata

    async def get_game_bindings(
        self,
        players: Sequence[dict[str, Any]],
        *,
        season: int,
        target_week: int,
        now: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Bind a roster to upcoming games using the validated schedule only.

        Absence establishes a bye only with complete regular-season coverage;
        no player statistics, historical seasons, or numeric effects are loaded.
        """
        if type(season) is not int or not 2000 <= season <= 2100:
            raise MatchupEvidenceError("Season must be an integer between 2000 and 2100")
        if type(target_week) is not int or not 1 <= target_week <= 18:
            raise MatchupEvidenceError("Target week must be an integer between 1 and 18")
        if now is not None and (
            not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
        ):
            raise MatchupEvidenceError("Binding clock must be timezone-aware")
        clock = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
        if not players:
            return []
        schedule_meta = None
        target_by_team: dict[str, ScheduleGame] = {}
        schedule_reason = None
        complete_schedule = False
        try:
            schedule, schedule_meta = await self._validated(
                season=season,
                url=SCHEDULE_URL,
                ttl=timedelta(minutes=15),
                validator=lambda text: parse_schedule(text, season=season),
            )
            if (
                not isinstance(schedule_meta, SourceMetadata)
                or schedule_meta.source_url != SCHEDULE_URL
                or not isinstance(schedule_meta.version, str)
                or not schedule_meta.version.strip()
                or not isinstance(schedule_meta.fetched_at, datetime)
                or schedule_meta.fetched_at.tzinfo is None
                or schedule_meta.fetched_at.utcoffset() is None
            ):
                raise MatchupEvidenceError("Invalid schedule provenance")
            game_ids: set[str] = set()
            team_counts = {team: 0 for team in CANONICAL_TEAMS}
            for game in schedule:
                if (
                    not isinstance(game, ScheduleGame)
                    or type(game.season) is not int
                    or game.season != season
                    or type(game.week) is not int
                    or not 1 <= game.week <= 18
                    or not isinstance(game.game_id, str)
                    or not game.game_id.strip()
                    or game.game_id in game_ids
                    or game.home_team not in CANONICAL_TEAMS
                    or game.away_team not in CANONICAL_TEAMS
                    or game.home_team == game.away_team
                ):
                    raise MatchupEvidenceError("Invalid schedule binding rows")
                game_ids.add(game.game_id)
                team_counts[game.home_team] += 1
                team_counts[game.away_team] += 1
            validate_target_week(schedule, target_week)
            for game in schedule:
                if game.week == target_week:
                    target_by_team[game.home_team] = game
                    target_by_team[game.away_team] = game
            expected_games = 17 if season >= 2021 else 16
            complete_schedule = all(count == expected_games for count in team_counts.values())
        except Exception:
            # Provider bodies/exception strings are not part of this small public contract.
            target_by_team = {}
            schedule_meta = None
            schedule_reason = "schedule_unavailable_or_invalid"
        if now is None:
            clock = datetime.now(timezone.utc)  # A fetch crossing kickoff is no longer pregame.
        output = []
        for player in players:
            raw_team = (
                player.get("team") if isinstance(player, dict) else getattr(player, "team", None)
            )
            raw_opponent = (
                player.get("opponent")
                if isinstance(player, dict)
                else getattr(player, "opponent", None)
            )
            if isinstance(raw_opponent, str) and not raw_opponent.strip():
                raw_opponent = None
            team = canonical_team(raw_team)
            row: dict[str, Any] = {
                "status": "unavailable",
                "available": False,
                "reason": None,
                "team": team,
                "opponent": None,
                "schedule_game_id": None,
                "kickoff": None,
                "season": season,
                "week": target_week,
                "provenance": {
                    "schedule": (
                        _source_payload(schedule_meta, season=season) if schedule_meta else None
                    ),
                    "attribution": NFLVERSE_ATTRIBUTION,
                    "assessed_at": clock.isoformat(),
                },
            }
            if team is None:
                row["reason"] = "unrecognized_nfl_team"
            elif schedule_reason:
                row["reason"] = schedule_reason
            elif team not in target_by_team:
                if not complete_schedule:
                    row["reason"] = "incomplete_schedule_cannot_establish_bye"
                elif raw_opponent not in (None, "") and str(raw_opponent).strip().upper() != "BYE":
                    row["reason"] = "opponent_mismatch"
                else:
                    row.update(status="bye", reason="bye_week")
            else:
                game = target_by_team[team]
                opponent = game.away_team if team == game.home_team else game.home_team
                supplied = canonical_team(raw_opponent)
                if raw_opponent not in (None, "") and supplied != opponent:
                    row["reason"] = "opponent_mismatch"
                elif (
                    not isinstance(game.kickoff, datetime)
                    or game.kickoff.tzinfo is None
                    or game.kickoff.utcoffset() is None
                ):
                    row["reason"] = "kickoff_unavailable"
                elif game.kickoff.astimezone(timezone.utc).year not in (season, season + 1):
                    row["reason"] = "kickoff_period_mismatch"
                elif game.completed or game.kickoff.astimezone(timezone.utc) <= clock:
                    row["reason"] = "game_already_started"
                else:
                    row.update(
                        status="matched",
                        available=True,
                        team=team,
                        opponent=opponent,
                        schedule_game_id=game.game_id,
                        kickoff=game.kickoff.astimezone(timezone.utc).isoformat(),
                        home_away="home" if team == game.home_team else "away",
                    )
            output.append(row)
        return output

    async def _environment_history(
        self,
        *,
        season: int,
        cutoff_week: int,
        now: datetime,
        schedule_by_season: dict[int, Sequence[ScheduleGame]],
        schedule_errors: dict[int, str],
        schedule_meta: SourceMetadata,
        current_stats: Optional[Sequence[StatsRow]],
        current_stats_meta: Optional[SourceMetadata],
        current_stats_error: str,
    ) -> tuple[
        list[ScheduleGame],
        list[StatsRow],
        list[int],
        list[int],
        list[tuple[int, SourceMetadata]],
        list[tuple[int, SourceMetadata]],
        list[str],
    ]:
        games: list[ScheduleGame] = []
        stats: list[StatsRow] = []
        included_seasons: list[int] = []
        schedule_sources: list[tuple[int, SourceMetadata]] = []
        stats_sources: list[tuple[int, SourceMetadata]] = []
        seasons = list(range(max(2020, season - 2), season + 1))
        warnings = [
            f"{failed_season} schedule source unavailable: {reason}"
            for failed_season, reason in sorted(schedule_errors.items())
            if failed_season in seasons
        ]

        for schedule_season in seasons:
            if schedule_season in schedule_by_season:
                schedule_sources.append((schedule_season, schedule_meta))

        for history_season in seasons:
            history_cutoff = cutoff_week if history_season == season else 18
            if history_cutoff < 1:
                continue
            season_schedule = schedule_by_season.get(history_season)
            if season_schedule is None:
                continue

            completed = _completed_games(season_schedule, cutoff_week=history_cutoff, now=now)
            completed_by_id = {game.game_id: game for game in completed}
            if not completed:
                warnings.append(f"{history_season} has no completed games before the cutoff")
                continue

            season_stats: Optional[Sequence[StatsRow]] = None
            season_stats_meta: Optional[SourceMetadata] = None
            if history_season == season and current_stats is not None:
                season_stats = current_stats
                season_stats_meta = current_stats_meta
            elif history_season == season and current_stats_error:
                warnings.append(f"{history_season} player stats unavailable: {current_stats_error}")
                continue
            else:
                stats_url = STATS_URL_TEMPLATE.format(season=history_season)
                try:
                    season_stats, season_stats_meta = await self._validated(
                        season=history_season,
                        url=stats_url,
                        ttl=timedelta(hours=6),
                        validator=lambda text, value=history_season: parse_stats(
                            text, season=value
                        ),
                    )
                except Exception as exc:
                    warnings.append(f"{history_season} player stats unavailable: {exc}")
                    continue

            included_rows: list[StatsRow] = []
            try:
                for row in season_stats or []:
                    if row.week > history_cutoff:
                        continue
                    game = completed_by_id.get(row.game_id)
                    if game is None:
                        raise MatchupEvidenceError(
                            f"Stats row references incomplete or unknown game {row.game_id}"
                        )
                    if row.week != game.week:
                        raise MatchupEvidenceError(
                            f"Stats week does not match schedule for game {row.game_id}"
                        )
                    if {row.team, row.opponent} != {game.home_team, game.away_team}:
                        raise MatchupEvidenceError(
                            f"Invalid team/opponent direction for game {row.game_id}"
                        )
                    included_rows.append(row)
            except MatchupEvidenceError as exc:
                warnings.append(f"{history_season} player stats unavailable: {exc}")
                continue

            games.extend(completed)
            stats.extend(included_rows)
            included_seasons.append(history_season)
            if season_stats_meta is not None:
                stats_sources.append((history_season, season_stats_meta))

        return (
            games,
            stats,
            seasons,
            included_seasons,
            schedule_sources,
            stats_sources,
            warnings,
        )

    async def get_evidence(
        self,
        players: Sequence[dict[str, Any]],
        *,
        season: int,
        target_week: int,
        cutoff_week: int,
        scoring_basis: str,
        now: Optional[datetime] = None,
        include_player_context: bool = False,
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise MatchupEvidenceError("Evidence clock must be timezone-aware")
        now = now.astimezone(timezone.utc)
        if not 1 <= target_week <= 18:
            raise MatchupEvidenceError("Target week must be between 1 and 18")
        if cutoff_week < 0 or cutoff_week >= target_week:
            raise MatchupEvidenceError("Cutoff week must precede the target week")
        basis = canonical_scoring_basis(scoring_basis)

        requested_history_seasons = list(range(max(2020, season - 2), season + 1))
        if include_player_context and not requested_history_seasons:
            raise MatchupEvidenceError("Player environment context requires season 2020 or later")
        schedule_errors: dict[int, str] = {}
        if include_player_context:
            schedule_bundle, schedule_meta = await self._validated(
                season=season,
                url=SCHEDULE_URL,
                ttl=timedelta(minutes=15),
                validator=lambda text: _parse_schedule_bundle(
                    text,
                    seasons=requested_history_seasons,
                    required_season=season,
                ),
                cache_namespace=f"player_context:{requested_history_seasons[0]}:{season}",
            )
            schedule_by_season = schedule_bundle["games"]
            schedule_errors = schedule_bundle["errors"]
            schedule = schedule_by_season[season]
        else:
            schedule, schedule_meta = await self._validated(
                season=season,
                url=SCHEDULE_URL,
                ttl=timedelta(minutes=15),
                validator=lambda text: parse_schedule(text, season=season),
            )
            schedule_by_season = {season: schedule}
        validate_target_week(schedule, target_week)

        strength: dict[tuple[str, str], dict[str, Any]] = {}
        strength_meta: Optional[SourceMetadata] = None
        strength_reason = ""
        current_stats: Optional[Sequence[StatsRow]] = None
        if basis not in SCORING_BASES:
            strength_reason = "unsupported_scoring_basis"
        elif cutoff_week < 1:
            strength_reason = "insufficient_history"
        else:
            stats_url = STATS_URL_TEMPLATE.format(season=season)
            try:

                def validate_stats(text: str) -> list[StatsRow]:
                    rows = parse_stats(text, season=season)
                    _calculate_strength_rows(
                        rows,
                        cutoff_week=cutoff_week,
                        schedule=schedule,
                        scoring_basis=basis,
                        now=now,
                    )
                    return rows

                stats_rows, strength_meta = await self._validated(
                    season=season,
                    url=stats_url,
                    ttl=timedelta(hours=6),
                    validator=validate_stats,
                )
                strength = _calculate_strength_rows(
                    stats_rows,
                    cutoff_week=cutoff_week,
                    schedule=schedule,
                    scoring_basis=basis,
                    now=now,
                )
                if not strength:
                    strength_reason = "insufficient_history"
                current_stats = stats_rows
            except Exception as exc:
                strength_reason = f"source_unavailable: {exc}"

        target_by_team: dict[str, ScheduleGame] = {}
        for game in schedule:
            if game.week == target_week:
                target_by_team[game.home_team] = game
                target_by_team[game.away_team] = game

        historical_games: list[ScheduleGame] = []
        historical_stats: list[StatsRow] = []
        history_seasons: list[int] = (
            list(requested_history_seasons) if include_player_context else []
        )
        included_history_seasons: list[int] = []
        schedule_sources: list[tuple[int, SourceMetadata]] = (
            [
                (schedule_season, schedule_meta)
                for schedule_season in requested_history_seasons
                if schedule_season in schedule_by_season
            ]
            if include_player_context
            else []
        )
        stats_sources: list[tuple[int, SourceMetadata]] = []
        context_warnings: list[str] = [
            f"{failed_season} schedule source unavailable: {reason}"
            for failed_season, reason in sorted(schedule_errors.items())
            if failed_season in requested_history_seasons
        ]
        if include_player_context and basis in SCORING_BASES:
            (
                historical_games,
                historical_stats,
                history_seasons,
                included_history_seasons,
                schedule_sources,
                stats_sources,
                context_warnings,
            ) = await self._environment_history(
                season=season,
                cutoff_week=cutoff_week,
                now=now,
                schedule_by_season=schedule_by_season,
                schedule_errors=schedule_errors,
                schedule_meta=schedule_meta,
                current_stats=current_stats,
                current_stats_meta=strength_meta,
                current_stats_error=(
                    strength_reason if strength_reason.startswith("source_unavailable") else ""
                ),
            )

        output: list[dict[str, Any]] = []
        for player in players:
            team = canonical_team(player.get("team"))
            position = canonical_position(player.get("position"))
            warnings: list[str] = []
            evidence: dict[str, Any] = {
                "enabled": True,
                "available": False,
                "applied": False,
                "unavailable_reason": None,
                "season": season,
                "target_week": target_week,
                "cutoff_week": cutoff_week,
                "opponent": None,
                "home_away": None,
                "kickoff": None,
                "canonical_scoring_basis": basis or "unknown",
                "games_sampled": 0,
                "points_allowed_per_game": None,
                "rank": None,
                "percentile": None,
                "source_url": schedule_meta.source_url,
                "source_version": schedule_meta.version,
                "fetched_at": schedule_meta.fetched_at.isoformat(),
                "attribution": NFLVERSE_ATTRIBUTION,
                "warnings": warnings,
                "tie_break_audit": [],
                "schedule": {"status": "unavailable"},
                "strength": {"status": "source_unavailable"},
            }
            if not team:
                evidence["unavailable_reason"] = "unrecognized_nfl_team"
                warnings.append("NFL team could not be reconciled exactly")
                if include_player_context:
                    evidence["player_environment_context"] = empty_player_environment_context(
                        "target_environment_unavailable",
                        "NFL team could not be reconciled exactly",
                    )
                output.append(evidence)
                continue
            game = target_by_team.get(team)
            if game is None:
                evidence["schedule"] = {"status": "bye"}
                evidence["unavailable_reason"] = "bye_week"
                if include_player_context:
                    evidence["player_environment_context"] = _build_player_environment_context(
                        player,
                        target_game=None,
                        target_team=team,
                        scoring_basis=basis,
                        historical_games=historical_games,
                        historical_stats=historical_stats,
                        history_seasons=history_seasons,
                        included_history_seasons=included_history_seasons,
                        schedule_source=schedule_meta,
                        schedule_sources=schedule_sources,
                        stats_sources=stats_sources,
                        source_warnings=context_warnings,
                        successful_history_sources=len(stats_sources),
                    )
                output.append(evidence)
                continue
            opponent = game.away_team if team == game.home_team else game.home_team
            home_away = "home" if team == game.home_team else "away"
            kickoff = game.kickoff.isoformat() if game.kickoff else None
            evidence.update(
                {
                    "opponent": opponent,
                    "home_away": home_away,
                    "kickoff": kickoff,
                    "schedule": {"status": "matched", "game_id": game.game_id},
                }
            )
            if include_player_context:
                evidence["player_environment_context"] = _build_player_environment_context(
                    player,
                    target_game=game,
                    target_team=team,
                    scoring_basis=basis,
                    historical_games=historical_games,
                    historical_stats=historical_stats,
                    history_seasons=history_seasons,
                    included_history_seasons=included_history_seasons,
                    schedule_source=schedule_meta,
                    schedule_sources=schedule_sources,
                    stats_sources=stats_sources,
                    source_warnings=context_warnings,
                    successful_history_sources=len(stats_sources),
                )
            if not position:
                evidence["strength"] = {"status": "unsupported_position"}
                evidence["unavailable_reason"] = "unsupported_position"
                output.append(evidence)
                continue
            row = strength.get((opponent, position))
            if not row:
                status = (
                    "insufficient_history"
                    if strength_reason == "insufficient_history"
                    else "source_unavailable"
                )
                evidence["strength"] = {"status": status}
                evidence["unavailable_reason"] = strength_reason or status
                output.append(evidence)
                continue
            evidence.update(row)
            evidence["strength"] = {"status": "available"}
            if strength_meta:
                evidence["source_url"] = strength_meta.source_url
                evidence["source_version"] = strength_meta.version
                evidence["fetched_at"] = strength_meta.fetched_at.isoformat()
            if game.kickoff is None:
                evidence["unavailable_reason"] = "kickoff_unavailable"
            elif game.kickoff <= now:
                evidence["unavailable_reason"] = "game_already_started"
            else:
                evidence["available"] = True
            output.append(evidence)

        return {
            "enabled": True,
            "season": season,
            "target_week": target_week,
            "cutoff_week": cutoff_week,
            "canonical_scoring_basis": basis or "unknown",
            "players": output,
            "warnings": [],
            "attribution": NFLVERSE_ATTRIBUTION,
            "schedule_source": {
                "url": schedule_meta.source_url,
                "version": schedule_meta.version,
                "fetched_at": schedule_meta.fetched_at.isoformat(),
            },
            "strength_source": (
                {
                    "url": strength_meta.source_url,
                    "version": strength_meta.version,
                    "fetched_at": strength_meta.fetched_at.isoformat(),
                }
                if strength_meta
                else None
            ),
        }


weekly_matchup_evidence_service = WeeklyMatchupEvidenceService()


__all__ = [
    "CANONICAL_TEAMS",
    "MatchupEvidenceError",
    "NFLVERSE_ATTRIBUTION",
    "SCHEDULE_URL",
    "STATS_URL_TEMPLATE",
    "WeeklyMatchupEvidenceService",
    "calculate_strength",
    "canonical_scoring_basis",
    "canonical_team",
    "empty_player_environment_context",
    "parse_schedule",
    "parse_stats",
    "validate_target_week",
    "weekly_matchup_evidence_service",
]
