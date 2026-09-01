"""Offline parser, transport-bound, and cache tests for manual-draft sources."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.manual_draft_service import (
    ECR_URL,
    ESPN_URL,
    FFC_URL,
    MAX_PLAYERS,
    NFLVERSE_URL_TEMPLATE,
    PROVIDER_CAPS,
    PROVIDER_TTLS,
    SLEEPER_PLAYERS_URL,
    SLEEPER_TRENDING_ADD_URL,
    SLEEPER_TRENDING_DROP_URL,
    ManualDraftService,
    ProviderError,
    _source_freshness,
    parse_ecr_rows,
    parse_espn_projection_rows,
    parse_ffc_rows,
    parse_nflverse_rows,
    parse_sleeper_rows,
)

ESPN_PAYLOAD = json.dumps(
    {
        "players": [
            {
                "player": {
                    "id": 1,
                    "fullName": "Raw Projection",
                    "active": True,
                    "defaultPositionId": 1,
                    "proTeamId": 2,
                    "stats": [
                        {
                            "seasonId": 2026,
                            "statSourceId": 1,
                            "statSplitTypeId": 1,
                            "appliedTotal": 999,
                            "stats": {"3": 100},
                        },
                        {
                            "seasonId": 2026,
                            "statSourceId": 1,
                            "statSplitTypeId": 0,
                            "appliedTotal": 9_999,
                            "stats": {
                                "3": 4_000,
                                "4": 30,
                                "15": 5,
                                "19": 2,
                                "20": 10,
                                "24": 500,
                                "25": 5,
                                "26": 1,
                                "53": 4,
                                "42": 50,
                                "43": 1,
                                "44": 1,
                                "72": 3,
                                "37": 4,
                                "38": 1,
                                "56": 2,
                                "57": 0.5,
                            },
                        },
                    ],
                }
            }
        ]
    }
).encode()


class FakeResponse:
    def __init__(self, payload=ESPN_PAYLOAD, status=200, content_length=None, headers=None):
        self.payload = payload
        self.status = status
        self.content_length = len(payload) if content_length is None else content_length
        self.content = self
        self.headers = headers or {"ETag": "fixture-etag", "Last-Modified": "fixture-date"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def iter_chunked(self, _size):
        yield self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.get = Mock(side_effect=lambda *_args, **_kwargs: self.response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def test_espn_parser_uses_only_raw_season_projection_stats() -> None:
    rows = parse_espn_projection_rows(ESPN_PAYLOAD)

    assert rows == [
        {
            "provider_id": "1",
            "name": "Raw Projection",
            "position": "QB",
            "team": "BUF",
            "raw_projection_stats": {
                "passing_yards": 4_000,
                "passing_touchdowns": 30,
                "passing_40_yard_touchdowns": 5,
                "passing_two_point_conversions": 2,
                "interceptions": 10,
                "rushing_yards": 500,
                "rushing_touchdowns": 5,
                "rushing_two_point_conversions": 1,
                "receptions": 4,
                "receiving_yards": 50,
                "receiving_touchdowns": 1,
                "receiving_two_point_conversions": 1,
                "fumbles_lost": 3,
                "_rushing_100_199_games": 4,
                "_rushing_200_plus_games": 1,
                "_receiving_100_199_games": 2,
                "_receiving_200_plus_games": 0.5,
            },
        }
    ]
    assert "appliedTotal" not in rows[0]["raw_projection_stats"]


def test_espn_parser_discards_inactive_unrostered_and_wrong_projection_rows() -> None:
    def player(
        player_id: int,
        name: str,
        position_id: int,
        *,
        active: bool = True,
        source_id: int = 1,
        split_id: int = 0,
    ) -> dict:
        return {
            "player": {
                "id": player_id,
                "fullName": name,
                "active": active,
                "defaultPositionId": position_id,
                "proTeamId": 2,
                "stats": [
                    {
                        "seasonId": 2026,
                        "statSourceId": source_id,
                        "statSplitTypeId": split_id,
                        "stats": {"3": 100},
                    }
                ],
            }
        }

    missing_season = player(6, "Missing Season Runner", 2)
    del missing_season["player"]["stats"][0]["seasonId"]
    payload = json.dumps(
        {
            "players": [
                player(1, "Eligible Quarterback", 1),
                player(2, "Inactive Runner", 2, active=False),
                player(3, "Unrostered Kicker", 5),
                player(4, "Wrong Source Receiver", 3, source_id=0),
                player(5, "Wrong Split Tight End", 4, split_id=1),
                missing_season,
            ]
        }
    ).encode()

    rows = parse_espn_projection_rows(payload, {"QB", "RB", "WR", "TE", "DEF"})

    assert [row["name"] for row in rows] == ["Eligible Quarterback"]


def test_current_ecr_and_adp_parsers_select_only_the_requested_evidence() -> None:
    ecr = (
        b"page_type,ecr_type,player,id,pos,team,ecr,sd,scrape_date\n"
        b"best-overall,bo,Wrong Board,1,RB,BUF,1,1,2026-08-31\n"
        b"redraft-overall,ro,Right Board,2,RB,BUF,8,2,2026-08-31\n"
    )
    adp = json.dumps(
        {
            "status": "Success",
            "players": [
                {
                    "player_id": 2,
                    "name": "Right Board",
                    "position": "RB",
                    "team": "BUF",
                    "adp": 9.5,
                    "stdev": 1.2,
                }
            ],
        }
    ).encode()

    assert parse_ecr_rows(ecr)[0]["name"] == "Right Board"
    assert parse_ecr_rows(ecr)[0]["ecr"] == 8
    assert parse_ffc_rows(adp)[0]["adp"] == 9.5
    assert ECR_URL.endswith("/files/db_fpecr_latest.csv")
    assert "half-ppr" in FFC_URL and "teams=12" in FFC_URL and "year=2026" in FFC_URL


def test_sleeper_is_identity_and_context_only_and_nflverse_keeps_weekly_yards() -> None:
    sleeper = json.dumps(
        {
            "s1": {
                "full_name": "Context Player",
                "position": "WR",
                "team": "BUF",
                "active": True,
                "status": "Active",
                "depth_chart_order": 1,
                "fantasy_points": 999,
            }
        }
    ).encode()
    adds = json.dumps([{"player_id": "s1", "count": 20}]).encode()
    sleeper_rows = parse_sleeper_rows(sleeper, adds, None)
    assert sleeper_rows[0]["trending_adds"] == 20
    assert "fantasy_points" not in sleeper_rows[0]

    nflverse = (
        b"player_display_name,position,season_type,team,rushing_yards,receiving_yards\n"
        b"Context Player,WR,REG,BUF,0,160\n"
        b"Ignored Player,WR,POST,BUF,0,200\n"
    )
    assert parse_nflverse_rows([(2025, nflverse)]) == [
        {
            "season": 2025,
            "name": "Context Player",
            "position": "WR",
            "team": "BUF",
            "rushing_yards": 0,
            "receiving_yards": 160,
        }
    ]


@pytest.mark.asyncio
async def test_sleeper_source_provenance_includes_trending_freshness() -> None:
    fetched_at = "2026-08-31T20:00:00Z"
    payloads = {
        SLEEPER_PLAYERS_URL: json.dumps(
            {
                "s1": {
                    "full_name": "Context Player",
                    "position": "WR",
                    "team": "BUF",
                    "active": True,
                }
            }
        ).encode(),
        SLEEPER_TRENDING_ADD_URL: b'[{"player_id":"s1","count":5}]',
        SLEEPER_TRENDING_DROP_URL: b"[]",
    }

    async def request(url: str, _cap: int):
        payload = payloads[url]
        return payload, {
            "url": url,
            "fetched_at": fetched_at,
            "sha256": f"checksum-{len(payload)}",
            "bytes": len(payload),
        }

    service = ManualDraftService()
    service._request = AsyncMock(side_effect=request)
    result = await service._sleeper(True)

    assert set(result.source["components"]) == {
        "players",
        "trending_adds",
        "trending_drops",
    }
    assert (
        result.source["components"]["players"]["cache_ttl_seconds"]
        == PROVIDER_TTLS["sleeper_players"]
    )
    assert (
        result.source["components"]["trending_adds"]["cache_ttl_seconds"]
        == PROVIDER_TTLS["sleeper_trending"]
    )
    assert all(value["sha256"] for value in result.source["components"].values())
    freshness = _source_freshness(
        result.source,
        PROVIDER_TTLS["sleeper_players"],
        datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)
        + timedelta(seconds=PROVIDER_TTLS["sleeper_trending"] + 1),
    )
    assert freshness["components"]["players"]["is_stale"] is False
    assert freshness["components"]["trending_adds"]["is_stale"] is True
    assert freshness["is_stale"] is True


@pytest.mark.asyncio
async def test_espn_request_is_fixed_bounded_no_redirect_and_cached() -> None:
    response = FakeResponse()
    session = FakeSession(response)
    session_factory = Mock(return_value=session)
    service = ManualDraftService(session_factory=session_factory, monotonic=Mock(return_value=10.0))

    allowed_positions = {"QB", "RB", "WR", "TE", "DEF"}
    roster_slot_ids = [0, 2, 4, 6, 16]
    first = await service._espn(False, allowed_positions, roster_slot_ids)
    second = await service._espn(False, allowed_positions, roster_slot_ids)

    assert first.rows[0]["name"] == "Raw Projection"
    assert second.source["served_from_cache"] is True
    assert session_factory.call_count == 1
    timeout = session_factory.call_args.kwargs["timeout"]
    assert timeout.total == 12
    player_filter = json.loads(session_factory.call_args.kwargs["headers"]["X-Fantasy-Filter"])[
        "players"
    ]
    assert player_filter["limit"] == MAX_PLAYERS
    assert player_filter["offset"] == 0
    assert player_filter["filterActive"] == {"value": True}
    assert player_filter["filterStatus"] == {"value": ["FREEAGENT", "WAIVERS", "ONTEAM"]}
    assert player_filter["filterSlotIds"] == {"value": roster_slot_ids}
    assert player_filter["filterStatsForSourceIds"] == {"value": [1]}
    assert player_filter["filterStatsForSplitTypeIds"] == {"value": [0]}
    assert player_filter["filterStatsForTopScoringPeriodIds"] == {
        "value": 2,
        "additionalValue": ["102026"],
    }
    assert player_filter["sortAppliedStatTotal"] == {
        "sortPriority": 1,
        "sortAsc": False,
        "value": "102026",
    }
    assert 17 not in player_filter["filterSlotIds"]["value"]
    assert session.get.call_args.args == (ESPN_URL,)
    assert session.get.call_args.kwargs["allow_redirects"] is False
    assert PROVIDER_CAPS["espn"] == 2 * 1024 * 1024


@pytest.mark.asyncio
async def test_transport_rejects_redirects_oversize_and_non_allowlisted_urls() -> None:
    redirect = ManualDraftService(
        session_factory=Mock(return_value=FakeSession(FakeResponse(status=302)))
    )
    with pytest.raises(ProviderError, match="redirect"):
        await redirect._request(ESPN_URL, 1_000_000)

    oversized = ManualDraftService(
        session_factory=Mock(
            return_value=FakeSession(FakeResponse(payload=b"{}", content_length=101))
        )
    )
    with pytest.raises(ProviderError, match="exceeded 100 bytes"):
        await oversized._request(ESPN_URL, 100)

    with pytest.raises(ProviderError, match="allowlist"):
        await oversized._request("https://example.com/not-allowed", 100)


@pytest.mark.asyncio
async def test_nflverse_follows_only_one_trusted_bounded_github_asset_redirect() -> None:
    asset_url = (
        "https://release-assets.githubusercontent.com/github-production-release-asset/"
        "452908115/fixture?signature=bounded"
    )
    redirect = FakeResponse(status=302, headers={"Location": asset_url})
    asset = FakeResponse(payload=b"weekly-history", headers={"ETag": "history"})
    session = FakeSession(redirect)
    session.get = Mock(side_effect=[redirect, asset])
    service = ManualDraftService(session_factory=Mock(return_value=session))
    canonical_url = NFLVERSE_URL_TEMPLATE.format(season=2025)

    payload, source = await service._request(canonical_url, 100)

    assert payload == b"weekly-history"
    assert source["url"] == canonical_url
    assert source["trusted_redirect_host"] == "release-assets.githubusercontent.com"
    assert session.get.call_args_list[0].args == (canonical_url,)
    assert session.get.call_args_list[1].args == (asset_url,)
    assert all(call.kwargs["allow_redirects"] is False for call in session.get.call_args_list)
