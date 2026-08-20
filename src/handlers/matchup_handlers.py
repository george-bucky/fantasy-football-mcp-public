"""Matchup MCP tool handlers."""

import asyncio
from typing import Any, Optional

from src.services import get_decision_news_context

# These will be injected from main file
get_user_team_key = None
get_user_team_info = None
yahoo_api_call = None
parse_team_roster = None


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_dicts(nested)


def _lineup_scoring_format(settings_data: dict, categories_data: dict) -> Optional[str]:
    """Resolve standard/half-PPR/PPR from Yahoo reception scoring."""
    stat_names: dict[str, str] = {}
    for node in _walk_dicts(categories_data):
        stat = node.get("stat")
        if not isinstance(stat, dict) and "stat_id" in node:
            stat = node
        if isinstance(stat, dict) and stat.get("stat_id") is not None:
            name = stat.get("display_name") or stat.get("name") or stat.get("abbr")
            if name:
                stat_names[str(stat["stat_id"])] = str(name).strip().lower()

    for node in _walk_dicts(settings_data):
        stat = node.get("stat")
        if not isinstance(stat, dict) and "stat_id" in node and "value" in node:
            stat = node
        if not isinstance(stat, dict) or "stat_id" not in stat or "value" not in stat:
            continue
        stat_name = (
            str(
                stat.get("display_name")
                or stat.get("name")
                or stat.get("abbr")
                or stat_names.get(str(stat["stat_id"]))
                or ""
            )
            .strip()
            .lower()
        )
        if stat_name not in {"reception", "receptions", "rec"}:
            continue
        try:
            reception_points = float(stat["value"])
        except (TypeError, ValueError):
            return None
        if abs(reception_points - 1.0) < 0.001:
            return "ppr"
        if abs(reception_points - 0.5) < 0.001:
            return "half-ppr"
        if abs(reception_points) < 0.001:
            return "standard"
        return "custom"
    return None


async def _get_lineup_scoring_format(league_key: str) -> tuple[str, str]:
    game_key = league_key.split(".", 1)[0]
    settings_data, categories_data = await asyncio.gather(
        yahoo_api_call(f"league/{league_key}/settings"),
        yahoo_api_call(f"game/{game_key}/stat_categories"),
        return_exceptions=True,
    )
    if isinstance(settings_data, Exception) or isinstance(categories_data, Exception):
        return "ppr", "fallback_default_ppr"
    scoring_format = _lineup_scoring_format(settings_data, categories_data)
    if scoring_format == "custom":
        return "ppr", "fallback_custom_ppr"
    if scoring_format is None:
        return "ppr", "fallback_default_ppr"
    return scoring_format, "yahoo_settings"


async def handle_ff_get_matchup(arguments: dict) -> dict:
    """Get matchup information for a team in a specific week.

    Args:
        arguments: Dict containing:
            - league_key: League identifier
            - week: Week number (optional, defaults to current)

    Returns:
        Dict with matchup data
    """
    league_key = arguments.get("league_key")
    week = arguments.get("week")
    team_key = await get_user_team_key(league_key)

    if not team_key:
        return {"error": f"Could not find your team in league {league_key}"}

    week_param = f";week={week}" if week else ""
    data = await yahoo_api_call(f"team/{team_key}/matchups{week_param}")
    return {
        "league_key": league_key,
        "team_key": team_key,
        "week": week or "current",
        "message": "Matchup data retrieved",
        "raw_matchups": data,
    }


async def handle_ff_compare_teams(arguments: dict) -> dict:
    """Compare rosters of two teams.

    Args:
        arguments: Dict containing:
            - league_key: League identifier
            - team_key_a: First team identifier
            - team_key_b: Second team identifier

    Returns:
        Dict with comparison data
    """
    league_key = arguments.get("league_key")
    team_key_a = arguments.get("team_key_a")
    team_key_b = arguments.get("team_key_b")

    data_a = await yahoo_api_call(f"team/{team_key_a}/roster")
    data_b = await yahoo_api_call(f"team/{team_key_b}/roster")

    roster_a = parse_team_roster(data_a)
    roster_b = parse_team_roster(data_b)

    return {
        "league_key": league_key,
        "team_a": {"team_key": team_key_a, "roster": roster_a},
        "team_b": {"team_key": team_key_b, "roster": roster_b},
    }


async def handle_ff_build_lineup(arguments: dict) -> dict:
    """Build optimal lineup using advanced analytics.

    Args:
        arguments: Dict containing:
            - league_key: League identifier
            - week: Week number (optional)
            - strategy: "balanced", "conservative", or "aggressive" (default: "balanced")
            - use_llm: Use LLM for additional insights (default: False)

    Returns:
        Dict with optimal lineup and recommendations
    """
    league_key = arguments.get("league_key")
    week = arguments.get("week")
    strategy = arguments.get("strategy", "balanced")
    use_llm = arguments.get("use_llm", False)

    team_key = await get_user_team_key(league_key)
    if not team_key:
        return {"error": f"Could not find your team in league {league_key}"}

    try:
        roster_data = await yahoo_api_call(f"team/{team_key}/roster")
        try:
            from lineup_optimizer import lineup_optimizer
        except ImportError as exc:
            return {
                "error": f"Lineup optimizer unavailable: {exc}",
                "suggestion": "Please check lineup_optimizer.py dependencies",
                "league_key": league_key,
                "team_key": team_key,
            }

        players = await lineup_optimizer.parse_yahoo_roster(roster_data)
        if not players:
            return {
                "error": "Failed to parse Yahoo roster data",
                "league_key": league_key,
                "team_key": team_key,
                "suggestion": "Check roster data format or try refreshing",
            }

        scoring_format, scoring_format_source = await _get_lineup_scoring_format(league_key)
        for player in players:
            player.scoring_format = scoring_format
            player.scoring_format_source = scoring_format_source
        players = await lineup_optimizer.enhance_with_external_data(players, week=week)
        try:
            decision_news = await get_decision_news_context([player.name for player in players])
        except Exception as exc:
            decision_news = {
                "by_player": {},
                "sources": [],
                "warnings": [f"Decision news unavailable: {exc}"],
            }
        optimization = await lineup_optimizer.optimize_lineup_smart(
            players,
            strategy,
            week,
            use_llm,
            decision_news=decision_news["by_player"],
        )
        if optimization["status"] == "error":
            return {
                "status": "error",
                "error": "Lineup optimization failed",
                "league_key": league_key,
                "team_key": team_key,
                "errors": optimization.get("errors", []),
                "details": optimization.get("errors", []),
                "data_quality": optimization.get("data_quality", {}),
            }

        starters_formatted = {}
        for pos, player in optimization["starters"].items():
            starters_formatted[pos] = {
                "name": player.name,
                "tier": player.player_tier.upper() if player.player_tier else "UNKNOWN",
                "team": player.team,
                "opponent": player.opponent,
                "matchup_score": player.matchup_score,
                "matchup": player.matchup_description,
                "composite_score": round(player.composite_score, 1),
                "yahoo_proj": (
                    round(player.yahoo_projection, 1) if player.yahoo_projection else None
                ),
                "sleeper_proj": (
                    round(player.sleeper_projection, 1) if player.sleeper_projection else None
                ),
                "trending": (
                    f"{player.trending_score:,} adds" if player.trending_score > 0 else None
                ),
                "floor": round(player.floor_projection, 1) if player.floor_projection else None,
                "ceiling": (
                    round(player.ceiling_projection, 1) if player.ceiling_projection else None
                ),
                "news_context": decision_news["by_player"].get(
                    player.name,
                    {"espn": [], "rotowire": [], "espn_athlete_refs": []},
                ),
                "selection_evidence": optimization.get("player_evidence", {}).get(player.name, {}),
            }

        bench_formatted = [
            {
                "name": player.name,
                "position": player.position,
                "opponent": player.opponent,
                "composite_score": round(player.composite_score, 1),
                "matchup_score": player.matchup_score,
                "tier": player.player_tier.upper() if player.player_tier else "UNKNOWN",
                "news_context": decision_news["by_player"].get(
                    player.name,
                    {"espn": [], "rotowire": [], "espn_athlete_refs": []},
                ),
                "selection_evidence": optimization.get("player_evidence", {}).get(player.name, {}),
            }
            for player in optimization["bench"][:5]
        ]

        result: dict[str, Any] = {
            "status": optimization["status"],
            "league_key": league_key,
            "team_key": team_key,
            "week": week or "current",
            "strategy": strategy,
            "optimal_lineup": starters_formatted,
            "bench": bench_formatted,
            "recommendations": optimization["recommendations"],
            "errors": optimization.get("errors", []),
            "analysis": {
                "total_players": optimization["data_quality"]["total_players"],
                "valid_players": optimization["data_quality"]["valid_players"],
                "players_with_projections": optimization["data_quality"][
                    "players_with_projections"
                ],
                "players_with_matchup_data": optimization["data_quality"][
                    "players_with_matchup_data"
                ],
                "strategy_used": optimization["strategy_used"],
                "data_sources": [
                    *optimization.get("strategy_summary", {}).get("inputs_used", []),
                    *decision_news["sources"],
                ],
                "strategy_evidence": optimization.get("strategy_summary", {}),
                "news_evidence_note": (
                    "ESPN and RotoWire news is attributed and used only for "
                    "qualitative confidence/risk flags, never fabricated points."
                ),
            },
        }
        warnings = [*optimization.get("errors", []), *decision_news["warnings"]]
        if warnings:
            result["warnings"] = warnings
        return result
    except Exception as exc:
        return {
            "error": f"Unexpected error during lineup optimization: {exc}",
            "league_key": league_key,
            "team_key": team_key,
            "suggestion": "Try again or check system logs for details",
        }
