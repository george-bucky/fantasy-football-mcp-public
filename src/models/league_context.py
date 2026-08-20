"""Immutable, provider-neutral contracts for exact league context."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class EvidenceMetadata:
    """Fetch, freshness, pagination, and completeness evidence."""

    fetched_at: datetime
    stale_after_seconds: int
    complete: bool
    page_count: int = 1
    item_count: int = 0
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must include a timezone")
        if self.stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        if self.page_count < 0 or self.item_count < 0:
            raise ValueError("page_count and item_count cannot be negative")

    def is_stale(self, at: Optional[datetime] = None) -> bool:
        checked_at = at or datetime.now(timezone.utc)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("staleness check time must include a timezone")
        return (checked_at - self.fetched_at).total_seconds() > self.stale_after_seconds


@dataclass(frozen=True)
class RosterSlot:
    """One Yahoo roster-position rule, with explicit eligibility."""

    position: str
    count: int
    eligible_positions: tuple[str, ...]
    is_starting: Optional[bool]

    def __post_init__(self) -> None:
        _require_text(self.position, "position")
        if self.count <= 0:
            raise ValueError("roster slot count must be positive")


@dataclass(frozen=True)
class ScoringSetting:
    """An exact Yahoo scoring modifier keyed by Yahoo stat ID."""

    stat_id: str
    value: str

    def __post_init__(self) -> None:
        _require_text(self.stat_id, "stat_id")
        _require_text(self.value, "value")


@dataclass(frozen=True)
class LeagueSettings:
    provider: str
    league_key: str
    league_id: Optional[str]
    name: Optional[str]
    team_count: Optional[int]
    scoring_type: Optional[str]
    roster_slots: tuple[RosterSlot, ...]
    scoring_settings: tuple[ScoringSetting, ...]
    evidence: EvidenceMetadata

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        _require_text(self.league_key, "league_key")
        if self.team_count is not None and self.team_count <= 0:
            raise ValueError("team_count must be positive when known")


@dataclass(frozen=True)
class UserIdentity:
    manager_id: Optional[str]
    guid: Optional[str]
    nickname: Optional[str] = None

    def __post_init__(self) -> None:
        if self.manager_id is None and self.guid is None:
            raise ValueError("a user identity requires manager_id or guid")


@dataclass(frozen=True)
class TeamIdentity:
    team_key: str
    team_id: Optional[str]
    name: Optional[str]
    users: tuple[UserIdentity, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.team_key, "team_key")


@dataclass(frozen=True)
class RosterPlayerIdentity:
    player_key: str
    player_id: str
    name: Optional[str]
    selected_position: Optional[str]
    eligible_positions: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.player_key, "player_key")
        _require_text(self.player_id, "player_id")


@dataclass(frozen=True)
class TeamRoster:
    team: TeamIdentity
    players: tuple[RosterPlayerIdentity, ...]
    evidence: EvidenceMetadata


@dataclass(frozen=True)
class AvailablePlayerIdentity:
    player_key: str
    player_id: str
    name: Optional[str]
    display_position: Optional[str]
    eligible_positions: tuple[str, ...]
    availability_status: str
    injury_status: Optional[str]

    def __post_init__(self) -> None:
        _require_text(self.player_key, "player_key")
        _require_text(self.player_id, "player_id")
        _require_text(self.availability_status, "availability_status")


@dataclass(frozen=True)
class AvailabilityContext:
    league_key: str
    players: tuple[AvailablePlayerIdentity, ...]
    evidence: EvidenceMetadata

    def __post_init__(self) -> None:
        _require_text(self.league_key, "league_key")


@dataclass(frozen=True)
class LeagueContext:
    settings: LeagueSettings
    rosters: tuple[TeamRoster, ...]
    availability: AvailabilityContext
    evidence: EvidenceMetadata


@dataclass(frozen=True)
class ReplacementDemand:
    position: str
    starter_demand: int
