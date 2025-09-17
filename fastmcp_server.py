from __future__ import annotations

"""FastMCP-compatible fantasy football server entry point.

This module wraps the existing Yahoo Fantasy Football tooling defined in
``fantasy_football_multi_league`` and exposes it through the FastMCP
``@server.tool`` decorator so it can be deployed on fastmcp.cloud.
"""

import json
import os
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Sequence

from fastmcp import Context, FastMCP
from mcp.types import TextContent

import fantasy_football_multi_league

LegacyCallFn = Callable[[str, Dict[str, Any]], Awaitable[Sequence[TextContent]]]

_legacy_call_tool: LegacyCallFn = fantasy_football_multi_league.call_tool
_legacy_refresh_token = fantasy_football_multi_league.refresh_yahoo_token

server = FastMCP(
    name="fantasy-football",
    instructions=(
        "Yahoo Fantasy Football operations including league discovery, roster "
        "analysis, waiver insights, draft tools, and Reddit sentiment checks. "
        "Set the YAHOO_* environment variables before starting the server."
    ),
)

_TOOL_PROMPTS: Dict[str, str] = {
    "ff_get_leagues": (
        "List the Yahoo fantasy football leagues available to the connected "
        "manager so you can collect league_key identifiers before other calls."
    ),
    "ff_get_league_info": (
        "Summarize configuration, scoring, and team context for a specific "
        "Yahoo league when you already know the league_key."
    ),
    "ff_get_standings": (
        "Check the current rankings, records, and points totals for every team "
        "in a league to answer questions about standings."
    ),
    "ff_get_roster": (
        "Inspect the players, positions, and statuses for either the "
        "authenticated roster or another team within a league."
    ),
    "ff_get_matchup": (
        "Look up the opponent, projected points, and matchup details for a "
        "given week in the authenticated manager's league schedule."
    ),
    "ff_get_players": (
        "Research free agents or player pools for waiver pickups by filtering "
        "Yahoo players by position and limiting the result count."
    ),
    "ff_compare_teams": (
        "Contrast two league rosters side-by-side to evaluate trades or matchup "
        "advantages. Provide both Yahoo team keys."
    ),
    "ff_get_optimal_lineup": (
        "Generate a recommended starting lineup for the authenticated team, "
        "optionally targeting a conservative, balanced, or aggressive strategy."
    ),
    "ff_refresh_token": (
        "Refresh the stored Yahoo OAuth access token when API responses start "
        "failing with authentication errors."
    ),
    "ff_get_api_status": (
        "Diagnose API availability by checking rate-limit usage, cache status, "
        "and other service health metrics."
    ),
    "ff_clear_cache": (
        "Clear cached Yahoo responses to force the next call to fetch fresh "
        "data. Optionally specify a pattern to target certain entries."
    ),
    "ff_get_draft_results": (
        "Retrieve the draft board and pick summaries for every team in a league "
        "after the draft has completed."
    ),
    "ff_get_waiver_wire": (
        "List waiver-wire candidates sorted by rank, points, or trends to aid "
        "mid-season roster moves."
    ),
    "ff_get_draft_rankings": (
        "Access Yahoo pre-draft rankings and ADP information for planning "
        "upcoming drafts, filtered by position if desired."
    ),
    "ff_get_draft_recommendation": (
        "Recommend players to draft at the current or upcoming pick based on "
        "your strategy and league context."
    ),
    "ff_analyze_draft_state": (
        "Evaluate the evolving draft board for your team to highlight "
        "positional needs and strategy adjustments."
    ),
    "ff_analyze_reddit_sentiment": (
        "Summarize recent Reddit sentiment and engagement around one or more "
        "players to complement scouting insights."
    ),
}


def _tool_meta(name: str) -> Dict[str, str]:
    """Helper to attach consistent prompt metadata to each tool."""

    return {"prompt": _TOOL_PROMPTS[name]}


async def _call_legacy_tool(
    name: str,
    *,
    ctx: Context | None = None,
    **arguments: Any,
) -> Dict[str, Any]:
    """Delegate to the legacy MCP tool implementation and parse its JSON payload."""

    filtered_args = {key: value for key, value in arguments.items() if value is not None}

    if ctx is not None:
        await ctx.info(f"Calling legacy Yahoo tool: {name}")

    responses = await _legacy_call_tool(name=name, arguments=filtered_args)

    if not responses:
        return {
            "status": "error",
            "message": "Legacy tool returned no response",
            "tool": name,
            "arguments": filtered_args,
        }

    first = responses[0]
    payload = getattr(first, "text", "")

    if not payload:
        return {
            "status": "error",
            "message": "Legacy tool returned an empty payload",
            "tool": name,
            "arguments": filtered_args,
        }

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {
            "status": "error",
            "message": "Could not parse legacy response as JSON",
            "tool": name,
            "arguments": filtered_args,
            "raw": payload,
        }


@server.tool(
    name="ff_get_leagues",
    description=(
        "Discover all Yahoo fantasy football leagues linked to the current "
        "credentials. Use this before other calls to obtain league keys."
    ),
    meta=_tool_meta("ff_get_leagues"),
)
async def ff_get_leagues(ctx: Context) -> Dict[str, Any]:
    return await _call_legacy_tool("ff_get_leagues", ctx=ctx)


@server.tool(
    name="ff_get_league_info",
    description=(
        "Retrieve metadata about a single Yahoo league including scoring "
        "settings, season, and your team summary. Requires a league_key."
    ),
    meta=_tool_meta("ff_get_league_info"),
)
async def ff_get_league_info(ctx: Context, league_key: str) -> Dict[str, Any]:
    return await _call_legacy_tool("ff_get_league_info", ctx=ctx, league_key=league_key)


@server.tool(
    name="ff_get_standings",
    description=(
        "Return the current standings table for a Yahoo league showing ranks, "
        "records, and points for each team."
    ),
    meta=_tool_meta("ff_get_standings"),
)
async def ff_get_standings(ctx: Context, league_key: str) -> Dict[str, Any]:
    return await _call_legacy_tool("ff_get_standings", ctx=ctx, league_key=league_key)


@server.tool(
    name="ff_get_roster",
    description=(
        "List the players on a roster for the authenticated manager or a "
        "specified team in the league, including status and position info."
    ),
    meta=_tool_meta("ff_get_roster"),
)
async def ff_get_roster(
    ctx: Context,
    league_key: str,
    team_key: Optional[str] = None,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_roster",
        ctx=ctx,
        league_key=league_key,
        team_key=team_key,
    )


@server.tool(
    name="ff_get_matchup",
    description=(
        "Retrieve matchup information for the authenticated team in a given "
        "week. Provide week to inspect historical or future matchups."
    ),
    meta=_tool_meta("ff_get_matchup"),
)
async def ff_get_matchup(
    ctx: Context,
    league_key: str,
    week: Optional[int] = None,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_matchup",
        ctx=ctx,
        league_key=league_key,
        week=week,
    )


@server.tool(
    name="ff_get_players",
    description=(
        "Surface free-agent players from Yahoo for waiver research. Optionally "
        "filter by position and limit the number of results."
    ),
    meta=_tool_meta("ff_get_players"),
)
async def ff_get_players(
    ctx: Context,
    league_key: str,
    position: Optional[str] = None,
    count: int = 10,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_players",
        ctx=ctx,
        league_key=league_key,
        position=position,
        count=count,
    )


@server.tool(
    name="ff_compare_teams",
    description=(
        "Compare the rosters of two teams in the same league to support trade "
        "or matchup analysis. Provide both team keys."
    ),
    meta=_tool_meta("ff_compare_teams"),
)
async def ff_compare_teams(
    ctx: Context,
    league_key: str,
    team_key_a: str,
    team_key_b: str,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_compare_teams",
        ctx=ctx,
        league_key=league_key,
        team_key_a=team_key_a,
        team_key_b=team_key_b,
    )


@server.tool(
    name="ff_get_optimal_lineup",
    description=(
        "Generate AI-supported lineup recommendations for the authenticated "
        "team using Yahoo data and Sleeper projections."
    ),
    meta=_tool_meta("ff_get_optimal_lineup"),
)
async def ff_get_optimal_lineup(
    ctx: Context,
    league_key: str,
    week: Optional[int] = None,
    strategy: Literal["conservative", "aggressive", "balanced"] = "balanced",
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_optimal_lineup",
        ctx=ctx,
        league_key=league_key,
        week=week,
        strategy=strategy,
    )


@server.tool(
    name="ff_refresh_token",
    description=(
        "Refresh the Yahoo OAuth access token using the configured refresh "
        "credentials. Use when API calls return 401 errors."
    ),
    meta=_tool_meta("ff_refresh_token"),
)
async def ff_refresh_token(ctx: Context) -> Dict[str, Any]:
    if ctx is not None:
        await ctx.info("Refreshing Yahoo OAuth token")
    return await _legacy_refresh_token()


@server.tool(
    name="ff_get_api_status",
    description=(
        "Inspect rate limiter and cache metrics for troubleshooting API "
        "throttling or stale data issues."
    ),
    meta=_tool_meta("ff_get_api_status"),
)
async def ff_get_api_status(ctx: Context) -> Dict[str, Any]:
    return await _call_legacy_tool("ff_get_api_status", ctx=ctx)


@server.tool(
    name="ff_clear_cache",
    description=(
        "Invalidate the Yahoo response cache. Optionally provide a pattern to "
        "clear a subset of cached endpoints."
    ),
    meta=_tool_meta("ff_clear_cache"),
)
async def ff_clear_cache(
    ctx: Context,
    pattern: Optional[str] = None,
) -> Dict[str, Any]:
    return await _call_legacy_tool("ff_clear_cache", ctx=ctx, pattern=pattern)


@server.tool(
    name="ff_get_draft_results",
    description=(
        "Fetch draft grades and pick positions for every team in a league to "
        "review draft performance."
    ),
    meta=_tool_meta("ff_get_draft_results"),
)
async def ff_get_draft_results(ctx: Context, league_key: str) -> Dict[str, Any]:
    return await _call_legacy_tool("ff_get_draft_results", ctx=ctx, league_key=league_key)


@server.tool(
    name="ff_get_waiver_wire",
    description=(
        "List top waiver-wire candidates with Yahoo stats and projections. "
        "Supports position and sort filtering."
    ),
    meta=_tool_meta("ff_get_waiver_wire"),
)
async def ff_get_waiver_wire(
    ctx: Context,
    league_key: str,
    position: Optional[str] = None,
    sort: Literal["rank", "points", "owned", "trending"] = "rank",
    count: int = 20,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_waiver_wire",
        ctx=ctx,
        league_key=league_key,
        position=position,
        sort=sort,
        count=count,
    )


@server.tool(
    name="ff_get_draft_rankings",
    description=(
        "Access pre-draft Yahoo rankings and ADP data. Useful before or during "
        "drafts to evaluate player tiers."
    ),
    meta=_tool_meta("ff_get_draft_rankings"),
)
async def ff_get_draft_rankings(
    ctx: Context,
    league_key: Optional[str] = None,
    position: Optional[str] = "all",
    count: int = 50,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_draft_rankings",
        ctx=ctx,
        league_key=league_key,
        position=position,
        count=count,
    )


@server.tool(
    name="ff_get_draft_recommendation",
    description=(
        "Provide draft pick recommendations tailored to a strategy such as "
        "balanced, aggressive, or conservative."
    ),
    meta=_tool_meta("ff_get_draft_recommendation"),
)
async def ff_get_draft_recommendation(
    ctx: Context,
    league_key: str,
    strategy: Literal["conservative", "aggressive", "balanced"] = "balanced",
    num_recommendations: int = 10,
    current_pick: Optional[int] = None,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_draft_recommendation",
        ctx=ctx,
        league_key=league_key,
        strategy=strategy,
        num_recommendations=num_recommendations,
        current_pick=current_pick,
    )


@server.tool(
    name="ff_analyze_draft_state",
    description=(
        "Summarize the current draft landscape for your team, highlighting "
        "positional needs and strategic advice."
    ),
    meta=_tool_meta("ff_analyze_draft_state"),
)
async def ff_analyze_draft_state(
    ctx: Context,
    league_key: str,
    strategy: Literal["conservative", "aggressive", "balanced"] = "balanced",
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_analyze_draft_state",
        ctx=ctx,
        league_key=league_key,
        strategy=strategy,
    )


@server.tool(
    name="ff_analyze_reddit_sentiment",
    description=(
        "Analyze recent Reddit chatter for one or more players to gauge public "
        "sentiment, injury mentions, and engagement levels."
    ),
    meta=_tool_meta("ff_analyze_reddit_sentiment"),
)
async def ff_analyze_reddit_sentiment(
    ctx: Context,
    players: Sequence[str],
    time_window_hours: int = 48,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_analyze_reddit_sentiment",
        ctx=ctx,
        players=list(players),
        time_window_hours=time_window_hours,
    )


def run_http_server(host: Optional[str] = None, port: Optional[int] = None, *, show_banner: bool = True) -> None:
    """Start the FastMCP server using the HTTP transport."""

    resolved_host = host or os.getenv("HOST", "0.0.0.0")
    resolved_port = port or int(os.getenv("PORT", "8000"))

    server.run(
        "http",
        host=resolved_host,
        port=resolved_port,
        show_banner=show_banner,
    )


def main() -> None:
    """Console script entry point for launching the HTTP server."""

    run_http_server()


__all__ = [
    "server",
    "run_http_server",
    "main",
    "ff_get_leagues",
    "ff_get_league_info",
    "ff_get_standings",
    "ff_get_roster",
    "ff_get_matchup",
    "ff_get_players",
    "ff_compare_teams",
    "ff_get_optimal_lineup",
    "ff_refresh_token",
    "ff_get_api_status",
    "ff_clear_cache",
    "ff_get_draft_results",
    "ff_get_waiver_wire",
    "ff_get_draft_rankings",
    "ff_get_draft_recommendation",
    "ff_analyze_draft_state",
    "ff_analyze_reddit_sentiment",
]


if __name__ == "__main__":
    main()
