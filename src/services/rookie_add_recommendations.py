"""Complete, league-aware rookie-only waiver recommendations."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from src.models.league_context import LeagueContext, TeamRoster
from src.services.league_context import calculate_replacement_demand
from src.services.rookie_intelligence import RookieBoard, load_rookie_board

_SUPPORTED_POSITIONS = {"QB", "RB", "WR", "TE"}


class RookieAddContextError(ValueError):
    """The complete league context needed for rookie-only recommendations is unusable."""


def _require_fresh_complete_context(
    context: LeagueContext,
    roster: TeamRoster,
    *,
    checked_at: datetime,
) -> None:
    evidence = (
        ("league", context.evidence),
        ("settings", context.settings.evidence),
        ("availability", context.availability.evidence),
        ("user roster", roster.evidence),
    )
    failures: list[str] = []
    for label, metadata in evidence:
        if not metadata.complete:
            failures.append(f"{label} evidence is incomplete")
        if metadata.is_stale(checked_at):
            failures.append(f"{label} evidence is stale")
    if failures:
        raise RookieAddContextError("; ".join(failures))


def _resolve_roster(context: LeagueContext, team_key: str) -> TeamRoster:
    matches = [roster for roster in context.rosters if roster.team.team_key == team_key]
    if len(matches) != 1:
        raise RookieAddContextError(
            f"Expected one exact roster for team_key {team_key!r}; found {len(matches)}"
        )
    return matches[0]


def _roster_position_counts(roster: TeamRoster) -> Counter[str]:
    counts: Counter[str] = Counter()
    for player in roster.players:
        supported = {
            str(position).upper()
            for position in player.eligible_positions
            if str(position).upper() in _SUPPORTED_POSITIONS
        }
        if not supported and str(player.selected_position or "").upper() in _SUPPORTED_POSITIONS:
            supported.add(str(player.selected_position).upper())
        for position in supported:
            counts[position] += 1
    return counts


def build_rookie_add_recommendations(
    context: LeagueContext,
    team_key: str,
    *,
    position: str = "all",
    count: int = 30,
    board: Optional[RookieBoard] = None,
    checked_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build a complete rookie-only add board with conservative team-fit ordering.

    Rookie-year tier remains the primary boundary. Verified roster need and
    league-wide starter demand may reorder players only within that tier, and
    the reviewed board rank is always the final tie-breaker.
    """

    if context.availability.league_key != context.settings.league_key:
        raise RookieAddContextError("Availability and settings league keys do not match")
    if not team_key or not team_key.strip():
        raise RookieAddContextError("An exact team_key is required")
    if count < 1:
        raise RookieAddContextError("count must be positive")

    checked_at = checked_at or datetime.now(timezone.utc)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise RookieAddContextError("Freshness check time must include a timezone")

    roster = _resolve_roster(context, team_key)
    _require_fresh_complete_context(context, roster, checked_at=checked_at)

    team_count = context.settings.team_count
    if team_count is None:
        raise RookieAddContextError("Verified team count is unavailable")
    demand = {
        row.position: row.starter_demand
        for row in calculate_replacement_demand(team_count, context.settings.roster_slots)
    }
    if not demand:
        raise RookieAddContextError("Verified starting roster demand is unavailable")

    roster_counts = _roster_position_counts(roster)
    per_team_demand = {
        supported_position: starter_demand // team_count
        for supported_position, starter_demand in demand.items()
        if supported_position in _SUPPORTED_POSITIONS
    }
    roster_gaps = {
        supported_position: max(
            0,
            required - roster_counts.get(supported_position, 0),
        )
        for supported_position, required in per_team_demand.items()
    }

    requested_position = str(position or "all").upper()
    if requested_position != "ALL" and requested_position not in _SUPPORTED_POSITIONS:
        raise RookieAddContextError(f"Unsupported rookie position filter: {position!r}")

    board = board or load_rookie_board()
    recommendations: list[dict[str, Any]] = []
    not_on_board = 0
    quarantined = 0
    quarantine_warnings: list[str] = []
    for available in context.availability.players:
        available_position = str(available.display_position or "").upper()
        if requested_position != "ALL" and available_position != requested_position:
            continue
        intelligence = board.match(available.name, available_position)
        if intelligence["status"] == "not_on_current_rookie_board":
            not_on_board += 1
            continue
        if intelligence["status"] != "matched":
            quarantined += 1
            quarantine_warnings.extend(intelligence.get("warnings", []))
            continue

        player_position = intelligence["position"]
        roster_gap = roster_gaps.get(player_position, 0)
        starter_demand = demand.get(player_position, 0)
        recommendations.append(
            {
                "name": available.name,
                "position": player_position,
                "team": intelligence["nfl_team"],
                "player_key": available.player_key,
                "player_id": available.player_id,
                "status": "Available",
                "injury_status": available.injury_status,
                "rookie_intelligence": intelligence,
                "league_fit": {
                    "roster_need": roster_gap > 0,
                    "roster_gap": roster_gap,
                    "roster_eligible_players": roster_counts.get(player_position, 0),
                    "per_team_starter_demand": per_team_demand.get(player_position, 0),
                    "league_wide_starter_demand": starter_demand,
                    "ordering_role": "within rookie-year tier only",
                },
            }
        )

    recommendations.sort(
        key=lambda row: (
            row["rookie_intelligence"]["tier"],
            0 if row["league_fit"]["roster_need"] else 1,
            -row["league_fit"]["league_wide_starter_demand"],
            row["rookie_intelligence"]["base_rank"],
            row["rookie_intelligence"]["canonical_id"],
        )
    )
    discovered_match_count = len(recommendations)
    recommendations = recommendations[:count]

    warnings = list(dict.fromkeys(quarantine_warnings))
    if not recommendations:
        warnings.append(
            "No exact current-class rookie matches were available; no veterans returned"
        )

    return {
        "players": recommendations,
        "evidence": {
            "enabled": True,
            "context": "waiver",
            "rookie_only": True,
            "matched_players": discovered_match_count,
            "returned_players": len(recommendations),
            "not_on_current_rookie_board_players": not_on_board,
            "quarantined_players": quarantined,
            "match_method": "unique_normalized_exact_name_position",
            "league_context": {
                "complete": True,
                "fresh": True,
                "team_key": team_key,
                "team_count": team_count,
                "availability_pages": context.availability.evidence.page_count,
                "availability_players": context.availability.evidence.item_count,
                "roster_players": roster.evidence.item_count,
                "roster_position_counts": dict(sorted(roster_counts.items())),
                "per_team_starter_demand": dict(sorted(per_team_demand.items())),
                "league_wide_starter_demand": dict(sorted(demand.items())),
            },
            "ordering": (
                "Rookie-year tier first; exact roster need and verified starter demand only "
                "within a tier; reviewed board rank is the final tie-breaker."
            ),
            "scoring_adjustment": (
                "None. The reviewed board remains a PPR outlook; no unsupported league-scoring "
                "conversion was invented."
            ),
            "opponent_aware": False,
            "warnings": warnings,
            "provenance": board.provenance(),
        },
    }


__all__ = [
    "RookieAddContextError",
    "build_rookie_add_recommendations",
]
