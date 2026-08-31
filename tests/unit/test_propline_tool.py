"""Contract tests for the PropLine sportsbook odds MCP tool."""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

import fantasy_football_multi_league as legacy_server
import fastmcp_server
from src.handlers.analytics_handlers import handle_ff_get_sportsbook_odds
from src.services.propline_service import SPORTSBOOK_ODDS_INPUT_SCHEMA, propline_service


@pytest.mark.asyncio
async def test_propline_handler_forwards_arguments_and_defaults():
    expected = {"status": "ok", "results": []}
    with patch(
        "src.handlers.analytics_handlers.get_sportsbook_odds",
        AsyncMock(return_value=expected),
    ) as get_odds:
        result = await handle_ff_get_sportsbook_odds(
            {
                "players": ["Josh Allen"],
                "teams": ["BUF"],
                "markets": ["player_pass_yds"],
                "bookmakers": ["draftkings"],
            }
        )

    assert result == expected
    get_odds.assert_awaited_once_with(
        players=["Josh Allen"],
        teams=["BUF"],
        scope="auto",
        markets=["player_pass_yds"],
        bookmakers=["draftkings"],
    )


@pytest.mark.asyncio
async def test_legacy_server_advertises_shared_schema_and_dispatches_tool():
    tools = {tool.name: tool for tool in await legacy_server.list_tools()}
    tool = tools["ff_get_sportsbook_odds"]

    assert tool.inputSchema == SPORTSBOOK_ODDS_INPUT_SCHEMA
    assert tool.inputSchema["anyOf"] == [
        {"required": ["players"]},
        {"required": ["teams"]},
    ]
    assert tool.inputSchema["properties"]["scope"] == {
        "type": "string",
        "enum": ["auto", "season", "next_game"],
        "default": "auto",
    }
    for field in ("players", "teams"):
        assert tool.inputSchema["properties"][field]["minItems"] == 1
        assert tool.inputSchema["properties"][field]["maxItems"] == 10
        assert tool.inputSchema["properties"][field]["items"]["maxLength"] == 100
    for field in ("markets", "bookmakers"):
        field_schema = tool.inputSchema["properties"][field]
        assert field_schema["maxItems"] == 10
        assert field_schema["uniqueItems"] is True
        assert field_schema["items"]["pattern"] == "^[a-z0-9_]+$"
        assert field_schema["items"]["maxLength"] == 64

    handler = AsyncMock(return_value={"status": "ok", "results": []})
    arguments = {"teams": ["BUF"], "scope": "next_game"}
    with patch.dict(legacy_server.TOOL_HANDLERS, {"ff_get_sportsbook_odds": handler}):
        content = await legacy_server.call_tool("ff_get_sportsbook_odds", arguments)

    assert json.loads(content[0].text) == {"status": "ok", "results": []}
    handler.assert_awaited_once_with(arguments)


@pytest.mark.asyncio
async def test_fastmcp_advertises_identical_schema_and_forwards_defaults():
    legacy_tools = {tool.name: tool for tool in await legacy_server.list_tools()}

    assert (
        fastmcp_server.ff_get_sportsbook_odds.parameters
        == legacy_tools["ff_get_sportsbook_odds"].inputSchema
    )

    expected = {"status": "ok", "results": []}
    with patch.object(
        fastmcp_server,
        "_call_legacy_tool",
        AsyncMock(return_value=expected),
    ) as call_legacy:
        result = await fastmcp_server.ff_get_sportsbook_odds.fn(
            None,
            players=["Josh Allen"],
        )

    assert result == expected
    call_legacy.assert_awaited_once_with(
        "ff_get_sportsbook_odds",
        ctx=None,
        players=["Josh Allen"],
        teams=None,
        scope="auto",
        markets=None,
        bookmakers=None,
    )


@pytest.mark.asyncio
async def test_missing_key_through_both_entrypoints_never_opens_http_session(monkeypatch):
    monkeypatch.delenv("PROPLINE_API_KEY", raising=False)
    session_factory = Mock(side_effect=AssertionError("HTTP session must not be opened"))
    monkeypatch.setattr(propline_service, "_session_factory", session_factory)

    content = await legacy_server.call_tool(
        "ff_get_sportsbook_odds",
        {"players": ["Josh Allen"]},
    )
    fastmcp_response = await fastmcp_server.ff_get_sportsbook_odds.fn(
        None,
        players=["Josh Allen"],
    )

    response = json.loads(content[0].text)
    assert response["status"] == "error"
    assert response["provider"] == "propline"
    assert response["error"] == {
        "code": "not_configured",
        "message": "PROPLINE_API_KEY is not configured",
        "stage": "configuration",
    }
    assert fastmcp_response["status"] == "error"
    assert fastmcp_response["provider"] == "propline"
    assert fastmcp_response["error"] == response["error"]
    session_factory.assert_not_called()
