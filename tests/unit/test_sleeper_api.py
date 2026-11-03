"""Unit tests for credential-free Sleeper helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from sleeper_api import SleeperAPI


@pytest.mark.asyncio
async def test_position_rankings_preserve_sleeper_player_id(monkeypatch):
    api = SleeperAPI()
    monkeypatch.setattr(
        api,
        "get_all_players",
        AsyncMock(
            return_value={
                "1234": {
                    "player_id": "1234",
                    "full_name": "Test Quarterback",
                    "team": "BUF",
                    "position": "QB",
                    "active": True,
                    "search_rank": 1,
                }
            }
        ),
    )

    rankings = await api.get_position_rankings("QB")

    assert rankings[0]["player_id"] == "1234"


@pytest.mark.asyncio
async def test_real_projection_is_labeled_with_sleeper_api_provenance(monkeypatch):
    api = SleeperAPI()
    monkeypatch.setattr(
        api,
        "_make_request",
        AsyncMock(return_value={"1234": {"pts": 18.5}}),
    )
    monkeypatch.setattr(
        api,
        "get_all_players",
        AsyncMock(
            return_value={
                "1234": {
                    "first_name": "Test",
                    "last_name": "Quarterback",
                    "team": "BUF",
                    "position": "QB",
                }
            }
        ),
    )

    projections = await api.get_projections(2026, 1)

    assert projections["1234"]["projection_source"] == "sleeper_api"


@pytest.mark.asyncio
async def test_weekly_stats_normalize_real_nested_rows_and_preserve_zero_negative(monkeypatch):
    api = SleeperAPI()
    request = AsyncMock(
        return_value=[
            {
                "player_id": "421",
                "season": "2026",
                "week": 8,
                "season_type": "regular",
                "opponent": "LAC",
                "company": "sportradar",
                "stats": {"pts_std": -1.5, "pts_ppr": -1.5, "pass_int": 3},
            },
            {"player_id": "8161", "stats": {"pts_std": 0.0, "pts_ppr": 0.0}},
            {"player_id": "empty", "stats": {}},
            {"player_id": "wrong_week", "week": 7, "stats": {"pts_std": 25}},
            {"player_id": "wrong_season", "season": "2025", "stats": {"pts_std": 25}},
        ]
    )
    monkeypatch.setattr(api, "_make_request", request)

    stats = await api.get_player_stats(2026, 8)

    request.assert_awaited_once_with(
        "https://api.sleeper.app/stats/nfl/2026/8?season_type=regular", use_cache=True
    )
    assert set(stats) == {"421", "8161"}
    assert stats["421"]["pts"] == -1.5
    assert stats["421"]["pass_int"] == 3
    assert stats["421"]["opponent"] == "LAC"
    assert stats["421"]["company"] == "sportradar"
    assert stats["421"]["week"] == 8
    assert stats["8161"]["pts"] == 0.0


@pytest.mark.asyncio
async def test_projections_accept_current_nested_points_without_legacy_pts(monkeypatch):
    api = SleeperAPI()
    monkeypatch.setattr(
        api,
        "_make_request",
        AsyncMock(
            return_value=[
                {
                    "player_id": "421",
                    "season": "2026",
                    "week": 9,
                    "opponent": "WAS",
                    "company": "rotowire",
                    "updated_at": 1793725859907,
                    "stats": {"pts_std": 18.51, "pts_half_ppr": 18.51, "pass_yd": 270.41},
                },
                {"player_id": "zero", "stats": {"pts_std": 0.0}},
            ]
        ),
    )
    monkeypatch.setattr(api, "get_all_players", AsyncMock(return_value={}))
    fallback = AsyncMock()
    monkeypatch.setattr(api, "_create_fallback_projections", fallback)

    projections = await api.get_projections(2026, 9)

    fallback.assert_not_awaited()
    assert projections["421"]["pts"] == 18.51
    assert projections["421"]["pts_half_ppr"] == 18.51
    assert projections["421"]["projection_source"] == "sleeper_api"
    assert projections["421"]["opponent"] == "WAS"
    assert projections["421"]["company"] == "rotowire"
    assert projections["421"]["updated_at"] == 1793725859907
    assert projections["zero"]["pts"] == 0.0


@pytest.mark.asyncio
async def test_legacy_empty_weekly_dict_does_not_become_zero_actuals(monkeypatch):
    api = SleeperAPI()
    monkeypatch.setattr(api, "_make_request", AsyncMock(return_value={"421": {}, "8161": {}}))
    assert await api.get_player_stats(2026, 8) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["fallback_ranking", None])
async def test_expert_advice_never_presents_ranking_fallback_as_projection(monkeypatch, source):
    api = SleeperAPI()
    monkeypatch.setattr(
        api,
        "get_player_by_name",
        AsyncMock(return_value={"player_id": "8161", "position": "QB", "team": "MIA"}),
    )
    monkeypatch.setattr(
        api,
        "get_projections",
        AsyncMock(return_value={"8161": {"pts": 30.0, "projection_source": source}}),
    )
    monkeypatch.setattr("sleeper_api.get_current_season", AsyncMock(return_value=2026))
    trending = AsyncMock()
    monkeypatch.setattr(api, "_get_trending_factor", trending)

    advice = await api.get_expert_advice("Malik Willis", week=9)

    assert advice["projection"] is None
    assert advice["confidence"] == 0
    assert advice["recommendation"] == "Monitor"
    assert "projects for" not in advice["advice"]
    trending.assert_not_awaited()


@pytest.mark.asyncio
async def test_sleeper_requests_have_bounded_timeout_and_use_environment_proxy(monkeypatch):
    api = SleeperAPI()
    response = AsyncMock()
    response.status = 200
    response.json.return_value = []
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    monkeypatch.setattr("sleeper_api.aiohttp.ClientSession", session_factory)

    assert await api._make_request("players/nfl", use_cache=False) == []

    kwargs = session_factory.call_args.kwargs
    assert kwargs["trust_env"] is True
    assert kwargs["timeout"].total == 15
    assert kwargs["timeout"].connect == 5


@pytest.mark.asyncio
async def test_sleeper_request_errors_remain_recoverable(monkeypatch):
    api = SleeperAPI()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr("sleeper_api.aiohttp.ClientSession", session_factory)

    assert await api._make_request("state/nfl", use_cache=False) is None


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), 10**400, True])
@pytest.mark.asyncio
async def test_nonfinite_or_boolean_totals_never_become_source_projections(monkeypatch, invalid):
    api = SleeperAPI()
    monkeypatch.setattr(
        api, "_make_request", AsyncMock(return_value={"A": {"stats": {"pts_std": invalid}}})
    )
    fallback = AsyncMock(return_value={})
    monkeypatch.setattr(api, "_create_fallback_projections", fallback)

    assert await api.get_projections(2026, 9) == {}
    fallback.assert_awaited_once()


@pytest.mark.parametrize(
    "raw",
    [
        {"A": {"player_id": "B", "stats": {"pts_std": 10}}},
        [{"player_id": "A", "stats": {"player_id": "B", "pts_std": 10}}],
        [{"player_id": "A", "stats": {"season": 2025, "pts_std": 10}}],
        [{"player_id": "A", "stats": {"week": 8, "pts_std": 10}}],
        [{"player_id": "A", "stats": {"season_type": "post", "pts_std": 10}}],
    ],
)
def test_conflicting_identity_or_nested_period_is_not_relabelled(raw):
    assert SleeperAPI._normalize_weekly_data(raw, season=2026, week=9, source_url="synthetic") == {}


def test_duplicate_conflicting_ids_fail_closed_but_identical_rows_are_deduplicated():
    first = {"player_id": "A", "stats": {"pts_std": 10}}
    second = {"player_id": "A", "stats": {"pts_std": 20}}
    assert (
        SleeperAPI._normalize_weekly_data(
            [first, second, first], season=2026, week=9, source_url="synthetic"
        )
        == {}
    )
    identical = SleeperAPI._normalize_weekly_data(
        [first, dict(first)], season=2026, week=9, source_url="synthetic"
    )
    assert identical["A"]["pts"] == 10


def test_normalization_preserves_valid_format_when_another_format_is_nonfinite():
    normalized = SleeperAPI._normalize_weekly_data(
        {"A": {"stats": {"pts_std": float("nan"), "pts_ppr": 15, "pass_yd": float("inf")}}},
        season=2026,
        week=9,
        source_url="synthetic",
    )
    assert normalized["A"]["pts_ppr"] == 15
    assert "pts_std" not in normalized["A"]
    assert "pts" not in normalized["A"]
    assert "pass_yd" not in normalized["A"]


@pytest.mark.parametrize("scoring_format", ["standard", "custom", "unknown"])
@pytest.mark.asyncio
async def test_ppr_only_projection_is_not_zero_or_a_custom_league_forecast(
    monkeypatch, scoring_format
):
    api = SleeperAPI()
    monkeypatch.setattr(
        api,
        "get_player_by_name",
        AsyncMock(return_value={"player_id": "A", "position": "WR", "team": "BUF"}),
    )
    monkeypatch.setattr(
        api,
        "get_projections",
        AsyncMock(return_value={"A": {"projection_source": "sleeper_api", "pts_ppr": 15}}),
    )
    monkeypatch.setattr("sleeper_api.get_current_season", AsyncMock(return_value=2026))
    trending = AsyncMock()
    monkeypatch.setattr(api, "_get_trending_factor", trending)

    advice = await api.get_expert_advice("Synthetic", week=9, scoring_format=scoring_format)

    assert advice["projection"] is None
    assert advice["recommendation"] == "Monitor"
    assert advice["confidence"] == 0
    assert "projects for" not in advice["advice"]
    trending.assert_not_awaited()


@pytest.mark.parametrize(
    "scoring_format,totals,expected",
    [
        ("standard", {"pts_std": 0, "pts_ppr": 15}, 0),
        ("standard", {"pts_std": -2}, -2),
        ("ppr", {"pts_std": 8, "pts_ppr": 15}, 15),
        ("half-ppr", {"pts_std": 8, "pts_half_ppr": 11.5}, 11.5),
    ],
)
@pytest.mark.asyncio
async def test_expert_advice_uses_requested_finite_scoring_format(
    monkeypatch, scoring_format, totals, expected
):
    api = SleeperAPI()
    monkeypatch.setattr(
        api,
        "get_player_by_name",
        AsyncMock(return_value={"player_id": "A", "position": "WR", "team": "BUF"}),
    )
    monkeypatch.setattr(
        api,
        "get_projections",
        AsyncMock(return_value={"A": {"projection_source": "sleeper_api", **totals}}),
    )
    monkeypatch.setattr("sleeper_api.get_current_season", AsyncMock(return_value=2026))
    monkeypatch.setattr(api, "_get_trending_factor", AsyncMock(return_value=1))
    monkeypatch.setattr("matchup_analyzer.MatchupAnalyzer.load_defensive_rankings", AsyncMock())
    monkeypatch.setattr(
        "matchup_analyzer.MatchupAnalyzer.get_matchup_score", lambda *_args: (50, "synthetic")
    )

    advice = await api.get_expert_advice("Synthetic", week=9, scoring_format=scoring_format)

    assert advice["projection"] == expected
    assert advice["projection_source"] == "sleeper_api"
    assert advice["scoring_format"] == scoring_format.replace("-", "_")
