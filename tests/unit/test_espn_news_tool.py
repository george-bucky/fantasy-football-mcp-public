"""Contract tests for the ESPN NFL news MCP tool."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import fantasy_football_multi_league as legacy_server
import fastmcp_server
from src.handlers.analytics_handlers import handle_ff_get_espn_nfl_news


@pytest.mark.asyncio
async def test_espn_handler_delegates_optional_filters():
    expected = {"status": "success", "count": 1, "items": []}
    with patch(
        "src.handlers.analytics_handlers.get_espn_nfl_news",
        AsyncMock(return_value=expected),
    ) as get_news:
        result = await handle_ff_get_espn_nfl_news(
            {"players": ["Josh Allen"], "limit": 1}
        )

    assert result == expected
    get_news.assert_awaited_once_with(players=["Josh Allen"], limit=1)


@pytest.mark.asyncio
async def test_espn_handler_returns_safe_error():
    with patch(
        "src.handlers.analytics_handlers.get_espn_nfl_news",
        AsyncMock(side_effect=RuntimeError("ESPN NFL news request failed")),
    ):
        result = await handle_ff_get_espn_nfl_news({})

    assert result == {
        "status": "error",
        "source": "ESPN NFL News API",
        "error": "ESPN NFL news request failed",
    }


@pytest.mark.asyncio
async def test_legacy_server_lists_and_dispatches_espn_tool():
    tools = {tool.name: tool for tool in await legacy_server.list_tools()}
    tool = tools["ff_get_espn_nfl_news"]
    assert tool.inputSchema["properties"]["limit"]["maximum"] == 10
    assert "players" not in tool.inputSchema.get("required", [])

    handler = AsyncMock(return_value={"status": "success", "count": 0, "items": []})
    with patch.dict(legacy_server.TOOL_HANDLERS, {"ff_get_espn_nfl_news": handler}):
        content = await legacy_server.call_tool("ff_get_espn_nfl_news", {"limit": 2})

    assert json.loads(content[0].text)["status"] == "success"
    handler.assert_awaited_once_with({"limit": 2})


@pytest.mark.asyncio
async def test_fastmcp_wrapper_delegates_to_legacy_tool():
    expected = {"status": "success", "count": 0, "items": []}
    with patch.object(
        fastmcp_server,
        "_call_legacy_tool",
        AsyncMock(return_value=expected),
    ) as call_legacy:
        result = await fastmcp_server.ff_get_espn_nfl_news.fn(
            None, players=["Lamar Jackson"], limit=3
        )

    assert result == expected
    call_legacy.assert_awaited_once_with(
        "ff_get_espn_nfl_news",
        ctx=None,
        players=["Lamar Jackson"],
        limit=3,
    )
