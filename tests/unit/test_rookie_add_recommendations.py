"""Pure league-aware rookie add recommendation tests."""

from datetime import datetime, timedelta, timezone

import pytest

from src.models.league_context import (
    AvailabilityContext,
    AvailablePlayerIdentity,
    EvidenceMetadata,
    LeagueContext,
    LeagueSettings,
    RosterPlayerIdentity,
    RosterSlot,
    TeamIdentity,
    TeamRoster,
)
from src.services.rookie_add_recommendations import (
    RookieAddContextError,
    build_rookie_add_recommendations,
)

NOW = datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc)
LEAGUE_KEY = "461.l.61410"
TEAM_KEY = "461.l.61410.t.1"


def _evidence(*, complete=True, fetched_at=NOW, pages=1, items=0):
    return EvidenceMetadata(
        fetched_at=fetched_at,
        stale_after_seconds=300,
        complete=complete,
        page_count=pages,
        item_count=items,
    )


def _context(*, superflex=False, complete=True, fetched_at=NOW):
    slots = [
        RosterSlot("QB", 1, ("QB",), True),
        RosterSlot("RB", 2, ("RB",), True),
        RosterSlot("WR", 2, ("WR",), True),
        RosterSlot("TE", 1, ("TE",), True),
    ]
    if superflex:
        slots.append(RosterSlot("Q/W/R/T", 1, ("QB", "WR", "RB", "TE"), True))
    slots.append(RosterSlot("BN", 6, (), False))
    metadata = _evidence(complete=complete, fetched_at=fetched_at)
    settings = LeagueSettings(
        provider="yahoo",
        league_key=LEAGUE_KEY,
        league_id="61410",
        name="Test League",
        team_count=10,
        scoring_type="head",
        roster_slots=tuple(slots),
        scoring_settings=(),
        evidence=metadata,
    )
    team = TeamIdentity(TEAM_KEY, "1", "My Team")
    roster_players = (
        RosterPlayerIdentity("461.p.1", "1", "Roster QB", "QB", ("QB",)),
        RosterPlayerIdentity("461.p.2", "2", "Roster RB One", "RB", ("RB",)),
        RosterPlayerIdentity("461.p.3", "3", "Roster RB Two", "RB", ("RB",)),
        RosterPlayerIdentity("461.p.4", "4", "Roster RB Three", "BN", ("RB",)),
    )
    roster = TeamRoster(
        team,
        roster_players,
        _evidence(complete=complete, fetched_at=fetched_at, items=4),
    )
    available = (
        AvailablePlayerIdentity(
            "461.p.100",
            "100",
            "Veteran Player",
            "WR",
            ("WR",),
            "A",
            None,
        ),
        AvailablePlayerIdentity(
            "461.p.101",
            "101",
            "Jeremiyah Love",
            "RB",
            ("RB",),
            "A",
            None,
        ),
        AvailablePlayerIdentity(
            "461.p.102",
            "102",
            "Fernando Mendoza",
            "QB",
            ("QB",),
            "A",
            "Q",
        ),
    )
    availability = AvailabilityContext(
        LEAGUE_KEY,
        available,
        _evidence(complete=complete, fetched_at=fetched_at, pages=2, items=3),
    )
    return LeagueContext(settings, (roster,), availability, metadata)


def test_team_fit_reorders_only_within_tier_and_board_rank_breaks_final_tie():
    one_qb = build_rookie_add_recommendations(_context(), TEAM_KEY, checked_at=NOW)
    superflex = build_rookie_add_recommendations(
        _context(superflex=True), TEAM_KEY, checked_at=NOW
    )

    assert [player["name"] for player in one_qb["players"]] == [
        "Jeremiyah Love",
        "Fernando Mendoza",
    ]
    assert [player["name"] for player in superflex["players"]] == [
        "Fernando Mendoza",
        "Jeremiyah Love",
    ]
    assert superflex["players"][0]["league_fit"]["roster_gap"] == 1
    assert superflex["players"][0]["league_fit"]["ordering_role"] == (
        "within rookie-year tier only"
    )
    assert superflex["evidence"]["not_on_current_rookie_board_players"] == 1
    assert superflex["evidence"]["quarantined_players"] == 0
    assert superflex["evidence"]["league_context"]["availability_pages"] == 2


@pytest.mark.parametrize(
    "context,team_key,checked_at,match",
    [
        (_context(complete=False), TEAM_KEY, NOW, "incomplete"),
        (
            _context(fetched_at=NOW - timedelta(minutes=10)),
            TEAM_KEY,
            NOW,
            "stale",
        ),
        (_context(), "461.l.61410.t.99", NOW, "found 0"),
    ],
)
def test_incomplete_stale_or_unresolved_team_context_fails_closed(
    context, team_key, checked_at, match
):
    with pytest.raises(RookieAddContextError, match=match):
        build_rookie_add_recommendations(
            context,
            team_key,
            checked_at=checked_at,
        )


def test_position_and_count_apply_after_complete_rookie_discovery():
    result = build_rookie_add_recommendations(
        _context(superflex=True),
        TEAM_KEY,
        position="RB",
        count=1,
        checked_at=NOW,
    )

    assert [player["name"] for player in result["players"]] == ["Jeremiyah Love"]
    assert result["evidence"]["matched_players"] == 1
    assert result["evidence"]["returned_players"] == 1
    assert result["evidence"]["scoring_adjustment"].startswith("None.")


def test_count_does_not_hide_complete_match_evidence():
    result = build_rookie_add_recommendations(
        _context(superflex=True),
        TEAM_KEY,
        count=1,
        checked_at=NOW,
    )

    assert len(result["players"]) == 1
    assert result["evidence"]["matched_players"] == 2
    assert result["evidence"]["returned_players"] == 1
