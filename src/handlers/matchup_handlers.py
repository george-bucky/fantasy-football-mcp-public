"""Matchup MCP tool handlers."""

import asyncio
from copy import deepcopy
from typing import Any, Optional

from src.services import (
    MatchupEvidenceError,
    apply_rookie_intelligence,
    get_decision_news_context,
    rookie_identity_key,
    rookie_identity_token,
    weekly_matchup_evidence_service,
)

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


def _first_int_field(data: Any, field: str) -> Optional[int]:
    for node in _walk_dicts(data):
        value = node.get(field)
        if isinstance(value, bool):
            continue
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        return parsed
    return None


async def _get_lineup_context(league_key: str) -> dict[str, Any]:
    game_key = league_key.split(".", 1)[0]
    settings_data, categories_data = await asyncio.gather(
        yahoo_api_call(f"league/{league_key}/settings"),
        yahoo_api_call(f"game/{game_key}/stat_categories"),
        return_exceptions=True,
    )
    if isinstance(settings_data, Exception):
        settings_data = {}
    if isinstance(categories_data, Exception):
        categories_data = {}
    scoring_format = _lineup_scoring_format(settings_data, categories_data)
    canonical_basis = str(scoring_format or "unknown").replace("-", "_")
    if scoring_format == "custom":
        projection_format, source = "ppr", "fallback_custom_ppr"
    elif scoring_format is None:
        projection_format, source = "ppr", "fallback_default_ppr"
    else:
        projection_format, source = scoring_format, "yahoo_settings"
    return {
        "scoring_format": projection_format,
        "scoring_format_source": source,
        "canonical_scoring_basis": canonical_basis,
        "season": _first_int_field(settings_data, "season"),
        "current_week": _first_int_field(settings_data, "current_week"),
    }


async def _get_lineup_scoring_format(league_key: str) -> tuple[str, str]:
    """Compatibility wrapper retained for focused parser tests."""
    context = await _get_lineup_context(league_key)
    return context["scoring_format"], context["scoring_format_source"]


async def _resolve_matchup_period(
    *, season: Optional[int], requested_week: Any, yahoo_current_week: Optional[int]
) -> tuple[int, int, int]:
    if season is None or not 2000 <= season <= 2100:
        raise MatchupEvidenceError("Exact Yahoo league season is unavailable")
    current_week = yahoo_current_week
    if current_week is None or not 1 <= current_week <= 18:
        from sleeper_api import sleeper_client

        state = await sleeper_client.get_nfl_state()
        sleeper_season = _first_int_field(state, "season")
        sleeper_week = _first_int_field(state, "week")
        if sleeper_season != season:
            raise MatchupEvidenceError("Sleeper season does not match the Yahoo league season")
        if sleeper_week is None or not 1 <= sleeper_week <= 18:
            raise MatchupEvidenceError("Current week is unavailable from Yahoo and Sleeper")
        current_week = sleeper_week
    if requested_week is None:
        target_week = current_week
    else:
        if isinstance(requested_week, bool):
            raise MatchupEvidenceError("Week must be an integer between 1 and 18")
        try:
            target_week = int(requested_week)
        except (TypeError, ValueError) as exc:
            raise MatchupEvidenceError("Week must be an integer between 1 and 18") from exc
        if not 1 <= target_week <= 18:
            raise MatchupEvidenceError("Week must be an integer between 1 and 18")
    cutoff_week = min(target_week - 1, current_week - 1)
    return season, target_week, max(0, cutoff_week)


def _unavailable_matchup_evidence(
    *, reason: str, season: Optional[int], target_week: Any, scoring_basis: str
) -> dict[str, Any]:
    return {
        "enabled": True,
        "available": False,
        "applied": False,
        "unavailable_reason": reason,
        "season": season,
        "target_week": target_week,
        "cutoff_week": None,
        "opponent": None,
        "home_away": None,
        "kickoff": None,
        "canonical_scoring_basis": scoring_basis,
        "games_sampled": 0,
        "points_allowed_per_game": None,
        "rank": None,
        "percentile": None,
        "source_url": None,
        "source_version": None,
        "fetched_at": None,
        "warnings": [reason],
        "tie_break_audit": [],
        "schedule": {"status": "unavailable"},
        "strength": {"status": "source_unavailable"},
    }


def _apply_weekly_matchup_evidence(players, evidence_rows: list[dict[str, Any]]) -> None:
    if len(players) != len(evidence_rows):
        raise MatchupEvidenceError("Player and matchup evidence counts do not match")
    for player, evidence in zip(players, evidence_rows):
        player.weekly_matchup_evidence = evidence
        schedule_status = evidence.get("schedule", {}).get("status")
        if schedule_status == "bye":
            player.opponent = "BYE"
        elif schedule_status == "matched":
            player.opponent = str(evidence.get("opponent") or "")
        if evidence.get("strength", {}).get("status") == "available":
            player.matchup_description = (
                f"{evidence['canonical_scoring_basis']} points allowed: "
                f"{evidence['points_allowed_per_game']:.1f}/game vs {player.position} "
                f"(rank {evidence['rank']:g}/32)"
            )


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
    use_rookie_intelligence = arguments.get("use_rookie_intelligence", False)
    use_matchup_evidence = arguments.get("use_matchup_evidence", False)

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

        lineup_context = await _get_lineup_context(league_key)
        scoring_format = lineup_context["scoring_format"]
        scoring_format_source = lineup_context["scoring_format_source"]
        for player in players:
            player.scoring_format = scoring_format
            player.scoring_format_source = scoring_format_source
        players = await lineup_optimizer.enhance_with_external_data(players, week=week)
        matchup_context = None
        if use_matchup_evidence:
            try:
                season, target_week, cutoff_week = await _resolve_matchup_period(
                    season=lineup_context["season"],
                    requested_week=week,
                    yahoo_current_week=lineup_context["current_week"],
                )
                matchup_context = await weekly_matchup_evidence_service.get_evidence(
                    [
                        {"name": player.name, "team": player.team, "position": player.position}
                        for player in players
                    ],
                    season=season,
                    target_week=target_week,
                    cutoff_week=cutoff_week,
                    scoring_basis=lineup_context["canonical_scoring_basis"],
                )
                _apply_weekly_matchup_evidence(players, matchup_context["players"])
            except Exception as exc:
                unavailable = _unavailable_matchup_evidence(
                    reason=f"Weekly matchup evidence unavailable: {exc}",
                    season=lineup_context["season"],
                    target_week=(
                        week
                        if week is not None
                        else lineup_context["current_week"] or "current"
                    ),
                    scoring_basis=lineup_context["canonical_scoring_basis"],
                )
                _apply_weekly_matchup_evidence(
                    players, [deepcopy(unavailable) for _ in players]
                )
                matchup_context = {
                    "enabled": True,
                    "players": [player.weekly_matchup_evidence for player in players],
                    "warnings": [unavailable["unavailable_reason"]],
                }
        try:
            decision_news = await get_decision_news_context([player.name for player in players])
        except Exception as exc:
            decision_news = {
                "by_player": {},
                "sources": [],
                "warnings": [f"Decision news unavailable: {exc}"],
            }
        rookie_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
        rookie_evidence = None
        if use_rookie_intelligence:
            try:
                rookie_context = apply_rookie_intelligence(
                    [{"name": player.name, "position": player.position} for player in players],
                    context="lineup",
                )
                rookie_by_identity = rookie_context["by_identity"]
                rookie_evidence = rookie_context["evidence"]
            except Exception as exc:
                rookie_evidence = {
                    "enabled": False,
                    "warnings": [f"Rookie intelligence unavailable: {exc}"],
                    "opponent_aware": False,
                    "influence": "None; reviewed rookie data failed closed.",
                }
        optimization = await lineup_optimizer.optimize_lineup_smart(
            players,
            strategy,
            week,
            use_llm,
            decision_news=decision_news["by_player"],
            rookie_intelligence=rookie_by_identity,
            use_matchup_evidence=use_matchup_evidence,
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
                "selection_evidence": optimization.get("player_evidence", {}).get(
                    rookie_identity_token(player.name, player.position)
                    if use_rookie_intelligence or use_matchup_evidence
                    else player.name,
                    {},
                ),
            }
            if use_matchup_evidence:
                starters_formatted[pos]["weekly_matchup_evidence"] = (
                    player.weekly_matchup_evidence
                )
            if use_rookie_intelligence:
                starters_formatted[pos]["rookie_intelligence"] = rookie_by_identity.get(
                    rookie_identity_key(player.name, player.position)
                )

        bench_formatted = []
        for player in optimization["bench"][:5]:
            bench_player = {
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
                "selection_evidence": optimization.get("player_evidence", {}).get(
                    rookie_identity_token(player.name, player.position)
                    if use_rookie_intelligence or use_matchup_evidence
                    else player.name,
                    {},
                ),
            }
            if use_matchup_evidence:
                bench_player["weekly_matchup_evidence"] = player.weekly_matchup_evidence
            if use_rookie_intelligence:
                bench_player["rookie_intelligence"] = rookie_by_identity.get(
                    rookie_identity_key(player.name, player.position)
                )
            bench_formatted.append(bench_player)

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
        if rookie_evidence is not None:
            result["analysis"]["rookie_intelligence"] = rookie_evidence
            warnings.extend(rookie_evidence.get("warnings", []))
        if matchup_context is not None:
            result["analysis"]["weekly_matchup_evidence"] = {
                key: value for key, value in matchup_context.items() if key != "players"
            }
            warnings.extend(matchup_context.get("warnings", []))
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
