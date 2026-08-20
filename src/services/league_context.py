"""Private Yahoo adapter and deterministic league-context calculations."""

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, cast

from src.api.yahoo_client import yahoo_api_call
from src.models.league_context import (
    AvailabilityContext,
    AvailablePlayerIdentity,
    EvidenceMetadata,
    LeagueContext,
    LeagueSettings,
    ReplacementDemand,
    RosterPlayerIdentity,
    RosterSlot,
    ScoringSetting,
    TeamIdentity,
    TeamRoster,
    UserIdentity,
)

YahooCall = Callable[[str], Awaitable[dict[str, Any]]]

_ELIGIBLE_POSITIONS: Mapping[str, tuple[str, ...]] = {
    "QB": ("QB",),
    "RB": ("RB",),
    "WR": ("WR",),
    "TE": ("TE",),
    "K": ("K",),
    "DEF": ("DEF",),
    "D/ST": ("DEF",),
    "W/T": ("WR", "TE"),
    "W/R": ("WR", "RB"),
    "W/R/T": ("WR", "RB", "TE"),
    "Q/W/R/T": ("QB", "WR", "RB", "TE"),
    "OP": ("QB", "WR", "RB", "TE"),
}
_NON_STARTING_POSITIONS = {"BN", "IR", "IR+", "NA"}


class LeagueContextError(RuntimeError):
    """A visible league-context fetch or contract failure."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _first_value(value: Any, key: str) -> Any:
    for node in _walk(value):
        if isinstance(node, dict) and key in node:
            return node[key]
    return None


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> Optional[int]:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _league_key_parts(league_key: str) -> Optional[tuple[str, str]]:
    parts = league_key.split(".")
    if len(parts) != 3 or not parts[0] or parts[1] != "l" or not parts[2]:
        return None
    return parts[0], parts[2]


def _team_key_parts(team_key: str) -> Optional[tuple[str, str]]:
    parts = team_key.split(".")
    if (
        len(parts) != 5
        or not parts[0]
        or parts[1] != "l"
        or not parts[2]
        or parts[3] != "t"
        or not parts[4]
    ):
        return None
    return ".".join(parts[:3]), parts[4]


def _player_key_parts(player_key: str) -> Optional[tuple[str, str]]:
    parts = player_key.split(".")
    if len(parts) != 3 or not parts[0] or parts[1] != "p" or not parts[2]:
        return None
    return parts[0], parts[2]


def _player_identity_warning(
    player_key: str,
    player_id: str,
    label: str,
    expected_game_key: Optional[str] = None,
) -> Optional[str]:
    parts = _player_key_parts(player_key)
    if parts is None:
        return f"{label} player_key {player_key!r} has malformed Yahoo key shape"
    game_key, encoded_id = parts
    if expected_game_key is not None and game_key != expected_game_key:
        return (
            f"{label} player_key {player_key!r} belongs to Yahoo game {game_key!r} "
            f"but requested league belongs to game {expected_game_key!r}"
        )
    if encoded_id != player_id:
        return (
            f"{label} player_key {player_key!r} encodes player_id {encoded_id!r} "
            f"but supplied player_id is {player_id!r}"
        )
    return None


@dataclass(frozen=True)
class _NumberedEnvelope:
    entries: tuple[Any, ...]
    declared_count: Optional[int]
    present: bool
    complete: bool
    warnings: tuple[str, ...]


def _numbered_envelope(
    container: Any, label: str, *, require_count: bool = False
) -> _NumberedEnvelope:
    """Separate Yahoo numbered entries from envelope metadata."""
    warnings: list[str] = []
    if container is None:
        return _NumberedEnvelope((), None, False, False, (f"{label} container is missing",))
    if isinstance(container, list):
        if require_count:
            warnings.append(f"{label} omitted declared count")
        return _NumberedEnvelope(tuple(container), None, True, not warnings, tuple(warnings))
    if not isinstance(container, dict):
        return _NumberedEnvelope(
            (),
            None,
            True,
            False,
            (f"{label} container must be an object or list",),
        )
    numeric_keys = sorted(
        (key for key in container if str(key).isdigit()), key=lambda key: int(key)
    )
    is_envelope = bool(numeric_keys) or "count" in container
    if not is_envelope:
        if require_count:
            warnings.append(f"{label} omitted declared count")
        return _NumberedEnvelope((container,), None, True, not warnings, tuple(warnings))

    unexpected = [key for key in container if key != "count" and key not in numeric_keys]
    if unexpected:
        warnings.append(f"{label} contained unexpected metadata keys {unexpected!r}")

    declared_count: Optional[int] = None
    if "count" not in container:
        if require_count:
            warnings.append(f"{label} omitted declared count")
    else:
        try:
            declared_count = int(container["count"])
        except (TypeError, ValueError):
            warnings.append(f"{label} declared count is not an integer")
        else:
            if declared_count < 0:
                warnings.append(f"{label} declared count cannot be negative")
                declared_count = None

    indices = [int(key) for key in numeric_keys]
    if indices != list(range(len(indices))):
        warnings.append(f"{label} numeric entry keys are not contiguous from zero")
    if declared_count is not None and declared_count != len(numeric_keys):
        warnings.append(
            f"{label} declared {declared_count} entries but contained {len(numeric_keys)}"
        )
    return _NumberedEnvelope(
        tuple(container[key] for key in numeric_keys),
        declared_count,
        True,
        not warnings,
        tuple(warnings),
    )


def _require_matching_league_key(
    payload: dict[str, Any], expected_league_key: str, label: str
) -> tuple[str, ...]:
    league = _first_value(payload.get("fantasy_content", {}), "league")
    metadata = _metadata_dict(league)
    returned_key = _as_text(metadata.get("league_key"))
    if returned_key is None:
        return (f"{label} omitted league_key",)
    if returned_key != expected_league_key:
        raise LeagueContextError(
            f"{label} league_key mismatch: requested {expected_league_key!r}, received {returned_key!r}"
        )
    parts = _league_key_parts(returned_key)
    if parts is None:
        return (f"{label} league_key {returned_key!r} has malformed Yahoo key shape",)
    league_id = _as_text(metadata.get("league_id"))
    if league_id is not None and parts[1] != league_id:
        return (
            f"{label} league_key {returned_key!r} encodes league_id {parts[1]!r} "
            f"but supplied league_id is {league_id!r}",
        )
    return ()


def _metadata_dict(value: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for node in _walk(value):
        if isinstance(node, dict):
            for key, item in node.items():
                if key not in {"settings", "teams", "players", "roster", "managers"}:
                    metadata.setdefault(key, item)
    return metadata


def _eligible(position: str) -> tuple[str, ...]:
    return _ELIGIBLE_POSITIONS.get(position.upper(), ())


def parse_yahoo_settings(
    payload: dict[str, Any], league_key: str, fetched_at: datetime
) -> LeagueSettings:
    league = _first_value(payload.get("fantasy_content", {}), "league")
    metadata = _metadata_dict(league)
    returned_key = _as_text(metadata.get("league_key"))
    if returned_key != league_key:
        raise LeagueContextError(
            f"Yahoo settings league_key mismatch: requested {league_key!r}, received {returned_key!r}"
        )

    warnings: list[str] = []
    league_id = _as_text(metadata.get("league_id"))
    league_parts = _league_key_parts(returned_key)
    if league_parts is None:
        warnings.append(f"Yahoo league_key {returned_key!r} has malformed Yahoo key shape")
    if league_id is None:
        warnings.append("Yahoo response omitted league_id")
    elif league_parts is not None and league_parts[1] != league_id:
        warnings.append(
            f"Yahoo league_key {returned_key!r} encodes league_id {league_parts[1]!r} "
            f"but supplied league_id is {league_id!r}"
        )
    settings = _first_value(league, "settings")
    if settings is None:
        warnings.append("Yahoo response omitted league settings")

    slots: list[RosterSlot] = []
    roster_positions = _first_value(settings, "roster_positions")
    slot_envelope = _numbered_envelope(roster_positions, "Yahoo roster_positions")
    warnings.extend(slot_envelope.warnings)
    rejected_slots = 0
    for index, candidate in enumerate(slot_envelope.entries):
        position_data = candidate.get("roster_position") if isinstance(candidate, dict) else None
        if position_data is None and isinstance(candidate, dict):
            position_data = candidate
        if not isinstance(position_data, dict):
            rejected_slots += 1
            warnings.append(f"Yahoo roster_positions entry {index} is malformed")
            continue
        position = _as_text(position_data.get("position"))
        count = _as_int(position_data.get("count"))
        if position is None or count is None:
            rejected_slots += 1
            warnings.append(
                f"Yahoo roster_positions entry {index} omitted position or positive count"
            )
            continue
        explicit_starting = position_data.get("is_starting_position")
        if explicit_starting is None:
            if position.upper() in _NON_STARTING_POSITIONS:
                is_starting: Optional[bool] = False
            else:
                is_starting = True if _eligible(position) else None
        else:
            starting_value = str(explicit_starting).lower()
            if starting_value in {"1", "true", "yes"}:
                is_starting = True
            elif starting_value in {"0", "false", "no"}:
                is_starting = False
            else:
                is_starting = None
                warnings.append(
                    f"Roster slot {position!r} has unresolved is_starting_position "
                    f"{explicit_starting!r}"
                )
        eligible = _eligible(position)
        if not eligible and position.upper() not in _NON_STARTING_POSITIONS:
            warnings.append(f"Unknown eligibility for roster slot {position!r}")
        slots.append(RosterSlot(position, count, eligible, is_starting))
    if slot_envelope.declared_count is not None and slot_envelope.declared_count != (
        len(slots) + rejected_slots
    ):
        warnings.append(
            f"Yahoo roster_positions declared {slot_envelope.declared_count} entries but parsed "
            f"{len(slots)} and rejected {rejected_slots}"
        )

    scoring: list[ScoringSetting] = []
    scoring_ids = set()
    stats = _first_value(_first_value(settings, "stat_modifiers"), "stats")
    stat_envelope = _numbered_envelope(stats, "Yahoo stat_modifiers stats")
    warnings.extend(stat_envelope.warnings)
    rejected_stats = 0
    for index, candidate in enumerate(stat_envelope.entries):
        stat = candidate.get("stat") if isinstance(candidate, dict) else None
        if stat is None and isinstance(candidate, dict):
            stat = candidate
        if not isinstance(stat, dict):
            rejected_stats += 1
            warnings.append(f"Yahoo stat_modifiers entry {index} is malformed")
            continue
        stat_id = _as_text(stat.get("stat_id"))
        value = _as_text(stat.get("value"))
        if stat_id is None or value is None:
            rejected_stats += 1
            warnings.append(f"Yahoo stat_modifiers entry {index} omitted stat_id or modifier value")
            continue
        if stat_id in scoring_ids:
            rejected_stats += 1
            warnings.append(f"Duplicate scoring stat_id {stat_id!r}; kept first occurrence")
            continue
        scoring_ids.add(stat_id)
        scoring.append(ScoringSetting(stat_id, value))
    if stat_envelope.declared_count is not None and stat_envelope.declared_count != (
        len(scoring) + rejected_stats
    ):
        warnings.append(
            f"Yahoo stat_modifiers declared {stat_envelope.declared_count} entries but parsed "
            f"{len(scoring)} and rejected {rejected_stats}"
        )

    team_count = _as_int(metadata.get("num_teams"))
    if team_count is None:
        warnings.append("Yahoo response omitted team count")
    if not slots:
        warnings.append("Yahoo response supplied no usable roster slots")
    scoring_type = _as_text(_first_value(settings, "scoring_type"))
    if scoring_type is None:
        warnings.append("Yahoo response omitted scoring type")
    if not scoring:
        warnings.append("Yahoo response supplied no scoring modifiers")

    evidence = EvidenceMetadata(
        fetched_at=fetched_at,
        stale_after_seconds=3600,
        complete=(
            settings is not None
            and team_count is not None
            and bool(slots)
            and scoring_type is not None
            and bool(scoring)
            and slot_envelope.complete
            and stat_envelope.complete
            and not warnings
        ),
        item_count=len(slots),
        warnings=tuple(warnings),
    )
    return LeagueSettings(
        provider="yahoo",
        league_key=league_key,
        league_id=league_id,
        name=_as_text(metadata.get("name")),
        team_count=team_count,
        scoring_type=scoring_type,
        roster_slots=tuple(slots),
        scoring_settings=tuple(scoring),
        evidence=evidence,
    )


def _parse_yahoo_teams(
    payload: dict[str, Any], expected_league_key: Optional[str]
) -> tuple[tuple[TeamIdentity, ...], tuple[str, ...], bool]:
    warnings: list[str] = []
    if expected_league_key is not None:
        warnings.extend(
            _require_matching_league_key(payload, expected_league_key, "Yahoo teams response")
        )

    league = _first_value(payload.get("fantasy_content", {}), "league")
    envelope = _numbered_envelope(_first_value(league, "teams"), "Yahoo teams")
    warnings.extend(envelope.warnings)
    teams: list[TeamIdentity] = []
    seen = set()
    for index, candidate in enumerate(envelope.entries):
        if not isinstance(candidate, dict) or "team" not in candidate:
            warnings.append(f"Yahoo teams entry {index} omitted team object")
            continue
        raw_team = candidate["team"]
        metadata = _metadata_dict(raw_team)
        team_key = _as_text(metadata.get("team_key"))
        if team_key is None:
            warnings.append(f"Yahoo teams entry {index} omitted team_key")
            continue
        team_parts = _team_key_parts(team_key)
        if team_parts is None:
            warnings.append(f"Yahoo team_key {team_key!r} has malformed Yahoo key shape")
            continue
        if expected_league_key is not None and team_parts[0] != expected_league_key:
            raise LeagueContextError(
                "Yahoo team object does not belong to requested league: "
                f"requested {expected_league_key!r}, received team_key {team_key!r}"
            )
        team_id = _as_text(metadata.get("team_id"))
        if team_id is None:
            warnings.append(f"Yahoo team {team_key!r} omitted team_id")
        elif team_parts[1] != team_id:
            warnings.append(
                f"Yahoo team_key {team_key!r} encodes team_id {team_parts[1]!r} "
                f"but supplied team_id is {team_id!r}"
            )
            continue
        if team_key in seen:
            warnings.append(f"Yahoo team response repeated team_key {team_key!r}")
            continue
        seen.add(team_key)
        users: list[UserIdentity] = []
        seen_manager_ids: dict[str, Optional[str]] = {}
        seen_guids: dict[str, Optional[str]] = {}
        managers = _numbered_envelope(_first_value(raw_team, "managers"), "Yahoo managers")
        warnings.extend(f"Team {team_key!r}: {warning}" for warning in managers.warnings)
        for manager_index, manager_candidate in enumerate(managers.entries):
            if not isinstance(manager_candidate, dict) or "manager" not in manager_candidate:
                warnings.append(
                    f"Team {team_key!r} manager entry {manager_index} omitted manager object"
                )
                continue
            raw_manager = manager_candidate["manager"]
            manager = _metadata_dict(raw_manager)
            manager_id = _as_text(manager.get("manager_id"))
            guid = _as_text(manager.get("guid"))
            if manager_id is None and guid is None:
                warnings.append(
                    f"Team {team_key!r} manager entry {manager_index} contained data but "
                    "omitted manager_id and guid"
                )
                continue
            if manager_id is not None and manager_id in seen_manager_ids:
                prior_guid = seen_manager_ids[manager_id]
                if prior_guid == guid:
                    warnings.append(
                        f"Team {team_key!r} repeated manager identity manager_id "
                        f"{manager_id!r} and guid {guid!r}"
                    )
                elif prior_guid is None or guid is None:
                    warnings.append(
                        f"Team {team_key!r} manager_id {manager_id!r} overlaps a partial "
                        "manager identity; rejected without linking identities"
                    )
                else:
                    warnings.append(
                        f"Team {team_key!r} manager_id {manager_id!r} maps to conflicting "
                        f"GUIDs {prior_guid!r} and {guid!r}"
                    )
                continue
            if guid is not None and guid in seen_guids:
                prior_manager_id = seen_guids[guid]
                if prior_manager_id == manager_id:
                    warnings.append(
                        f"Team {team_key!r} repeated manager identity manager_id "
                        f"{manager_id!r} and guid {guid!r}"
                    )
                elif prior_manager_id is None or manager_id is None:
                    warnings.append(
                        f"Team {team_key!r} guid {guid!r} overlaps a partial manager "
                        "identity; rejected without linking identities"
                    )
                else:
                    warnings.append(
                        f"Team {team_key!r} guid {guid!r} maps to conflicting manager_ids "
                        f"{prior_manager_id!r} and {manager_id!r}"
                    )
                continue
            users.append(UserIdentity(manager_id, guid, _as_text(manager.get("nickname"))))
            if manager_id is not None:
                seen_manager_ids[manager_id] = guid
            if guid is not None:
                seen_guids[guid] = manager_id
        teams.append(
            TeamIdentity(
                team_key=team_key,
                team_id=team_id,
                name=_as_text(metadata.get("name")),
                users=tuple(users),
            )
        )
    return tuple(teams), tuple(warnings), envelope.complete and not warnings


def parse_yahoo_teams(
    payload: dict[str, Any], expected_league_key: Optional[str] = None
) -> tuple[TeamIdentity, ...]:
    """Parse team identities; the service also retains private completeness evidence."""
    teams, _, _ = _parse_yahoo_teams(payload, expected_league_key)
    return teams


def _parse_player(raw_player: Any) -> dict[str, Any]:
    return _metadata_dict(raw_player)


def _player_eligible(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    value = metadata.get("eligible_positions")
    positions: list[str] = []
    for node in _walk(value):
        if isinstance(node, dict) and "position" in node:
            position = _as_text(node.get("position"))
            if position and position not in positions:
                positions.append(position)
    if not positions:
        display = _as_text(metadata.get("display_position"))
        if display:
            positions.extend(part.strip() for part in display.split(",") if part.strip())
    return tuple(positions)


def _selected_position(metadata: Mapping[str, Any]) -> Optional[str]:
    selected = metadata.get("selected_position")
    return _as_text(_first_value(selected, "position"))


def parse_yahoo_roster(
    payload: dict[str, Any],
    team: TeamIdentity,
    fetched_at: datetime,
    expected_league_key: Optional[str] = None,
) -> TeamRoster:
    raw_team = _first_value(payload.get("fantasy_content", {}), "team")
    team_metadata = _metadata_dict(raw_team)
    returned_key = _as_text(team_metadata.get("team_key"))
    if returned_key != team.team_key:
        raise LeagueContextError(
            f"Yahoo roster team_key mismatch: requested {team.team_key!r}, received {returned_key!r}"
        )
    warnings: list[str] = []
    returned_parts = _team_key_parts(returned_key)
    if returned_parts is None:
        warnings.append(f"Yahoo roster team_key {returned_key!r} has malformed Yahoo key shape")
    elif expected_league_key is not None and returned_parts[0] != expected_league_key:
        raise LeagueContextError(
            "Yahoo roster team object does not belong to requested league: "
            f"requested {expected_league_key!r}, received team_key {returned_key!r}"
        )
    returned_team_id = _as_text(team_metadata.get("team_id"))
    if returned_team_id is None:
        warnings.append(f"Yahoo roster team {returned_key!r} omitted team_id")
    elif returned_parts is not None and returned_parts[1] != returned_team_id:
        warnings.append(
            f"Yahoo roster team_key {returned_key!r} encodes team_id {returned_parts[1]!r} "
            f"but supplied team_id is {returned_team_id!r}"
        )
    if (
        team.team_id is not None
        and returned_team_id is not None
        and team.team_id != returned_team_id
    ):
        warnings.append(
            f"Yahoo roster team_id {returned_team_id!r} does not match teams response "
            f"team_id {team.team_id!r}"
        )
    expected_league_parts = (
        _league_key_parts(expected_league_key) if expected_league_key is not None else None
    )
    expected_game_key = expected_league_parts[0] if expected_league_parts is not None else None
    players: list[RosterPlayerIdentity] = []
    seen_keys: dict[str, str] = {}
    seen_ids: dict[str, str] = {}
    players_container = _first_value(raw_team, "players")
    envelope = _numbered_envelope(
        players_container, f"Yahoo roster {team.team_key!r} players", require_count=True
    )
    warnings.extend(envelope.warnings)
    rejected_entries = 0
    for index, candidate in enumerate(envelope.entries):
        if not isinstance(candidate, dict) or "player" not in candidate:
            rejected_entries += 1
            warnings.append(
                f"Yahoo roster {team.team_key!r} player entry {index} omitted player object"
            )
            continue
        raw_player = candidate["player"]
        metadata = _parse_player(raw_player)
        player_key = _as_text(metadata.get("player_key"))
        player_id = _as_text(metadata.get("player_id"))
        if player_key is None or player_id is None:
            rejected_entries += 1
            warnings.append(
                f"Yahoo roster {team.team_key!r} player entry {index} omitted player_key or player_id"
            )
            continue
        identity_warning = _player_identity_warning(
            player_key,
            player_id,
            f"Yahoo roster {team.team_key!r} entry {index}",
            expected_game_key,
        )
        if identity_warning is not None:
            rejected_entries += 1
            warnings.append(identity_warning)
            continue
        prior_id = seen_keys.get(player_key)
        prior_key = seen_ids.get(player_id)
        if prior_id is not None or prior_key is not None:
            rejected_entries += 1
            if prior_id is not None and prior_id != player_id:
                warnings.append(
                    f"Roster player_key {player_key!r} maps to conflicting player_ids "
                    f"{prior_id!r} and {player_id!r}"
                )
            elif prior_key is not None and prior_key != player_key:
                warnings.append(
                    f"Roster player_id {player_id!r} maps to conflicting player_keys "
                    f"{prior_key!r} and {player_key!r}"
                )
            else:
                warnings.append(
                    f"Duplicate roster player identity {player_key!r}/{player_id!r}; "
                    "kept first occurrence"
                )
            continue
        seen_keys[player_key] = player_id
        seen_ids[player_id] = player_key
        name = _first_value(metadata.get("name"), "full")
        players.append(
            RosterPlayerIdentity(
                player_key=player_key,
                player_id=player_id,
                name=_as_text(name),
                selected_position=_selected_position(metadata),
                eligible_positions=_player_eligible(metadata),
            )
        )
    if envelope.declared_count is not None and envelope.declared_count != (
        len(players) + rejected_entries
    ):
        warnings.append(
            f"Yahoo roster {team.team_key!r} declared {envelope.declared_count} players but "
            f"parsed {len(players)} and rejected {rejected_entries}"
        )
    evidence = EvidenceMetadata(
        fetched_at=fetched_at,
        stale_after_seconds=300,
        complete=envelope.complete and not warnings,
        item_count=len(players),
        warnings=tuple(warnings),
    )
    return TeamRoster(team=team, players=tuple(players), evidence=evidence)


@dataclass(frozen=True)
class _AvailablePage:
    players: tuple[AvailablePlayerIdentity, ...]
    candidate_count: int
    declared_count: Optional[int]
    complete: bool
    warnings: tuple[str, ...]


def _parse_yahoo_available_page(
    payload: dict[str, Any], expected_league_key: Optional[str]
) -> _AvailablePage:
    warnings: list[str] = []
    if expected_league_key is not None:
        warnings.extend(
            _require_matching_league_key(
                payload, expected_league_key, "Yahoo availability response"
            )
        )
    expected_league_parts = (
        _league_key_parts(expected_league_key) if expected_league_key is not None else None
    )
    expected_game_key = expected_league_parts[0] if expected_league_parts is not None else None
    players_container = _first_value(
        _first_value(payload.get("fantasy_content", {}), "league"), "players"
    )
    envelope = _numbered_envelope(
        players_container, "Yahoo availability players", require_count=True
    )
    warnings.extend(envelope.warnings)
    players: list[AvailablePlayerIdentity] = []
    rejected_entries = 0
    for index, candidate in enumerate(envelope.entries):
        if not isinstance(candidate, dict) or "player" not in candidate:
            rejected_entries += 1
            warnings.append(f"Yahoo availability entry {index} omitted player object")
            continue
        raw_player = candidate["player"]
        metadata = _parse_player(raw_player)
        player_key = _as_text(metadata.get("player_key"))
        player_id = _as_text(metadata.get("player_id"))
        if player_key is None or player_id is None:
            rejected_entries += 1
            warnings.append(f"Yahoo availability entry {index} omitted player_key or player_id")
            continue
        identity_warning = _player_identity_warning(
            player_key,
            player_id,
            f"Yahoo availability entry {index}",
            expected_game_key,
        )
        if identity_warning is not None:
            rejected_entries += 1
            warnings.append(identity_warning)
            continue
        players.append(
            AvailablePlayerIdentity(
                player_key=player_key,
                player_id=player_id,
                name=_as_text(_first_value(metadata.get("name"), "full")),
                display_position=_as_text(metadata.get("display_position")),
                eligible_positions=_player_eligible(metadata),
                availability_status="A",
                injury_status=_as_text(metadata.get("status")),
            )
        )
    if envelope.declared_count is not None and envelope.declared_count != (
        len(players) + rejected_entries
    ):
        warnings.append(
            f"Yahoo availability declared {envelope.declared_count} players but parsed "
            f"{len(players)} and rejected {rejected_entries}"
        )
    return _AvailablePage(
        tuple(players),
        len(envelope.entries),
        envelope.declared_count,
        envelope.complete and not warnings,
        tuple(warnings),
    )


def parse_yahoo_available_page(
    payload: dict[str, Any], expected_league_key: Optional[str] = None
) -> tuple[list[AvailablePlayerIdentity], int, Optional[int], bool]:
    """Parse one page while exposing candidate/count/completeness evidence."""
    page = _parse_yahoo_available_page(payload, expected_league_key)
    return list(page.players), page.candidate_count, page.declared_count, page.complete


def calculate_replacement_demand(
    team_count: Optional[int], roster_slots: Sequence[RosterSlot]
) -> tuple[ReplacementDemand, ...]:
    """Calculate maximum league-wide starter demand from explicit slot eligibility.

    A multi-position slot contributes once to every position it explicitly accepts.
    This is a transparent upper bound, not an inferred lineup allocation. Unknown,
    bench, and IR slots contribute nothing. Missing team count returns no demands.
    """
    if team_count is None:
        return ()
    if team_count <= 0:
        raise ValueError("team_count must be positive")
    demand: dict[str, int] = {}
    for slot in roster_slots:
        if slot.is_starting is not True:
            continue
        for position in slot.eligible_positions:
            demand[position] = demand.get(position, 0) + team_count * slot.count
    return tuple(ReplacementDemand(position, demand[position]) for position in sorted(demand))


def _identity_overlap_warnings(
    rosters: Sequence[TeamRoster], availability: AvailabilityContext
) -> tuple[tuple[str, ...], AvailabilityContext]:
    warnings: list[str] = []
    roster_keys: dict[str, tuple[str, str]] = {}
    roster_ids: dict[str, tuple[str, str]] = {}

    for roster in rosters:
        owner = roster.team.team_key
        for rostered_player in roster.players:
            roster_key_record = roster_keys.get(rostered_player.player_key)
            if roster_key_record is not None:
                prior_player_id, prior_owner = roster_key_record
                if prior_player_id == rostered_player.player_id:
                    warnings.append(
                        f"Roster player {rostered_player.player_key!r}/"
                        f"{rostered_player.player_id!r} appears on "
                        f"both {prior_owner!r} and {owner!r}"
                    )
                else:
                    warnings.append(
                        f"Roster player_key {rostered_player.player_key!r} maps to conflicting "
                        f"player_ids {prior_player_id!r} and {rostered_player.player_id!r}"
                    )
            roster_id_record = roster_ids.get(rostered_player.player_id)
            if roster_id_record is not None and roster_id_record[0] != rostered_player.player_key:
                warnings.append(
                    f"Roster player_id {rostered_player.player_id!r} maps to conflicting "
                    f"player_keys {roster_id_record[0]!r} and {rostered_player.player_key!r}"
                )
            roster_keys.setdefault(rostered_player.player_key, (rostered_player.player_id, owner))
            roster_ids.setdefault(rostered_player.player_id, (rostered_player.player_key, owner))

    availability_warnings: list[str] = []
    for available_player in availability.players:
        roster_key = roster_keys.get(available_player.player_key)
        if roster_key is not None:
            roster_id, roster_owner = roster_key
            if roster_id == available_player.player_id:
                availability_warnings.append(
                    f"Player {available_player.player_key!r}/{available_player.player_id!r} "
                    "is both rostered by "
                    f"{roster_owner!r} and listed available"
                )
            else:
                availability_warnings.append(
                    f"Available player_key {available_player.player_key!r} conflicts with roster "
                    f"player_ids {roster_id!r} and {available_player.player_id!r}"
                )
        roster_id_record = roster_ids.get(available_player.player_id)
        if roster_id_record is not None and roster_id_record[0] != available_player.player_key:
            availability_warnings.append(
                f"Available player_id {available_player.player_id!r} conflicts with roster "
                f"player_keys {roster_id_record[0]!r} and {available_player.player_key!r}"
            )

    if availability_warnings:
        evidence = EvidenceMetadata(
            fetched_at=availability.evidence.fetched_at,
            stale_after_seconds=availability.evidence.stale_after_seconds,
            complete=False,
            page_count=availability.evidence.page_count,
            item_count=availability.evidence.item_count,
            warnings=availability.evidence.warnings + tuple(availability_warnings),
        )
        availability = AvailabilityContext(availability.league_key, availability.players, evidence)
    warnings.extend(availability_warnings)
    return tuple(warnings), availability


class YahooLeagueContextService:
    """Fetch exact Yahoo context through the existing asynchronous API client."""

    def __init__(
        self,
        api_call: Optional[YahooCall] = None,
        clock: Callable[[], datetime] = _now,
        availability_page_size: int = 25,
        max_availability_pages: int = 100,
    ) -> None:
        if availability_page_size <= 0 or max_availability_pages <= 0:
            raise ValueError("pagination limits must be positive")
        self._api_call = api_call or self._uncached_api_call
        self._clock = clock
        self._page_size = availability_page_size
        self._max_pages = max_availability_pages

    @staticmethod
    async def _uncached_api_call(endpoint: str) -> dict[str, Any]:
        return cast(dict[str, Any], await yahoo_api_call(endpoint, use_cache=False))

    async def _fetch(self, endpoint: str) -> dict[str, Any]:
        try:
            payload = await self._api_call(endpoint)
        except Exception as error:
            raise LeagueContextError(f"Yahoo request failed for {endpoint!r}: {error}") from error
        if not isinstance(payload, dict):
            raise LeagueContextError(
                f"Yahoo request for {endpoint!r} returned a non-object payload"
            )
        return payload

    async def fetch(self, league_key: str) -> LeagueContext:
        if not league_key or not league_key.strip():
            raise ValueError("league_key must be non-empty")
        settings_payload = await self._fetch(f"league/{league_key}/settings")
        settings = parse_yahoo_settings(settings_payload, league_key, self._clock())

        teams_payload = await self._fetch(f"league/{league_key}/teams")
        teams, team_warnings, teams_complete = _parse_yahoo_teams(teams_payload, league_key)
        rosters: list[TeamRoster] = []
        for team in teams:
            roster_payload = await self._fetch(f"team/{team.team_key}/roster")
            rosters.append(
                parse_yahoo_roster(
                    roster_payload, team, self._clock(), expected_league_key=league_key
                )
            )

        availability = await self._fetch_availability(league_key)
        overlap_warnings, availability = _identity_overlap_warnings(rosters, availability)
        warnings: list[str] = list(settings.evidence.warnings)
        warnings.extend(team_warnings)
        warnings.extend(overlap_warnings)
        if settings.team_count is not None and len(teams) != settings.team_count:
            warnings.append(
                f"Yahoo returned {len(teams)} teams but league settings declare {settings.team_count}"
            )
        if any(not roster.evidence.complete for roster in rosters):
            warnings.append("At least one team roster is incomplete")
        evidence = EvidenceMetadata(
            fetched_at=self._clock(),
            stale_after_seconds=300,
            complete=(
                settings.evidence.complete
                and teams_complete
                and not warnings
                and availability.evidence.complete
                and bool(teams)
            ),
            item_count=len(teams),
            warnings=tuple(warnings),
        )
        return LeagueContext(
            settings=settings,
            rosters=tuple(rosters),
            availability=availability,
            evidence=evidence,
        )

    async def _fetch_availability(self, league_key: str) -> AvailabilityContext:
        players: list[AvailablePlayerIdentity] = []
        seen_keys: dict[str, str] = {}
        seen_ids: dict[str, str] = {}
        warnings: list[str] = []
        complete = False
        page_count = 0
        for page_number in range(self._max_pages):
            start = page_number * self._page_size
            endpoint = f"league/{league_key}/players;status=A;start={start};count={self._page_size}"
            payload = await self._fetch(endpoint)
            page = _parse_yahoo_available_page(payload, league_key)
            page_count += 1
            warnings.extend(f"start={start}: {warning}" for warning in page.warnings)
            for player in page.players:
                prior_id = seen_keys.get(player.player_key)
                prior_key = seen_ids.get(player.player_id)
                if prior_id is not None or prior_key is not None:
                    if prior_id is not None and prior_id != player.player_id:
                        warnings.append(
                            f"Available player_key {player.player_key!r} maps to conflicting "
                            f"player_ids {prior_id!r} and {player.player_id!r}"
                        )
                    elif prior_key is not None and prior_key != player.player_key:
                        warnings.append(
                            f"Available player_id {player.player_id!r} maps to conflicting "
                            f"player_keys {prior_key!r} and {player.player_key!r}"
                        )
                    else:
                        warnings.append(
                            "Duplicate available player identity "
                            f"{player.player_key!r}/{player.player_id!r}; kept first occurrence"
                        )
                    continue
                seen_keys[player.player_key] = player.player_id
                seen_ids[player.player_id] = player.player_key
                players.append(player)
            if page.candidate_count < self._page_size:
                complete = True
                break
        if not complete:
            warnings.append(
                f"Availability pagination stopped at {self._max_pages} pages without a short final page"
            )
        if warnings:
            complete = False
        evidence = EvidenceMetadata(
            fetched_at=self._clock(),
            stale_after_seconds=300,
            complete=complete,
            page_count=page_count,
            item_count=len(players),
            warnings=tuple(warnings),
        )
        return AvailabilityContext(league_key, tuple(players), evidence)
