"""Offline contract tests for private Yahoo league context."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from src.models.league_context import EvidenceMetadata, RosterSlot
from src.services.league_context import (
    LeagueContextError,
    YahooLeagueContextService,
    calculate_replacement_demand,
    parse_yahoo_available_page,
    parse_yahoo_roster,
    parse_yahoo_settings,
    parse_yahoo_teams,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
LEAGUE_KEY = "461.l.61410"
TEAM_KEY = "461.l.61410.t.7"


def _settings_payload(
    *,
    direct_settings=False,
    include_team_count=True,
    team_count=10,
    league_key=LEAGUE_KEY,
    league_id="61410",
):
    metadata = [
        {"league_key": league_key},
        {"league_id": league_id},
        {"name": "Exact League"},
        {"scoring_type": "head"},
    ]
    if include_team_count:
        metadata.append({"num_teams": team_count})
    settings = [
        {"scoring_type": "head"},
        {
            "roster_positions": [
                {
                    "roster_position": {
                        "position": "QB",
                        "count": 1,
                        "is_starting_position": 1,
                    }
                },
                {
                    "roster_position": {
                        "position": "W/R/T",
                        "count": "2",
                        "is_starting_position": "1",
                    }
                },
                {"roster_position": {"position": "BN", "count": 6}},
            ]
        },
        {
            "stat_modifiers": {
                "stats": {
                    "0": {"stat": {"stat_id": "4", "value": "4"}},
                    "1": {"stat": {"stat_id": "10", "value": "0.5"}},
                    "count": 2,
                }
            }
        },
    ]
    if direct_settings:
        settings = {
            "scoring_type": "head",
            "roster_positions": settings[1]["roster_positions"],
            "stat_modifiers": settings[2]["stat_modifiers"],
        }
    return {"fantasy_content": {"league": [metadata, {"settings": settings}]}}


def _raw_team(team_key=TEAM_KEY, team_id="7", managers=None):
    if managers is None:
        managers = [
            {
                "manager": {
                    "manager_id": "12",
                    "guid": "USER-GUID-12",
                    "nickname": "Exact User",
                }
            }
        ]
    team = [
        [
            {"team_key": team_key},
            {"team_id": team_id},
            {"name": "Identity Keepers"},
        ],
        {"managers": managers},
    ]
    return team


def _manager(*, manager_id=None, guid=None, nickname="Manager"):
    data = {"nickname": nickname}
    if manager_id is not None:
        data["manager_id"] = manager_id
    if guid is not None:
        data["guid"] = guid
    return {"manager": data}


def _teams_payload(*, list_shape=False, league_key=LEAGUE_KEY, raw_teams=None):
    raw_teams = raw_teams or [_raw_team()]
    teams = (
        [{"team": team} for team in raw_teams]
        if list_shape
        else {
            **{str(index): {"team": team} for index, team in enumerate(raw_teams)},
            "count": len(raw_teams),
        }
    )
    return {"fantasy_content": {"league": [[{"league_key": league_key}], {"teams": teams}]}}


def _player(player_id, name, *, selected=None, status=None, player_key=None):
    fields = [
        {"player_key": player_key or f"461.p.{player_id}"},
        {"player_id": str(player_id)},
        {"name": {"full": name}},
        {"display_position": "QB"},
        {"eligible_positions": [{"position": "QB"}]},
    ]
    if status:
        fields.append({"status": status})
    tail = {"selected_position": [{"position": selected}]} if selected else {}
    return [fields, tail]


def _roster_payload(*players, team_key=TEAM_KEY, declared_count=None, entries_override=None):
    if not players:
        players = (_player("1001", "Rookie One", selected="QB"),)
    entries = (
        entries_override
        if entries_override is not None
        else {str(index): {"player": player} for index, player in enumerate(players)}
    )
    entries["count"] = len(players) if declared_count is None else declared_count
    return {
        "fantasy_content": {
            "team": [
                [{"team_key": team_key}, {"team_id": team_key.rsplit(".", 1)[-1]}],
                {"roster": {"0": {"players": entries}}},
            ]
        }
    }


def _available_payload(*players, league_key=LEAGUE_KEY, declared_count=None):
    entries = {str(index): {"player": player} for index, player in enumerate(players)}
    entries["count"] = len(players) if declared_count is None else declared_count
    return {"fantasy_content": {"league": [[{"league_key": league_key}], {"players": entries}]}}


async def _fetch_single_team_context(
    *, settings_payload=None, teams_payload=None, roster_payload=None, availability_payload=None
):
    responses = {
        f"league/{LEAGUE_KEY}/settings": settings_payload or _settings_payload(team_count=1),
        f"league/{LEAGUE_KEY}/teams": teams_payload or _teams_payload(),
        f"team/{TEAM_KEY}/roster": roster_payload or _roster_payload(),
        f"league/{LEAGUE_KEY}/players;status=A;start=0;count=25": (
            availability_payload or _available_payload()
        ),
    }

    async def api_call(endpoint):
        return responses[endpoint]

    return await YahooLeagueContextService(api_call=api_call, clock=lambda: NOW).fetch(LEAGUE_KEY)


@pytest.mark.parametrize("direct_settings", [False, True])
def test_settings_preserve_exact_keys_slots_and_scoring(direct_settings):
    settings = parse_yahoo_settings(
        _settings_payload(direct_settings=direct_settings), LEAGUE_KEY, NOW
    )

    assert settings.league_key == "461.l.61410"
    assert settings.league_id == "61410"
    assert settings.team_count == 10
    assert settings.scoring_type == "head"
    assert [(slot.position, slot.count) for slot in settings.roster_slots] == [
        ("QB", 1),
        ("W/R/T", 2),
        ("BN", 6),
    ]
    assert settings.roster_slots[1].eligible_positions == ("WR", "RB", "TE")
    assert [(stat.stat_id, stat.value) for stat in settings.scoring_settings] == [
        ("4", "4"),
        ("10", "0.5"),
    ]
    assert settings.evidence.complete is True
    with pytest.raises(FrozenInstanceError):
        settings.team_count = 12


def test_missing_settings_are_unknown_and_incomplete():
    settings = parse_yahoo_settings(_settings_payload(include_team_count=False), LEAGUE_KEY, NOW)

    assert settings.team_count is None
    assert settings.evidence.complete is False
    assert "Yahoo response omitted team count" in settings.evidence.warnings


def test_truncated_roster_positions_force_settings_incomplete():
    payload = _settings_payload(direct_settings=True)
    settings_data = payload["fantasy_content"]["league"][1]["settings"]
    first_slot = settings_data["roster_positions"][0]
    settings_data["roster_positions"] = {"0": first_slot, "count": 2}

    settings = parse_yahoo_settings(payload, LEAGUE_KEY, NOW)

    assert settings.evidence.complete is False
    assert any(
        "roster_positions declared 2 entries but contained 1" in warning
        for warning in settings.evidence.warnings
    )


def test_malformed_roster_position_with_matching_count_is_incomplete():
    payload = _settings_payload(direct_settings=True)
    payload["fantasy_content"]["league"][1]["settings"]["roster_positions"] = {
        "0": {"not_roster_position": {}},
        "count": 1,
    }

    settings = parse_yahoo_settings(payload, LEAGUE_KEY, NOW)

    assert settings.evidence.complete is False
    assert any("entry 0 omitted position" in warning for warning in settings.evidence.warnings)


def test_truncated_and_malformed_stat_modifiers_force_settings_incomplete():
    truncated = _settings_payload(direct_settings=True)
    stats = truncated["fantasy_content"]["league"][1]["settings"]["stat_modifiers"]["stats"]
    stats.pop("1")
    truncated_settings = parse_yahoo_settings(truncated, LEAGUE_KEY, NOW)

    malformed = _settings_payload(direct_settings=True)
    malformed["fantasy_content"]["league"][1]["settings"]["stat_modifiers"]["stats"] = {
        "0": {"stat": {"stat_id": "4"}},
        "count": 1,
    }
    malformed_settings = parse_yahoo_settings(malformed, LEAGUE_KEY, NOW)

    assert truncated_settings.evidence.complete is False
    assert any(
        "stat_modifiers stats declared 2 entries but contained 1" in warning
        for warning in truncated_settings.evidence.warnings
    )
    assert malformed_settings.evidence.complete is False
    assert any(
        "entry 0 omitted stat_id or modifier value" in warning
        for warning in malformed_settings.evidence.warnings
    )


@pytest.mark.asyncio
async def test_unknown_roster_slot_forces_settings_and_context_incomplete():
    payload = _settings_payload(direct_settings=True, team_count=1)
    payload["fantasy_content"]["league"][1]["settings"]["roster_positions"][0]["roster_position"][
        "position"
    ] = "Q/X"

    context = await _fetch_single_team_context(settings_payload=payload)

    assert context.settings.evidence.complete is False
    assert context.evidence.complete is False
    assert "Unknown eligibility for roster slot 'Q/X'" in context.evidence.warnings


@pytest.mark.parametrize(
    ("league_key", "league_id", "warning"),
    [
        (LEAGUE_KEY, "99999", "encodes league_id '61410'"),
        ("malformed", "61410", "malformed Yahoo key shape"),
    ],
)
def test_league_key_and_id_internal_consistency_is_enforced(league_key, league_id, warning):
    settings = parse_yahoo_settings(
        _settings_payload(league_key=league_key, league_id=league_id),
        league_key,
        NOW,
    )

    assert settings.evidence.complete is False
    assert any(warning in item for item in settings.evidence.warnings)


@pytest.mark.asyncio
async def test_availability_envelope_league_key_id_mismatch_is_incomplete():
    payload = _available_payload()
    payload["fantasy_content"]["league"][0].append({"league_id": "99999"})

    async def api_call(_endpoint):
        return payload

    availability = await YahooLeagueContextService(
        api_call=api_call, clock=lambda: NOW
    )._fetch_availability(LEAGUE_KEY)

    assert availability.evidence.complete is False
    assert any("encodes league_id '61410'" in warning for warning in availability.evidence.warnings)


@pytest.mark.parametrize("list_shape", [False, True])
def test_team_and_user_ids_survive_alternate_singleton_list_nesting(list_shape):
    teams = parse_yahoo_teams(_teams_payload(list_shape=list_shape), expected_league_key=LEAGUE_KEY)

    assert len(teams) == 1
    assert teams[0].team_key == TEAM_KEY
    assert teams[0].team_id == "7"
    assert teams[0].users[0].manager_id == "12"
    assert teams[0].users[0].guid == "USER-GUID-12"


@pytest.mark.asyncio
async def test_team_key_id_mismatch_forces_context_incomplete():
    context = await _fetch_single_team_context(
        teams_payload=_teams_payload(raw_teams=[_raw_team(team_id="9")])
    )

    assert context.rosters == ()
    assert context.evidence.complete is False
    assert any("encodes team_id '7'" in warning for warning in context.evidence.warnings)


@pytest.mark.asyncio
async def test_malformed_team_key_shape_forces_context_incomplete():
    context = await _fetch_single_team_context(
        teams_payload=_teams_payload(raw_teams=[_raw_team("461.team.7")])
    )

    assert context.rosters == ()
    assert context.evidence.complete is False
    assert any("malformed Yahoo key shape" in warning for warning in context.evidence.warnings)


@pytest.mark.asyncio
async def test_manager_data_without_identity_is_not_silently_discarded():
    managers = {
        "0": {"manager": {"nickname": "Missing Identity"}},
        "count": 1,
    }
    context = await _fetch_single_team_context(
        teams_payload=_teams_payload(raw_teams=[_raw_team(managers=managers)])
    )

    assert context.rosters[0].team.users == ()
    assert context.evidence.complete is False
    assert any("omitted manager_id and guid" in warning for warning in context.evidence.warnings)


@pytest.mark.asyncio
async def test_truncated_manager_collection_forces_context_incomplete():
    managers = {
        "0": {
            "manager": {
                "manager_id": "12",
                "guid": "USER-GUID-12",
                "nickname": "Exact User",
            }
        },
        "count": 2,
    }
    context = await _fetch_single_team_context(
        teams_payload=_teams_payload(raw_teams=[_raw_team(managers=managers)])
    )

    assert context.rosters[0].team.users[0].manager_id == "12"
    assert context.evidence.complete is False
    assert any(
        "Yahoo managers declared 2 entries but contained 1" in warning
        for warning in context.evidence.warnings
    )


@pytest.mark.asyncio
async def test_duplicate_identical_manager_identity_is_rejected():
    identity = _manager(manager_id="12", guid="GUID-12")
    managers = {"0": identity, "1": identity, "count": 2}

    context = await _fetch_single_team_context(
        teams_payload=_teams_payload(raw_teams=[_raw_team(managers=managers)])
    )

    assert len(context.rosters[0].team.users) == 1
    assert context.evidence.complete is False
    assert any("repeated manager identity" in warning for warning in context.evidence.warnings)


@pytest.mark.parametrize(
    ("managers", "warning"),
    [
        (
            {
                "0": _manager(manager_id="12", guid="GUID-A"),
                "1": _manager(manager_id="12", guid="GUID-B"),
                "count": 2,
            },
            "manager_id '12' maps to conflicting GUIDs",
        ),
        (
            {
                "0": _manager(manager_id="12", guid="GUID-A"),
                "1": _manager(manager_id="13", guid="GUID-A"),
                "count": 2,
            },
            "guid 'GUID-A' maps to conflicting manager_ids",
        ),
    ],
)
@pytest.mark.asyncio
async def test_conflicting_manager_identity_mappings_are_rejected(managers, warning):
    context = await _fetch_single_team_context(
        teams_payload=_teams_payload(raw_teams=[_raw_team(managers=managers)])
    )

    assert len(context.rosters[0].team.users) == 1
    assert context.evidence.complete is False
    assert any(warning in item for item in context.evidence.warnings)


@pytest.mark.asyncio
async def test_distinct_partial_manager_identities_remain_separate():
    managers = {
        "0": _manager(manager_id="12", nickname="ID only"),
        "1": _manager(guid="GUID-13", nickname="GUID only"),
        "count": 2,
    }

    context = await _fetch_single_team_context(
        teams_payload=_teams_payload(raw_teams=[_raw_team(managers=managers)])
    )

    assert context.evidence.complete is True
    assert [(user.manager_id, user.guid) for user in context.rosters[0].team.users] == [
        ("12", None),
        (None, "GUID-13"),
    ]


@pytest.mark.asyncio
async def test_overlapping_partial_manager_identity_is_rejected_without_linking():
    managers = {
        "0": _manager(manager_id="12", guid="GUID-12"),
        "1": _manager(manager_id="12", nickname="Partial"),
        "count": 2,
    }

    context = await _fetch_single_team_context(
        teams_payload=_teams_payload(raw_teams=[_raw_team(managers=managers)])
    )

    assert [(user.manager_id, user.guid) for user in context.rosters[0].team.users] == [
        ("12", "GUID-12")
    ]
    assert context.evidence.complete is False
    assert any(
        "rejected without linking identities" in warning for warning in context.evidence.warnings
    )


def test_available_player_parser_preserves_player_identity_and_status():
    players, raw_count, declared_count, container_present = parse_yahoo_available_page(
        _available_payload(_player("2001", "Available Rookie", status="Q")),
        expected_league_key=LEAGUE_KEY,
    )

    assert raw_count == 1
    assert declared_count == 1
    assert container_present is True
    assert players[0].player_key == "461.p.2001"
    assert players[0].player_id == "2001"
    assert players[0].availability_status == "A"
    assert players[0].injury_status == "Q"


def _demand(team_count, *slots):
    return {
        result.position: result.starter_demand
        for result in calculate_replacement_demand(team_count, slots)
    }


def test_replacement_demand_1qb_is_hand_calculable():
    demand = _demand(
        10,
        RosterSlot("QB", 1, ("QB",), True),
        RosterSlot("RB", 2, ("RB",), True),
        RosterSlot("W/R/T", 1, ("WR", "RB", "TE"), True),
        RosterSlot("BN", 6, (), False),
    )

    assert demand == {"QB": 10, "RB": 30, "TE": 10, "WR": 10}


def test_replacement_demand_2qb_and_superflex_are_hand_calculable():
    assert _demand(12, RosterSlot("QB", 2, ("QB",), True)) == {"QB": 24}
    assert _demand(
        12,
        RosterSlot("QB", 1, ("QB",), True),
        RosterSlot("Q/W/R/T", 1, ("QB", "WR", "RB", "TE"), True),
    ) == {"QB": 24, "RB": 12, "TE": 12, "WR": 12}


def test_replacement_demand_does_not_invent_unknown_inputs():
    unknown = RosterSlot("MYSTERY", 1, (), None)
    unknown_starting_state = RosterSlot("QB", 1, ("QB",), None)
    assert calculate_replacement_demand(None, (unknown,)) == ()
    assert calculate_replacement_demand(10, (unknown,)) == ()
    assert calculate_replacement_demand(10, (unknown_starting_state,)) == ()


@pytest.mark.asyncio
async def test_service_fetches_rosters_and_all_availability_pages():
    calls = []
    responses = {
        f"league/{LEAGUE_KEY}/settings": _settings_payload(),
        f"league/{LEAGUE_KEY}/teams": _teams_payload(),
        f"team/{TEAM_KEY}/roster": _roster_payload(),
        f"league/{LEAGUE_KEY}/players;status=A;start=0;count=2": _available_payload(
            _player("2001", "Available One"), _player("2002", "Available Two")
        ),
        f"league/{LEAGUE_KEY}/players;status=A;start=2;count=2": _available_payload(
            _player("2003", "Available Three")
        ),
    }

    async def api_call(endpoint):
        calls.append(endpoint)
        return responses[endpoint]

    context = await YahooLeagueContextService(
        api_call=api_call, clock=lambda: NOW, availability_page_size=2
    ).fetch(LEAGUE_KEY)

    assert context.rosters[0].team.team_key == TEAM_KEY
    assert context.rosters[0].players[0].player_key == "461.p.1001"
    assert [player.player_id for player in context.availability.players] == [
        "2001",
        "2002",
        "2003",
    ]
    assert context.availability.evidence.complete is True
    assert context.availability.evidence.page_count == 2
    assert context.evidence.complete is False
    assert "returned 1 teams" in context.evidence.warnings[0]
    assert calls[-2:] == [
        f"league/{LEAGUE_KEY}/players;status=A;start=0;count=2",
        f"league/{LEAGUE_KEY}/players;status=A;start=2;count=2",
    ]


@pytest.mark.asyncio
async def test_auth_failure_is_visible_with_endpoint_and_cause():
    async def api_call(_endpoint):
        raise RuntimeError("401 token rejected")

    with pytest.raises(LeagueContextError, match="401 token rejected"):
        await YahooLeagueContextService(api_call=api_call).fetch(LEAGUE_KEY)


@pytest.mark.asyncio
async def test_duplicate_availability_ids_are_deduplicated_and_incomplete():
    pages = iter(
        [
            _available_payload(_player("2001", "First"), _player("2002", "Second")),
            _available_payload(_player("2002", "Second Duplicate")),
        ]
    )

    async def api_call(_endpoint):
        return next(pages)

    availability = await YahooLeagueContextService(
        api_call=api_call, clock=lambda: NOW, availability_page_size=2
    )._fetch_availability(LEAGUE_KEY)

    assert [player.player_id for player in availability.players] == ["2001", "2002"]
    assert availability.evidence.complete is False
    assert "Duplicate available player identity" in availability.evidence.warnings[0]


@pytest.mark.asyncio
async def test_availability_page_limit_is_explicitly_incomplete():
    async def api_call(_endpoint):
        return _available_payload(_player("2001", "One"), _player("2002", "Two"))

    availability = await YahooLeagueContextService(
        api_call=api_call,
        clock=lambda: NOW,
        availability_page_size=2,
        max_availability_pages=1,
    )._fetch_availability(LEAGUE_KEY)

    assert availability.evidence.complete is False
    assert "without a short final page" in availability.evidence.warnings[0]


@pytest.mark.asyncio
async def test_empty_count_zero_page_cleanly_terminates_after_full_page():
    pages = iter(
        [
            _available_payload(_player("2001", "One"), _player("2002", "Two")),
            _available_payload(),
        ]
    )

    async def api_call(_endpoint):
        return next(pages)

    availability = await YahooLeagueContextService(
        api_call=api_call, clock=lambda: NOW, availability_page_size=2
    )._fetch_availability(LEAGUE_KEY)

    assert [player.player_id for player in availability.players] == ["2001", "2002"]
    assert availability.evidence.complete is True
    assert availability.evidence.page_count == 2
    assert availability.evidence.warnings == ()


@pytest.mark.asyncio
async def test_malformed_availability_entry_with_matching_count_is_incomplete():
    payload = _available_payload(_player("2001", "Ignored"))
    payload["fantasy_content"]["league"][1]["players"]["0"] = {"not_player": {}}

    async def api_call(_endpoint):
        return payload

    availability = await YahooLeagueContextService(
        api_call=api_call, clock=lambda: NOW
    )._fetch_availability(LEAGUE_KEY)

    assert availability.players == ()
    assert availability.evidence.complete is False
    assert "entry 0 omitted player object" in availability.evidence.warnings[0]


def test_truncated_roster_declared_count_is_incomplete():
    team = parse_yahoo_teams(_teams_payload(), expected_league_key=LEAGUE_KEY)[0]
    roster = parse_yahoo_roster(
        _roster_payload(declared_count=2),
        team,
        NOW,
        expected_league_key=LEAGUE_KEY,
    )

    assert len(roster.players) == 1
    assert roster.evidence.complete is False
    assert "declared 2 entries but contained 1" in roster.evidence.warnings[0]


def test_empty_roster_count_zero_is_complete():
    team = parse_yahoo_teams(_teams_payload(), expected_league_key=LEAGUE_KEY)[0]
    roster = parse_yahoo_roster(
        _roster_payload(entries_override={}, declared_count=0),
        team,
        NOW,
        expected_league_key=LEAGUE_KEY,
    )

    assert roster.players == ()
    assert roster.evidence.complete is True


def test_roster_team_key_and_id_mismatch_is_incomplete():
    team = parse_yahoo_teams(_teams_payload(), expected_league_key=LEAGUE_KEY)[0]
    payload = _roster_payload()
    payload["fantasy_content"]["team"][0][1]["team_id"] = "9"

    roster = parse_yahoo_roster(payload, team, NOW, expected_league_key=LEAGUE_KEY)

    assert roster.evidence.complete is False
    assert any("encodes team_id '7'" in warning for warning in roster.evidence.warnings)


@pytest.mark.parametrize(
    ("player_key", "player_id", "warning"),
    [
        ("461.p.1001", "9999", "encodes player_id '1001'"),
        ("461.player.1001", "1001", "malformed Yahoo key shape"),
        ("462.p.1001", "1001", "belongs to Yahoo game '462'"),
        (".p.1001", "1001", "malformed Yahoo key shape"),
    ],
)
def test_roster_player_key_id_consistency_is_enforced(player_key, player_id, warning):
    team = parse_yahoo_teams(_teams_payload(), expected_league_key=LEAGUE_KEY)[0]
    roster = parse_yahoo_roster(
        _roster_payload(_player(player_id, "Invalid", player_key=player_key)),
        team,
        NOW,
        expected_league_key=LEAGUE_KEY,
    )

    assert roster.players == ()
    assert roster.evidence.complete is False
    assert any(warning in item for item in roster.evidence.warnings)


@pytest.mark.parametrize(
    ("player_key", "warning"),
    [
        ("461.player.1001", "malformed Yahoo key shape"),
        ("462.p.1001", "belongs to Yahoo game '462'"),
        (".p.1001", "malformed Yahoo key shape"),
    ],
)
@pytest.mark.asyncio
async def test_available_player_game_and_key_shape_are_enforced(player_key, warning):
    async def api_call(_endpoint):
        return _available_payload(_player("1001", "Invalid", player_key=player_key))

    availability = await YahooLeagueContextService(
        api_call=api_call,
        clock=lambda: NOW,
    )._fetch_availability(LEAGUE_KEY)

    assert availability.players == ()
    assert availability.evidence.complete is False
    assert any(warning in item for item in availability.evidence.warnings)


@pytest.mark.asyncio
async def test_missing_availability_container_is_explicitly_incomplete():
    async def api_call(_endpoint):
        return {"fantasy_content": {"league": [[{"league_key": LEAGUE_KEY}], {}]}}

    availability = await YahooLeagueContextService(
        api_call=api_call, clock=lambda: NOW
    )._fetch_availability(LEAGUE_KEY)

    assert availability.players == ()
    assert availability.evidence.complete is False
    assert "players container is missing" in availability.evidence.warnings[0]


@pytest.mark.asyncio
async def test_cross_roster_identity_overlap_marks_context_incomplete():
    second_team_key = "461.l.61410.t.8"
    shared = _player("1001", "Shared Rookie")
    responses = {
        f"league/{LEAGUE_KEY}/settings": _settings_payload(team_count=2),
        f"league/{LEAGUE_KEY}/teams": _teams_payload(
            raw_teams=[_raw_team(), _raw_team(second_team_key, "8")]
        ),
        f"team/{TEAM_KEY}/roster": _roster_payload(shared),
        f"team/{second_team_key}/roster": _roster_payload(shared, team_key=second_team_key),
        f"league/{LEAGUE_KEY}/players;status=A;start=0;count=25": _available_payload(),
    }

    async def api_call(endpoint):
        return responses[endpoint]

    context = await YahooLeagueContextService(api_call=api_call, clock=lambda: NOW).fetch(
        LEAGUE_KEY
    )

    assert context.evidence.complete is False
    assert "appears on both" in context.evidence.warnings[0]


@pytest.mark.asyncio
async def test_foreign_game_roster_player_marks_context_incomplete():
    second_team_key = "461.l.61410.t.8"
    responses = {
        f"league/{LEAGUE_KEY}/settings": _settings_payload(team_count=2),
        f"league/{LEAGUE_KEY}/teams": _teams_payload(
            raw_teams=[_raw_team(), _raw_team(second_team_key, "8")]
        ),
        f"team/{TEAM_KEY}/roster": _roster_payload(_player("1001", "First")),
        f"team/{second_team_key}/roster": _roster_payload(
            _player("1001", "Conflict", player_key="462.p.1001"),
            team_key=second_team_key,
        ),
        f"league/{LEAGUE_KEY}/players;status=A;start=0;count=25": _available_payload(),
    }

    async def api_call(endpoint):
        return responses[endpoint]

    context = await YahooLeagueContextService(api_call=api_call, clock=lambda: NOW).fetch(
        LEAGUE_KEY
    )

    assert context.evidence.complete is False
    assert context.rosters[1].players == ()
    assert any(
        "belongs to Yahoo game '462'" in warning for warning in context.rosters[1].evidence.warnings
    )


@pytest.mark.asyncio
async def test_rostered_available_overlap_marks_both_contexts_incomplete():
    shared = _player("1001", "Shared Rookie")
    responses = {
        f"league/{LEAGUE_KEY}/settings": _settings_payload(team_count=1),
        f"league/{LEAGUE_KEY}/teams": _teams_payload(),
        f"team/{TEAM_KEY}/roster": _roster_payload(shared),
        f"league/{LEAGUE_KEY}/players;status=A;start=0;count=25": _available_payload(shared),
    }

    async def api_call(endpoint):
        return responses[endpoint]

    context = await YahooLeagueContextService(api_call=api_call, clock=lambda: NOW).fetch(
        LEAGUE_KEY
    )

    assert context.evidence.complete is False
    assert context.availability.evidence.complete is False
    assert "both rostered" in context.availability.evidence.warnings[-1]


@pytest.mark.asyncio
async def test_available_internal_key_id_conflict_is_incomplete():
    rostered = _player("1001", "Rostered")
    conflicting = _player("9999", "Conflict", player_key="461.p.1001")
    responses = {
        f"league/{LEAGUE_KEY}/settings": _settings_payload(team_count=1),
        f"league/{LEAGUE_KEY}/teams": _teams_payload(),
        f"team/{TEAM_KEY}/roster": _roster_payload(rostered),
        f"league/{LEAGUE_KEY}/players;status=A;start=0;count=25": _available_payload(conflicting),
    }

    async def api_call(endpoint):
        return responses[endpoint]

    context = await YahooLeagueContextService(api_call=api_call, clock=lambda: NOW).fetch(
        LEAGUE_KEY
    )

    assert context.evidence.complete is False
    assert context.availability.evidence.complete is False
    assert "encodes player_id '1001'" in context.availability.evidence.warnings[0]


def test_foreign_teams_envelope_and_object_are_rejected():
    with pytest.raises(LeagueContextError, match="Yahoo teams response league_key mismatch"):
        parse_yahoo_teams(
            _teams_payload(league_key="461.l.99999"),
            expected_league_key=LEAGUE_KEY,
        )

    with pytest.raises(LeagueContextError, match="does not belong to requested league"):
        parse_yahoo_teams(
            _teams_payload(raw_teams=[_raw_team("461.l.99999.t.7")]),
            expected_league_key=LEAGUE_KEY,
        )


@pytest.mark.asyncio
async def test_foreign_availability_envelope_is_rejected():
    async def api_call(_endpoint):
        return _available_payload(league_key="461.l.99999")

    with pytest.raises(LeagueContextError, match="availability response league_key mismatch"):
        await YahooLeagueContextService(api_call=api_call)._fetch_availability(LEAGUE_KEY)


def test_freshness_is_explicit_and_stale_is_deterministic():
    evidence = EvidenceMetadata(NOW, stale_after_seconds=300, complete=True)

    assert evidence.is_stale(NOW + timedelta(seconds=300)) is False
    assert evidence.is_stale(NOW + timedelta(seconds=301)) is True
