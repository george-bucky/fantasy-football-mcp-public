"""Credential-free preparation of a source-attributed manual draft value board.

The service deliberately has no Yahoo imports.  Network providers are isolated so a
secondary source failure cannot erase an otherwise useful ESPN projection board.
"""

# Python 3.9 remains a declared package target, so keep Optional instead of PEP 604 unions.
# ruff: noqa: UP045

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import math
import os
import re
import tempfile
import time
import unicodedata
from collections import Counter, OrderedDict
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Callable,
    Optional,
    cast,
)
from urllib.parse import urlparse

import aiohttp

SCHEMA_VERSION = "1.0.0"
BOARD_SEASON = 2026
MAX_PLAYERS = 250
REQUEST_TIMEOUT_SECONDS = 12
OVERALL_TIMEOUT_SECONDS = 40

ESPN_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/"
    "segments/0/leaguedefaults/1?view=kona_player_info"
)
ECR_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_fpecr_latest.csv"
FFC_URL = (
    "https://fantasyfootballcalculator.com/api/v1/adp/half-ppr" "?teams=12&year=2026&position=all"
)
SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_TRENDING_ADD_URL = (
    "https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=24&limit=100"
)
SLEEPER_TRENDING_DROP_URL = (
    "https://api.sleeper.app/v1/players/nfl/trending/drop?lookback_hours=24&limit=100"
)
NFLVERSE_URL_TEMPLATE = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.csv"
)
NFLVERSE_SEASONS = (2023, 2024, 2025)

PROVIDER_CAPS = {
    "espn": 2 * 1024 * 1024,
    "ecr": 2 * 1024 * 1024,
    "ffc": 2 * 1024 * 1024,
    "sleeper_players": 16 * 1024 * 1024,
    "sleeper_trending": 1024 * 1024,
    "nflverse": 16 * 1024 * 1024,
}
PROVIDER_TTLS = {
    "espn": 6 * 60 * 60,
    "ecr": 6 * 60 * 60,
    "ffc": 24 * 60 * 60,
    "sleeper_players": 24 * 60 * 60,
    "sleeper_trending": 30 * 60,
    "nflverse": 7 * 24 * 60 * 60,
}
SNAPSHOT_FRESH_SECONDS = 6 * 60 * 60

SOURCE_LABELS = {
    "espn": "ESPN public fantasy endpoint (community-documented; no official contract)",
    "ecr": "DynastyProcess open-data FantasyPros ECR",
    "ffc": "Fantasy Football Calculator 12-team half-PPR ADP",
    "sleeper": "Sleeper public API identity/status/depth/trending context",
    "nflverse": "nflverse weekly player stats, CC BY 4.0",
}

MANUAL_DRAFT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "profile": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "profile_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "season": {"type": "integer", "const": BOARD_SEASON, "default": BOARD_SEASON},
                "team_count": {"type": "integer", "minimum": 2, "maximum": 32},
                "draft": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {"type": "string", "enum": ["snake", "linear", "auction"]},
                        "slot": {"type": "integer", "minimum": 1, "maximum": 32},
                    },
                    "required": ["type", "slot"],
                },
                "roster_slots": {
                    "oneOf": [
                        {
                            "type": "object",
                            "additionalProperties": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 32,
                            },
                        },
                        {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                            "maxItems": 64,
                        },
                    ]
                },
                "scoring": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": True,
                    "properties": {
                        **{
                            field: {"type": "number"}
                            for field in (
                                "passing_yards",
                                "passing_touchdowns",
                                "interceptions",
                                "passing_40_yard_touchdowns",
                                "fumbles_lost",
                                "rushing_yards",
                                "rushing_touchdowns",
                                "receiving_yards",
                                "receiving_touchdowns",
                                "receptions",
                                "two_point_conversions",
                                "passing_two_point_conversions",
                                "rushing_two_point_conversions",
                                "receiving_two_point_conversions",
                            )
                        },
                        "rushing_yard_milestones": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                            "description": "Mutually exclusive rushing-yard tier totals.",
                        },
                        "receiving_yard_milestones": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                            "description": "Mutually exclusive receiving-yard tier totals.",
                        },
                    },
                    "description": (
                        "Explicit points per raw stat. Unknown fields are retained and returned "
                        "as unsupported instead of being silently scored."
                    ),
                },
            },
            "required": ["team_count", "draft", "roster_slots", "scoring"],
        },
        "preview_limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        "force_refresh": {"type": "boolean", "default": False},
    },
    "required": ["profile"],
}


class ManualDraftError(ValueError):
    """The manual draft profile or prepared snapshot is invalid."""


class ProviderError(RuntimeError):
    """A bounded public provider request or response failed."""


@dataclass
class _CacheEntry:
    value: dict[str, Any]
    stored_at: float
    ttl_seconds: int


@dataclass
class _ProviderResult:
    name: str
    rows: list[dict[str, Any]]
    source: dict[str, Any]
    warnings: list[str]


_ESPN_POSITION = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
_ESPN_FIXED_SLOT = {"QB": 0, "RB": 2, "WR": 4, "TE": 6, "DEF": 16, "K": 17}
_ESPN_TEAM = {
    1: "ATL",
    2: "BUF",
    3: "CHI",
    4: "CIN",
    5: "CLE",
    6: "DAL",
    7: "DEN",
    8: "DET",
    9: "GB",
    10: "TEN",
    11: "IND",
    12: "KC",
    13: "LV",
    14: "LAR",
    15: "MIA",
    16: "MIN",
    17: "NE",
    18: "NO",
    19: "NYG",
    20: "NYJ",
    21: "PHI",
    22: "ARI",
    23: "PIT",
    24: "LAC",
    25: "SF",
    26: "SEA",
    27: "TB",
    28: "WAS",
    29: "CAR",
    30: "JAX",
    33: "BAL",
    34: "HOU",
}
_TEAM_ALIASES = {
    "JAC": "JAX",
    "LAR": "LAR",
    "LA": "LAR",
    "WSH": "WAS",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
}
_POSITION_ALIASES = {"D/ST": "DEF", "DST": "DEF", "D": "DEF", "PK": "K", "FB": "RB"}

# ESPN raw season projection stat IDs.  Applied fantasy totals are intentionally never read.
_ESPN_STAT_IDS = {
    "passing_yards": "3",
    "passing_touchdowns": "4",
    "passing_40_yard_touchdowns": "15",
    "passing_two_point_conversions": "19",
    "interceptions": "20",
    "rushing_yards": "24",
    "rushing_touchdowns": "25",
    "rushing_two_point_conversions": "26",
    "receptions": "53",
    "receiving_yards": "42",
    "receiving_touchdowns": "43",
    "receiving_two_point_conversions": "44",
    "fumbles_lost": "72",
    "_rushing_100_199_games": "37",
    "_rushing_200_plus_games": "38",
    "_receiving_100_199_games": "56",
    "_receiving_200_plus_games": "57",
}

_SCORING_ALIASES = {
    "pass_yd": "passing_yards",
    "pass_yds": "passing_yards",
    "pass_td": "passing_touchdowns",
    "pass_tds": "passing_touchdowns",
    "pass_td_40": "passing_40_yard_touchdowns",
    "passing_40_plus_yard_touchdowns": "passing_40_yard_touchdowns",
    "interceptions_thrown": "interceptions",
    "fumble_lost": "fumbles_lost",
    "rush_yd": "rushing_yards",
    "rush_yds": "rushing_yards",
    "rush_td": "rushing_touchdowns",
    "rush_tds": "rushing_touchdowns",
    "rec_yd": "receiving_yards",
    "rec_yds": "receiving_yards",
    "rec_td": "receiving_touchdowns",
    "rec_tds": "receiving_touchdowns",
    "reception": "receptions",
    "pass_two_point": "passing_two_point_conversions",
    "rush_two_point": "rushing_two_point_conversions",
    "receiving_two_point": "receiving_two_point_conversions",
}
_DIRECT_SCORING_FIELDS = frozenset(field for field in _ESPN_STAT_IDS if not field.startswith("_"))
_SCORING_POSITION_SCOPE = {
    field: (
        {"QB"}
        if field.startswith("passing_") or field == "interceptions"
        else {"QB", "RB", "WR", "TE"}
    )
    for field in _DIRECT_SCORING_FIELDS
}
_MILESTONE_FIELDS = ("rushing_yard_milestones", "receiving_yard_milestones")
_COMPONENT_WEIGHTS = {
    "projection_value": 0.55,
    "ecr": 0.25,
    "adp": 0.15,
    "availability": 0.05,
}

_FLEX_ELIGIBILITY = {
    "FLEX": ("RB", "WR", "TE"),
    "W/R/T": ("RB", "WR", "TE"),
    "WR/RB/TE": ("RB", "WR", "TE"),
    "RB/WR/TE": ("RB", "WR", "TE"),
    "W/R": ("RB", "WR"),
    "WR/RB": ("RB", "WR"),
    "W/T": ("WR", "TE"),
    "WR/TE": ("WR", "TE"),
    "R/T": ("RB", "TE"),
    "RB/TE": ("RB", "TE"),
    "SUPERFLEX": ("QB", "RB", "WR", "TE"),
    "OP": ("QB", "RB", "WR", "TE"),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> Optional[float]:
    if value in (None, "", "NA", "N/A"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalize_name(value: Any) -> str:
    """Normalize a name for conservative exact matching, never fuzzy matching."""

    text = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = text.encode("ascii", "ignore").decode("ascii").casefold()
    tokens = re.sub(r"[^a-z0-9]+", " ", ascii_text).split()
    collapsed: list[str] = []
    index = 0
    while index < len(tokens):
        if len(tokens[index]) == 1:
            initials: list[str] = []
            while index < len(tokens) and len(tokens[index]) == 1:
                initials.append(tokens[index])
                index += 1
            collapsed.append("".join(initials))
        else:
            collapsed.append(tokens[index])
            index += 1
    tokens = collapsed
    while tokens and tokens[-1] in {"jr", "sr", "ii", "iii", "iv", "v"}:
        tokens.pop()
    return " ".join(tokens)


def normalize_position(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return _POSITION_ALIASES.get(raw, raw)


def normalize_team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(raw, raw)


def identity_key(name: Any, position: Any, team: Any = None) -> tuple[str, str, str]:
    """Return the exact normalized name, position, and optional team identity."""

    return normalize_name(name), normalize_position(position), normalize_team(team)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _checksum(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _roster_counts(value: Any) -> dict[str, int]:
    raw_counts: dict[str, int]
    if isinstance(value, list):
        if not value or not all(isinstance(item, str) and item.strip() for item in value):
            raise ManualDraftError("roster_slots must contain non-empty slot names")
        raw_counts = dict(Counter(item.strip().upper() for item in value))
    elif isinstance(value, dict):
        raw_counts = {}
        for raw_slot, raw_count in value.items():
            if not isinstance(raw_slot, str) or not raw_slot.strip():
                raise ManualDraftError("roster slot names must be non-empty strings")
            if (
                isinstance(raw_count, bool)
                or not isinstance(raw_count, int)
                or not 0 <= raw_count <= 32
            ):
                raise ManualDraftError("roster slot counts must be integers between 0 and 32")
            raw_counts[raw_slot.strip().upper()] = raw_count
    else:
        raise ManualDraftError("roster_slots must be an object or list")
    counts: dict[str, int] = {}
    for slot, count in raw_counts.items():
        canonical = _POSITION_ALIASES.get(slot, slot)
        counts[canonical] = counts.get(canonical, 0) + count
    if not any(counts.values()):
        raise ManualDraftError("roster_slots must include at least one slot")
    return dict(sorted(counts.items()))


def _milestones(value: Any, field: str) -> dict[int, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ManualDraftError(f"{field} must be an object keyed by yard threshold")
    result: dict[int, float] = {}
    for raw_threshold, raw_points in value.items():
        try:
            threshold = int(raw_threshold)
            points = float(raw_points)
        except (TypeError, ValueError) as exc:
            raise ManualDraftError(f"{field} thresholds and points must be numeric") from exc
        if threshold <= 0 or not math.isfinite(points):
            raise ManualDraftError(f"{field} contains an invalid threshold or point value")
        result[threshold] = points
    return dict(sorted(result.items()))


def _canonical_scoring(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or not value:
        raise ManualDraftError("scoring must be a non-empty object")
    scoring: dict[str, Any] = {}
    unsupported: dict[str, Any] = {}
    two_point = value.get("two_point_conversions")
    for raw_key, raw_value in value.items():
        key = _SCORING_ALIASES.get(str(raw_key), str(raw_key))
        if key == "two_point_conversions":
            continue
        if key in _MILESTONE_FIELDS:
            scoring[key] = _milestones(raw_value, key)
        elif key in _DIRECT_SCORING_FIELDS:
            number = _number(raw_value)
            if number is None:
                raise ManualDraftError(f"scoring field {raw_key} must be numeric")
            scoring[key] = number
        else:
            unsupported[str(raw_key)] = raw_value
    if two_point is not None:
        points = _number(two_point)
        if points is None:
            raise ManualDraftError("two_point_conversions must be numeric")
        for key in (
            "passing_two_point_conversions",
            "rushing_two_point_conversions",
            "receiving_two_point_conversions",
        ):
            scoring.setdefault(key, points)
    return scoring, dict(sorted(unsupported.items()))


def validate_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize a reusable no-Yahoo league profile."""

    if not isinstance(profile, Mapping):
        raise ManualDraftError("profile must be an object")
    team_count = profile.get("team_count")
    if isinstance(team_count, bool) or not isinstance(team_count, int) or not 2 <= team_count <= 32:
        raise ManualDraftError("team_count must be an integer between 2 and 32")
    season = profile.get("season", BOARD_SEASON)
    if season != BOARD_SEASON:
        raise ManualDraftError("only the 2026 prepared board is supported")
    draft = profile.get("draft")
    if not isinstance(draft, Mapping):
        raise ManualDraftError("draft must include type and slot")
    draft_type = str(draft.get("type") or "").strip().lower()
    if draft_type not in {"snake", "linear", "auction"}:
        raise ManualDraftError("draft.type must be snake, linear, or auction")
    draft_slot = draft.get("slot")
    if (
        isinstance(draft_slot, bool)
        or not isinstance(draft_slot, int)
        or not 1 <= draft_slot <= team_count
    ):
        raise ManualDraftError("draft.slot must be within team_count")
    roster_slots = _roster_counts(profile.get("roster_slots"))
    scoring, unsupported_inputs = _canonical_scoring(profile.get("scoring"))
    raw_id = str(profile.get("profile_id") or "").strip()
    if raw_id and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", raw_id) is None:
        raise ManualDraftError(
            "profile_id must use only letters, numbers, dot, dash, or underscore"
        )
    canonical: dict[str, Any] = {
        "profile_id": raw_id,
        "season": BOARD_SEASON,
        "team_count": team_count,
        "draft": {"type": draft_type, "slot": draft_slot},
        "roster_slots": roster_slots,
        "scoring": scoring,
        "unsupported_scoring_fields": sorted(unsupported_inputs),
        "unsupported_scoring_inputs": unsupported_inputs,
    }
    if not raw_id:
        identity = dict(canonical)
        identity.pop("profile_id")
        canonical["profile_id"] = f"profile-{_checksum(identity)[:12]}"
    canonical["profile_checksum"] = _checksum(
        {key: value for key, value in canonical.items() if key != "profile_checksum"}
    )
    return canonical


def calculate_projected_points(
    raw_stats: Mapping[str, Any],
    scoring: Mapping[str, Any],
    milestone_estimates: Optional[Mapping[str, Mapping[int, float]]] = None,
) -> tuple[float, dict[str, float]]:
    """Score raw season projections with a transparent per-category breakdown."""

    breakdown: dict[str, float] = {}
    for field in sorted(_DIRECT_SCORING_FIELDS):
        if field not in scoring:
            continue
        stat = _number(raw_stats.get(field))
        if stat is None:
            continue
        breakdown[field] = stat * float(scoring[field])
    milestone_estimates = milestone_estimates or {}
    for field in _MILESTONE_FIELDS:
        rules = scoring.get(field)
        if not isinstance(rules, Mapping):
            continue
        estimates = milestone_estimates.get(field, {})
        for raw_threshold, raw_points in rules.items():
            threshold = int(raw_threshold)
            events = _number(estimates.get(threshold))
            if events is not None:
                breakdown[f"{field}_{threshold}"] = events * float(raw_points)
    return round(sum(breakdown.values()), 4), {
        key: round(value, 4) for key, value in sorted(breakdown.items())
    }


def _percentile_scores(
    values: Sequence[Optional[float]], lower_is_better: bool = False
) -> list[Optional[float]]:
    present = sorted(value for value in values if value is not None)
    if not present:
        return [None for _ in values]
    if len(present) == 1 or present[0] == present[-1]:
        return [50.0 if value is not None else None for value in values]
    output: list[Optional[float]] = []
    for value in values:
        if value is None:
            output.append(None)
            continue
        position = sum(item < value for item in present) + 0.5 * sum(
            item == value for item in present
        )
        percentile = 100.0 * position / len(present)
        output.append(round(100.0 - percentile if lower_is_better else percentile, 4))
    return output


def calculate_replacement_values(
    players: Sequence[Mapping[str, Any]], team_count: int, roster_slots: Mapping[str, int]
) -> dict[str, Optional[float]]:
    """Return FLEX-aware projected-point replacement levels by position."""

    by_position: dict[str, list[float]] = {}
    for player in players:
        points = _number(player.get("projected_points"))
        position = normalize_position(player.get("position"))
        if points is not None and position:
            by_position.setdefault(position, []).append(points)
    for values in by_position.values():
        values.sort(reverse=True)

    fixed_counts: dict[str, int] = {}
    flex_slots: list[tuple[tuple[str, ...], int]] = []
    for raw_slot, count in roster_slots.items():
        slot = str(raw_slot).upper()
        if count <= 0 or slot in {"BN", "BENCH", "IR", "NA"}:
            continue
        if slot in _FLEX_ELIGIBILITY:
            flex_slots.append((_FLEX_ELIGIBILITY[slot], count * team_count))
        elif slot in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            fixed_counts[slot] = fixed_counts.get(slot, 0) + count * team_count

    flex_selected: Counter[str] = Counter()
    remaining: dict[str, list[float]] = {
        position: values[fixed_counts.get(position, 0) :]
        for position, values in by_position.items()
    }
    for eligible, demand in flex_slots:
        for _ in range(demand):
            choices = [
                (remaining[position][0], position)
                for position in eligible
                if remaining.get(position)
            ]
            if not choices:
                break
            _, selected_position = max(choices, key=lambda item: (item[0], item[1]))
            remaining[selected_position].pop(0)
            flex_selected[selected_position] += 1

    levels: dict[str, Optional[float]] = {}
    for position, values in by_position.items():
        demand = fixed_counts.get(position, 0) + flex_selected[position]
        levels[position] = values[min(max(demand, 1), len(values)) - 1] if values else None
    return levels


def _roster_eligible_positions(roster_slots: Mapping[str, int]) -> set[str]:
    positions: set[str] = set()
    for raw_slot, count in roster_slots.items():
        if count <= 0:
            continue
        slot = str(raw_slot).upper()
        if slot in _FLEX_ELIGIBILITY:
            positions.update(_FLEX_ELIGIBILITY[slot])
        elif slot in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            positions.add(slot)
    return positions


def _espn_position_slot_ids(allowed_positions: set[str]) -> list[int]:
    return sorted(_ESPN_FIXED_SLOT[position] for position in allowed_positions)


def weighted_board_score(components: Mapping[str, Optional[float]]) -> dict[str, Any]:
    """Blend available evidence and reweight only the non-missing components."""

    available = {
        name: float(value)
        for name, value in components.items()
        if name in _COMPONENT_WEIGHTS and value is not None
    }
    weight_total = sum(_COMPONENT_WEIGHTS[name] for name in available)
    if not available or weight_total <= 0:
        return {
            "score": None,
            "components": {},
            "effective_weights": {},
            "missing": sorted(_COMPONENT_WEIGHTS),
        }
    effective = {name: _COMPONENT_WEIGHTS[name] / weight_total for name in available}
    score = sum(available[name] * effective[name] for name in available)
    return {
        "score": round(max(0.0, min(100.0, score)), 4),
        "components": {name: round(value, 4) for name, value in available.items()},
        "effective_weights": {name: round(value, 6) for name, value in effective.items()},
        "missing": sorted(set(_COMPONENT_WEIGHTS) - set(available)),
    }


def _parse_json(payload: bytes, provider: str) -> Any:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderError(f"{provider} returned malformed JSON") from exc


def parse_espn_projection_rows(
    payload: bytes, allowed_positions: Optional[set[str]] = None
) -> list[dict[str, Any]]:
    """Parse ESPN raw 2026 season stats, ignoring applied fantasy totals."""

    data = _parse_json(payload, "ESPN")
    if not isinstance(data, dict) or not isinstance(data.get("players"), list):
        raise ProviderError("ESPN returned an invalid player projection response")
    rows: list[dict[str, Any]] = []
    for container in data["players"][:MAX_PLAYERS]:
        if not isinstance(container, dict):
            continue
        entry_value = (
            container.get("playerPoolEntry")
            if isinstance(container.get("playerPoolEntry"), dict)
            else container
        )
        entry = cast(dict[str, Any], entry_value)
        player_value = entry.get("player") if isinstance(entry.get("player"), dict) else entry
        player = cast(dict[str, Any], player_value)
        if player.get("active") is not True:
            continue
        position_id = _number(player.get("defaultPositionId"))
        position = _ESPN_POSITION.get(int(position_id)) if position_id is not None else None
        if not position or (allowed_positions is not None and position not in allowed_positions):
            continue
        stats_value = player.get("stats")
        stats_entries = stats_value if isinstance(stats_value, list) else []
        season_projection = next(
            (
                stat
                for stat in stats_entries
                if isinstance(stat, dict)
                and stat.get("statSourceId") == 1
                and stat.get("statSplitTypeId") == 0
                and stat.get("seasonId") == BOARD_SEASON
                and isinstance(stat.get("stats"), dict)
            ),
            None,
        )
        if season_projection is None:
            continue
        raw = season_projection["stats"]
        normalized_stats = {
            field: _number(raw.get(stat_id, raw.get(int(stat_id))))
            for field, stat_id in _ESPN_STAT_IDS.items()
        }
        normalized_stats = {
            key: value for key, value in normalized_stats.items() if value is not None
        }
        name = str(player.get("fullName") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "provider_id": str(player.get("id") or entry.get("id") or "") or None,
                "name": name,
                "position": position,
                "team": (
                    _ESPN_TEAM.get(int(team_id), "")
                    if (team_id := _number(player.get("proTeamId"))) is not None
                    else ""
                ),
                "raw_projection_stats": normalized_stats,
            }
        )
    if not rows:
        raise ProviderError("ESPN returned no usable raw 2026 season projections")
    return rows


def parse_ecr_rows(payload: bytes) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProviderError("DynastyProcess ECR was not valid UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    required = {"page_type", "ecr_type", "player", "pos", "team", "ecr", "scrape_date"}
    if required - set(reader.fieldnames or []):
        raise ProviderError("DynastyProcess ECR response is missing required columns")
    rows: list[dict[str, Any]] = []
    for row in reader:
        if row.get("page_type") != "redraft-overall" or row.get("ecr_type") not in (None, "", "ro"):
            continue
        rank = _number(row.get("ecr"))
        if rank is None or not row.get("player") or not row.get("pos"):
            continue
        rows.append(
            {
                "provider_id": row.get("id") or None,
                "name": row["player"].strip(),
                "position": normalize_position(row["pos"]),
                "team": normalize_team(row.get("team")),
                "ecr": rank,
                "ecr_sd": _number(row.get("sd")),
                "source_date": row.get("scrape_date") or None,
            }
        )
    if not rows:
        raise ProviderError("DynastyProcess returned no current redraft-overall ECR rows")
    return rows[:MAX_PLAYERS]


def parse_ffc_rows(payload: bytes) -> list[dict[str, Any]]:
    data = _parse_json(payload, "Fantasy Football Calculator")
    candidates = data.get("players") if isinstance(data, dict) else None
    if not isinstance(candidates, list):
        raise ProviderError("Fantasy Football Calculator returned an invalid ADP response")
    rows: list[dict[str, Any]] = []
    for row in candidates[:MAX_PLAYERS]:
        if not isinstance(row, dict):
            continue
        rank = _number(row.get("adp"))
        name = str(row.get("name") or row.get("player_name") or "").strip()
        position = normalize_position(row.get("position"))
        if rank is None or not name or not position:
            continue
        rows.append(
            {
                "provider_id": str(row.get("player_id") or row.get("id") or "") or None,
                "name": name,
                "position": position,
                "team": normalize_team(row.get("team")),
                "adp": rank,
                "adp_sd": _number(
                    row.get("stdev") or row.get("sd") or row.get("standard_deviation")
                ),
            }
        )
    if not rows:
        raise ProviderError("Fantasy Football Calculator returned no usable half-PPR ADP rows")
    return rows


def parse_sleeper_rows(
    players_payload: bytes,
    adds_payload: Optional[bytes],
    drops_payload: Optional[bytes],
) -> list[dict[str, Any]]:
    players = _parse_json(players_payload, "Sleeper players")
    if not isinstance(players, dict):
        raise ProviderError("Sleeper returned an invalid players response")

    def trending(payload: Optional[bytes]) -> dict[str, float]:
        if payload is None:
            return {}
        values = _parse_json(payload, "Sleeper trending")
        if not isinstance(values, list):
            raise ProviderError("Sleeper returned an invalid trending response")
        return {
            str(item.get("player_id")): float(item.get("count") or 0)
            for item in values
            if isinstance(item, dict) and item.get("player_id") is not None
        }

    adds = trending(adds_payload)
    drops = trending(drops_payload)
    rows: list[dict[str, Any]] = []
    for player_id, player in players.items():
        if not isinstance(player, dict):
            continue
        name = str(
            player.get("full_name")
            or "{} {}".format(player.get("first_name") or "", player.get("last_name") or "")
        ).strip()
        position = normalize_position(player.get("position"))
        if not name or position not in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            continue
        rows.append(
            {
                "provider_id": str(player_id),
                "name": name,
                "position": position,
                "team": normalize_team(player.get("team")),
                "active": player.get("active"),
                "status": player.get("status"),
                "injury_status": player.get("injury_status"),
                "depth_chart_position": player.get("depth_chart_position"),
                "depth_chart_order": player.get("depth_chart_order"),
                "trending_adds": adds.get(str(player_id)),
                "trending_drops": drops.get(str(player_id)),
            }
        )
    if not rows:
        raise ProviderError("Sleeper returned no usable player identity rows")
    return rows


def parse_nflverse_rows(payloads: Sequence[tuple[int, bytes]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season, payload in payloads:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ProviderError("nflverse weekly stats were not valid UTF-8") from exc
        reader = csv.DictReader(io.StringIO(text))
        fields = set(reader.fieldnames or [])
        name_field = "player_display_name" if "player_display_name" in fields else "player_name"
        team_field = "recent_team" if "recent_team" in fields else "team"
        required = {name_field, "position", "rushing_yards", "receiving_yards"}
        if required - fields:
            raise ProviderError("nflverse weekly stats are missing milestone columns")
        for row in reader:
            if row.get("season_type", "REG") != "REG":
                continue
            name = str(row.get(name_field) or "").strip()
            position = normalize_position(row.get("position"))
            if not name or position not in {"QB", "RB", "WR", "TE"}:
                continue
            rows.append(
                {
                    "season": season,
                    "name": name,
                    "position": position,
                    "team": normalize_team(row.get(team_field)),
                    "rushing_yards": _number(row.get("rushing_yards")) or 0.0,
                    "receiving_yards": _number(row.get("receiving_yards")) or 0.0,
                }
            )
    if not rows:
        raise ProviderError("nflverse returned no usable weekly milestone history")
    return rows


def _provider_index(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[tuple[str, str, str], list[Mapping[str, Any]]],
    dict[tuple[str, str], list[Mapping[str, Any]]],
]:
    full: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    short: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        name, position, team = identity_key(row.get("name"), row.get("position"), row.get("team"))
        if not name or not position:
            continue
        full.setdefault((name, position, team), []).append(row)
        short.setdefault((name, position), []).append(row)
    return full, short


def exact_match(
    player: Mapping[str, Any], provider: str, rows: Sequence[Mapping[str, Any]]
) -> tuple[Optional[Mapping[str, Any]], Optional[dict[str, Any]]]:
    """Match name+position+team exactly, quarantining every ambiguity."""

    full, short = _provider_index(rows)
    name, position, team = identity_key(
        player.get("name"), player.get("position"), player.get("team")
    )
    candidates: list[Mapping[str, Any]] = []
    match_key = "name_position"
    if team:
        candidates = list(full.get((name, position, team), []))
        match_key = "name_position_team"
        if not candidates:
            short_candidates = list(short.get((name, position), []))
            if short_candidates and all(
                not normalize_team(row.get("team")) for row in short_candidates
            ):
                candidates = short_candidates
                match_key = "name_position_provider_team_missing"
    else:
        candidates = list(short.get((name, position), []))
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, {
            "provider": provider,
            "identity": {"name": name, "position": position, "team": team or None},
            "reason": "ambiguous_normalized_exact_match",
            "match_key": match_key,
            "candidate_count": len(candidates),
            "candidate_ids": sorted(str(row.get("provider_id") or "") for row in candidates),
        }
    return None, None


def _match_provenance(
    player: Mapping[str, Any], provider: str, match: Optional[Mapping[str, Any]]
) -> Optional[dict[str, Any]]:
    if match is None:
        return None
    player_team = normalize_team(player.get("team"))
    provider_team = normalize_team(match.get("team"))
    if player_team and provider_team:
        method = "unique_normalized_exact_name_position_team"
    elif player_team:
        method = "unique_normalized_exact_name_position_provider_team_missing"
    else:
        method = "unique_normalized_exact_name_position"
    provenance: dict[str, Any] = {
        "provider": provider,
        "provider_id": match.get("provider_id"),
        "match_method": method,
    }
    if match.get("source_date"):
        provenance["source_date"] = match["source_date"]
    return provenance


def _source_freshness(
    source: Mapping[str, Any], ttl_seconds: int, observed_at: datetime
) -> dict[str, Any]:
    components = source.get("components")
    if isinstance(components, Mapping):
        component_freshness: dict[str, dict[str, Any]] = {}
        for name, component in components.items():
            if not isinstance(component, Mapping):
                continue
            component_ttl = int(_number(component.get("cache_ttl_seconds")) or ttl_seconds)
            component_freshness[str(name)] = _source_freshness(
                component, component_ttl, observed_at
            )
        ages = [
            value["age_seconds"]
            for value in component_freshness.values()
            if value["age_seconds"] is not None
        ]
        return {
            "fetched_at": source.get("fetched_at"),
            "data_date": source.get("data_date"),
            "observed_at": _iso(observed_at),
            "age_seconds": max(ages) if ages else None,
            "cache_ttl_seconds": source.get("cache_ttl_seconds", ttl_seconds),
            "is_stale": not component_freshness
            or any(value["is_stale"] for value in component_freshness.values()),
            "components": component_freshness,
        }
    fetched_at = source.get("fetched_at")
    age_seconds: Optional[float] = None
    if fetched_at:
        try:
            fetched = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
            age_seconds = max(0.0, (observed_at - fetched).total_seconds())
        except (TypeError, ValueError):
            pass
    return {
        "fetched_at": fetched_at,
        "data_date": source.get("data_date"),
        "observed_at": _iso(observed_at),
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "cache_ttl_seconds": source.get("cache_ttl_seconds", ttl_seconds),
        "is_stale": age_seconds is None or age_seconds > ttl_seconds,
    }


def _provider_ttl(provider: str) -> int:
    return (
        PROVIDER_TTLS["sleeper_players"]
        if provider == "sleeper"
        else PROVIDER_TTLS.get(provider, SNAPSHOT_FRESH_SECONDS)
    )


def _milestone_estimates(
    player: Mapping[str, Any], history: Sequence[Mapping[str, Any]], scoring: Mapping[str, Any]
) -> tuple[dict[str, dict[int, float]], list[dict[str, Any]], list[str]]:
    estimates: dict[str, dict[int, float]] = {}
    provenance: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not any(scoring.get(field) for field in _MILESTONE_FIELDS):
        return estimates, provenance, warnings
    raw_projection = player.get("raw_projection_stats")
    raw_projection = raw_projection if isinstance(raw_projection, Mapping) else {}
    position = normalize_position(player.get("position"))
    if position not in {"QB", "RB", "WR", "TE"}:
        return estimates, provenance, warnings
    player_history = [
        row
        for row in history
        if identity_key(row.get("name"), row.get("position"), row.get("team"))
        == identity_key(player.get("name"), player.get("position"), player.get("team"))
    ]
    matching = player_history
    match_method = "unique_normalized_exact_name_position_team"
    if len(matching) < 8:
        matching = [row for row in history if normalize_position(row.get("position")) == position]
        match_method = "nflverse_position_level_fallback"
    used_position_fallback = False
    projected_games = 17.0
    for field, yard_field, raw_prefix in (
        ("rushing_yard_milestones", "rushing_yards", "_rushing"),
        ("receiving_yard_milestones", "receiving_yards", "_receiving"),
    ):
        rules = scoring.get(field)
        if not isinstance(rules, Mapping) or not rules:
            continue
        field_estimates: dict[int, float] = {}
        methods: dict[str, dict[str, Any]] = {}
        thresholds = sorted(int(threshold) for threshold in rules)

        def historical_tier(
            lower: int, upper: Optional[int], yard_stat: str = yard_field
        ) -> Optional[float]:
            if not matching:
                return None
            events = sum(
                float(row.get(yard_stat) or 0) >= lower
                and (upper is None or float(row.get(yard_stat) or 0) < upper)
                for row in matching
            )
            return events / len(matching) * projected_games

        def historical_150_share(yard_stat: str = yard_field) -> Optional[float]:
            if not matching:
                return None
            projected_bracket = [
                float(row.get(yard_stat) or 0)
                for row in matching
                if 100 <= float(row.get(yard_stat) or 0) < 200
            ]
            if not projected_bracket:
                return 0.0
            return sum(value >= 150 for value in projected_bracket) / len(projected_bracket)

        for index, threshold in enumerate(thresholds):
            next_threshold = thresholds[index + 1] if index + 1 < len(thresholds) else None
            raw_events: Optional[float] = None
            method: Optional[dict[str, Any]] = None
            raw_100_199 = _number(raw_projection.get(f"{raw_prefix}_100_199_games")) or 0.0
            raw_200_plus = _number(raw_projection.get(f"{raw_prefix}_200_plus_games")) or 0.0

            if thresholds == [100, 150, 200] and threshold in {100, 150}:
                split_share = historical_150_share()
                if split_share is not None:
                    estimated_150_199 = raw_100_199 * split_share
                    raw_events = (
                        raw_100_199 - estimated_150_199 if threshold == 100 else estimated_150_199
                    )
                    method = {
                        "method": "nflverse_historical_split_of_espn_raw_100_199",
                        "sources": [SOURCE_LABELS["espn"], SOURCE_LABELS["nflverse"]],
                        "games_sampled": len(matching),
                        "history_match_method": match_method,
                        "historical_150_199_share": round(split_share, 6),
                    }
            elif threshold == 100 and next_threshold == 200:
                raw_events = raw_100_199
            elif threshold == 200 and next_threshold is None:
                raw_events = raw_200_plus

            if raw_events is not None:
                field_estimates[threshold] = raw_events
                methods[str(threshold)] = method or {
                    "method": "espn_raw_2026_season_milestone_projection",
                    "source": SOURCE_LABELS["espn"],
                }
                used_position_fallback = used_position_fallback or (
                    method is not None and match_method.endswith("fallback")
                )
                continue

            estimated_events = historical_tier(threshold, next_threshold)
            if estimated_events is None:
                warnings.append(
                    f"{field} tier {threshold} unsupported: nflverse history unavailable"
                )
                continue
            field_estimates[threshold] = estimated_events
            methods[str(threshold)] = {
                "method": match_method,
                "source": SOURCE_LABELS["nflverse"],
                "tier": {
                    "minimum_yards": threshold,
                    "maximum_yards_exclusive": next_threshold,
                },
                "games_sampled": len(matching),
                "projected_games": projected_games,
            }
            used_position_fallback = used_position_fallback or match_method.endswith("fallback")
        if not field_estimates:
            continue
        estimates[field] = field_estimates
        provenance.append(
            {
                "field": field,
                "threshold_methods": methods,
                "estimated_events": {
                    str(key): round(value, 4) for key, value in field_estimates.items()
                },
            }
        )
    if used_position_fallback:
        warnings.append(
            "Milestone rates used nflverse position-level fallback due to insufficient player history"
        )
    return estimates, provenance, warnings


def _availability(
    row: Optional[Mapping[str, Any]],
) -> Optional[tuple[float, dict[str, Any]]]:
    if row is None:
        return None
    status = str(row.get("status") or "").strip().upper()
    injury = str(row.get("injury_status") or "").strip().upper()
    active = row.get("active")
    if active is None and not status and not injury and row.get("depth_chart_order") is None:
        return None
    score = 100.0
    if (
        active is False
        or status in {"INACTIVE", "OUT", "IR", "PUP", "SUSPENDED"}
        or injury in {"OUT", "IR", "PUP", "SUS", "SUSPENDED"}
    ):
        score = 0.0
    elif injury in {"DOUBTFUL", "D"}:
        score = 25.0
    elif injury in {"QUESTIONABLE", "Q"}:
        score = 65.0
    depth = _number(row.get("depth_chart_order"))
    if depth is not None and depth > 1:
        score -= min(20.0, (depth - 1) * 5.0)
    adds = _number(row.get("trending_adds"))
    drops = _number(row.get("trending_drops"))
    if adds is not None and (drops is None or adds > drops):
        score += 3.0
    elif drops is not None and (adds is None or drops > adds):
        score -= 3.0
    context = {
        key: row.get(key)
        for key in (
            "provider_id",
            "active",
            "status",
            "injury_status",
            "depth_chart_position",
            "depth_chart_order",
            "trending_adds",
            "trending_drops",
        )
    }
    return max(0.0, min(100.0, score)), context


class ManualDraftService:
    """Fetch, join, score, rank, and persist a no-Yahoo manual draft board."""

    def __init__(
        self,
        *,
        snapshot_dir: Optional[Path] = None,
        session_factory: Callable[..., Any] = aiohttp.ClientSession,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.snapshot_dir = snapshot_dir or project_root / ".cache" / "manual_draft"
        self._session_factory = session_factory
        self._monotonic = monotonic
        self._now = now
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._cache_lock = asyncio.Lock()

    async def _request(
        self, url: str, cap: int, headers: Optional[dict[str, str]] = None
    ) -> tuple[bytes, dict[str, Any]]:
        allowed_urls = {
            ESPN_URL,
            ECR_URL,
            FFC_URL,
            SLEEPER_PLAYERS_URL,
            SLEEPER_TRENDING_ADD_URL,
            SLEEPER_TRENDING_DROP_URL,
            *(NFLVERSE_URL_TEMPLATE.format(season=season) for season in NFLVERSE_SEASONS),
        }
        if url not in allowed_urls:
            raise ProviderError("request URL is not on the fixed provider allowlist")
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ProviderError("unsafe provider URL")
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)

        async def read_response(
            response: Any, *, trusted_redirect: bool = False
        ) -> tuple[bytes, dict[str, Any]]:
            status = int(response.status)
            if status < 200 or status >= 300:
                raise ProviderError(f"provider returned HTTP {status}")
            if response.content_length is not None and response.content_length > cap:
                raise ProviderError(f"provider response exceeded {cap} bytes")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > cap:
                    raise ProviderError(f"provider response exceeded {cap} bytes")
                chunks.append(chunk)
            payload = b"".join(chunks)
            metadata = {
                "url": url,
                "fetched_at": _iso(self._now()),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            if trusted_redirect:
                metadata["trusted_redirect_host"] = "release-assets.githubusercontent.com"
            return payload, metadata

        try:
            async with self._session_factory(timeout=timeout, headers=headers or {}) as session:
                async with session.get(url, allow_redirects=False) as response:
                    status = int(response.status)
                    if 300 <= status < 400:
                        location = response.headers.get("Location")
                        redirect = urlparse(str(location or ""))
                        is_nflverse = url.startswith(
                            "https://github.com/nflverse/nflverse-data/releases/download/"
                        )
                        trusted_asset = (
                            redirect.scheme == "https"
                            and redirect.hostname == "release-assets.githubusercontent.com"
                            and not redirect.username
                            and not redirect.password
                            and redirect.port in (None, 443)
                            and redirect.path.startswith("/github-production-release-asset/")
                        )
                        if not is_nflverse or not trusted_asset:
                            raise ProviderError("provider redirect target is not trusted")
                        async with session.get(str(location), allow_redirects=False) as asset:
                            if 300 <= int(asset.status) < 400:
                                raise ProviderError("provider returned more than one redirect")
                            return await read_response(asset, trusted_redirect=True)
                    return await read_response(response)
        except ProviderError:
            raise
        except asyncio.TimeoutError as exc:
            raise ProviderError("provider request timed out") from exc
        except aiohttp.ClientError as exc:
            raise ProviderError("provider request failed") from exc

    async def _cached(
        self, key: str, ttl: int, loader: Callable[[], Awaitable[dict[str, Any]]], force: bool
    ) -> dict[str, Any]:
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry and not force and self._monotonic() - entry.stored_at < entry.ttl_seconds:
                output = cast(dict[str, Any], json.loads(json.dumps(entry.value)))
                output["source"]["served_from_cache"] = True
                output["source"]["cache_age_seconds"] = round(
                    self._monotonic() - entry.stored_at, 3
                )
                return output
        value = await loader()
        value["source"]["served_from_cache"] = False
        value["source"]["cache_ttl_seconds"] = ttl
        async with self._cache_lock:
            self._cache[key] = _CacheEntry(json.loads(json.dumps(value)), self._monotonic(), ttl)
            while len(self._cache) > 16:
                self._cache.popitem(last=False)
        return value

    async def _espn(
        self, force: bool, allowed_positions: set[str], roster_slot_ids: list[int]
    ) -> _ProviderResult:
        async def loader() -> dict[str, Any]:
            fantasy_filter = json.dumps(
                {
                    "players": {
                        "filterActive": {"value": True},
                        "filterStatus": {"value": ["FREEAGENT", "WAIVERS", "ONTEAM"]},
                        "filterSlotIds": {"value": roster_slot_ids},
                        "filterStatsForSourceIds": {"value": [1]},
                        "filterStatsForSplitTypeIds": {"value": [0]},
                        "filterStatsForTopScoringPeriodIds": {
                            "value": 2,
                            "additionalValue": [f"10{BOARD_SEASON}"],
                        },
                        "limit": MAX_PLAYERS,
                        "offset": 0,
                        "sortAppliedStatTotal": {
                            "sortPriority": 1,
                            "sortAsc": False,
                            "value": f"10{BOARD_SEASON}",
                        },
                    }
                },
                separators=(",", ":"),
            )
            payload, source = await self._request(
                ESPN_URL,
                PROVIDER_CAPS["espn"],
                headers={"X-Fantasy-Filter": fantasy_filter, "Accept": "application/json"},
            )
            source["selection"] = {
                "season": BOARD_SEASON,
                "statSourceId": 1,
                "statSplitTypeId": 0,
                "max_players": MAX_PLAYERS,
                "draft_pool_coverage_target": 168,
                "requested_player_margin": MAX_PLAYERS - 168,
                "active_statuses": ["FREEAGENT", "WAIVERS", "ONTEAM"],
                "allowed_positions": sorted(allowed_positions),
                "roster_slot_ids": roster_slot_ids,
                "sort": "sortAppliedStatTotal",
                "applied_total_usage": "server_side_acquisition_order_only",
                "uses_applied_fantasy_total_for_scoring": False,
            }
            rows = parse_espn_projection_rows(payload, allowed_positions)
            source["selection"]["raw_stat_player_coverage"] = {
                field: sum(field in row["raw_projection_stats"] for row in rows)
                for field in sorted(_ESPN_STAT_IDS)
            }
            return {
                "rows": rows,
                "source": source,
                "warnings": [],
            }

        cache_key = "espn:{}:{}".format(
            ",".join(sorted(allowed_positions)), ",".join(str(value) for value in roster_slot_ids)
        )
        value = await self._cached(cache_key, PROVIDER_TTLS["espn"], loader, force)
        value["source"].update({"provider": "espn", "attribution": SOURCE_LABELS["espn"]})
        return _ProviderResult("espn", value["rows"], value["source"], value["warnings"])

    async def _ecr(self, force: bool) -> _ProviderResult:
        async def loader() -> dict[str, Any]:
            payload, source = await self._request(ECR_URL, PROVIDER_CAPS["ecr"])
            rows = parse_ecr_rows(payload)
            source["data_date"] = max(str(row.get("source_date") or "") for row in rows) or None
            source["selection"] = {"page_type": "redraft-overall", "ecr_type": "ro"}
            return {"rows": rows, "source": source, "warnings": []}

        value = await self._cached("ecr", PROVIDER_TTLS["ecr"], loader, force)
        value["source"].update({"provider": "ecr", "attribution": SOURCE_LABELS["ecr"]})
        return _ProviderResult("ecr", value["rows"], value["source"], value["warnings"])

    async def _ffc(self, force: bool) -> _ProviderResult:
        async def loader() -> dict[str, Any]:
            payload, source = await self._request(FFC_URL, PROVIDER_CAPS["ffc"])
            source["selection"] = {
                "scoring": "half-ppr",
                "team_count": 12,
                "season": BOARD_SEASON,
                "usage": "market_timing_not_primary_ranking",
            }
            return {"rows": parse_ffc_rows(payload), "source": source, "warnings": []}

        value = await self._cached("ffc", PROVIDER_TTLS["ffc"], loader, force)
        value["source"].update({"provider": "ffc", "attribution": SOURCE_LABELS["ffc"]})
        return _ProviderResult("ffc", value["rows"], value["source"], value["warnings"])

    async def _sleeper(self, force: bool) -> _ProviderResult:
        async def fetch_component(key: str, url: str, ttl: int, cap: int) -> dict[str, Any]:
            async def loader() -> dict[str, Any]:
                payload, source = await self._request(url, cap)
                return {"rows": [], "payload_hex": payload.hex(), "source": source, "warnings": []}

            return await self._cached(key, ttl, loader, force)

        components = list(
            await asyncio.gather(
                fetch_component(
                    "sleeper_players",
                    SLEEPER_PLAYERS_URL,
                    PROVIDER_TTLS["sleeper_players"],
                    PROVIDER_CAPS["sleeper_players"],
                ),
                fetch_component(
                    "sleeper_adds",
                    SLEEPER_TRENDING_ADD_URL,
                    PROVIDER_TTLS["sleeper_trending"],
                    PROVIDER_CAPS["sleeper_trending"],
                ),
                fetch_component(
                    "sleeper_drops",
                    SLEEPER_TRENDING_DROP_URL,
                    PROVIDER_TTLS["sleeper_trending"],
                    PROVIDER_CAPS["sleeper_trending"],
                ),
                return_exceptions=True,
            )
        )
        players, adds, drops = components
        if isinstance(players, BaseException):
            raise players
        warnings: list[str] = []
        adds_payload = None
        drops_payload = None
        if isinstance(adds, BaseException):
            warnings.append(f"Sleeper trending adds unavailable: {adds}")
        else:
            adds_payload = bytes.fromhex(adds["payload_hex"])
        if isinstance(drops, BaseException):
            warnings.append(f"Sleeper trending drops unavailable: {drops}")
        else:
            drops_payload = bytes.fromhex(drops["payload_hex"])
        rows = parse_sleeper_rows(
            bytes.fromhex(players["payload_hex"]), adds_payload, drops_payload
        )
        component_sources: dict[str, dict[str, Any]] = {
            "players": {
                **dict(players["source"]),
                "cache_ttl_seconds": PROVIDER_TTLS["sleeper_players"],
            }
        }
        if not isinstance(adds, BaseException):
            component_sources["trending_adds"] = {
                **dict(adds["source"]),
                "cache_ttl_seconds": PROVIDER_TTLS["sleeper_trending"],
            }
        if not isinstance(drops, BaseException):
            component_sources["trending_drops"] = {
                **dict(drops["source"]),
                "cache_ttl_seconds": PROVIDER_TTLS["sleeper_trending"],
            }
        fetched_values = [
            str(value["fetched_at"])
            for value in component_sources.values()
            if value.get("fetched_at")
        ]
        source = {
            "provider": "sleeper",
            "attribution": SOURCE_LABELS["sleeper"],
            "url": SLEEPER_PLAYERS_URL,
            "fetched_at": max(fetched_values) if fetched_values else None,
            "bytes": sum(int(value.get("bytes") or 0) for value in component_sources.values()),
            "sha256": _checksum(
                {name: value.get("sha256") for name, value in sorted(component_sources.items())}
            ),
            "cache_ttl_seconds": min(
                int(value["cache_ttl_seconds"]) for value in component_sources.values()
            ),
            "components": component_sources,
        }
        return _ProviderResult("sleeper", rows, source, warnings)

    async def _nflverse(self, force: bool) -> _ProviderResult:
        async def loader() -> dict[str, Any]:
            results = await asyncio.gather(
                *(
                    self._request(
                        NFLVERSE_URL_TEMPLATE.format(season=season), PROVIDER_CAPS["nflverse"]
                    )
                    for season in NFLVERSE_SEASONS
                ),
                return_exceptions=True,
            )
            payloads: list[tuple[int, bytes]] = []
            sources: list[dict[str, Any]] = []
            warnings: list[str] = []
            for season, result in zip(NFLVERSE_SEASONS, results):
                if isinstance(result, BaseException):
                    warnings.append(f"nflverse {season} unavailable: {result}")
                else:
                    payload, source = result
                    payloads.append((season, payload))
                    sources.append(source)
            if not payloads:
                raise ProviderError("all nflverse milestone-history downloads failed")
            rows = parse_nflverse_rows(payloads)
            aggregate = {
                "urls": [source["url"] for source in sources],
                "fetched_at": max(source["fetched_at"] for source in sources),
                "sha256": _checksum([source["sha256"] for source in sources]),
                "bytes": sum(source["bytes"] for source in sources),
            }
            return {"rows": rows, "source": aggregate, "warnings": warnings}

        value = await self._cached("nflverse", PROVIDER_TTLS["nflverse"], loader, force)
        value["source"].update({"provider": "nflverse", "attribution": SOURCE_LABELS["nflverse"]})
        return _ProviderResult("nflverse", value["rows"], value["source"], value["warnings"])

    def _snapshot_path(self, profile_id: str) -> Path:
        return self.snapshot_dir / (profile_id + ".json")

    def _load_snapshot(self, profile: Mapping[str, Any]) -> Optional[dict[str, Any]]:
        path = self._snapshot_path(str(profile["profile_id"]))
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            return None
        expected = value.get("snapshot_checksum")
        body = {key: item for key, item in value.items() if key != "snapshot_checksum"}
        if (
            expected != _checksum(body)
            or value.get("profile_checksum") != profile["profile_checksum"]
        ):
            return None
        return value

    def _save_snapshot(self, value: dict[str, Any]) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self._snapshot_path(str(value["profile_id"]))
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self.snapshot_dir),
            prefix=".manual-draft-",
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600)
            with handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary), str(path))
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def _snapshot_response(
        self,
        snapshot: Mapping[str, Any],
        preview_limit: int,
        warning: Optional[str] = None,
    ) -> dict[str, Any]:
        warnings = list(snapshot.get("warnings") or [])
        if warning:
            warnings.append(warning)
        observed_at = self._now()
        sources: dict[str, dict[str, Any]] = {}
        for name, value in cast(Mapping[str, Any], snapshot.get("sources") or {}).items():
            source = dict(cast(Mapping[str, Any], value))
            source["freshness"] = _source_freshness(source, _provider_ttl(name), observed_at)
            if source["freshness"]["is_stale"]:
                stale_components = [
                    component
                    for component, freshness in source["freshness"].get("components", {}).items()
                    if freshness["is_stale"]
                ]
                detail = f" ({', '.join(stale_components)})" if stale_components else ""
                warnings.append(f"{name} source evidence is stale{detail}")
            sources[name] = source
        return {
            "status": "success",
            "readiness": "ready_with_warnings" if warnings else "ready",
            "profile_id": snapshot["profile_id"],
            "profile_checksum": snapshot["profile_checksum"],
            "schema_version": snapshot["schema_version"],
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_checksum": snapshot["snapshot_checksum"],
            "prepared_at": snapshot["prepared_at"],
            "snapshot_reused": True,
            "source_coverage": snapshot["source_coverage"],
            "sources": sources,
            "unsupported_scoring_fields": snapshot["unsupported_scoring_fields"],
            "unsupported_scoring_inputs": snapshot["unsupported_scoring_inputs"],
            "estimated_scoring_fields": snapshot["estimated_scoring_fields"],
            "quarantined_identities": snapshot["quarantined_identities"],
            "board_count": len(snapshot["board"]),
            "board_preview": list(snapshot["board"][:preview_limit]),
            "warnings": warnings,
        }

    async def prepare(
        self, profile: Mapping[str, Any], preview_limit: int = 25, force_refresh: bool = False
    ) -> dict[str, Any]:
        """Prepare and persist a credential-free value board for a reusable profile."""

        canonical = validate_profile(profile)
        eligible_positions = _roster_eligible_positions(canonical["roster_slots"])
        roster_slot_ids = _espn_position_slot_ids(eligible_positions)
        if (
            isinstance(preview_limit, bool)
            or not isinstance(preview_limit, int)
            or not 1 <= preview_limit <= 100
        ):
            raise ManualDraftError("preview_limit must be an integer between 1 and 100")
        if not isinstance(force_refresh, bool):
            raise ManualDraftError("force_refresh must be a boolean")
        previous = self._load_snapshot(canonical)
        if previous is not None and not force_refresh:
            try:
                age = (
                    self._now()
                    - datetime.fromisoformat(str(previous["prepared_at"]).replace("Z", "+00:00"))
                ).total_seconds()
            except (KeyError, TypeError, ValueError):
                age = SNAPSHOT_FRESH_SECONDS + 1
            if age < SNAPSHOT_FRESH_SECONDS:
                return self._snapshot_response(previous, preview_limit)

        outcomes: list[Any]
        try:
            outcomes = list(
                await asyncio.wait_for(
                    asyncio.gather(
                        self._espn(force_refresh, eligible_positions, roster_slot_ids),
                        self._ecr(force_refresh),
                        self._ffc(force_refresh),
                        self._sleeper(force_refresh),
                        self._nflverse(force_refresh),
                        return_exceptions=True,
                    ),
                    timeout=OVERALL_TIMEOUT_SECONDS,
                )
            )
        except asyncio.TimeoutError:
            outcomes = [ProviderError("overall provider deadline exceeded") for _ in range(5)]

        providers: dict[str, _ProviderResult] = {}
        warnings: list[str] = []
        expected_names = ("espn", "ecr", "ffc", "sleeper", "nflverse")
        for index, outcome in enumerate(outcomes):
            name = expected_names[index] if index < len(expected_names) else "provider"
            if isinstance(outcome, BaseException):
                warnings.append(f"{name} unavailable: {outcome}")
            else:
                providers[outcome.name] = outcome
                warnings.extend(outcome.warnings)
        if "espn" not in providers:
            if previous is not None:
                return self._snapshot_response(
                    previous,
                    preview_limit,
                    warning="Fresh ESPN projections unavailable; using last-known-good prepared snapshot",
                )
            observed_at = self._now()
            available_sources: dict[str, dict[str, Any]] = {}
            for name, result in providers.items():
                source = dict(result.source)
                source["freshness"] = _source_freshness(source, _provider_ttl(name), observed_at)
                available_sources[name] = source
            return {
                "status": "error",
                "readiness": "not_ready",
                "profile_id": canonical["profile_id"],
                "profile_checksum": canonical["profile_checksum"],
                "schema_version": SCHEMA_VERSION,
                "source_coverage": {name: name in providers for name in expected_names},
                "sources": available_sources,
                "unsupported_scoring_fields": canonical["unsupported_scoring_fields"],
                "unsupported_scoring_inputs": canonical["unsupported_scoring_inputs"],
                "estimated_scoring_fields": [],
                "quarantined_identities": [],
                "board_count": 0,
                "board_preview": [],
                "warnings": warnings,
            }

        ecr_rows = providers["ecr"].rows if "ecr" in providers else []
        adp_rows = providers["ffc"].rows if "ffc" in providers else []
        sleeper_rows = providers["sleeper"].rows if "sleeper" in providers else []
        history = providers["nflverse"].rows if "nflverse" in providers else []
        board: list[dict[str, Any]] = []
        quarantined: list[dict[str, Any]] = []
        estimated_fields: set[str] = set()
        for projection in providers["espn"].rows:
            if projection["position"] not in eligible_positions:
                continue
            ecr, ecr_quarantine = exact_match(projection, "ecr", ecr_rows)
            adp, adp_quarantine = exact_match(projection, "ffc", adp_rows)
            sleeper, sleeper_quarantine = exact_match(projection, "sleeper", sleeper_rows)
            for item in (ecr_quarantine, adp_quarantine, sleeper_quarantine):
                if item is not None:
                    quarantined.append(item)
            estimates, estimate_provenance, player_warnings = _milestone_estimates(
                projection, history, canonical["scoring"]
            )
            for item in estimate_provenance:
                for threshold, method in item["threshold_methods"].items():
                    if not str(method.get("method") or "").startswith("espn_raw"):
                        estimated_fields.add(f"{item['field']}.{threshold}")
            points, breakdown = calculate_projected_points(
                projection["raw_projection_stats"], canonical["scoring"], estimates
            )
            projected_points: Optional[float] = points if breakdown else None
            availability = _availability(sleeper)
            board.append(
                {
                    "player_id": "espn:{}".format(projection.get("provider_id")),
                    "name": projection["name"],
                    "position": projection["position"],
                    "team": projection.get("team") or None,
                    "projected_points": projected_points,
                    "projection_source": (
                        "espn_raw_2026_season_stats" if projected_points is not None else None
                    ),
                    "raw_projection_stats": projection["raw_projection_stats"],
                    "score_breakdown": breakdown,
                    "milestone_estimates": estimate_provenance,
                    "ecr": ecr.get("ecr") if ecr else None,
                    "ecr_sd": ecr.get("ecr_sd") if ecr else None,
                    "ecr_source": _match_provenance(projection, "ecr", ecr),
                    "adp": adp.get("adp") if adp else None,
                    "adp_sd": adp.get("adp_sd") if adp else None,
                    "adp_source": _match_provenance(projection, "ffc", adp),
                    "availability_confidence": availability[0] if availability else None,
                    "sleeper_context": availability[1] if availability else None,
                    "warnings": player_warnings,
                }
            )

        replacements = calculate_replacement_values(
            board, canonical["team_count"], canonical["roster_slots"]
        )
        for player in board:
            replacement = replacements.get(player["position"])
            player["replacement_level"] = round(replacement, 4) if replacement is not None else None
            player["vorp"] = (
                round(float(player["projected_points"]) - replacement, 4)
                if replacement is not None
                else None
            )
        projection_components = _percentile_scores([player.get("vorp") for player in board])
        ecr_components = _percentile_scores([_number(player.get("ecr")) for player in board], True)
        adp_components = _percentile_scores([_number(player.get("adp")) for player in board], True)
        missing_component_warnings: set = set()
        for player, projection_score, ecr_score, adp_score in zip(
            board, projection_components, ecr_components, adp_components
        ):
            blended = weighted_board_score(
                {
                    "projection_value": projection_score,
                    "ecr": ecr_score,
                    "adp": adp_score,
                    "availability": _number(player.get("availability_confidence")),
                }
            )
            player["base_board_score"] = blended["score"]
            player["board_score"] = blended
            if blended["missing"]:
                player["warnings"].append(
                    "Missing evidence was omitted and available component weights were renormalized: {}".format(
                        ", ".join(blended["missing"])
                    )
                )
                missing_component_warnings.update(blended["missing"])
        if missing_component_warnings:
            warnings.append(
                "Missing evidence was never scored as zero; weights were renormalized per player for: {}".format(
                    ", ".join(sorted(missing_component_warnings))
                )
            )

        def board_sort_key(player: Mapping[str, Any]) -> tuple[float, float, str]:
            score = _number(player.get("base_board_score"))
            vorp = _number(player.get("vorp"))
            return (
                -(score if score is not None else -1.0),
                -(vorp if vorp is not None else -999999.0),
                str(player["name"]),
            )

        board.sort(key=board_sort_key)
        for rank, player in enumerate(board, 1):
            player["rank"] = rank

        freshness_observed_at = self._now()
        sources: dict[str, dict[str, Any]] = {}
        for name, result in providers.items():
            source = dict(result.source)
            ttl = _provider_ttl(name)
            source["freshness"] = _source_freshness(source, ttl, freshness_observed_at)
            sources[name] = source
        source_coverage = {
            name: {
                "available": name in providers,
                "matched_players": sum(
                    1
                    for player in board
                    if (
                        (name == "espn")
                        or (name == "ecr" and player.get("ecr") is not None)
                        or (name == "ffc" and player.get("adp") is not None)
                        or (name == "sleeper" and player.get("sleeper_context") is not None)
                        or (name == "nflverse" and player.get("milestone_estimates"))
                    )
                ),
                "board_players": len(board),
            }
            for name in expected_names
        }
        unsupported = list(canonical["unsupported_scoring_fields"])
        for field in sorted(_DIRECT_SCORING_FIELDS & canonical["scoring"].keys()):
            applicable = [
                row
                for row in providers["espn"].rows
                if row["position"] in _SCORING_POSITION_SCOPE[field]
            ]
            if applicable and not any(field in row["raw_projection_stats"] for row in applicable):
                unsupported.append(field)
                warnings.append(f"ESPN raw projections did not supply scoring field {field}")
        if "DEF" in canonical["roster_slots"]:
            unsupported.append(
                "defense_scoring_not_supplied_or_not_supported_by_offensive_projection_parser"
            )
        if not history:
            for field in _MILESTONE_FIELDS:
                rules = canonical["scoring"].get(field)
                if isinstance(rules, Mapping):
                    thresholds = sorted(int(threshold) for threshold in rules)
                    unsupported.extend(
                        f"{field}.{threshold}"
                        for threshold in thresholds
                        if threshold != 200 and not (threshold == 100 and thresholds == [100, 200])
                    )
        unsupported = sorted(set(unsupported))
        prepared_at = _iso(self._now())
        body: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "profile_id": canonical["profile_id"],
            "profile_checksum": canonical["profile_checksum"],
            "profile": canonical,
            "prepared_at": prepared_at,
            "sources": sources,
            "source_coverage": source_coverage,
            "unsupported_scoring_fields": unsupported,
            "unsupported_scoring_inputs": canonical["unsupported_scoring_inputs"],
            "estimated_scoring_fields": sorted(estimated_fields),
            "quarantined_identities": quarantined,
            "replacement_levels": replacements,
            "weights": dict(_COMPONENT_WEIGHTS),
            "board": board,
            "warnings": warnings,
        }
        body["snapshot_id"] = f"manual-draft-{_checksum(body)[:16]}"
        body["snapshot_checksum"] = _checksum(body)
        self._save_snapshot(body)
        response = self._snapshot_response(body, preview_limit)
        response["snapshot_reused"] = False
        return response


manual_draft_service = ManualDraftService()


__all__ = [
    "MANUAL_DRAFT_INPUT_SCHEMA",
    "ManualDraftError",
    "ManualDraftService",
    "calculate_projected_points",
    "calculate_replacement_values",
    "exact_match",
    "identity_key",
    "manual_draft_service",
    "normalize_name",
    "parse_ecr_rows",
    "parse_espn_projection_rows",
    "parse_ffc_rows",
    "parse_nflverse_rows",
    "parse_sleeper_rows",
    "validate_profile",
    "weighted_board_score",
]
