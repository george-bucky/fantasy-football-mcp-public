"""Roster MCP tool handlers."""

import logging

from src.services.player_enhancement import serialize_weekly_evidence
import math
from dataclasses import replace
from typing import Any, Dict, List

# These will be injected from main file
get_user_team_info = None
yahoo_api_call = None
parse_team_roster = None


def _yahoo_only_player(player: Any) -> Any:
    """Scope inputs on a copy so disabled external evidence cannot affect the estimate."""
    prior = player.projection_context if isinstance(player.projection_context, dict) else {}
    context = dict(prior)
    context.pop("weekly_projection_inputs", None)
    context.pop("game_environment_inputs", None)
    context["environment_adjustments_enabled"] = False
    context["market_adjustments_enabled"] = False
    context["market_input_status"] = {"status": "unavailable", "reason": "disabled_by_request"}
    provenance = context.get("source_provenance")
    if isinstance(provenance, dict):
        context["source_provenance"] = {
            key: value for key, value in provenance.items() if key == "yahoo"
        }
    return replace(
        player,
        sleeper_projection=0.0,
        sleeper_projection_std=0.0,
        sleeper_projection_ppr=0.0,
        sleeper_projection_half_ppr=0.0,
        sleeper_projection_source="",
        sleeper_id="",
        sleeper_status="",
        sleeper_injury_status="",
        sleeper_depth_chart_order=0,
        sleeper_match_method="",
        match_confidence=0.0,
        recent_performance_data=None,
        recent_performance=[],
        performance_flags=(
            ["ON_BYE"] if player.on_bye or "ON_BYE" in player.performance_flags else []
        ),
        target_share=0.0,
        snap_count_pct=0.0,
        trending_score=0,
        season_avg=0.0,
        floor_projection=0.0,
        ceiling_projection=0.0,
        consistency_score=0.0,
        player_tier="unknown",
        risk_level="unknown",
        projection_context=context,
        projection_assessment={},
    )


def _scope_yahoo_assessment(assessment: dict) -> dict:
    """State request-disabled inputs as unknown, not fabricated zero forecasts."""
    for field in ("raw_source_values", "raw_provider_values"):
        if isinstance(assessment.get(field), dict):
            for source in list(assessment[field]):
                if source != "yahoo":
                    assessment[field][source] = None
    for field in ("configured_source_weights", "effective_source_weights"):
        if isinstance(assessment.get(field), dict):
            assessment[field] = {
                key: value for key, value in assessment[field].items() if key == "yahoo"
            }
    trace = assessment.get("strategy_trace", {})
    for field in ("utility_source_weights", "utility_source_values"):
        if isinstance(trace.get(field), dict):
            trace[field] = {key: value for key, value in trace[field].items() if key == "yahoo"}
    assessment.setdefault("missing_sources", {}).update(
        sleeper="disabled_by_request"
    )
    recent = assessment.get("supporting_evidence", {}).get("recent_actuals", {})
    recent.update(average=None, minimum=None, maximum=None, status="disabled_by_request")
    assessment["input_policy"] = {
        "allowed_sources": ["yahoo"],
        "external_data": "disabled_by_request",
    }
    assessment.setdefault("limitations", []).append(
        "External forecast, recent-performance, role, status and trending evidence disabled by request"
    )
    return assessment


async def handle_ff_get_roster(arguments: dict) -> dict:
    """Get roster for a team with optional enhanced data.

    Args:
        arguments: Dict containing:
            - league_key: League identifier
            - team_key: Team identifier (optional, will auto-detect user's team)
            - data_level: "basic", "standard", or "enhanced" (default: "basic")
            - include_projections: Include projection data (default: True)
            - include_external_data: Include Sleeper API data (default: True)
            - include_analysis: Include analysis (default: True)
            - include_weekly_context: Include report-only weekly player context (default: False)
            - week: Specific week (optional)

    Returns:
        Dict with roster data and optional enhancements
    """
    league_key = arguments.get("league_key")
    team_key = arguments.get("team_key")
    data_level = arguments.get("data_level", "basic")
    include_projections = arguments.get("include_projections", True)
    include_external_data = arguments.get("include_external_data", True)
    include_analysis = arguments.get("include_analysis", True)
    include_weekly_context = arguments.get("include_weekly_context", False)
    from src.handlers.matchup_handlers import (
        _requested_roster_week,
        _roster_endpoint,
        _verify_roster_response,
    )

    try:
        week = _requested_roster_week(arguments.get("week"))
    except ValueError as exc:
        return {"status": "error", "error": str(exc), "league_key": league_key}

    if data_level == "basic":
        effective_projections = False
        effective_external = False
        effective_analysis = False
    elif data_level == "standard":
        effective_projections = True
        effective_external = False
        effective_analysis = False
    else:
        effective_projections = True
        effective_external = True
        effective_analysis = True

    if not include_projections:
        effective_projections = False
    if not include_external_data:
        effective_external = False
    if not include_analysis:
        effective_analysis = False

    needs_enhanced = effective_projections or effective_external or effective_analysis

    team_info = None
    if not team_key:
        team_info = await get_user_team_info(league_key)
        if team_info:
            team_key = team_info.get("team_key")
        else:
            return {
                "error": f"Could not find your team in league {league_key}",
                "suggestion": "Provide team_key explicitly if multiple teams exist",
            }

    data = await yahoo_api_call(_roster_endpoint(team_key, week))
    try:
        roster_warnings = _verify_roster_response(data, team_key=team_key, requested_week=week)
    except ValueError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "league_key": league_key,
            "team_key": team_key,
        }
    roster = parse_team_roster(data)

    if not roster:
        logging.debug(
            f"Empty roster for team {team_key}. Raw data keys: {list(data.keys()) if data else 'None'}"
        )
        if data:
            import json

            logging.debug("Truncated raw data: %s", json.dumps(data, indent=2)[:2000])

    if team_info is None or team_info.get("team_key") != team_key:
        team_info = await get_user_team_info(league_key)

    result: dict[str, Any] = {
        "status": "success",
        "league_key": league_key,
        "team_key": team_key,
        "team_name": team_info.get("team_name") if team_info else None,
        "draft_position": team_info.get("draft_position") if team_info else None,
        "draft_grade": team_info.get("draft_grade") if team_info else None,
        "roster": roster,
    }
    if not effective_projections:
        forecast_fields = {
            "yahoo_projection",
            "sleeper_projection",
            "projection",
            "floor_projection",
            "ceiling_projection",
            "adjusted_projection",
            "projection_assessment",
            "expected_points",
            "expected_points_if_available",
            "selection_score",
        }
        result["roster"] = [
            {key: value for key, value in row.items() if key not in forecast_fields}
            for row in roster
        ]
    if roster_warnings:
        result["warnings"] = roster_warnings

    if not roster and data:
        result["debug_info"] = {
            "raw_response_keys": list(data.keys()),
            "fantasy_content_present": "fantasy_content" in data,
            "team_structure": str(type(data.get("fantasy_content", {}).get("team", []))),
            "note": "Empty roster - possibly off-season or parsing variation. Check logs for raw data.",
        }

    if not needs_enhanced and not include_weekly_context:
        return result

    try:
        from lineup_optimizer import Player, assess_player_projection, lineup_optimizer
    except ImportError as exc:
        result["note"] = f"Enhanced view unavailable: {exc}"
        if include_weekly_context:
            from src.handlers import matchup_handlers

            result["weekly_player_context"] = matchup_handlers._unavailable_weekly_player_context(
                roster,
                reason=f"Weekly player context unavailable: {exc}",
                season=None,
                target_week=week or "current",
                scoring_basis="unknown",
            )
        return result

    try:
        optimizer_payload = {
            "league_key": league_key,
            "team_key": team_key,
            "roster": roster,
        }
        players = await lineup_optimizer.parse_yahoo_roster(optimizer_payload)
        if not players:
            raise ValueError("No players parsed from roster payload")
    except Exception as exc:
        result["note"] = f"Enhanced view unavailable: {exc}"
        if include_weekly_context:
            from src.handlers import matchup_handlers

            result["weekly_player_context"] = matchup_handlers._unavailable_weekly_player_context(
                roster,
                reason=f"Weekly player context unavailable: {exc}",
                season=None,
                target_week=week or "current",
                scoring_basis="unknown",
            )
        return result

    from src.handlers import matchup_handlers

    try:
        lineup_context = await matchup_handlers._get_lineup_context(
            league_key, api_call=yahoo_api_call
        )
    except ValueError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "league_key": league_key,
            "team_key": team_key,
        }
    except Exception as exc:
        lineup_context = {"warnings": [f"League projection context unavailable: {exc}"]}
    projection_season, effective_week = matchup_handlers._bind_projection_request(
        players, lineup_context, week
    )
    try:
        roster_warnings = _verify_roster_response(
            data, team_key=team_key, requested_week=effective_week
        )
    except ValueError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "league_key": league_key,
            "team_key": team_key,
        }
    context_warnings = [*roster_warnings, *lineup_context.get("warnings", [])]
    context_warnings.extend(
        matchup_handlers._apply_roster_lock_context(
            data, players, team_key=team_key, target_week=effective_week
        )
    )
    if context_warnings:
        result["warnings"] = context_warnings
    else:
        result.pop("warnings", None)

    if include_weekly_context:
        try:
            season, target_week, cutoff_week = await matchup_handlers._resolve_matchup_period(
                season=lineup_context.get("season"),
                requested_week=week,
                yahoo_current_week=lineup_context.get("current_week"),
            )
            matchup_context = await matchup_handlers.weekly_matchup_evidence_service.get_evidence(
                matchup_handlers._weekly_player_inputs(players),
                season=season,
                target_week=target_week,
                cutoff_week=cutoff_week,
                scoring_basis=lineup_context.get("canonical_scoring_basis", "unknown"),
                include_player_context=True,
            )
            result["weekly_player_context"] = matchup_handlers._weekly_player_context(
                matchup_context, players
            )
        except Exception as exc:
            result["weekly_player_context"] = matchup_handlers._unavailable_weekly_player_context(
                players,
                reason=f"Weekly player context unavailable: {exc}",
                season=lineup_context.get("season"),
                target_week=(
                    week if week is not None else lineup_context.get("current_week") or "current"
                ),
                scoring_basis=lineup_context.get("canonical_scoring_basis", "unknown"),
            )

    if not needs_enhanced:
        return result

    if effective_external:
        try:
            players = await lineup_optimizer.enhance_with_external_data(
                players, week=effective_week, season=projection_season
            )
            from src.services.weekly_projection_runtime import enrich_weekly_projection_inputs

            players = await enrich_weekly_projection_inputs(
                players, season=projection_season, week=effective_week,
                coefficients=lineup_context.get("projection_stat_coefficients", {}),
                enabled=arguments.get("include_market_adjustments", True),
                environment_enabled=arguments.get("include_environment_adjustments", True),
            )
        except Exception as exc:
            result["note"] = f"Enhanced view unavailable: {exc}"
            return result

    from src.services.weekly_projection_runtime import refresh_live_assessment_clock

    refresh_live_assessment_clock(players)
    logger = logging.getLogger(__name__)

    def serialize_player(player: Player) -> Dict[str, Any]:
        if not effective_external:
            player = _yahoo_only_player(player)
        known_bye = player.on_bye or "ON_BYE" in player.performance_flags
        base = {
            "name": player.name,
            "player_key": player.player_key or None,
            "position": player.position,
            "team": player.team,
            "opponent": player.opponent,
            "status": player.status,
            "yahoo_projection": player.yahoo_projection if effective_projections else None,
            "sleeper_projection": (
                player.sleeper_projection if effective_projections and effective_external else None
            ),
            "weekly_evidence": serialize_weekly_evidence(
                player, include_projections=effective_projections and effective_external,
                include_recent=effective_external,
            ),
            "sleeper_id": player.sleeper_id if effective_external else None,
            "sleeper_match_method": player.sleeper_match_method if effective_external else None,
            "floor_projection": (
                player.floor_projection if effective_projections and effective_external else None
            ),
            "ceiling_projection": (
                player.ceiling_projection if effective_projections and effective_external else None
            ),
            "consistency_score": player.consistency_score if effective_external else None,
            "player_tier": player.player_tier,
            "matchup_score": player.matchup_score if effective_external else None,
            "matchup_description": player.matchup_description if effective_external else None,
            "trending_score": player.trending_score if effective_external else None,
            "risk_level": player.risk_level,
            # Expert advice fields
            "expert_tier": player.expert_tier if effective_external else None,
            "expert_recommendation": player.expert_recommendation if effective_external else None,
            "expert_confidence": player.expert_confidence if effective_external else None,
            "expert_advice": player.expert_advice if effective_external else None,
            "search_rank": player.search_rank if effective_external else None,
            # Enhancement layer fields (bye weeks, recent stats, performance flags)
            "bye_week": player.bye if effective_external else None,
            "on_bye": True if known_bye else (False if effective_external else None),
            "performance_flags": player.performance_flags if effective_external else [],
            "enhancement_context": player.enhancement_context if effective_external else None,
            "adjusted_projection": (
                player.adjusted_projection if effective_projections and effective_external else None
            ),
        }

        if effective_projections:
            zero_out = False

            if known_bye:
                zero_out = True
            elif week is not None and isinstance(player.bye, int) and player.bye == week:
                zero_out = True
                base["on_bye"] = True

            if zero_out:
                base["yahoo_projection"] = 0.0
                if effective_external:
                    base["sleeper_projection"] = 0.0
                    base["adjusted_projection"] = 0.0
                base["floor_projection"] = 0.0
                base["ceiling_projection"] = 0.0

        if effective_projections:
            assessment = assess_player_projection(player, "balanced")
            if not effective_external:
                assessment = _scope_yahoo_assessment(assessment)
            base.update(
                projection_assessment=assessment,
                expected_points=assessment.get("final_expected_points"),
                expected_points_if_available=assessment.get("final_expected_points"),
                selection_score=assessment.get("strategy_utility"),
                projection_semantics="conditional_on_availability",
                eligibility=assessment.get("eligibility"),
            )

        if effective_external and base["bye_week"] in (None, "N/A"):
            raw_payload = getattr(player, "raw", {})
            team_context = getattr(player, "team", None)
            logger.debug(
                "Roster enhancement missing bye week for %s (%s). player.bye=%r api_team=%r keys=%s",
                player.name,
                team_context,
                getattr(player, "bye", None),
                raw_payload.get("team"),
                sorted(raw_payload.keys()) if isinstance(raw_payload, dict) else None,
            )

        # Add analysis if flagged
        if effective_analysis:
            assessment = base.get("projection_assessment", {})
            unavailable = assessment.get("strategy_trace", {}).get("availability_multiplier") == 0
            points = assessment.get("final_expected_points")
            if unavailable and effective_projections:
                points = 0.0

            if known_bye:
                start_rec = "BYE WEEK - DO NOT START"
            elif unavailable:
                start_rec = "UNAVAILABLE - DO NOT START"
            elif not effective_projections:
                start_rec = "Projection output disabled"
            else:
                start_rec = "Compare with eligible alternatives using lineup optimization"

            analysis = {
                "projected_points": round(points, 1) if points is not None else None,
                "projection_semantics": (
                    "known_unavailable_zero_else_conditional_on_availability"
                    if effective_projections
                    else None
                ),
                "tier_summary": f"{player.player_tier} tier player",
                "start_recommendation": start_rec,
            }

            # Add recent performance summary if available
            if player.recent_performance_data:
                recent = player.recent_performance_data
                analysis["recent_performance"] = (
                    f"L{recent.weeks_analyzed}W avg: {recent.avg_points:.1f} pts/game"
                )
                analysis["trend"] = recent.trend.upper()

            # Add performance flag summaries
            if player.performance_flags:
                analysis["performance_alerts"] = player.performance_flags

            base["roster_analysis"] = analysis

        return base

    players_by_position: Dict[str, List[Dict[str, Any]]] = {}
    for player in players:
        bucket = players_by_position.setdefault(player.position, [])
        bucket.append(serialize_player(player))

    for bucket in players_by_position.values():
        bucket.sort(key=lambda entry: entry.get("yahoo_projection") or 0, reverse=True)

    result.update(
        {
            "total_players": len(players),
            "players_by_position": players_by_position,
            "all_players": [serialize_player(player) for player in players],
            "analysis_context": {
                "data_sources": ["Yahoo"] + (["Sleeper"] if effective_external else []),
                "data_level": data_level,
                "includes": {
                    "projections": effective_projections,
                    "external_data": effective_external,
                    "analysis": effective_analysis,
                },
                "week": week or "current",
                "enhancement_features": (
                    [
                        "Expert tiers and recommendations",
                        "Position rankings and confidence scores",
                        "Risk assessment and trending data",
                        "Sleeper player matching and IDs",
                    ]
                    if effective_external
                    else []
                ),
            },
        }
    )

    # Add overall analysis if flagged
    if effective_analysis:
        summary_points = [
            (
                0.0
                if entry.get("projection_assessment", {})
                .get("strategy_trace", {})
                .get("availability_multiplier")
                == 0
                else entry.get("expected_points_if_available")
            )
            for entry in result["all_players"]
        ]
        try:
            total_proj = (
                math.fsum(summary_points)
                if effective_projections and all(value is not None for value in summary_points)
                else None
            )
        except OverflowError:
            total_proj = None
        if total_proj is not None and not math.isfinite(total_proj):
            total_proj = None
        known_points = [value for value in summary_points if value is not None]
        try:
            known_total = (
                math.fsum(known_points) if effective_projections and known_points else None
            )
        except OverflowError:
            known_total = None
        if known_total is not None and not math.isfinite(known_total):
            known_total = None
        starters_count = sum(1 for pos in players_by_position if pos not in ["BN", "IR"])
        result["overall_analysis"] = {
            "total_projected_points": round(total_proj, 1) if total_proj is not None else None,
            "known_projected_points_total": (
                round(known_total, 1) if known_total is not None else None
            ),
            "projection_coverage": {
                "enabled": effective_projections,
                "players": len(summary_points),
                "known": len(known_points) if effective_projections else None,
                "missing": (
                    len(summary_points) - len(known_points) if effective_projections else None
                ),
                "complete": effective_projections and len(known_points) == len(summary_points),
            },
            "projection_scope": "entire_roster_including_bench_not_selected_lineup",
            "projection_semantics": (
                "known_unavailable_zero_else_conditional_on_availability"
                if effective_projections
                else None
            ),
            "starters_count": starters_count,
            "recommendation": "Use lineup optimization to compare eligible starters",
        }

    return result
