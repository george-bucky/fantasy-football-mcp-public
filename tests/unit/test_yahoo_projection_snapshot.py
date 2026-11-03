"""Pure synthetic UI forecast bridge: no browser or provider access."""

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from src.services.yahoo_projection_snapshot import apply_yahoo_projection_snapshot

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


@dataclass
class SyntheticPlayer:
    player_key: str
    yahoo_projection: float = 0
    projection_context: dict = field(default_factory=dict)
    raw: dict = field(default_factory=lambda: {"api_forecast": "unavailable"})


def players():
    return [
        SyntheticPlayer("777.p.1001"),
        SyntheticPlayer("777.p.1002", 12),
        SyntheticPlayer("777.p.1999"),
    ]


def snapshot():
    return {
        "source_kind": "yahoo_visible_projection_snapshot",
        "source_url": "https://football.fantasysports.yahoo.com/f1/1234/2",
        "season": 2026,
        "week": 9,
        "scoring_basis": "ppr",
        "observed_at": NOW.isoformat(),
        "rows": [
            {"player_id": "1001", "projection": 15.5},
            {"player_key": "777.p.1002", "projection": 0},
        ],
    }


def apply(ps=None, snap=None, **kwargs):
    args = {
        "league_key": "777.l.1234",
        "team_key": "777.l.1234.t.2",
        "season": 2026,
        "week": 9,
        "scoring_basis": "ppr",
        "as_of": NOW,
    }
    args.update(kwargs)
    return apply_yahoo_projection_snapshot(
        players() if ps is None else ps, snapshot() if snap is None else snap, **args
    )


def test_valid_snapshot_copies_roster_preserves_raw_and_marks_known_zero():
    ps, snap = players(), snapshot()
    before = copy.deepcopy((ps, snap))
    result, audit = apply(ps, snap)
    assert (ps, snap) == before
    assert audit["available"] and audit["applied_count"] == 2
    assert [p.yahoo_projection for p in result] == [15.5, 0, 0]
    assert result[0] is not ps[0]
    assert result[0].raw == ps[0].raw
    context = result[1].projection_context
    assert context["yahoo_projection_present"] is True
    assert context["yahoo_projection_snapshot"]["original_yahoo_projection"] == 12
    assert context["yahoo_projection_snapshot"]["raw_snapshot_value"] == 0
    assert context["as_of"] == NOW.isoformat()
    assert context["live_context_collected"] is True
    source = context["source_provenance"]["yahoo"]
    assert source["max_age_seconds"] == 900
    assert source["observed_at"] == source["as_of"] == NOW.isoformat()
    assert source["server_refetched"] is False
    assert "issued_at" not in source
    assert "yahoo_projection_present" not in result[2].projection_context


def test_negative_projection_and_old_observation_preserved_distinct_from_assessment_clock():
    snap = snapshot()
    snap["observed_at"] = (NOW - timedelta(minutes=10)).isoformat()
    snap["rows"][0]["projection"] = -1.5
    result, audit = apply(snap=snap)
    assert result[0].yahoo_projection == -1.5
    assert result[0].projection_context["as_of"] == NOW.isoformat()
    assert (
        result[0].projection_context["source_provenance"]["yahoo"]["as_of"] == snap["observed_at"]
    )
    assert audit["applied_values"][0]["raw_snapshot_value"] == -1.5


def test_idempotent_reapplication_keeps_original_provider_value():
    a, _ = apply()
    b, _ = apply(a)
    assert a == b


@pytest.mark.parametrize(
    "change",
    [
        {"source_kind": "yahoo_api_actuals"},
        {"season": 2025},
        {"week": 8},
        {"week": True},
        {"scoring_basis": "standard"},
        {"league_key": "777.l.9"},
        {"team_key": "777.l.1234.t.3"},
        {"source_url": "http://football.fantasysports.yahoo.com/f1/1234/2"},
        {"source_url": "https://football.fantasysports.yahoo.com/f1/1234/3"},
        {"source_url": "https://football.fantasysports.yahoo.com/f1/1234/2?token=private"},
        {"source_url": "https://football.fantasysports.yahoo.com.evil.example/f1/1234/2"},
        {"source_url": "https://user:secret@football.fantasysports.yahoo.com/f1/1234/2"},
        {"observed_at": (NOW - timedelta(seconds=901)).isoformat()},
        {"observed_at": (NOW + timedelta(seconds=1)).isoformat()},
        {"observed_at": "2026-11-03T12:00:00"},
        {"rows": {}},
        {"rows": [{}] * 101},
    ],
)
def test_invalid_snapshot_rejected_atomically_without_echoing_sensitive_input(change):
    ps, snap = players(), snapshot()
    snap.update(change)
    result, audit = apply(ps, snap)
    assert result == ps
    assert not audit["available"] and audit["applied_count"] == 0
    assert "private" not in json.dumps(audit) and "secret" not in json.dumps(audit)


@pytest.mark.parametrize(
    "bad",
    [True, float("inf"), float("nan"), pytest.param(1 << 20000, id="huge-integer"), "15.5", None],
)
def test_invalid_numeric_projection_rejects_whole_snapshot(bad):
    snap = snapshot()
    snap["rows"][1]["projection"] = bad
    result, audit = apply(snap=snap)
    assert result == players()
    assert not audit["available"]
    json.dumps(audit, allow_nan=False)


@pytest.mark.parametrize(
    "row",
    [
        {"player_key": "778.p.1001", "projection": 2},
        {"player_id": "1001", "player_key": "777.p.1002", "projection": 2},
        {"player_id": "BUF", "projection": 2},
        {"name": "Synthetic Receiver", "projection": 2},
        {"player_id": 1001, "projection": 2},
        {"player_key": "777.p.1001", "projection": 3},
    ],
)
def test_invalid_or_duplicate_identity_rejects_all(row):
    snap = snapshot()
    snap["rows"].append(row)
    result, audit = apply(snap=snap)
    assert result == players()
    assert not audit["available"]


def test_valid_unrostered_rows_skipped_and_never_match_defense_by_team():
    snap = snapshot()
    snap["rows"].append({"player_id": "9999", "projection": 7})
    result, audit = apply(snap=snap)
    assert audit["available"] and audit["unmatched_count"] == 1
    assert audit["applied_count"] == 2
    assert result[2].yahoo_projection == 0
    assert "yahoo_projection_present" not in result[2].projection_context


@pytest.mark.parametrize(
    "roster",
    [
        [SyntheticPlayer("777.p.1001"), SyntheticPlayer("777.p.1001")],
        [SyntheticPlayer("778.p.1001")],
        [SyntheticPlayer("")],
    ],
)
def test_ambiguous_or_unscoped_roster_rejects(roster):
    result, audit = apply(roster)
    assert result == roster and not audit["available"]


def test_missing_snapshot_has_explicit_no_api_forecast_reason():
    result, audit = apply_yahoo_projection_snapshot(
        players(),
        None,
        league_key="777.l.1234",
        team_key="777.l.1234.t.2",
        season=2026,
        week=9,
        scoring_basis="ppr",
        as_of=NOW,
    )
    assert result == players()
    assert audit["reason"] == "yahoo_forecast_not_provided_by_api_or_snapshot"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"season": True},
        {"week": 0},
        {"scoring_basis": []},
        {"team_key": "777.l.9999.t.2"},
        {"as_of": datetime(2026, 11, 3, 12)},
    ],
)
def test_invalid_request_safe_unavailable(kwargs):
    result, audit = apply(**kwargs)
    assert result == players() and not audit["available"]
