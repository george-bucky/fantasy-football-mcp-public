import json
from typing import Any, Dict

import pytest

import fastmcp_server


class DummyResponse:
    """Simple helper that mimics :class:`mcp.types.TextContent`."""

    def __init__(self, payload: Dict[str, Any]):
        self.text = json.dumps(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("func_name", "kwargs", "expected_name", "expected_arguments"),
    [
        ("ff_get_leagues", {}, "ff_get_leagues", {}),
        ("ff_get_league_info", {"league_key": "123"}, "ff_get_league_info", {"league_key": "123"}),
        ("ff_get_standings", {"league_key": "123"}, "ff_get_standings", {"league_key": "123"}),
        ("ff_get_roster", {"league_key": "123"}, "ff_get_roster", {"league_key": "123"}),
        ("ff_get_matchup", {"league_key": "123"}, "ff_get_matchup", {"league_key": "123"}),
        (
            "ff_get_players",
            {"league_key": "123"},
            "ff_get_players",
            {"league_key": "123", "count": 10},
        ),
        (
            "ff_compare_teams",
            {"league_key": "123", "team_key_a": "a", "team_key_b": "b"},
            "ff_compare_teams",
            {"league_key": "123", "team_key_a": "a", "team_key_b": "b"},
        ),
        (
            "ff_get_optimal_lineup",
            {"league_key": "123"},
            "ff_get_optimal_lineup",
            {"league_key": "123", "strategy": "balanced"},
        ),
        ("ff_get_api_status", {}, "ff_get_api_status", {}),
        ("ff_clear_cache", {}, "ff_clear_cache", {}),
        ("ff_get_draft_results", {"league_key": "123"}, "ff_get_draft_results", {"league_key": "123"}),
        (
            "ff_get_waiver_wire",
            {"league_key": "123"},
            "ff_get_waiver_wire",
            {"league_key": "123", "sort": "rank", "count": 20},
        ),
        (
            "ff_get_draft_rankings",
            {},
            "ff_get_draft_rankings",
            {"position": "all", "count": 50},
        ),
        (
            "ff_get_draft_recommendation",
            {"league_key": "123"},
            "ff_get_draft_recommendation",
            {"league_key": "123", "strategy": "balanced", "num_recommendations": 10},
        ),
        (
            "ff_analyze_draft_state",
            {"league_key": "123"},
            "ff_analyze_draft_state",
            {"league_key": "123", "strategy": "balanced"},
        ),
        (
            "ff_analyze_reddit_sentiment",
            {"players": ["Player"]},
            "ff_analyze_reddit_sentiment",
            {"players": ["Player"], "time_window_hours": 48},
        ),
    ],
)
async def test_tool_wrappers_delegate_to_legacy(monkeypatch, func_name, kwargs, expected_name, expected_arguments):
    captured: Dict[str, Any] = {}

    async def fake_call(name: str, arguments: Dict[str, Any]):
        captured["name"] = name
        captured["arguments"] = arguments
        return [DummyResponse({"ok": name, "arguments": arguments})]

    monkeypatch.setattr(fastmcp_server, "_legacy_call_tool", fake_call)

    tool_fn = getattr(fastmcp_server, func_name)
    result = await tool_fn.fn(None, **kwargs)

    assert captured["name"] == expected_name
    assert captured["arguments"] == expected_arguments
    assert result["ok"] == expected_name


@pytest.mark.asyncio
async def test_refresh_token_delegates_to_legacy(monkeypatch):
    async def fake_refresh() -> Dict[str, Any]:
        return {"status": "success"}

    monkeypatch.setattr(fastmcp_server, "_legacy_refresh_token", fake_refresh)

    result = await fastmcp_server.ff_refresh_token.fn(None)

    assert result == {"status": "success"}


@pytest.mark.asyncio
async def test_call_legacy_tool_handles_non_json(monkeypatch):
    async def fake_call(name: str, arguments: Dict[str, Any]):
        return [type("T", (), {"text": "not-json"})()]

    monkeypatch.setattr(fastmcp_server, "_legacy_call_tool", fake_call)

    payload = await fastmcp_server.ff_get_leagues.fn(None)

    assert payload["status"] == "error"
    assert payload["tool"] == "ff_get_leagues"


@pytest.mark.parametrize("tool_name", sorted(fastmcp_server._TOOL_PROMPTS))
def test_tools_include_prompt_metadata(tool_name: str) -> None:
    tool = getattr(fastmcp_server, tool_name)
    assert tool.meta is not None
    assert tool.meta["prompt"] == fastmcp_server._TOOL_PROMPTS[tool_name]


def test_run_http_server_uses_environment(monkeypatch):
    captured: Dict[str, Any] = {}

    def fake_run(transport: str, **kwargs: Any) -> None:
        captured["transport"] = transport
        captured["kwargs"] = kwargs

    monkeypatch.setattr(fastmcp_server.server, "run", fake_run)
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9000")

    fastmcp_server.run_http_server()

    assert captured["transport"] == "http"
    assert captured["kwargs"] == {"host": "127.0.0.1", "port": 9000, "show_banner": True}
