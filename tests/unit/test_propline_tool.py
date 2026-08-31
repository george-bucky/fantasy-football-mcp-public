"""Contract tests for the PropLine sportsbook odds MCP tool."""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

import fantasy_football_multi_league as legacy_server
import fastmcp_server
from src.handlers.analytics_handlers import handle_ff_get_sportsbook_odds
from src.handlers.draft_handlers import handle_ff_get_draft_recommendation
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
async def test_draft_sportsbook_contract_is_aligned_and_delegates():
    legacy_tools = {tool.name: tool for tool in await legacy_server.list_tools()}
    schema = legacy_tools["ff_get_draft_recommendation"].inputSchema

    assert fastmcp_server.ff_get_draft_recommendation.parameters == schema
    assert schema["properties"]["include_sportsbook_odds"] == {
        "type": "boolean",
        "default": False,
        "description": "Opt in to attributed PropLine context for the final draft shortlist",
    }
    assert schema["properties"]["sportsbook_scope"]["enum"] == [
        "auto",
        "season",
        "next_game",
    ]
    assert schema["properties"]["sportsbook_shortlist_size"]["minimum"] == 1
    assert schema["properties"]["sportsbook_shortlist_size"]["maximum"] == 5

    expected = {"status": "success", "recommendations": []}
    with patch.object(
        fastmcp_server,
        "_call_legacy_tool",
        AsyncMock(return_value=expected),
    ) as call_legacy:
        result = await fastmcp_server.ff_get_draft_recommendation.fn(
            None,
            league_key="league.test",
            include_sportsbook_odds=True,
            sportsbook_scope="season",
            sportsbook_shortlist_size=3,
        )

    assert result == expected
    call_legacy.assert_awaited_once_with(
        "ff_get_draft_recommendation",
        ctx=None,
        league_key="league.test",
        strategy="balanced",
        num_recommendations=10,
        current_pick=None,
        use_rookie_intelligence=False,
        rookie_only=False,
        include_sportsbook_odds=True,
        sportsbook_scope="season",
        sportsbook_shortlist_size=3,
    )


@pytest.mark.asyncio
async def test_draft_handler_threads_sportsbook_arguments_into_recommendation_flow():
    expected = {"status": "success", "recommendations": []}
    with patch(
        "src.handlers.draft_handlers.get_draft_recommendation_simple",
        AsyncMock(return_value=expected),
    ) as recommend:
        result = await handle_ff_get_draft_recommendation(
            {
                "league_key": "league.test",
                "include_sportsbook_odds": True,
                "sportsbook_scope": "next_game",
                "sportsbook_shortlist_size": 4,
            }
        )

    assert result == expected
    recommend.assert_awaited_once_with(
        "league.test",
        "balanced",
        10,
        None,
        False,
        False,
        True,
        "next_game",
        4,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("shortlist_size", [0, 6, True, 2.5])
async def test_draft_handler_rejects_invalid_sportsbook_shortlist_size(shortlist_size):
    with patch(
        "src.handlers.draft_handlers.get_draft_recommendation_simple",
        AsyncMock(),
    ) as recommend:
        result = await handle_ff_get_draft_recommendation(
            {
                "league_key": "league.test",
                "sportsbook_shortlist_size": shortlist_size,
            }
        )

    assert result == {"error": "sportsbook_shortlist_size must be an integer between 1 and 5"}
    recommend.assert_not_awaited()


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
