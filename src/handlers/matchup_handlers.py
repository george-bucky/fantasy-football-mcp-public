"""Matchup MCP tool handlers."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from src.services import (
    MatchupEvidenceError,
    apply_rookie_intelligence,
    empty_player_environment_context,
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


def _requested_roster_week(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Week must be an integer between 1 and 18")
    try:
        week = int(value)
    except (TypeError, ValueError):
        raise ValueError("Week must be an integer between 1 and 18") from None
    if not 1 <= week <= 18:
        raise ValueError("Week must be an integer between 1 and 18")
    return week


def _roster_endpoint(team_key: str, week: Optional[int]) -> str:
    return f"team/{team_key}/roster" + (f";week={week}" if week is not None else "")


def _authoritative_roster_slots(
    settings_data: dict, league_key: str
) -> tuple[Optional[dict], list[str]]:
    """Only complete, league-bound settings may define required starting slots."""
    from src.services.league_context import LeagueContextError, parse_yahoo_settings

    try:
        if not isinstance(settings_data, dict):
            raise ValueError("invalid league settings")
        # Used for parsing/validation only; this time is not reported as provider freshness.
        settings = parse_yahoo_settings(settings_data, league_key, datetime.now(timezone.utc))
        if not settings.evidence.complete:
            raise ValueError("incomplete league settings")
        slots = {}
        for slot in settings.roster_slots:
            if slot.is_starting is None:
                raise ValueError("unresolved roster slot")
            if slot.is_starting:
                if not slot.eligible_positions or slot.position in slots:
                    raise ValueError("unsupported or duplicate roster slot")
                slots[slot.position] = slot.count
        if not slots:
            raise ValueError("no verified starting slots")
        return slots, []
    except (LeagueContextError, ValueError, TypeError, KeyError):
        return None, ["Required slots unverified; using occupied roster positions only"]


def _verify_roster_response(
    roster_data: dict, *, team_key: str, requested_week: Optional[int]
) -> list[str]:
    """Reject explicit response mismatches without inventing missing bindings."""
    if not isinstance(roster_data, dict) or not isinstance(
        roster_data.get("fantasy_content", {}), dict
    ):
        raise ValueError("Yahoo roster response is malformed")
    team = roster_data.get("fantasy_content", {}).get("team", [])
    if not isinstance(team, list):
        raise ValueError("Yahoo roster team response is malformed")
    keys = [node["team_key"] for node in _walk_dicts(team) if "team_key" in node]
    if keys and keys != [team_key]:
        raise ValueError("Yahoo roster response does not match the requested team")
    warnings = [] if keys else ["Roster team binding was not returned by the provider"]
    rosters = [node["roster"] for node in team if isinstance(node, dict) and "roster" in node]
    if requested_week is not None:
        if len(rosters) != 1 or not isinstance(rosters[0], dict):
            warnings.append("Requested roster week was not verified in the response")
        else:
            value = rosters[0].get("week")
            coverage = rosters[0].get("coverage_type")
            if value is not None and _requested_roster_week(value) != requested_week:
                raise ValueError("Yahoo roster response does not match the requested week")
            if coverage is not None and coverage != "week":
                raise ValueError("Yahoo roster response does not use weekly coverage")
            if value is None or coverage is None:
                warnings.append("Requested roster week was not verified in the response")
    else:
        warnings.append("Roster week unverified; league current week is unavailable")
    return warnings


def _apply_roster_lock_context(
    roster_data: dict, players: Any, *, team_key: str, target_week: Optional[int]
) -> list[str]:
    """A noneditable exact-week roster locks all slots; editable does not unlock players."""
    try:
        team = roster_data["fantasy_content"]["team"]
        keys = [node["team_key"] for node in _walk_dicts(team) if "team_key" in node]
        rosters = [node["roster"] for node in team if isinstance(node, dict) and "roster" in node]
        if keys != [team_key] or len(rosters) != 1 or target_week is None:
            raise ValueError
        roster = rosters[0]
        if (
            not isinstance(roster, dict)
            or roster.get("coverage_type") != "week"
            or _requested_roster_week(roster.get("week")) != target_week
        ):
            raise ValueError
        editable = roster.get("is_editable")
        if editable is False or (type(editable) is int and editable == 0) or editable == "0":
            for player in players:
                player.lineup_locked = True
            return []
    except (KeyError, TypeError, ValueError):
        pass
    return ["Individual lineup locks unverified; verify provider lock rules before acting"]


def _bind_projection_request(
    players: Any, context: dict, requested_week: Optional[int]
) -> tuple[Optional[int], Optional[int]]:
    """Bind known request facts without inventing provider snapshot timestamps."""
    year = context.get("season")
    year = year if type(year) is int and 2000 <= year <= 2100 else None
    target = requested_week if requested_week is not None else context.get("current_week")
    try:
        target = _requested_roster_week(target)
    except ValueError:
        target = None
    for player in players:
        prior = player.projection_context if isinstance(player.projection_context, dict) else {}
        player.projection_context = {
            **prior,
            "season": year,
            "week": target,
            "scoring_basis": context.get("canonical_scoring_basis", "unknown"),
            "stat_scoring_coefficients": context.get("projection_stat_coefficients", {}),
        }
        player.scoring_format = context.get("scoring_format", "ppr")
        player.scoring_format_source = context.get("scoring_format_source", "fallback_default_ppr")
    return year, target


def _player_assessment_output(
    optimization: dict,
    players: Any,
    player: Any,
    *,
    strategy: str,
    news_context: dict,
    fallback_key: str,
) -> dict:
    """Prefer the actual selector assessment; use the shared function for mock/legacy results."""
    from lineup_optimizer import assess_player_projection

    evidence = _selection_evidence(optimization, players, player, fallback_key=fallback_key)
    assessment = evidence.get("projection_assessment")
    if not isinstance(assessment, dict):
        assessment = assess_player_projection(player, strategy, news_context)
    return {
        "projection_assessment": assessment,
        "expected_points": assessment.get("final_expected_points"),
        "expected_points_if_available": assessment.get("final_expected_points"),
        "selection_score": assessment.get("strategy_utility"),
        "projection_semantics": "conditional_on_availability",
        "eligibility": assessment.get("eligibility"),
    }


def _selection_evidence(
    optimization: dict, players: Any, player: Any, *, fallback_key: str
) -> dict:
    mapping = (
        optimization.get("strategy_summary", {})
        .get("assignment_audit", {})
        .get("evidence_keys", {})
    )
    index = next((str(i) for i, candidate in enumerate(players) if candidate is player), None)
    key = mapping.get(index, fallback_key)
    return optimization.get("player_evidence", {}).get(key, {})


def _check_explicit_context_binding(data: Any, *, field: str, expected: str, label: str) -> None:
    """Missing metadata remains unknown; explicit contradictory metadata is unusable."""
    values = [node[field] for node in _walk_dicts(data) if node.get(field) not in (None, "")]
    if values and any(str(value) != expected for value in values):
        raise ValueError(f"Yahoo {label} response does not match the requested {field}")


async def _get_lineup_context(league_key: str, *, api_call: Any = None) -> dict[str, Any]:
    api_call = api_call or yahoo_api_call
    game_key = league_key.split(".", 1)[0]
    settings_data, categories_data = await asyncio.gather(
        api_call(f"league/{league_key}/settings"),
        api_call(f"game/{game_key}/stat_categories"),
        return_exceptions=True,
    )
    if isinstance(settings_data, Exception):
        settings_data = {}
    if isinstance(categories_data, Exception):
        categories_data = {}
    _check_explicit_context_binding(
        settings_data, field="league_key", expected=league_key, label="settings"
    )
    for field in ("game_key", "game_id"):
        _check_explicit_context_binding(
            categories_data, field=field, expected=game_key, label="stat categories"
        )
    scoring_format = _lineup_scoring_format(settings_data, categories_data)
    canonical_basis = str(scoring_format or "unknown").replace("-", "_")
    if scoring_format == "custom":
        projection_format, source = "ppr", "fallback_custom_ppr"
    elif scoring_format is None:
        projection_format, source = "ppr", "fallback_default_ppr"
    else:
        projection_format, source = scoring_format, "yahoo_settings"
    roster_slots, slot_warnings = _authoritative_roster_slots(settings_data, league_key)
    from src.services.weekly_projection_runtime import scoring_coefficients

    return {
        "projection_stat_coefficients": scoring_coefficients(settings_data, categories_data),
        "roster_slots": roster_slots,
        "warnings": slot_warnings,
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


def _player_identity(player: Any) -> dict[str, Any]:
    def value(field: str) -> Any:
        return player.get(field) if isinstance(player, dict) else getattr(player, field, None)

    return {
        "name": value("name"),
        "team": value("team"),
        "position": value("position"),
    }


def _weekly_player_inputs(players: Any) -> list[dict[str, Any]]:
    return [_player_identity(player) for player in players]


def _weekly_player_context(matchup_context: dict[str, Any], players: Any) -> dict[str, Any]:
    evidence_rows = matchup_context.get("players", [])
    if len(evidence_rows) != len(players):
        raise MatchupEvidenceError("Player and weekly context counts do not match")

    rows = []
    for player, evidence in zip(players, evidence_rows):
        rows.append(
            {
                "identity": _player_identity(player),
                "matchup": {
                    key: value
                    for key, value in evidence.items()
                    if key != "player_environment_context"
                },
                "player_environment_context": evidence.get(
                    "player_environment_context",
                    empty_player_environment_context(
                        "unavailable", "Player environment context was not returned"
                    ),
                ),
            }
        )

    return {
        "enabled": True,
        "available": any(
            row["player_environment_context"].get("current_environment") is not None for row in rows
        ),
        "applied": False,
        "influence": "report_only",
        "season": matchup_context.get("season"),
        "target_week": matchup_context.get("target_week"),
        "cutoff_week": matchup_context.get("cutoff_week"),
        "canonical_scoring_basis": matchup_context.get("canonical_scoring_basis", "unknown"),
        "players": rows,
        "warnings": list(matchup_context.get("warnings", [])),
        "attribution": matchup_context.get("attribution"),
        "schedule_source": matchup_context.get("schedule_source"),
        "strength_source": matchup_context.get("strength_source"),
    }


def _unavailable_weekly_player_context(
    players: Any,
    *,
    reason: str,
    season: Optional[int],
    target_week: Any,
    scoring_basis: str,
) -> dict[str, Any]:
    evidence = _unavailable_matchup_evidence(
        reason=reason,
        season=season,
        target_week=target_week,
        scoring_basis=scoring_basis,
    )
    rows = [
        {
            "identity": _player_identity(player),
            "matchup": deepcopy(evidence),
            "player_environment_context": empty_player_environment_context(
                "source_unavailable", reason
            ),
        }
        for player in players
    ]
    return {
        "enabled": True,
        "available": False,
        "applied": False,
        "influence": "report_only",
        "season": season,
        "target_week": target_week,
        "cutoff_week": None,
        "canonical_scoring_basis": scoring_basis,
        "players": rows,
        "warnings": [reason],
        "attribution": None,
        "schedule_source": None,
        "strength_source": None,
    }


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
            - include_weekly_context: Include report-only weekly player context (default: False)

    Returns:
        Dict with optimal lineup and recommendations
    """
    league_key = arguments.get("league_key")
    try:
        week = _requested_roster_week(arguments.get("week"))
    except ValueError as exc:
        return {"status": "error", "error": str(exc), "league_key": league_key}
    strategy = arguments.get("strategy", "balanced")
    use_llm = arguments.get("use_llm", False)
    use_rookie_intelligence = arguments.get("use_rookie_intelligence", False)
    use_matchup_evidence = arguments.get("use_matchup_evidence", False)
    include_weekly_context = arguments.get("include_weekly_context", False)

    team_key = await get_user_team_key(league_key)
    if not team_key:
        return {"error": f"Could not find your team in league {league_key}"}

    try:
        roster_data = await yahoo_api_call(_roster_endpoint(team_key, week))
        roster_warnings = _verify_roster_response(
            roster_data, team_key=team_key, requested_week=week
        )
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
        effective_week = week if week is not None else lineup_context.get("current_week")
        try:
            effective_week = _requested_roster_week(effective_week)
        except ValueError:
            effective_week = None
        try:
            roster_warnings = _verify_roster_response(
                roster_data, team_key=team_key, requested_week=effective_week
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
            _apply_roster_lock_context(
                roster_data,
                players,
                team_key=team_key,
                target_week=effective_week,
            )
        )
        projection_season, effective_week = _bind_projection_request(players, lineup_context, week)
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
        matchup_context = None
        weekly_player_context = None
        if include_weekly_context or use_matchup_evidence:
            try:
                season, target_week, cutoff_week = await _resolve_matchup_period(
                    season=lineup_context["season"],
                    requested_week=week,
                    yahoo_current_week=lineup_context["current_week"],
                )
                matchup_context = await weekly_matchup_evidence_service.get_evidence(
                    _weekly_player_inputs(players),
                    season=season,
                    target_week=target_week,
                    cutoff_week=cutoff_week,
                    scoring_basis=lineup_context["canonical_scoring_basis"],
                    include_player_context=include_weekly_context,
                )
                if use_matchup_evidence:
                    _apply_weekly_matchup_evidence(players, matchup_context["players"])
                if include_weekly_context:
                    weekly_player_context = _weekly_player_context(matchup_context, players)
            except Exception as exc:
                context_reason = f"Weekly player context unavailable: {exc}"
                unavailable = _unavailable_matchup_evidence(
                    reason=f"Weekly matchup evidence unavailable: {exc}",
                    season=lineup_context["season"],
                    target_week=(
                        week if week is not None else lineup_context["current_week"] or "current"
                    ),
                    scoring_basis=lineup_context["canonical_scoring_basis"],
                )
                if use_matchup_evidence:
                    _apply_weekly_matchup_evidence(
                        players, [deepcopy(unavailable) for _ in players]
                    )
                matchup_context = {
                    "enabled": True,
                    "players": [player.weekly_matchup_evidence for player in players],
                    "warnings": [unavailable["unavailable_reason"]],
                }
                if include_weekly_context:
                    weekly_player_context = _unavailable_weekly_player_context(
                        players,
                        reason=context_reason,
                        season=lineup_context["season"],
                        target_week=(
                            week
                            if week is not None
                            else lineup_context["current_week"] or "current"
                        ),
                        scoring_basis=lineup_context["canonical_scoring_basis"],
                    )
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
        from src.services.weekly_projection_runtime import refresh_live_assessment_clock

        refresh_live_assessment_clock(players)
        optimization = await lineup_optimizer.optimize_lineup_smart(
            players,
            strategy,
            week,
            use_llm,
            decision_news=decision_news["by_player"],
            rookie_intelligence=rookie_by_identity,
            use_matchup_evidence=use_matchup_evidence,
            roster_slots=lineup_context.get("roster_slots"),
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
                "selection_evidence": _selection_evidence(
                    optimization,
                    players,
                    player,
                    fallback_key=(
                        rookie_identity_token(player.name, player.position)
                        if use_rookie_intelligence or use_matchup_evidence
                        else player.name
                    ),
                ),
            }
            starters_formatted[pos].update(
                _player_assessment_output(
                    optimization,
                    players,
                    player,
                    strategy=strategy,
                    news_context=decision_news["by_player"].get(player.name, {}),
                    fallback_key=(
                        rookie_identity_token(player.name, player.position)
                        if use_rookie_intelligence or use_matchup_evidence
                        else player.name
                    ),
                )
            )
            if use_matchup_evidence:
                starters_formatted[pos]["weekly_matchup_evidence"] = player.weekly_matchup_evidence
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
                "selection_evidence": _selection_evidence(
                    optimization,
                    players,
                    player,
                    fallback_key=(
                        rookie_identity_token(player.name, player.position)
                        if use_rookie_intelligence or use_matchup_evidence
                        else player.name
                    ),
                ),
            }
            bench_player.update(
                _player_assessment_output(
                    optimization,
                    players,
                    player,
                    strategy=strategy,
                    news_context=decision_news["by_player"].get(player.name, {}),
                    fallback_key=(
                        rookie_identity_token(player.name, player.position)
                        if use_rookie_intelligence or use_matchup_evidence
                        else player.name
                    ),
                )
            )
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
        if matchup_context is not None and use_matchup_evidence:
            result["analysis"]["weekly_matchup_evidence"] = {
                key: value for key, value in matchup_context.items() if key != "players"
            }
            warnings.extend(matchup_context.get("warnings", []))
        if weekly_player_context is not None:
            result["weekly_player_context"] = weekly_player_context
            warnings.extend(weekly_player_context.get("warnings", []))
        warnings.extend(context_warnings)
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
