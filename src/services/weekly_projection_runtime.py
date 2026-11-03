"""Read-only live collection and pure provisional market-ledger integration."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from src.services.performance_market_model import estimate_current_market_adjustment
from src.services.projection_assessment import PerformanceAdjustmentPolicy, ProjectionAdjustment
from src.services.weekly_projection_inputs import (
    WeeklyProjectionInputsService,
    projection_context_with_inputs,
    verified_sleeper_identity,
)

_COLLECTOR: WeeklyProjectionInputsService | None = None
_ENVIRONMENT_COLLECTOR: Any = None
_NAMES = {
    "passing yards": "passing_yards",
    "pass yds": "passing_yards",
    "pass yd": "passing_yards",
    "passing touchdowns": "passing_touchdowns",
    "passing tds": "passing_touchdowns",
    "pass td": "passing_touchdowns",
    "rushing touchdowns": "rushing_touchdowns",
    "rushing tds": "rushing_touchdowns",
    "rush td": "rushing_touchdowns",
    "receiving touchdowns": "receiving_touchdowns",
    "receiving tds": "receiving_touchdowns",
    "rec td": "receiving_touchdowns",
    "rushing yards": "rushing_yards",
    "rush yds": "rushing_yards",
    "rush yd": "rushing_yards",
    "receiving yards": "receiving_yards",
    "rec yds": "receiving_yards",
    "rec yd": "receiving_yards",
    "receptions": "receptions",
    "reception": "receptions",
    "rec": "receptions",
}


def _walk(value: Any):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def scoring_coefficients(settings: Mapping, categories: Mapping) -> dict[str, float]:
    """Resolve explicit linear Yahoo modifiers; never infer coefficients from PPR class."""
    names: dict[str, set[str]] = {}
    for node in _walk(categories):
        if node.get("stat_id") is not None:
            name = node.get("name") or node.get("display_name") or node.get("abbr")
            if name:
                names.setdefault(str(node["stat_id"]), set()).add(str(name).strip().lower())
    values: dict[str, set[float]] = {}
    invalid: set[str] = set()
    for node in _walk(settings):
        if node.get("stat_id") is None or "value" not in node:
            continue
        labels = names.get(str(node["stat_id"]), set())
        own = node.get("name") or node.get("display_name") or node.get("abbr")
        if own:
            labels = labels | {str(own).strip().lower()}
        mapped = {_NAMES[label] for label in labels if label in _NAMES}
        if len(mapped) != 1 or len(labels) != 1:
            invalid.update(mapped)
            continue
        stat = next(iter(mapped))
        try:
            if isinstance(node["value"], bool):
                raise ValueError
            value = float(node["value"])
            if not math.isfinite(value):
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            invalid.add(stat)
            continue
        values.setdefault(stat, set()).add(value)
    return {
        stat: next(iter(items))
        for stat, items in values.items()
        if len(items) == 1 and stat not in invalid
    }


def _time(value: Any) -> datetime:
    result = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if result.utcoffset() is None:
        raise ValueError("Aware timestamp required")
    return result.astimezone(timezone.utc)


async def enrich_weekly_projection_inputs(
    players: Sequence[Any],
    *,
    season: int | None,
    week: int | None,
    coefficients: Mapping[str, float],
    enabled: bool = True,
    environment_enabled: bool = True,
    sleeper: Any = None,
    schedule_service: Any = None,
    collector: Any = None,
    environment_collector: Any = None,
    now: Any = None,
) -> list[Any]:
    """Collect fresh full-roster inputs; independent source failures retain forecasts."""
    if not players:
        return list(players)
    clock = now or (lambda: datetime.now(timezone.utc))

    def unavailable(reason: str) -> list[Any]:
        for player in players:
            context = dict(player.projection_context)
            context.pop("weekly_projection_inputs", None)
            context.pop("game_environment_inputs", None)
            context["market_adjustments_enabled"] = enabled is True
            context["environment_adjustments_enabled"] = environment_enabled is True
            context["market_input_status"] = {"status": "unavailable", "reason": reason}
            player.projection_context = context
            player.projection_assessment = {}
        return list(players)

    if enabled is not True and environment_enabled is not True:
        return unavailable("disabled_by_request")
    if type(season) is not int or type(week) is not int or not coefficients:
        return unavailable("Exact season/week and explicit league stat scoring are required")
    if sleeper is None:
        from sleeper_api import sleeper_client

        sleeper = sleeper_client
    if schedule_service is None:
        from src.services.nflverse_matchups import weekly_matchup_evidence_service

        schedule_service = weekly_matchup_evidence_service
    try:
        state = await sleeper.get_nfl_state()
        if str(state.get("season")) != str(season) or str(state.get("week")) != str(week):
            return unavailable("Live context estimates support the verified current NFL week only")
        if state.get("season_type") not in (None, "regular"):
            return unavailable("Live context estimates support regular season only")
        bindings = await schedule_service.get_game_bindings(
            players, season=season, target_week=week
        )
        catalog = await sleeper.get_all_players()
        identities, games = [], {}
        for player, binding in zip(players, bindings, strict=True):
            if not player.player_key:
                continue
            sleeper_id = verified_sleeper_identity(player, catalog)
            identities.append(
                {
                    "player_key": player.player_key,
                    "sleeper_id": sleeper_id,
                    "sleeper_identity_verified": sleeper_id is not None,
                    "name": player.name,
                    "team": binding.get("team"),
                    "opponent": binding.get("opponent"),
                    "kickoff": binding.get("kickoff"),
                }
            )
            gid = binding.get("schedule_game_id")
            if (
                gid
                and binding.get("status") == "matched"
                and binding.get("home_away") in {"home", "away"}
            ):
                home = binding["team"] if binding["home_away"] == "home" else binding["opponent"]
                away = binding["opponent"] if binding["home_away"] == "home" else binding["team"]
                game = {
                    "game_id": gid,
                    "home_team": home,
                    "away_team": away,
                    "kickoff": binding["kickoff"],
                }
                if gid in games and games[gid] != game:
                    return unavailable("Conflicting game bindings")
                games[gid] = game
        global _COLLECTOR, _ENVIRONMENT_COLLECTOR
        if collector is None:
            if _COLLECTOR is None or _COLLECTOR.sleeper is not sleeper:
                _COLLECTOR = WeeklyProjectionInputsService(sleeper)
            collector = _COLLECTOR
        if environment_collector is None:
            from src.services.game_environment_inputs import GameEnvironmentInputsService

            if _ENVIRONMENT_COLLECTOR is None:
                _ENVIRONMENT_COLLECTOR = GameEnvironmentInputsService()
            environment_collector = _ENVIRONMENT_COLLECTOR

        async def collect_market():
            return await collector.collect(
                identities,
                season=season,
                week=week,
                current_season=season,
                current_week=week,
                scoring_coefficients=coefficients,
                include_odds=enabled is True,
            )

        async def collect_games():
            if not games:
                return {"games": {}, "warnings": []}
            return await environment_collector.collect(
                list(games.values()),
                season=season,
                week=week,
                include_weather=environment_enabled is True,
            )

        market, environment = await asyncio.gather(
            collect_market(), collect_games(), return_exceptions=True
        )
        if isinstance(market, BaseException):
            market = {"players": {}, "warnings": ["Weekly projection inputs unavailable"]}
        if isinstance(environment, BaseException):
            environment = {"games": {}, "warnings": ["Game environment inputs unavailable"]}
        finished = _time(clock()).isoformat()
        for player, binding in zip(players, bindings, strict=True):
            row = market.get("players", {}).get(player.player_key)
            if not isinstance(row, Mapping):
                row = {"available": False, "unavailable_reasons": ["No matched input report"]}
            context = projection_context_with_inputs(player.projection_context, row)
            gid = binding.get("schedule_game_id")
            game_row = environment.get("games", {}).get(gid, {})
            context["game_environment_inputs"] = {
                **game_row,
                "player_key": player.player_key,
                "season": season,
                "week": week,
                "team": binding.get("team"),
                "schedule_game_id": gid,
                "kickoff": binding.get("kickoff"),
            }
            context["schedule_game_id"] = gid
            context["live_context_collected"] = True
            if binding.get("kickoff"):
                context.update(
                    game_id=row.get("event_id") or gid, kickoff=binding["kickoff"], as_of=finished
                )
            elif row.get("event_id") and row.get("kickoff"):
                context.update(game_id=row["event_id"], kickoff=row["kickoff"], as_of=finished)
            context["market_adjustments_enabled"] = enabled is True
            context["environment_adjustments_enabled"] = environment_enabled is True
            input_available = enabled is True and bool(
                row.get("available") or row.get("game_quotes")
            )
            input_reasons = list(row.get("unavailable_reasons", []))
            if binding.get("reason"):
                input_reasons.append(str(binding["reason"]))
            if not input_available and not input_reasons:
                input_reasons.append("No verified current-game market inputs")
            context["market_input_status"] = {
                "status": "available" if input_available else "unavailable",
                "reason": (
                    (input_reasons[0] if input_reasons else None)
                    if enabled is True
                    else "disabled_by_request"
                ),
                "unavailable_reasons": (
                    list(dict.fromkeys(input_reasons))
                    if enabled is True
                    else ["disabled_by_request"]
                ),
                "warnings": market.get("warnings", []) + environment.get("warnings", []),
            }
            player.projection_context = context
            player.projection_assessment = {}
        return list(players)
    except Exception:
        return unavailable("Weekly context inputs unavailable; provider baseline retained")


def performance_adjustments(context: Mapping, request: Mapping) -> tuple[list, Any, dict | None]:
    """Recompute from raw evidence; never trust a cached delta or compound it."""
    if context.get("market_adjustments_enabled") is False:
        return [], None, None
    row = context.get("weekly_projection_inputs")
    if not isinstance(row, Mapping) or not row.get("available"):
        return [], None, None
    if request.get("scoring_basis") not in {"ppr", "half_ppr", "standard"}:
        return [], None, {"available": False, "reason": "League scoring unresolved or custom"}
    try:
        decision, kickoff = _time(request["as_of"]), _time(request["kickoff"])
        if (
            str(row["event_id"]) != request["game_id"]
            or _time(row["kickoff"]) != kickoff
            or row.get("player_key") != request["player_id"]
            or row.get("season") != request["season"]
            or row.get("week") != request["week"]
        ):
            raise ValueError("Mismatched request identity or period")
        estimate = estimate_current_market_adjustment(
            row["market_evidence"],
            row["observations"],
            event_id=row["event_id"],
            player_id=row["player_id"],
            kickoff=kickoff,
            as_of=decision,
            scoring_coefficients=row["scoring_coefficients"],
            baseline_stats=row["baseline_stats"],
            baseline_source=row.get("baseline_source"),
            target_season=request["season"],
            target_week=request["week"],
            current_period_verified=True,
        )
        if not estimate["available"]:
            return [], None, estimate
        policy = PerformanceAdjustmentPolicy(
            model_id="current_player_props",
            model_version=estimate["model_version"],
            scoring_basis=request["scoring_basis"],
            trained_through=decision,
            validated_at=decision,
            validation_reference="live-prior-stat-distribution",
            max_evidence_age_seconds=300,
            max_abs_delta_points=estimate["config"]["max_points"],
        )
        # Oldest accepted quote bounds the whole component estimate's freshness.
        quote_times = [_time(q["quote_fetched_at"]) for q in row["market_evidence"]["raw_quotes"]]
        quote_times += [
            _time(q["provider_observed_at"]) for q in row["market_evidence"]["raw_quotes"]
        ]
        evidence_time = min(quote_times)
        adjustments = [
            ProjectionAdjustment(
                adjustment_id=f"market:{row['event_id']}:{request['player_id']}:{component['stat']}",
                kind="market",
                delta_points=component["point_delta"],
                model_id=policy.model_id,
                model_version=policy.model_version,
                player_id=request["player_id"],
                game_id=row["event_id"],
                season=request["season"],
                week=request["week"],
                scoring_basis=request["scoring_basis"],
                source_id=f"propline:{row['event_id']}",
                evidence_as_of=evidence_time,
                valid_at=kickoff,
                estimate_semantics="expected_value",
            )
            for component in estimate["components"]
        ]
        return adjustments, policy, estimate
    except (KeyError, TypeError, ValueError, OverflowError):
        return (
            [],
            None,
            {"available": False, "reason": "Incomplete or mismatched market model inputs"},
        )


def weekly_context_adjustments(context: Mapping, request: Mapping) -> tuple[list, Any, Any, dict]:
    """Apply props first, otherwise disjoint TD-index and volume/weather components."""
    from src.services.environment_projection_model import estimate_environment_adjustment
    from src.services.game_market_model import estimate_game_market_adjustment
    from src.services.projection_assessment import ContextAdjustmentPolicy

    prop_adjustments, prop_policy, prop_report = performance_adjustments(context, request)
    details: dict[str, Any] = {"game_market": None, "environment": None}
    row, game = context.get("weekly_projection_inputs"), context.get("game_environment_inputs")
    if not isinstance(row, Mapping) or not isinstance(game, Mapping):
        return prop_adjustments, prop_policy, prop_report, details
    try:
        decision, kickoff = _time(request["as_of"]), _time(request["kickoff"])
        if (
            row.get("player_key") != request["player_id"]
            or row.get("season") != request["season"]
            or row.get("week") != request["week"]
            or game.get("player_key") != request["player_id"]
            or game.get("season") != request["season"]
            or game.get("week") != request["week"]
            or game.get("schedule_game_id") != context.get("schedule_game_id")
            or _time(game.get("kickoff")) != kickoff
        ):
            raise ValueError("Context identity or period mismatch")
        props_used = bool(prop_report and prop_report.get("available") and prop_adjustments)
        if context.get("environment_adjustments_enabled") is not False:
            details["environment"] = estimate_environment_adjustment(
                game.get("weather", {}),
                event_id=game["schedule_game_id"],
                kickoff=kickoff,
                as_of=decision,
                baseline_stats=row.get("baseline_stats", {}),
                baseline_source=row.get("baseline_source"),
                scoring_coefficients=row.get("scoring_coefficients", {}),
                relevant_player_props_applied=props_used,
            )
        else:
            details["environment"] = {"available": False, "reason": "disabled_by_request"}
        if props_used:
            details["game_market"] = {
                "available": False,
                "reason": "suppressed_overlapping_player_props",
            }
            return prop_adjustments, prop_policy, prop_report, details
        selected: list[tuple[str, Mapping, float, datetime, str]] = []
        try:
            if context.get("market_adjustments_enabled") is not False and row.get("game_quotes"):
                if (
                    row.get("event_id") != request["game_id"]
                    or _time(row.get("kickoff")) != kickoff
                ):
                    raise ValueError("Game market binding mismatch")
                history = [
                    {**sample, "team_key": row.get("event_team_key")}
                    for sample in game.get("team_points_history", [])
                    if isinstance(sample, Mapping) and sample.get("team") == game.get("team")
                ]
                game_report = estimate_game_market_adjustment(
                    row["game_quotes"],
                    history,
                    event_id=row["event_id"],
                    team_key=row["event_team_key"],
                    kickoff=kickoff,
                    as_of=decision,
                    baseline_stats=row.get("baseline_stats", {}),
                    baseline_source=row.get("baseline_source"),
                    scoring_coefficients=row.get("scoring_coefficients", {}),
                    target_season=request["season"],
                    target_week=request["week"],
                    current_period_verified=True,
                )
                details["game_market"] = game_report
                if game_report.get("available"):
                    chosen = [
                        quote for book in game_report["book_indices"] for quote in book["quotes"]
                    ]
                    age = min(
                        _time(q[field])
                        for q in chosen
                        for field in ("quote_fetched_at", "provider_observed_at")
                    )
                    selected.extend(
                        (
                            "market",
                            component,
                            component["point_delta"],
                            age,
                            f"propline:{row['event_id']}",
                        )
                        for component in game_report["components"]
                    )
            else:
                details["game_market"] = {
                    "available": False,
                    "reason": (
                        "disabled_by_request"
                        if context.get("market_adjustments_enabled") is False
                        else "No current game market quotes"
                    ),
                }
        except (KeyError, TypeError, ValueError, OverflowError):
            details["game_market"] = {
                "available": False,
                "reason": "Incomplete or mismatched game-market inputs",
            }
        weather_report = details["environment"]
        if weather_report and weather_report.get("available"):
            age = _time(weather_report["evidence_as_of"])
            selected.extend(
                (
                    "environment",
                    component,
                    component["delta_points"],
                    age,
                    "NWS:" + str(game["schedule_game_id"]),
                )
                for component in weather_report["candidate_components"]
            )
        if not selected:
            return [], None, prop_report, details
        absolute = math.fsum(abs(delta) for _, _, delta, _, _ in selected)
        scale = min(1.0, 2.0 / absolute) if absolute else 1.0
        if scale < 1.0:
            scale = math.nextafter(scale, 0.0)
        details["shared_absolute_budget_points"] = 2.0
        details["shared_budget_scale"] = scale
        policy = ContextAdjustmentPolicy(
            model_id="weekly_context",
            model_version="game_weather_rules_v1_provisional",
            scoring_basis=request["scoring_basis"],
            trained_through=decision,
            validated_at=decision,
            validation_reference="documented-game-index-and-weather-rules-no-backtest",
            max_evidence_age_seconds=300,
            max_abs_delta_points=2.0,
        )
        adjustments = [
            ProjectionAdjustment(
                adjustment_id=f"{kind}:{request['game_id']}:{request['player_id']}:{component['stat']}",
                kind=kind,
                delta_points=delta * scale,
                model_id=policy.model_id,
                model_version=policy.model_version,
                player_id=request["player_id"],
                game_id=request["game_id"],
                season=request["season"],
                week=request["week"],
                scoring_basis=request["scoring_basis"],
                source_id=source,
                evidence_as_of=evidence,
                valid_at=kickoff,
                estimate_semantics="forecast" if kind == "environment" else "game_scoring_index",
                exposure_verified=kind == "environment",
            )
            for kind, component, delta, evidence, source in selected
        ]
        return adjustments, policy, prop_report, details
    except (KeyError, TypeError, ValueError, OverflowError):
        details["reason"] = "Incomplete or mismatched game/environment inputs"
        return prop_adjustments, prop_policy, prop_report, details


def refresh_live_assessment_clock(players: Sequence[Any], *, as_of: datetime | None = None) -> None:
    """Revalidate current inputs after any later caller IO, including kickoff crossings."""
    cutoff = _time(as_of if as_of is not None else datetime.now(timezone.utc)).isoformat()
    for player in players:
        if player.projection_context.get("live_context_collected") is True:
            player.projection_context = {**player.projection_context, "as_of": cutoff}
            player.projection_assessment = {}
