"""Pure bridge for caller-observed Yahoo UI point forecasts, never a refetch.

No cookies, credentials, browser storage, network or disk access. The caller must
observe the actual Proj Pts column for the verified league/week/scoring settings;
this module checks scope, identity, shape and observation age, not the truth of a
browser observation. Yahoo actual player_points are not projected points.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

SOURCE_KIND = "yahoo_visible_projection_snapshot"
MAX_AGE_SECONDS = 900
LEAGUE_KEY = re.compile(r"([0-9]+|nfl)\.l\.([0-9]+)\Z")
PLAYER_KEY = re.compile(r"([0-9]+|nfl)\.p\.([0-9]+)\Z")


def _time(value: Any) -> datetime | None:
    try:
        result = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
        if result.tzinfo is None or result.utcoffset() is None:
            return None
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def apply_yahoo_projection_snapshot(
    players: Sequence[Any],
    snapshot: Any,
    *,
    league_key: str,
    team_key: str,
    season: int,
    week: int,
    scoring_basis: str,
    as_of: datetime | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Return copied players and safe audit; invalid snapshots leave values intact.

    Rows are ``{player_id: digits, projection: number}`` or
    ``{player_key: exact_game.p.id, projection: number}``. If both identifiers are
    present they must agree. No matching by name, position or NFL team occurs.
    A fresh explicit zero/negative is marked present for downstream consumers.
    """
    copies = copy.deepcopy(list(players))
    audit: dict[str, Any] = {
        "source_kind": SOURCE_KIND,
        "caller_provided": True,
        "server_refetched": False,
        "available": False,
        "applied_count": 0,
        "unmatched_count": 0,
        "reason": None,
        "applied_values": [],
    }

    def reject(reason: str) -> tuple[list[Any], dict[str, Any]]:
        audit["reason"] = reason
        return copies, audit

    scope = LEAGUE_KEY.fullmatch(league_key) if isinstance(league_key, str) else None
    if (
        scope is None
        or not isinstance(team_key, str)
        or re.fullmatch(re.escape(league_key) + r"\.t\.([0-9]+)", team_key) is None
        or type(season) is not int
        or not 2000 <= season <= 2100
        or type(week) is not int
        or not 1 <= week <= 18
        or not isinstance(scoring_basis, str)
        or scoring_basis not in {"ppr", "half_ppr", "standard", "custom"}
    ):
        return reject("verified_request_scope_invalid")
    clock = datetime.now(timezone.utc) if as_of is None else _time(as_of)
    if snapshot is None:
        return reject("yahoo_forecast_not_provided_by_api_or_snapshot")
    if clock is None or not isinstance(snapshot, Mapping):
        return reject("snapshot_or_clock_invalid")
    if snapshot.get("source_kind") != SOURCE_KIND:
        return reject("snapshot_source_kind_invalid")
    if any(
        snapshot.get(key, expected) != expected
        for key, expected in (("league_key", league_key), ("team_key", team_key))
    ):
        return reject("snapshot_league_or_team_mismatch")
    if (
        type(snapshot.get("season")) is not int
        or type(snapshot.get("week")) is not int
        or snapshot.get("season") != season
        or snapshot.get("week") != week
        or snapshot.get("scoring_basis") != scoring_basis
    ):
        return reject("snapshot_period_or_scoring_mismatch")
    url = snapshot.get("source_url")
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        expected_path = f"/f1/{scope.group(2)}/{team_key.rsplit('.',1)[1]}"
        if (
            parsed is None
            or parsed.scheme != "https"
            or parsed.netloc != "football.fantasysports.yahoo.com"
            or parsed.path.rstrip("/") != expected_path
            or parsed.query
            or parsed.fragment
        ):
            return reject("snapshot_source_url_invalid")
    except ValueError:
        return reject("snapshot_source_url_invalid")
    observed = _time(snapshot.get("observed_at"))
    if observed is None or not 0 <= (clock - observed).total_seconds() <= MAX_AGE_SECONDS:
        return reject("snapshot_stale_future_or_unaware")
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or len(rows) > 100:
        return reject("snapshot_rows_invalid")
    roster: dict[str, Any] = {}
    for player in copies:
        key = getattr(player, "player_key", None)
        match = PLAYER_KEY.fullmatch(key) if isinstance(key, str) else None
        if match is None or match.group(1) != scope.group(1):
            return reject("roster_identity_invalid")
        if key in roster:
            return reject("roster_identity_ambiguous")
        roster[key] = player
    staged, seen = [], set()
    for row in rows:
        if not isinstance(row, Mapping):
            return reject("snapshot_row_invalid")
        key, public_id = row.get("player_key"), row.get("player_id")
        if key is not None:
            match = PLAYER_KEY.fullmatch(key) if isinstance(key, str) else None
            if match is None or match.group(1) != scope.group(1):
                return reject("snapshot_player_scope_invalid")
            if public_id is not None and (
                not isinstance(public_id, str) or public_id != match.group(2)
            ):
                return reject("snapshot_player_identifiers_conflict")
        elif isinstance(public_id, str) and re.fullmatch(r"[0-9]+", public_id):
            key = f"{scope.group(1)}.p.{public_id}"
        else:
            return reject("snapshot_player_identity_invalid")
        if key in seen:
            return reject("snapshot_duplicate_player")
        seen.add(key)
        value = _number(row.get("projection"))
        if value is None:
            return reject("snapshot_projection_invalid")
        staged.append((key, value))
    for key, value in staged:
        player = roster.get(key)
        if player is None:
            audit["unmatched_count"] += 1
            continue
        context = (
            player.projection_context
            if isinstance(getattr(player, "projection_context", None), dict)
            else {}
        )
        context = copy.deepcopy(context)
        prior = context.get("yahoo_projection_snapshot")
        original = (
            _number(prior.get("original_yahoo_projection"))
            if isinstance(prior, Mapping)
            else _number(getattr(player, "yahoo_projection", None))
        )
        context["yahoo_projection_snapshot"] = {
            "original_yahoo_projection": original,
            "raw_snapshot_value": value,
            "observed_at": observed.isoformat(),
            "caller_provided": True,
            "server_refetched": False,
        }
        context.update(
            yahoo_projection_present=True,
            season=season,
            week=week,
            as_of=clock.isoformat(),
            live_context_collected=True,
        )
        provenance = context.get("source_provenance")
        provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
        provenance["yahoo"] = {
            "kind": "provider_forecast",
            "source_kind": SOURCE_KIND,
            "source_url": url,
            "observed_at": observed.isoformat(),
            "as_of": observed.isoformat(),
            "max_age_seconds": MAX_AGE_SECONDS,
            "season": season,
            "week": week,
            "scoring_basis": scoring_basis,
            "player_id": key,
            "caller_provided": True,
            "server_refetched": False,
        }
        context["source_provenance"] = provenance
        player.projection_context = context
        player.yahoo_projection = value
        audit["applied_values"].append({"player_key": key, "raw_snapshot_value": value})
        audit["applied_count"] += 1
    audit.update(
        available=True,
        observed_at=observed.isoformat(),
        reason="applied_with_unmatched_rows" if audit["unmatched_count"] else "snapshot_applied",
    )
    return copies, audit
