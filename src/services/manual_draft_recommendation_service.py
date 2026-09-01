"""Deterministic, offline recommendations from a prepared manual-draft snapshot."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.services.manual_draft_service import (
    SCHEMA_VERSION,
    normalize_name,
    normalize_position,
    normalize_team,
    validate_profile,
)

MANUAL_DRAFT_RECOMMENDATION_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prepared_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "description": "Prepared profile_id or snapshot_id returned by ff_prepare_manual_draft.",
        },
        "current_overall_pick": {"type": "integer", "minimum": 1, "maximum": 1024},
        "drafted_players": {
            "type": "array",
            "maxItems": 1024,
            "items": {
                "oneOf": [
                    {"type": "string", "minLength": 1, "maxLength": 120},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string", "minLength": 1, "maxLength": 120},
                            "position": {"type": "string", "minLength": 1, "maxLength": 16},
                            "team": {"type": "string", "minLength": 1, "maxLength": 16},
                        },
                        "required": ["name"],
                    },
                ]
            },
        },
        "roster": {
            "type": "array",
            "maxItems": 64,
            "items": {
                "oneOf": [
                    {"type": "string", "minLength": 1, "maxLength": 120},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string", "minLength": 1, "maxLength": 120},
                            "position": {"type": "string", "minLength": 1, "maxLength": 16},
                            "team": {"type": "string", "minLength": 1, "maxLength": 16},
                        },
                        "required": ["name"],
                    },
                ]
            },
        },
        "optional_evidence": {
            "type": "array",
            "maxItems": 50,
            "default": [],
            "description": "Already-cached evidence only; this tool never refreshes providers.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "player": {"type": "string", "minLength": 1, "maxLength": 120},
                    "kind": {
                        "type": "string",
                        "enum": ["news", "season_long_odds", "headline", "next_game_prop"],
                    },
                    "source": {"type": "string", "minLength": 1, "maxLength": 80},
                    "detail": {"type": "string", "minLength": 1, "maxLength": 500},
                    "adjustment": {"type": "number", "minimum": -3, "maximum": 3},
                    "age_seconds": {"type": "number", "minimum": 0},
                    "stale": {"type": "boolean", "default": False},
                },
                "required": ["player", "kind", "source", "detail"],
            },
        },
        "alternative_count": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4},
    },
    "required": ["prepared_id", "current_overall_pick", "drafted_players", "roster"],
}

_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
_FLEX_POSITIONS = {"RB", "WR", "TE"}
_EVIDENCE_ADJUSTABLE = {"news", "season_long_odds"}


class ManualDraftRecommendationError(ValueError):
    """The prepared snapshot or supplied manual draft state is invalid."""


def _canonical_checksum(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _as_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _snake_pick(round_number: int, team_count: int, slot: int) -> int:
    pick_in_round = slot if round_number % 2 else team_count - slot + 1
    return (round_number - 1) * team_count + pick_in_round


def _player_input(value: Any) -> tuple[str, str, str, Any]:
    if isinstance(value, str):
        return normalize_name(value), "", "", value
    if isinstance(value, Mapping):
        return (
            normalize_name(value.get("name")),
            normalize_position(value.get("position")),
            normalize_team(value.get("team")),
            dict(value),
        )
    return "", "", "", value


def _resolve_players(
    supplied: Sequence[Any], board: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for player in board:
        by_name[normalize_name(player.get("name"))].append(player)
    resolved: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in supplied:
        name, position, team, original = _player_input(raw)
        candidates = list(by_name.get(name, ())) if name else []
        if position:
            candidates = [
                row for row in candidates if normalize_position(row.get("position")) == position
            ]
        if team:
            candidates = [row for row in candidates if normalize_team(row.get("team")) == team]
        if len(candidates) == 1:
            row = dict(candidates[0])
            player_id = str(row.get("player_id") or "")
            if player_id and player_id not in seen_ids:
                resolved.append(row)
                seen_ids.add(player_id)
            continue
        unmatched.append(
            {
                "input": original,
                "normalized_name": name,
                "status": "ambiguous" if len(candidates) > 1 else "unknown",
                "candidates": [
                    {
                        "player_id": row.get("player_id"),
                        "name": row.get("name"),
                        "position": row.get("position"),
                        "team": row.get("team"),
                    }
                    for row in candidates
                ],
            }
        )
    return resolved, unmatched


class ManualDraftRecommendationService:
    """Load a last-known-good board and rank the current manual pick offline."""

    def __init__(
        self,
        *,
        snapshot_dir: Path | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.snapshot_dir = snapshot_dir or project_root / ".cache" / "manual_draft"
        self._monotonic = monotonic
        self._now = now

    def _validated_snapshot(self, value: Any, prepared_id: str) -> dict[str, Any] | None:
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            return None
        expected = value.get("snapshot_checksum")
        body = {key: item for key, item in value.items() if key != "snapshot_checksum"}
        if expected != _canonical_checksum(body):
            return None
        if prepared_id not in {value.get("profile_id"), value.get("snapshot_id")}:
            return None
        if not isinstance(value.get("board"), list) or not isinstance(value.get("profile"), dict):
            return None
        try:
            canonical_profile = validate_profile(value["profile"])
        except ValueError:
            return None
        if value.get("profile_id") != canonical_profile["profile_id"]:
            return None
        if value.get("profile_checksum") != canonical_profile["profile_checksum"]:
            return None
        snapshot_identity = {
            key: item
            for key, item in value.items()
            if key not in {"snapshot_id", "snapshot_checksum"}
        }
        if (
            value.get("snapshot_id")
            != f"manual-draft-{_canonical_checksum(snapshot_identity)[:16]}"
        ):
            return None
        if canonical_profile["draft"]["type"] != "snake":
            return None
        for row in value["board"]:
            if not isinstance(row, Mapping):
                return None
            if not all(row.get(field) for field in ("player_id", "name", "position")):
                return None
            if _number(row.get("base_board_score")) is None or not isinstance(row.get("rank"), int):
                return None
        return value

    def load_snapshot(self, prepared_id: str) -> dict[str, Any]:
        """Reload a checksum-verified snapshot by profile or snapshot identifier."""

        if not isinstance(prepared_id, str) or _PROFILE_ID.fullmatch(prepared_id) is None:
            raise ManualDraftRecommendationError("prepared_id is invalid")
        candidates: list[Path] = []
        direct = self.snapshot_dir / f"{prepared_id}.json"
        if direct.is_file():
            candidates.append(direct)
        try:
            candidates.extend(
                path for path in sorted(self.snapshot_dir.glob("*.json")) if path != direct
            )
        except OSError:
            candidates = []
        for path in candidates:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            snapshot = self._validated_snapshot(value, prepared_id)
            if snapshot is not None:
                return snapshot
        raise ManualDraftRecommendationError(
            "No valid prepared snapshot matched prepared_id; run ff_prepare_manual_draft first"
        )

    @staticmethod
    def _starter_state(
        profile: Mapping[str, Any], roster: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        slots = dict(profile.get("roster_slots") or {})
        counts = Counter(normalize_position(player.get("position")) for player in roster)
        base_required = {
            position: int(slots.get(position, 0)) for position in ("QB", "RB", "WR", "TE", "DEF")
        }
        base_filled = {
            position: min(counts[position], required)
            for position, required in base_required.items()
        }
        flex_total = sum(
            int(slots.get(slot, 0)) for slot in ("FLEX", "W/R/T", "WR/RB/TE", "RB/WR/TE")
        )
        flex_eligible_surplus = sum(
            max(0, counts[position] - base_required[position]) for position in _FLEX_POSITIONS
        )
        flex_filled = min(flex_total, flex_eligible_surplus)
        return {
            "position_counts": dict(sorted(counts.items())),
            "base_required": base_required,
            "base_unfilled": {
                position: max(0, required - base_filled[position])
                for position, required in base_required.items()
            },
            "flex_total": flex_total,
            "flex_filled": flex_filled,
            "flex_unfilled": max(0, flex_total - flex_filled),
            "roster_size": len(roster),
            "roster_limit": sum(int(value) for value in slots.values()),
        }

    @staticmethod
    def _source_ages(
        snapshot: Mapping[str, Any], observed_at: datetime
    ) -> tuple[dict[str, Any], list[str]]:
        ages: dict[str, Any] = {}
        warnings: list[str] = []
        for name, raw in sorted(dict(snapshot.get("sources") or {}).items()):
            source = dict(raw) if isinstance(raw, Mapping) else {}
            fetched = _as_utc(source.get("fetched_at"))
            age_seconds = max(0.0, (observed_at - fetched).total_seconds()) if fetched else None
            ttl_seconds = _number(source.get("cache_ttl_seconds")) or 6 * 60 * 60
            components = source.get("components")
            component_stale = False
            if isinstance(components, Mapping):
                for component in components.values():
                    if not isinstance(component, Mapping):
                        component_stale = True
                        continue
                    component_time = _as_utc(component.get("fetched_at"))
                    component_ttl = _number(component.get("cache_ttl_seconds")) or ttl_seconds
                    component_age = (
                        max(0.0, (observed_at - component_time).total_seconds())
                        if component_time
                        else None
                    )
                    component_stale = component_stale or (
                        component_age is None or component_age > component_ttl
                    )
            is_stale = age_seconds is None or age_seconds > ttl_seconds or component_stale
            ages[name] = {
                "fetched_at": source.get("fetched_at"),
                "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
                "cache_ttl_seconds": ttl_seconds,
                "is_stale": is_stale,
            }
            if is_stale:
                warnings.append(f"{name} source evidence is stale; prepared values were used")
        return ages, warnings

    @staticmethod
    def _evidence(
        player: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]
    ) -> tuple[float, list[dict[str, Any]], list[str]]:
        matched: list[dict[str, Any]] = []
        warnings: list[str] = []
        requested = normalize_name(player.get("name"))
        total = 0.0
        for item in evidence:
            if normalize_name(item.get("player")) != requested:
                continue
            kind = str(item.get("kind") or "")
            stale = item.get("stale") is True
            raw_adjustment = _number(item.get("adjustment")) or 0.0
            applied = raw_adjustment if kind in _EVIDENCE_ADJUSTABLE and not stale else 0.0
            if kind not in _EVIDENCE_ADJUSTABLE and raw_adjustment:
                warnings.append(f"{kind} is context only and did not change the score")
            if stale and raw_adjustment:
                warnings.append(f"stale {kind} evidence did not change the score")
            matched.append({**dict(item), "applied_adjustment": round(applied, 3)})
            total += applied
        capped = max(-3.0, min(3.0, total))
        if capped != total:
            warnings.append("optional evidence adjustment was capped at 3 points in magnitude")
        return round(capped, 3), matched, warnings

    async def recommend(
        self,
        *,
        prepared_id: str,
        current_overall_pick: int,
        drafted_players: Sequence[Any],
        roster: Sequence[Any],
        optional_evidence: Sequence[Mapping[str, Any]] = (),
        alternative_count: int = 4,
    ) -> dict[str, Any]:
        started = self._monotonic()
        if isinstance(current_overall_pick, bool) or not isinstance(current_overall_pick, int):
            raise ManualDraftRecommendationError("current_overall_pick must be an integer")
        if not isinstance(drafted_players, Sequence) or isinstance(drafted_players, (str, bytes)):
            raise ManualDraftRecommendationError("drafted_players must be an array")
        if not isinstance(roster, Sequence) or isinstance(roster, (str, bytes)):
            raise ManualDraftRecommendationError("roster must be an array")
        if (
            isinstance(alternative_count, bool)
            or not isinstance(alternative_count, int)
            or not 1 <= alternative_count <= 10
        ):
            raise ManualDraftRecommendationError("alternative_count must be between 1 and 10")

        snapshot = self.load_snapshot(prepared_id)
        board = list(snapshot["board"])
        profile = dict(snapshot["profile"])
        team_count = int(profile["team_count"])
        slot = int(profile["draft"]["slot"])
        roster_limit = sum(int(value) for value in profile["roster_slots"].values())
        max_pick = team_count * roster_limit
        if not 1 <= current_overall_pick <= max_pick:
            raise ManualDraftRecommendationError(
                f"current_overall_pick must be between 1 and {max_pick}"
            )

        resolved_drafted, unmatched_drafted = _resolve_players(drafted_players, board)
        resolved_roster, unmatched_roster = _resolve_players(roster, board)
        drafted_ids = {str(player.get("player_id")) for player in resolved_drafted}
        roster_ids = {str(player.get("player_id")) for player in resolved_roster}
        warnings = list(snapshot.get("warnings") or [])
        if len(drafted_players) != current_overall_pick - 1:
            warnings.append(
                "Complete drafted_players should contain exactly one entry for every prior overall pick"
            )
        if unmatched_drafted or unmatched_roster:
            warnings.append(
                "Unknown or ambiguous supplied names were surfaced and never guessed or removed"
            )
        if not roster_ids.issubset(drafted_ids):
            warnings.append("One or more roster players were not present in drafted_players")
        if len(roster) >= roster_limit:
            raise ManualDraftRecommendationError("roster is already full for the prepared profile")

        current_round = (current_overall_pick - 1) // team_count + 1
        expected_pick = _snake_pick(current_round, team_count, slot)
        if expected_pick != current_overall_pick:
            raise ManualDraftRecommendationError(
                f"current_overall_pick is not the prepared profile's turn; expected {expected_pick}"
            )
        next_pick = (
            _snake_pick(current_round + 1, team_count, slot)
            if current_round < roster_limit
            else None
        )
        roster_state = self._starter_state(profile, resolved_roster)
        roster_identity_complete = not unmatched_roster
        roster_state["identity_complete"] = roster_identity_complete
        remaining_slots = roster_limit - len(roster)
        requires_def_now = (
            roster_identity_complete
            and roster_state["base_unfilled"]["DEF"] > 0
            and remaining_slots == 1
        )

        unavailable_ids = drafted_ids | roster_ids
        available = [
            player for player in board if str(player.get("player_id")) not in unavailable_ids
        ]
        if "K" not in profile["roster_slots"]:
            available = [
                player for player in available if normalize_position(player.get("position")) != "K"
            ]
        if requires_def_now:
            available = [
                player
                for player in available
                if normalize_position(player.get("position")) == "DEF"
            ]
        required_vacancies = sum(int(value) for value in roster_state["base_unfilled"].values())
        required_vacancies += int(roster_state["flex_unfilled"])
        if roster_identity_complete and remaining_slots <= required_vacancies:
            required_positions = {
                position
                for position, count in roster_state["base_unfilled"].items()
                if int(count) > 0
            }
            if roster_state["flex_unfilled"]:
                required_positions.update(_FLEX_POSITIONS)
            available = [
                player
                for player in available
                if normalize_position(player.get("position")) in required_positions
            ]
        if not available:
            raise ManualDraftRecommendationError("No eligible prepared players remain")

        position_rows: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for player in available:
            position_rows[normalize_position(player.get("position"))].append(player)
        scored: list[dict[str, Any]] = []
        for player in available:
            position = normalize_position(player.get("position"))
            base_score = _number(player.get("base_board_score")) or 0.0
            unfilled = (
                int(roster_state["base_unfilled"].get(position, 0))
                if roster_identity_complete
                else 0
            )
            roster_need = 8.0 if unfilled else 0.0
            if (
                roster_identity_complete
                and position in _FLEX_POSITIONS
                and roster_state["flex_unfilled"]
            ):
                roster_need += min(5.0, 2.5 * int(roster_state["flex_unfilled"]))

            same_position = position_rows[position]
            index = same_position.index(player)
            next_same = same_position[index + 1] if index + 1 < len(same_position) else None
            next_score = _number(next_same.get("base_board_score")) if next_same else None
            tier_drop = max(0.0, base_score - next_score) if next_score is not None else 0.0
            tier_adjustment = min(6.0, tier_drop * 0.35)

            adp = _number(player.get("adp"))
            adp_sd = _number(player.get("adp_sd"))
            survival: float | None = None
            snake_adjustment = 0.0
            if next_pick is not None and adp is not None:
                spread = adp_sd if adp_sd and adp_sd > 0 else max(6.0, team_count / 2)
                survival = _normal_cdf((adp - next_pick) / spread)
                snake_adjustment = (1.0 - survival) * 4.0

            construction = 0.0
            if (
                roster_identity_complete
                and position in {"RB", "WR"}
                and int(roster_state["flex_unfilled"]) > 0
            ):
                construction = 2.0
            elif (
                roster_identity_complete
                and position == "TE"
                and int(roster_state["flex_unfilled"]) > 0
                and unfilled
            ):
                construction = 1.0

            avoidance = 0.0
            position_count = int(roster_state["position_counts"].get(position, 0))
            if position == "DEF" and current_round < 12:
                avoidance = -18.0
            elif (
                roster_identity_complete
                and position in {"QB", "TE"}
                and position_count >= 1
                and not unfilled
            ):
                avoidance = -12.0

            evidence_adjustment, evidence_used, evidence_warnings = self._evidence(
                player, optional_evidence
            )
            warnings.extend(evidence_warnings)
            adjustments = {
                "roster_need": round(roster_need, 3),
                "positional_tier_drop": round(tier_adjustment, 3),
                "two_flex_construction": round(construction, 3),
                "snake_next_turn_risk": round(snake_adjustment, 3),
                "early_def_or_backup_qb_te": round(avoidance, 3),
                "optional_cached_evidence": evidence_adjustment,
            }
            ordering_score = base_score + sum(adjustments.values())
            final_score = max(0.0, min(100.0, ordering_score))
            scored.append(
                {
                    "player_id": player.get("player_id"),
                    "name": player.get("name"),
                    "position": position,
                    "team": player.get("team"),
                    "base_score": round(base_score, 3),
                    "adjustments": adjustments,
                    "recommendation_score": round(final_score, 3),
                    "ordering_score_before_cap": round(ordering_score, 3),
                    "prepared_rank": player.get("rank"),
                    "tier_drop_to_next_at_position": round(tier_drop, 3),
                    "position_urgency": "high" if tier_adjustment >= 3 or unfilled else "normal",
                    "next_turn_survival_estimate": (
                        round(survival, 4) if survival is not None else None
                    ),
                    "adp": adp,
                    "adp_sd": adp_sd,
                    "optional_evidence": evidence_used,
                }
            )

        scored.sort(
            key=lambda row: (
                -float(row["recommendation_score"]),
                -float(row["ordering_score_before_cap"]),
                int(row["prepared_rank"] or 9999),
                normalize_name(row["name"]),
            )
        )
        selected = scored[: alternative_count + 1]
        top = selected[0]
        urgent = [
            position
            for position, count in roster_state["base_unfilled"].items()
            if count and (position != "DEF" or current_round >= 12 or requires_def_now)
        ]
        if not roster_identity_complete:
            strategy = (
                "Roster identity is incomplete; use prepared value and timing only until names "
                "are corrected"
            )
        elif urgent:
            strategy = f"Fill {', '.join(urgent)} while preserving two FLEX spots for RB/WR value"
        else:
            strategy = "Take best remaining value; avoid redundant QB/TE and wait on DEF until late"
        observed_at = self._now().astimezone(timezone.utc)
        source_ages, source_warnings = self._source_ages(snapshot, observed_at)
        warnings.extend(source_warnings)
        elapsed_ms = round((self._monotonic() - started) * 1000, 3)
        warnings = list(dict.fromkeys(warnings))
        return {
            "status": "success",
            "recommendation": top,
            "alternatives": selected[1:],
            "current_strategy": strategy,
            "pick_context": {
                "current_overall_pick": current_overall_pick,
                "round": current_round,
                "draft_slot": slot,
                "next_user_pick": next_pick,
                "picks_until_next_turn": next_pick - current_overall_pick if next_pick else None,
            },
            "roster_state": roster_state,
            "snapshot": {
                "profile_id": snapshot["profile_id"],
                "profile_checksum": snapshot["profile_checksum"],
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_checksum": snapshot["snapshot_checksum"],
                "prepared_at": snapshot["prepared_at"],
            },
            "source_ages": source_ages,
            "matched_input_counts": {
                "drafted": len(resolved_drafted),
                "roster": len(resolved_roster),
            },
            "unmatched_inputs": {
                "drafted_players": unmatched_drafted,
                "roster": unmatched_roster,
            },
            "warnings": warnings,
            "timing": {"elapsed_ms": elapsed_ms, "target_ms": 3000, "hard_limit_ms": 5000},
        }


manual_draft_recommendation_service = ManualDraftRecommendationService()


__all__ = [
    "MANUAL_DRAFT_RECOMMENDATION_INPUT_SCHEMA",
    "ManualDraftRecommendationError",
    "ManualDraftRecommendationService",
    "manual_draft_recommendation_service",
]
