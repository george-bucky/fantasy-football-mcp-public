from __future__ import annotations

"""FastMCP-compatible fantasy football server entry point.

This module wraps the existing Yahoo Fantasy Football tooling defined in
``fantasy_football_multi_league`` and exposes it through the FastMCP
``@server.tool`` decorator so it can be deployed on fastmcp.cloud.
"""

import json
import os
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Sequence, Union

from fastmcp import Context, FastMCP
from mcp.types import ContentBlock, TextContent

import fantasy_football_multi_league
# REMOVED: enhanced_mcp_tools imports - no longer using wrapper tools

# Remove explicit typing to avoid type conflicts with evolving MCP types
_legacy_call_tool = fantasy_football_multi_league.call_tool
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
        "Get roster data with configurable detail levels. Use data_level='basic' for "
        "quick roster info, 'standard' for roster + projections, or 'full' for "
        "comprehensive analysis with external data sources and enhanced insights."
    ),
    "ff_get_matchup": (
        "Look up the opponent, projected points, and matchup details for a "
        "given week in the authenticated manager's league schedule."
    ),
    "ff_get_players": (
        "Research free agents or player pools for waiver pickups by filtering "
        "Yahoo players by position and limiting the result count. Accepts optional "
        "parameters for enhanced analysis similar to roster data."
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

    raw_blocks = await _legacy_call_tool(name=name, arguments=filtered_args)
    if raw_blocks is None:
        blocks: Sequence[Any] = []
    elif isinstance(raw_blocks, Iterable) and not isinstance(raw_blocks, (str, bytes, TextContent)):
        blocks = list(raw_blocks)
    else:
        blocks = [raw_blocks]
    if not blocks:
        return {
            "status": "error",
            "message": "Legacy tool returned no response",
            "tool": name,
            "arguments": filtered_args,
        }

    def _coerce_text(block: Any) -> TextContent:
        if isinstance(block, TextContent):
            return block
        if hasattr(block, "text") and isinstance(getattr(block, "text"), str):
            return TextContent(type="text", text=getattr(block, "text"))
        if is_dataclass(block) and not isinstance(block, type):
            return TextContent(type="text", text=json.dumps(asdict(block)))
        if hasattr(block, "data"):
            data = getattr(block, "data")
            if isinstance(data, bytes):
                try:
                    data = data.decode("utf-8")
                except Exception:
                    data = repr(data)
            if isinstance(data, str):
                return TextContent(type="text", text=data)
        try:
            return TextContent(type="text", text=json.dumps(block, default=str))
        except Exception:
            return TextContent(type="text", text=str(block))

    responses = [_coerce_text(block) for block in blocks]

    first = responses[0]
    payload = getattr(first, "text", "")

    # Instrumentation: detect raw '0' / suspiciously tiny payloads that break higher layers
    if payload.strip() == "0":
        diag = {
            "status": "error",
            "message": "Legacy tool returned sentinel '0' string instead of JSON",
            "tool": name,
            "arguments": filtered_args,
            "raw": payload,
            "stage": "_call_legacy_tool:raw_payload_zero",
        }
        if ctx is not None:
            await ctx.info(f"[diagnostic] Detected raw '0' payload from legacy tool: {name}")
        return diag

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
async def ff_get_league_info(
    ctx: Context,
    league_key: str,
    week: Optional[int] = None,
    team_key: Optional[str] = None,
    data_level: Optional[str] = None,
    include_analysis: Optional[bool] = None,
    include_projections: Optional[bool] = None,
    include_external_data: Optional[bool] = None,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_league_info",
        ctx=ctx,
        league_key=league_key,
    )


@server.tool(
    name="ff_get_roster",
    description=(
        "Get roster data with configurable detail levels. Supports basic roster info, "
        "Yahoo projections, and comprehensive multi-source analysis including Sleeper, "
        "matchup data, and trending information for intelligent lineup decisions."
    ),
    meta=_tool_meta("ff_get_roster"),
)

async def ff_get_roster(
    ctx: Context,
    league_key: str,
    team_key: Optional[str] = None,
    week: Optional[int] = None,
    include_projections: bool = True,
    include_external_data: bool = True,
    include_analysis: bool = True,
    data_level: Literal["basic", "standard", "full"] = "full",
) -> Dict[str, Any]:
    """
    Consolidated roster tool with configurable detail levels.
    
    Args:
        league_key: League identifier
        team_key: Team identifier (optional, defaults to authenticated user's team)
        week: Week number for projections (optional, defaults to current week)
        include_projections: Include Yahoo and/or Sleeper projections
        include_external_data: Include Sleeper rankings, matchup analysis, trending data
        include_analysis: Include enhanced player analysis and recommendations
        data_level: "basic" (roster only), "standard" (+ projections), "full" (everything)
    """
    
    # Determine effective settings based on data_level and explicit parameters
    if data_level == "basic":
        effective_projections = False
        effective_external = False
        effective_analysis = False
    elif data_level == "standard":
        effective_projections = True
        effective_external = False
        effective_analysis = False
    else:  # "full"
        effective_projections = True
        effective_external = True
        effective_analysis = True

    # Explicit parameters override data_level defaults
    if not include_projections:
        effective_projections = False
    if not include_external_data:
        effective_external = False
    if not include_analysis:
        effective_analysis = False

    # Informational logging for the selected mode
    if ctx:
        if not any([effective_projections, effective_external, effective_analysis]):
            await ctx.info("Using basic roster data (legacy mode)")
        else:
            await ctx.info(
                "Using enhanced roster data "
                f"(projections: {effective_projections}, external: {effective_external}, analysis: {effective_analysis})"
            )

    try:
        result = await _call_legacy_tool(
            "ff_get_roster",
            ctx=ctx,
            league_key=league_key,
            team_key=team_key,
            week=week,
            include_projections=effective_projections,
            include_external_data=effective_external,
            include_analysis=effective_analysis,
            data_level=data_level,
        )
        return result
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Enhanced roster fetch failed: {exc}",
            "fallback_suggestion": "Try using data_level='basic' for simple roster data",
        }



@server.tool(
    name="ff_get_standings",
    description=(
        "Return the current standings table for a Yahoo league showing ranks, "
        "records, and points for each team."
    ),
    meta=_tool_meta("ff_get_standings"),
)
async def ff_get_standings(
    ctx: Context,
    league_key: str,
    week: Optional[int] = None,
    team_key: Optional[str] = None,
    data_level: Optional[str] = None,
    include_analysis: Optional[bool] = None,
    include_projections: Optional[bool] = None,
    include_external_data: Optional[bool] = None,
) -> Dict[str, Any]:
    return await _call_legacy_tool("ff_get_standings", ctx=ctx, league_key=league_key)


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
    team_key: Optional[str] = None,
    data_level: Optional[str] = None,
    include_analysis: Optional[bool] = None,
    include_projections: Optional[bool] = None,
    include_external_data: Optional[bool] = None,
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
        "filter by position and limit the number of results. Supports additional "
        "parameters for enhanced analysis (week, team_key, data_level, etc.) "
        "though the core functionality focuses on basic player discovery."
    ),
    meta=_tool_meta("ff_get_players"),
)
async def ff_get_players(
    ctx: Context,
    league_key: str,
    position: Optional[str] = None,
    count: int = 10,
    week: Optional[int] = None,
    team_key: Optional[str] = None,
    data_level: Optional[str] = None,
    include_analysis: Optional[bool] = None,
    include_projections: Optional[bool] = None,
    include_external_data: Optional[bool] = None,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_players",
        ctx=ctx,
        league_key=league_key,
        position=position,
        count=count,
        week=week,
        team_key=team_key,
        data_level=data_level,
        include_analysis=include_analysis,
        include_projections=include_projections,
        include_external_data=include_external_data,
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
    debug: bool = False,
) -> Dict[str, Any]:
    return await _call_legacy_tool(
        "ff_get_optimal_lineup",
        ctx=ctx,
        league_key=league_key,
        week=week,
        strategy=strategy,
        debug=debug,
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


# ============================================================================
# ENHANCED TOOLS - Advanced decision-making capabilities for client LLMs
# ============================================================================

# REMOVED: ff_get_roster_with_projections_wrapper - replaced by ff_get_roster with data_level='full'
# REMOVED: ff_analyze_lineup_options_wrapper - complex functionality can be achieved through ff_get_optimal_lineup


# REMOVED: ff_compare_players_wrapper - player comparison can be done through ff_get_players and ff_get_waiver_wire


# REMOVED: ff_what_if_analysis_wrapper - scenario analysis can be done using ff_get_optimal_lineup with different strategies


# REMOVED: ff_get_decision_context_wrapper - context can be gathered through ff_get_league_info, ff_get_matchup, ff_get_standings


# ============================================================================
# PROMPTS - Reusable message templates for better LLM interactions
# ============================================================================

@server.prompt
def analyze_roster_strengths(league_key: str, team_key: str) -> str:
    """Generate a prompt for analyzing roster strengths and weaknesses."""
    return f"""Please analyze the fantasy football roster for team {team_key} in league {league_key}. 
    
Focus on:
1. Positional depth and strength
2. Starting lineup quality vs bench depth
3. Injury concerns and bye week coverage
4. Trade opportunities and waiver wire needs
5. Overall team competitiveness

Provide specific recommendations for improvement."""


@server.prompt
def draft_strategy_advice(strategy: str, league_size: int, pick_position: int) -> str:
    """Generate a prompt for draft strategy recommendations."""
    return f"""Provide fantasy football draft strategy advice for:
- Strategy: {strategy}
- League size: {league_size} teams
- Draft position: {pick_position}

Include:
1. First 3 rounds strategy
2. Position priority order
3. Sleepers and value picks
4. Players to avoid
5. Late-round targets
6. PPR-specific considerations (pass-catching RBs, high-volume WRs)

Tailor the advice to the {strategy} approach and consider how PPR scoring affects player values."""


@server.prompt
def matchup_analysis(team_a: str, team_b: str, week: int) -> str:
    """Generate a prompt for head-to-head matchup analysis."""
    return f"""Analyze the fantasy football matchup between {team_a} and {team_b} for Week {week}.

Compare:
1. Starting lineup projections
2. Key positional advantages
3. Weather/venue factors
4. Recent performance trends
5. Injury reports and player status
6. Predicted outcome and confidence level

Provide a detailed breakdown with specific player recommendations."""


@server.prompt
def waiver_wire_priority(league_key: str, position: str, budget: int) -> str:
    """Generate a prompt for waiver wire priority recommendations."""
    return f"""Analyze waiver wire options for {position} in league {league_key} with a budget of ${budget}.

Evaluate:
1. Top 5 available players at {position}
2. FAAB bid recommendations
3. Long-term vs short-term value
4. Injury replacements vs upgrades
5. Schedule analysis for upcoming weeks

Prioritize based on immediate need and future potential."""


@server.prompt
def trade_evaluation(team_a: str, team_b: str, proposed_trade: str) -> str:
    """Generate a prompt for trade evaluation."""
    return f"""Evaluate this fantasy football trade proposal between {team_a} and {team_b}:

Proposed Trade: {proposed_trade}

Analyze:
1. Fairness and value balance
2. Team needs and fit
3. Positional scarcity impact
4. Playoff schedule implications
5. Risk vs reward assessment
6. Alternative trade suggestions

Provide a clear recommendation with reasoning."""


# ============================================================================
# RESOURCES - Static and dynamic data for LLM context
# ============================================================================

@server.resource("config://scoring")
def get_scoring_rules() -> str:
    """Provide standard fantasy football scoring rules for context."""
    return """Fantasy Football Scoring Rules:

PASSING:
- Passing TD: 4 points
- Passing Yards: 1 point per 25 yards
- Interception: -2 points
- 2-Point Conversion: 2 points

RUSHING:
- Rushing TD: 6 points
- Rushing Yards: 1 point per 10 yards
- 2-Point Conversion: 2 points

RECEIVING:
- Receiving TD: 6 points
- Receiving Yards: 1 point per 10 yards
- Reception: 1 point (PPR - Points Per Reception)
- 2-Point Conversion: 2 points

KICKING:
- Field Goal 0-39 yards: 3 points
- Field Goal 40-49 yards: 4 points
- Field Goal 50+ yards: 5 points
- Extra Point: 1 point

DEFENSE/SPECIAL TEAMS:
- Touchdown: 6 points
- Safety: 2 points
- Interception: 2 points
- Fumble Recovery: 2 points
- Sack: 1 point
- Blocked Kick: 2 points
- Points Allowed 0: 10 points
- Points Allowed 1-6: 7 points
- Points Allowed 7-13: 4 points
- Points Allowed 14-20: 1 point
- Points Allowed 21-27: 0 points
- Points Allowed 28-34: -1 point
- Points Allowed 35+: -4 points

SCORING VARIATIONS:
- Standard (Non-PPR): 0 points per reception
- Half-PPR: 0.5 points per reception
- Full-PPR: 1 point per reception (most common)
- Super-PPR: 1.5+ points per reception

PPR IMPACT:
- Increases value of pass-catching RBs and slot WRs
- Makes WRs more valuable relative to RBs
- Favors high-volume receivers over big-play specialists
- Changes draft strategy and player rankings"""


@server.resource("config://positions")
def get_position_info() -> str:
    """Provide fantasy football position information and requirements."""
    return """Fantasy Football Position Requirements:

STANDARD LEAGUE (10-12 teams):
- QB: 1 starter
- RB: 2 starters
- WR: 2 starters  
- TE: 1 starter
- FLEX: 1 (RB/WR/TE)
- K: 1 starter
- DEF/ST: 1 starter
- Bench: 6-7 players

SUPERFLEX LEAGUE:
- QB: 1 starter
- RB: 2 starters
- WR: 2 starters
- TE: 1 starter
- FLEX: 1 (RB/WR/TE)
- SUPERFLEX: 1 (QB/RB/WR/TE)
- K: 1 starter
- DEF/ST: 1 starter
- Bench: 6-7 players

POSITION ABBREVIATIONS:
- QB: Quarterback
- RB: Running Back
- WR: Wide Receiver
- TE: Tight End
- K: Kicker
- DEF/ST: Defense/Special Teams
- FLEX: Flexible position (RB/WR/TE)
- SUPERFLEX: Super flexible position (QB/RB/WR/TE)"""


@server.resource("config://strategies")
def get_draft_strategies() -> str:
    """Provide information about different fantasy football draft strategies."""
    return """Fantasy Football Draft Strategies:

CONSERVATIVE STRATEGY:
- Focus on safe, high-floor players
- Prioritize proven veterans
- Avoid injury-prone players
- Build depth over upside
- Target consistent performers
- Good for beginners

BALANCED STRATEGY:
- Mix of safe picks and upside plays
- Balance risk and reward
- Target value at each pick
- Consider positional scarcity
- Adapt to draft flow
- Most popular approach

AGGRESSIVE STRATEGY:
- Target high-upside players
- Take calculated risks
- Focus on ceiling over floor
- Target breakout candidates
- Embrace volatility
- High risk, high reward

POSITIONAL STRATEGIES:
- Zero RB: Wait on running backs (more viable in PPR)
- Hero RB: Draft one elite RB early
- Robust RB: Load up on running backs
- Late Round QB: Wait on quarterback
- Streaming: Target favorable matchups

PPR-SPECIFIC STRATEGIES:
- Target pass-catching RBs (higher floor in PPR)
- Prioritize high-volume WRs over big-play specialists
- Consider slot receivers and possession WRs
- Elite TEs become more valuable (reception floor)
- RB handcuffs less critical (more WR depth)

KEY PRINCIPLES:
- Value-based drafting
- Positional scarcity awareness
- Handcuff important players
- Monitor bye weeks
- Stay flexible and adapt
- PPR changes player values significantly"""


@server.resource("data://injury-status")
def get_injury_status_info() -> str:
    """Provide information about fantasy football injury statuses."""
    return """Fantasy Football Injury Status Guide:

QUESTIONABLE (Q):
- 50% chance to play
- Monitor closely
- Have backup ready
- Check game-time decisions

DOUBTFUL (D):
- 25% chance to play
- Likely to sit out
- Start backup if available
- High risk to start

OUT (O):
- Will not play
- Do not start
- Use backup or waiver pickup
- Check IR eligibility

PROBABLE (P):
- 75% chance to play
- Likely to start
- Monitor for changes
- Generally safe to start

INJURED RESERVE (IR):
- Out for extended time
- Can be stashed in IR slot
- Check league rules
- Monitor return timeline

COVID-19:
- Follow league protocols
- Check testing status
- Monitor updates
- Have backup plans

INACTIVE:
- Will not play
- Game-day decision
- Use alternative options
- Check pre-game reports"""


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
    # Enhanced Tools - Removed wrapper tools (use core tools instead)
    # Prompts
    "analyze_roster_strengths",
    "draft_strategy_advice",
    "matchup_analysis",
    "waiver_wire_priority",
    "trade_evaluation",
    # Resources
    "get_scoring_rules",
    "get_position_info",
    "get_draft_strategies",
    "get_injury_status_info",
    "get_tool_selection_guide",
]

# Optional resource: expose deployed commit SHA for diagnostics
try:
    with open(os.path.join(os.path.dirname(__file__), "COMMIT_SHA"), "r", encoding="utf-8") as _f:
        _COMMIT_SHA = _f.read().strip()
except Exception:  # pragma: no cover - best effort
    _COMMIT_SHA = "unknown"

@server.resource("guide://tool-selection")
def get_tool_selection_guide() -> str:
    """Comprehensive guide for LLMs on when and how to use fantasy football tools."""
    return json.dumps({
        "title": "Fantasy Football Tool Selection Guide for LLMs",
        "description": "Strategic guidance for AI assistants on optimal tool usage patterns",
        "workflow_priority": [
            "1. START: ff_get_leagues - Always begin here if you don't have a league_key",
            "2. CONTEXT: ff_get_league_info - Understand league settings and scoring",
            "3. BASELINE: ff_get_roster - Know current lineup before making recommendations",
            "4. COMPETITION: ff_get_matchup - Analyze weekly opponent for strategic adjustments",
            "5. OPPORTUNITIES: ff_get_waiver_wire - Identify available upgrades",
            "6. OPTIMIZATION: ff_get_optimal_lineup - AI-powered lineup recommendations"
        ],
        "tool_categories": {
            "CORE_LEAGUE_DATA": {
                "description": "Essential league information and setup",
                "tools": {
                    "ff_get_leagues": "Discovery: Find available leagues and extract league_key identifiers",
                    "ff_get_league_info": "Configuration: League settings, scoring rules, roster requirements",
                    "ff_get_standings": "Rankings: Current standings, records, points for strategy context"
                }
            },
            "PLAYER_ROSTER_ANALYSIS": {
                "description": "Player and roster management tools",
                "tools": {
                    "ff_get_roster": "Current Lineup: Configurable roster data (basic/standard/full detail levels) for lineup decisions",
                    "ff_get_players": "Player Search: Find specific players by name or position",
                    "ff_get_waiver_wire": "Free Agents: Available players with advanced metrics"
                }
            },
            "MATCHUP_COMPETITION": {
                "description": "Head-to-head analysis and competitive intelligence",
                "tools": {
                    "ff_get_matchup": "Opponent Analysis: Weekly head-to-head strategic insights",
                    "ff_compare_teams": "Team Comparison: Direct roster and performance comparisons"
                }
            },
            "OPTIMIZATION_STRATEGY": {
                "description": "AI-powered decision making and strategy tools",
                "tools": {
                    "ff_get_optimal_lineup": "AI Optimization: Championship-level lineup recommendations (use use_llm=true)",
                    "ff_get_draft_rankings": "Player Tiers: Value assessment and tier-based rankings",
                    "ff_analyze_reddit_sentiment": "Market Intelligence: Public opinion and trending players"
                }
            },
            "ADVANCED_ANALYSIS": {
                "description": "Deep analytics and historical insights",
                "tools": {
                    "ff_get_draft_results": "Draft History: Historical patterns and team building analysis",
                    "ff_analyze_draft_state": "Live Draft: Real-time draft strategy and recommendations"
                }
            },
            "UTILITY_MAINTENANCE": {
                "description": "System maintenance and troubleshooting",
                "tools": {
                    "ff_refresh_token": "Authentication: Fix Yahoo API authentication issues",
                    "ff_get_api_status": "Health Check: Verify system status and connectivity",
                    "ff_clear_cache": "Reset: Clear cached data for fresh analysis"
                }
            }
        },
        "strategic_usage_patterns": {
            "weekly_lineup_optimization": [
                "ff_get_leagues -> ff_get_roster -> ff_get_matchup -> ff_get_waiver_wire -> ff_get_optimal_lineup"
            ],
            "draft_preparation": [
                "ff_get_leagues -> ff_get_league_info -> ff_get_draft_rankings -> ff_analyze_draft_state"
            ],
            "competitive_analysis": [
                "ff_get_league_info -> ff_get_standings -> ff_compare_teams -> ff_get_matchup"
            ],
            "market_research": [
                "ff_get_waiver_wire -> ff_analyze_reddit_sentiment -> ff_get_players"
            ]
        },
        "decision_framework": {
            "data_gathering": "Always start with league discovery and current roster state",
            "context_building": "Understand league settings, scoring, and competitive landscape", 
            "opportunity_identification": "Use waiver wire and sentiment analysis for edge cases",
            "optimization": "Apply AI-powered tools for championship-level recommendations",
            "validation": "Cross-reference multiple data sources for confident decisions"
        },
        "best_practices": [
            "NEVER guess league_key - always use ff_get_leagues first",
            "ALWAYS check current roster before making lineup recommendations", 
            "USE ff_get_matchup for opponent-specific weekly strategy",
            "LEVERAGE ff_analyze_reddit_sentiment for contrarian plays",
            "APPLY use_llm=true in ff_get_optimal_lineup for AI analysis",
            "COMBINE multiple tools for comprehensive decision making"
        ]
    })

@server.resource("meta://version")
def get_version() -> str:  # pragma: no cover - simple accessor
    return json.dumps({"commit": _COMMIT_SHA})


if __name__ == "__main__":
    main()



