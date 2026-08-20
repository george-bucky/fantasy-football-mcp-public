"""Reviewed rookie-year fantasy outlook for opt-in decision support."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from jsonschema import Draft202012Validator, FormatChecker

CURRENT_DRAFT_CLASS = 2026
SCHEMA_VERSION = "1.0.0"
ARTIFACT_FILENAME = "rookie-board-2026.json"
MANIFEST_FILENAME = "rookie-board-2026.manifest.json"
SCHEMA_FILENAME = "rookie-board.schema.json"

# Filled with the final reviewed RR-05 digest when the artifact is vendored.
REVIEWED_ARTIFACT_SHA256 = "1c6f24fe081a45f322a6bc4d5e9a11a8d7005c922b2c85298d11c3538b440b14"
REVIEWED_MANIFEST_SHA256 = "b049b3142b6f9f0d61e5b8d4d27529d0e0bfdafda3aed3a13f96ddc155e1230a"
REVIEWED_SCHEMA_SHA256 = "d51a8f4e267aaff7fb7d11f1cd555e882c6d1813db2f89fde55ffe0255022641"

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_REQUIRED_PLAYER_FIELDS = {
    "canonical_id",
    "source_ids",
    "name",
    "position",
    "nfl_team",
    "overall_pick",
    "base_rank",
    "position_rank",
    "tier",
    "rookie_year_ppr",
    "confidence",
    "data_quality_warnings",
}


class RookieBoardError(ValueError):
    """The vendored rookie board failed a fail-closed contract check."""


def _normalized_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = text.encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split())


def _normalized_position(value: Any) -> str:
    return str(value or "").strip().upper()


def rookie_identity_key(name: Any, position: Any) -> tuple[str, str]:
    """Return the exact normalized identity used by the reviewed board."""

    return (_normalized_name(name), _normalized_position(position))


def rookie_identity_token(name: Any, position: Any) -> str:
    """Return a JSON-safe token for a normalized name-and-position identity."""

    normalized_name, normalized_position = rookie_identity_key(name, position)
    return f"{normalized_name}|{normalized_position}"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RookieBoardError(f"Duplicate JSON object key is not allowed: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise RookieBoardError(f"Could not read reviewed rookie data: {exc}") from exc
    if not isinstance(payload, dict):
        raise RookieBoardError(f"{path.name} must contain a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
    except OSError as exc:
        raise RookieBoardError(f"Could not hash reviewed rookie data: {exc}") from exc
    return digest.hexdigest()


def _rookie_p50(player: Mapping[str, Any]) -> float:
    quantiles = player.get("rookie_year_ppr")
    if not isinstance(quantiles, dict) or {"p10", "p50", "p90"} - set(quantiles):
        raise RookieBoardError("Every rookie must include rookie_year_ppr p10/p50/p90")
    try:
        p10, p50, p90 = (float(quantiles[key]) for key in ("p10", "p50", "p90"))
    except (TypeError, ValueError) as exc:
        raise RookieBoardError("Rookie-year PPR quantiles must be numeric") from exc
    if not p10 <= p50 <= p90:
        raise RookieBoardError("Rookie-year PPR quantiles must satisfy p10 <= p50 <= p90")
    return p50


def _public_record(player: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "matched",
        "match_method": "unique_normalized_exact_name_position",
        "warnings": list(player.get("data_quality_warnings") or []),
        "canonical_id": player["canonical_id"],
        "draft_class": CURRENT_DRAFT_CLASS,
        "name": player["name"],
        "position": player["position"],
        "nfl_team": player["nfl_team"],
        "overall_pick": player["overall_pick"],
        "base_rank": player["base_rank"],
        "position_rank": player["position_rank"],
        "tier": player["tier"],
        "confidence": player["confidence"],
        "rookie_year_ppr": dict(player["rookie_year_ppr"]),
        "outlook_scope": "season-long first NFL regular season PPR; not a weekly projection",
    }


@dataclass(frozen=True)
class RookieBoard:
    """Validated rookie board and its conservative exact-match index."""

    metadata: dict[str, Any]
    players: tuple[dict[str, Any], ...]
    artifact_sha256: str
    manifest_sha256: str
    schema_sha256: str
    artifact_filename: str
    manifest: dict[str, Any]
    _index: dict[tuple[str, str], tuple[dict[str, Any], ...]]

    def match(self, name: Any, position: Any) -> dict[str, Any]:
        normalized_name = _normalized_name(name)
        normalized_position = _normalized_position(position)
        candidates = self._index.get((normalized_name, normalized_position), ())
        if not normalized_name or not normalized_position:
            reason = "missing_name_or_position"
        elif not candidates:
            reason = "no_unique_normalized_exact_name_position_match"
        elif len(candidates) > 1:
            reason = "ambiguous_normalized_exact_name_position_match"
        else:
            return _public_record(candidates[0])
        return {
            "status": "quarantined",
            "match_method": "none",
            "warnings": [f"Rookie identity quarantined: {reason}"],
            "outlook_scope": "season-long first NFL regular season PPR; not a weekly projection",
        }

    def provenance(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact_filename,
            "artifact_sha256": self.artifact_sha256,
            "manifest_sha256": self.manifest_sha256,
            "schema_sha256": self.schema_sha256,
            "artifact_version": self.metadata["artifact_version"],
            "schema_version": self.metadata["schema_version"],
            "producer_commit": self.metadata["producer_commit"],
            "generated_at": self.metadata["generated_at"],
            "data_cutoff": self.metadata["data_cutoff"],
            "draft_class": self.metadata["draft_class"],
            "scoring_basis": self.metadata["scoring_basis"],
            "target": "rookie_year_ppr_points",
        }


def load_rookie_board(
    artifact_path: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    schema_path: Optional[Path] = None,
    *,
    expected_sha256: Optional[str] = None,
    expected_manifest_sha256: Optional[str] = None,
    expected_schema_sha256: Optional[str] = None,
    expected_draft_class: int = CURRENT_DRAFT_CLASS,
) -> RookieBoard:
    """Load and validate the reviewed artifact, manifest, rank, and target contract."""

    artifact_path = artifact_path or (_DATA_DIR / ARTIFACT_FILENAME)
    manifest_path = manifest_path or (_DATA_DIR / MANIFEST_FILENAME)
    schema_path = schema_path or (_DATA_DIR / SCHEMA_FILENAME)
    reviewed_sha = expected_sha256 if expected_sha256 is not None else REVIEWED_ARTIFACT_SHA256
    reviewed_manifest_sha = (
        expected_manifest_sha256
        if expected_manifest_sha256 is not None
        else REVIEWED_MANIFEST_SHA256
    )
    reviewed_schema_sha = (
        expected_schema_sha256 if expected_schema_sha256 is not None else REVIEWED_SCHEMA_SHA256
    )
    if not reviewed_sha:
        raise RookieBoardError("No reviewed rookie artifact SHA is configured")
    if not reviewed_manifest_sha:
        raise RookieBoardError("No reviewed rookie manifest SHA is configured")
    if not reviewed_schema_sha:
        raise RookieBoardError("No reviewed rookie schema SHA is configured")

    actual_schema_sha = _sha256(schema_path)
    if actual_schema_sha != reviewed_schema_sha:
        raise RookieBoardError("Rookie board schema SHA does not match the reviewed schema")
    schema = _read_json(schema_path)
    player_required = set(schema.get("$defs", {}).get("rookiePlayer", {}).get("required", []))
    metadata_required = set(schema.get("$defs", {}).get("artifactMetadata", {}).get("required", []))
    if (
        schema.get("x-schema-version") != SCHEMA_VERSION
        or set(schema.get("required", [])) != {"metadata", "players"}
        or not _REQUIRED_PLAYER_FIELDS <= player_required
        or not {
            "schema_version",
            "artifact_version",
            "producer_commit",
            "draft_class",
            "scoring_basis",
            "target_definitions",
            "capabilities",
        }
        <= metadata_required
    ):
        raise RookieBoardError("Reviewed rookie schema does not contain the required contract")

    actual_manifest_sha = _sha256(manifest_path)
    if actual_manifest_sha != reviewed_manifest_sha:
        raise RookieBoardError("Rookie board manifest SHA does not match the reviewed manifest")
    manifest = _read_json(manifest_path)
    actual_sha = _sha256(artifact_path)
    if manifest.get("artifact_filename") != artifact_path.name:
        raise RookieBoardError("Manifest artifact filename does not match the rookie board")
    if manifest.get("artifact_sha256") != actual_sha or actual_sha != reviewed_sha:
        raise RookieBoardError("Rookie board SHA does not match its reviewed manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RookieBoardError("Unsupported rookie board manifest schema version")
    if manifest.get("draft_class") != expected_draft_class:
        raise RookieBoardError("Rookie board manifest is not for the current draft class")

    artifact = _read_json(artifact_path)
    schema_errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(artifact),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if schema_errors:
        first_error = schema_errors[0]
        location = ".".join(str(part) for part in first_error.absolute_path) or "root"
        raise RookieBoardError(
            f"Rookie board failed reviewed schema validation at {location}: "
            f"{first_error.message}"
        )
    metadata = artifact.get("metadata")
    raw_players = artifact.get("players")
    if not isinstance(metadata, dict) or not isinstance(raw_players, list) or not raw_players:
        raise RookieBoardError("Rookie board must contain metadata and at least one player")
    if metadata.get("schema_version") != SCHEMA_VERSION:
        raise RookieBoardError("Unsupported rookie board schema version")
    if metadata.get("draft_class") != expected_draft_class:
        raise RookieBoardError("Rookie board is not for the current draft class")
    if metadata.get("scoring_basis") != "ppr":
        raise RookieBoardError("Rookie board scoring basis must be PPR")
    if metadata.get("capabilities", {}).get("rookie_year_predictions") is not True:
        raise RookieBoardError("Rookie board does not declare rookie-year predictions")
    if not metadata.get("target_definitions", {}).get("rookie_year_ppr_points"):
        raise RookieBoardError("Rookie-year target definition is missing")
    for key in ("artifact_version", "producer_commit", "generated_at", "data_cutoff"):
        if not metadata.get(key):
            raise RookieBoardError(f"Rookie board metadata is missing {key}")
    for key in ("artifact_version", "producer_commit", "generated_at"):
        if manifest.get(key) != metadata.get(key):
            raise RookieBoardError(f"Manifest {key} does not match rookie board metadata")

    players: list[dict[str, Any]] = []
    p50_values: list[float] = []
    ranks: list[int] = []
    canonical_ids: set[str] = set()
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw_player in raw_players:
        if not isinstance(raw_player, dict) or _REQUIRED_PLAYER_FIELDS - set(raw_player):
            raise RookieBoardError("A rookie player record is missing required schema fields")
        if raw_player["position"] not in {"QB", "RB", "WR", "TE"}:
            raise RookieBoardError("Rookie board contains an unsupported fantasy position")
        try:
            rank = int(raw_player["base_rank"])
        except (TypeError, ValueError) as exc:
            raise RookieBoardError("Rookie base ranks must be integers") from exc
        canonical_id = str(raw_player["canonical_id"])
        if canonical_id in canonical_ids:
            raise RookieBoardError("Rookie canonical IDs must be unique")
        canonical_ids.add(canonical_id)
        ranks.append(rank)
        p50_values.append(_rookie_p50(raw_player))
        player = dict(raw_player)
        players.append(player)
        identity_key = rookie_identity_key(player["name"], player["position"])
        index.setdefault(identity_key, []).append(player)

    if ranks != list(range(1, len(players) + 1)):
        raise RookieBoardError("Rookie base ranks must be unique, ordered, and contiguous")
    if any(left < right for left, right in zip(p50_values, p50_values[1:])):
        raise RookieBoardError("Rookie base_rank must correspond to descending rookie_year_ppr p50")
    for left, right, left_player, right_player in zip(
        p50_values,
        p50_values[1:],
        players,
        players[1:],
    ):
        if left == right and left_player["canonical_id"] > right_player["canonical_id"]:
            raise RookieBoardError(
                "Equal rookie_year_ppr p50 values must use canonical_id ascending"
            )

    return RookieBoard(
        metadata=dict(metadata),
        players=tuple(players),
        artifact_sha256=actual_sha,
        manifest_sha256=actual_manifest_sha,
        schema_sha256=actual_schema_sha,
        artifact_filename=artifact_path.name,
        manifest=dict(manifest),
        _index={key: tuple(value) for key, value in index.items()},
    )


def apply_rookie_intelligence(
    players: Sequence[Mapping[str, Any]],
    *,
    context: str,
    rookie_only: bool = False,
    board: Optional[RookieBoard] = None,
) -> dict[str, Any]:
    """Attach exact-match season outlook and conservatively order matched rookies."""

    board = board or load_rookie_board()
    enriched: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    matched_indices: list[int] = []
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for player in players:
        row = dict(player)
        intelligence = board.match(row.get("name"), row.get("position"))
        row["rookie_intelligence"] = intelligence
        by_identity[rookie_identity_key(row.get("name"), row.get("position"))] = intelligence
        enriched.append(row)
        if intelligence["status"] == "matched":
            matched.append(row)
            matched_indices.append(len(enriched) - 1)

    matched.sort(key=lambda row: row["rookie_intelligence"]["base_rank"])
    if rookie_only:
        output_players = matched
    else:
        output_players = enriched
        for index, rookie in zip(matched_indices, matched):
            output_players[index] = rookie

    unmatched_count = len(enriched) - len(matched)
    warnings: list[str] = []
    if unmatched_count:
        warnings.append(
            f"{unmatched_count} player(s) were quarantined from rookie matching; "
            "only unique normalized exact name+position matches were accepted"
        )
    if rookie_only and not matched:
        warnings.append("No exact current-class rookie matches; no veterans were returned")

    influence = {
        "draft": (
            "Exact-matched rookies use the reviewed rookie-year PPR rank as their base rank; "
            "roster, scoring, and draft-timing evidence remains visible."
        ),
        "waiver": (
            "Exact-matched rookies are ordered against other matched rookies by reviewed "
            "rookie-year PPR rank; weekly, injury, news, and availability evidence is preserved."
        ),
        "lineup": (
            "Rookie-year PPR is season-long context only and may break an otherwise near tie; "
            "it is not a weekly projection and is not opponent-aware."
        ),
    }.get(context, "Rookie-year PPR is season-long context only.")
    return {
        "players": output_players,
        "by_identity": by_identity,
        "evidence": {
            "enabled": True,
            "context": context,
            "rookie_only": rookie_only,
            "matched_players": len(matched),
            "quarantined_players": unmatched_count,
            "match_method": "unique_normalized_exact_name_position",
            "influence": influence,
            "opponent_aware": False,
            "warnings": warnings,
            "provenance": board.provenance(),
        },
    }


__all__ = [
    "RookieBoard",
    "RookieBoardError",
    "apply_rookie_intelligence",
    "load_rookie_board",
    "rookie_identity_key",
    "rookie_identity_token",
]
