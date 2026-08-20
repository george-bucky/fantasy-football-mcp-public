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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import aiohttp

SCHEDULE_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
)
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
            )
        )
    if not games:
        raise MatchupEvidenceError(f"No regular-season schedule rows for {season}")
    counts = set(team_games.values())
    if 0 in counts or len(counts) != 1:
        raise MatchupEvidenceError("Schedule does not reconcile all 32 canonical teams")
    return games


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
            raise MatchupEvidenceError(
                f"Stats week does not match schedule for game {row.game_id}"
            )
        if {row.team, row.opponent} != {game.home_team, game.away_team}:
            raise MatchupEvidenceError(
                f"Invalid team/opponent direction for game {row.game_id}"
            )
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


class WeeklyMatchupEvidenceService:
    """Fetch and apply validated nflverse weekly matchup evidence."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, str, str], _CacheEntry] = {}
        self._current: dict[tuple[int, str], tuple[int, str, str]] = {}
        self._lock = asyncio.Lock()

    async def _download(self, url: str) -> tuple[str, SourceMetadata]:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
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
    ) -> tuple[Any, SourceMetadata]:
        now = datetime.now(timezone.utc)
        current_key = self._current.get((season, url))
        if current_key:
            cached = self._cache.get(current_key)
            if cached and cached.expires_at > now:
                return cached.value, cached.metadata
        async with self._lock:
            now = datetime.now(timezone.utc)
            current_key = self._current.get((season, url))
            if current_key:
                cached = self._cache.get(current_key)
                if cached and cached.expires_at > now:
                    return cached.value, cached.metadata
            text, metadata = await self._download(url)
            value = validator(text)
            key = (season, url, metadata.version)
            self._cache[key] = _CacheEntry(value, metadata, now + ttl)
            self._current[(season, url)] = key
            return value, metadata

    async def get_evidence(
        self,
        players: Sequence[dict[str, Any]],
        *,
        season: int,
        target_week: int,
        cutoff_week: int,
        scoring_basis: str,
        now: Optional[datetime] = None,
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

        schedule, schedule_meta = await self._validated(
            season=season,
            url=SCHEDULE_URL,
            ttl=timedelta(minutes=15),
            validator=lambda text: parse_schedule(text, season=season),
        )
        validate_target_week(schedule, target_week)

        strength: dict[tuple[str, str], dict[str, Any]] = {}
        strength_meta: Optional[SourceMetadata] = None
        strength_reason = ""
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
            except Exception as exc:
                strength_reason = f"source_unavailable: {exc}"

        target_by_team: dict[str, ScheduleGame] = {}
        for game in schedule:
            if game.week == target_week:
                target_by_team[game.home_team] = game
                target_by_team[game.away_team] = game

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
                output.append(evidence)
                continue
            game = target_by_team.get(team)
            if game is None:
                evidence["schedule"] = {"status": "bye"}
                evidence["unavailable_reason"] = "bye_week"
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
    "parse_schedule",
    "parse_stats",
    "validate_target_week",
    "weekly_matchup_evidence_service",
]
