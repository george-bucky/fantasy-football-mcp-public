"""Contract tests for the Yahoo-free manual draft tool."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

import fantasy_football_multi_league as legacy_server
import fastmcp_server
from src.services.manual_draft_service import MANUAL_DRAFT_INPUT_SCHEMA, manual_draft_service

GOTHAM_PROFILE = {
    "profile_id": "gotham-2026",
    "season": 2026,
    "team_count": 12,
    "draft": {"type": "snake", "slot": 11},
    "roster_slots": {
        "QB": 1,
        "RB": 2,
        "WR": 2,
        "TE": 1,
        "W/R/T": 2,
        "DEF": 1,
        "BN": 5,
    },
    "scoring": {"receptions": 0.5, "passing_touchdowns": 4},
}


@pytest.mark.asyncio
async def test_both_active_entrypoints_advertise_the_same_profile_schema() -> None:
    legacy_tools = {tool.name: tool for tool in await legacy_server.list_tools()}

    assert legacy_tools["ff_prepare_manual_draft"].inputSchema == MANUAL_DRAFT_INPUT_SCHEMA
    assert fastmcp_server.ff_prepare_manual_draft.parameters == MANUAL_DRAFT_INPUT_SCHEMA
    profile = MANUAL_DRAFT_INPUT_SCHEMA["properties"]["profile"]
    assert set(profile["required"]) == {"team_count", "draft", "roster_slots", "scoring"}
    assert MANUAL_DRAFT_INPUT_SCHEMA["required"] == ["profile"]


@pytest.mark.asyncio
async def test_both_entrypoints_prepare_without_calling_yahoo(monkeypatch) -> None:
    for name in (
        "YAHOO_CLIENT_ID",
        "YAHOO_CLIENT_SECRET",
        "YAHOO_ACCESS_TOKEN",
        "YAHOO_REFRESH_TOKEN",
        "YAHOO_GUID",
    ):
        monkeypatch.delenv(name, raising=False)
    expected = {
        "status": "success",
        "readiness": "ready_with_warnings",
        "profile_id": "gotham-2026",
        "snapshot_id": "manual-draft-test",
        "board_count": 1,
        "board_preview": [{"name": "Example Player", "base_board_score": 80}],
        "warnings": ["example secondary provider unavailable"],
    }
    yahoo_call = AsyncMock(side_effect=AssertionError("Yahoo must not be called"))
    prepare = AsyncMock(return_value=expected)

    with (
        patch.object(legacy_server, "yahoo_api_call", yahoo_call),
        patch.object(manual_draft_service, "prepare", prepare),
    ):
        legacy_content = await legacy_server.call_tool(
            "ff_prepare_manual_draft",
            {"profile": deepcopy(GOTHAM_PROFILE), "preview_limit": 10},
        )
        fast_result = await fastmcp_server.ff_prepare_manual_draft.fn(
            None,
            profile=deepcopy(GOTHAM_PROFILE),
            preview_limit=10,
        )

    assert json.loads(legacy_content[0].text) == expected
    assert fast_result == expected
    assert prepare.await_count == 2
    assert prepare.await_args_list[0].kwargs == {
        "profile": GOTHAM_PROFILE,
        "preview_limit": 10,
        "force_refresh": False,
    }
    yahoo_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_fastmcp_forwards_force_refresh_without_changing_the_profile() -> None:
    expected = {"status": "success", "readiness": "ready", "board_preview": []}
    with patch.object(
        fastmcp_server,
        "_call_legacy_tool",
        AsyncMock(return_value=expected),
    ) as call_legacy:
        result = await fastmcp_server.ff_prepare_manual_draft.fn(
            None,
            profile=deepcopy(GOTHAM_PROFILE),
            preview_limit=5,
            force_refresh=True,
        )

    assert result == expected
    call_legacy.assert_awaited_once_with(
        "ff_prepare_manual_draft",
        ctx=None,
        profile=GOTHAM_PROFILE,
        preview_limit=5,
        force_refresh=True,
    )


@pytest.mark.asyncio
async def test_fastmcp_progress_message_is_credential_free() -> None:
    context = AsyncMock()
    response = fastmcp_server.TextContent(type="text", text='{"status":"success"}')
    with patch.object(fastmcp_server, "_legacy_call_tool", AsyncMock(return_value=[response])):
        result = await fastmcp_server._call_legacy_tool(
            "ff_prepare_manual_draft", ctx=context, profile=GOTHAM_PROFILE
        )

    assert result == {"status": "success"}
    context.info.assert_awaited_once_with("Calling credential-free tool: ff_prepare_manual_draft")
