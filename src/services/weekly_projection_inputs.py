"""Bounded live-week inputs for auditable roster-wide market adjustments.

No scheduler, persistence, authentication setup or name-fuzzy crosswalk. Names
only select provider rows; exact name, team pair and kickoff establish a unique
nonempty provider identity within this request. Historical samples are observed
weekly actuals, not archival as-of snapshots or invented provider game IDs.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from src.services.market_evidence import assess_player_markets
from src.services.nflverse_matchups import canonical_team
from src.services.propline_service import PLAYER_MARKETS, TEAM_ALIASES, TEAM_MARKETS

STAT_KEYS = {
    "passing_yards": "pass_yd",
    "passing_touchdowns": "pass_td",
    "rushing_yards": "rush_yd",
    "rushing_touchdowns": "rush_td",
    "receiving_yards": "rec_yd",
    "receiving_touchdowns": "rec_td",
    "receptions": "rec",
}


def _time(value: Any) -> datetime | None:
    try:
        result = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
        return result.astimezone(timezone.utc) if result.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _name(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _team_keys(value: Any) -> frozenset[str]:
    normalized = _name(value).replace("_", " ").replace("-", " ")
    return TEAM_ALIASES.get(normalized, frozenset())


def _stats(row: Any) -> dict[str, float]:
    if not isinstance(row, Mapping):
        return {}
    raw = row.get("stats", row.get("projected_stats", row))
    if not isinstance(raw, Mapping):
        return {}
    result = {}
    for canonical, key in STAT_KEYS.items():
        value = raw.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (OverflowError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        if (
            canonical
            in {"receptions", "passing_touchdowns", "rushing_touchdowns", "receiving_touchdowns"}
            and number < 0
        ):
            continue
        result[canonical] = number
    return result


def verified_sleeper_identity(player: Any, catalog: Mapping[str, Any]) -> str | None:
    """Verify an existing ID against exact full name/team; never trust fuzzy match tags."""
    sleeper_id = str(getattr(player, "sleeper_id", "") or "")
    row = catalog.get(sleeper_id)
    if not sleeper_id or not isinstance(row, Mapping):
        return None
    full_name = (
        row.get("full_name")
        or " ".join(str(row.get(part) or "") for part in ("first_name", "last_name")).strip()
    )
    team = canonical_team(getattr(player, "team", None))
    if (
        _name(full_name) == _name(getattr(player, "name", None))
        and team is not None
        and canonical_team(row.get("team")) == team
    ):
        return sleeper_id
    return None


def projection_context_with_inputs(context: Mapping[str, Any], report: Mapping[str, Any]) -> dict:
    """Return a new context, preserving caller provenance and other context fields."""
    result = copy.deepcopy(dict(context))
    result["weekly_projection_inputs"] = copy.deepcopy(dict(report))
    return result


class WeeklyProjectionInputsService:
    """Collect current-week inputs with a strict per-request provider-call budget.

    ``current_season/current_week`` must come from verified live Sleeper state.
    Every identity needs player_key, sleeper_id, sleeper_identity_verified=True,
    full name, team, opponent and aware kickoff. Optional exact event_id and
    provider_entity_id further constrain the request-local provider match.
    ``as_of`` is a live request start, not a historical replay cutoff. Returned
    as_of is actual completion and all fetch timestamps remain explicit.
    """

    def __init__(
        self,
        sleeper_client: Any,
        *,
        odds_fetcher: Callable[..., Any] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        history_weeks: int = 12,
        max_calls: int = 20,
        timeout_seconds: float = 20,
        cache_ttl_seconds: float = 60,
        cache_size: int = 24,
    ) -> None:
        if (
            not 1 <= history_weeks <= 17
            or not 1 <= max_calls <= 40
            or cache_size < 1
            or timeout_seconds <= 0
            or cache_ttl_seconds < 0
        ):
            raise ValueError("Invalid collection budget")
        if odds_fetcher is None:
            from src.services.propline_service import get_sportsbook_odds

            odds_fetcher = get_sportsbook_odds
        self.sleeper = sleeper_client
        self.odds_fetcher = odds_fetcher
        self.now = now
        self.history_weeks = history_weeks
        self.max_calls = max_calls
        self.timeout = timeout_seconds
        self.ttl = cache_ttl_seconds
        self.cache_size = cache_size
        self._cache: OrderedDict[tuple, tuple[datetime, Any]] = OrderedDict()

    async def collect(
        self,
        identities: Sequence[Mapping[str, Any]],
        *,
        season: int,
        week: int,
        current_season: int,
        current_week: int,
        scoring_coefficients: Mapping[str, Any],
        as_of: datetime | None = None,
        include_odds: bool = True,
    ) -> dict[str, Any]:
        start = _time(self.now())
        requested = _time(as_of) if as_of is not None else start
        if (
            start is None
            or requested is None
            or abs((start - requested).total_seconds()) > 60
            or type(season) is not int
            or type(week) is not int
            or not 1 <= week <= 18
            or not 2000 <= season <= 2100
            or type(current_season) is not int
            or type(current_week) is not int
            or (season, week) != (current_season, current_week)
        ):
            raise ValueError("Verified current season/week and live aware as_of required")
        if len(identities) > 100:
            raise ValueError("At most 100 roster identities per request")
        keys = [str(row.get("player_key") or "") for row in identities]
        if any(not key for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("Unique nonempty Yahoo player keys required")
        warnings: list[str] = []
        calls = 0
        source_ids = [str(row.get("sleeper_id") or "") for row in identities]

        async def fetch(key: tuple, operation: Callable[[], Any]) -> tuple[Any, datetime | None]:
            nonlocal calls
            cached = self._cache.get(key)
            current = _time(self.now())
            if cached and current and 0 <= (current - cached[0]).total_seconds() <= self.ttl:
                self._cache.move_to_end(key)
                return copy.deepcopy(cached[1]), cached[0]
            if calls >= self.max_calls:
                warnings.append("provider_call_budget_exhausted")
                return {}, None
            calls += 1
            try:
                raw = await asyncio.wait_for(operation(), timeout=min(5, self.timeout))
                fetched = _time(self.now())
                if fetched is None:
                    raise ValueError("Invalid clock")
                self._cache[key] = (fetched, copy.deepcopy(raw))
                self._cache.move_to_end(key)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
                return raw, fetched
            except Exception:
                # Provider exceptions can contain request URLs/headers: never serialize them.
                warnings.append(f"{key[0]}_fetch_failed")
                return {}, None

        valid = []
        reports: dict[str, dict[str, Any]] = {}
        for identity in identities:
            row = dict(identity)
            key = str(row["player_key"])
            report = {
                "available": False,
                "unavailable_reasons": [],
                "player_key": key,
                "baseline_stats": {},
                "baseline_source": None,
                "observations": [],
                "scoring_coefficients": dict(scoring_coefficients),
                "season": season,
                "week": week,
                "history_semantics": "live_retrieval_of_prior_week_actuals_not_archival_asof",
            }
            reports[key] = report
            team, opponent = canonical_team(row.get("team")), canonical_team(row.get("opponent"))
            kickoff = _time(row.get("kickoff"))
            if (
                row.get("sleeper_identity_verified") is not True
                or source_ids.count(str(row.get("sleeper_id") or "")) > 1
                or not str(row.get("sleeper_id") or "")
                or not _name(row.get("name"))
                or team is None
                or opponent is None
                or team == opponent
                or kickoff is None
                or kickoff <= start
            ):
                report["unavailable_reasons"].append("unverified_identity_or_upcoming_game")
                continue
            row.update(team=team, opponent=opponent, kickoff=kickoff)
            valid.append(row)

        async def gather() -> None:
            if not valid:
                return
            projections, projected_at = await fetch(
                ("projections", season, week), lambda: self.sleeper.get_projections(season, week)
            )
            for row in valid:
                report = reports[str(row["player_key"])]
                projection = (
                    projections.get(str(row["sleeper_id"]), {})
                    if isinstance(projections, Mapping)
                    else {}
                )
                if (
                    isinstance(projection, Mapping)
                    and projection.get("projection_source") == "sleeper_api"
                    and str(projection.get("season", season)) == str(season)
                    and str(projection.get("week", week)) == str(week)
                ):
                    report.update(baseline_stats=_stats(projection), baseline_source="sleeper_api")
                report["source_fetched_at"] = {
                    "projections": projected_at.isoformat() if projected_at else None
                }
                report["kickoff"] = row["kickoff"].isoformat()
                if not report["baseline_stats"]:
                    report["unavailable_reasons"].append("genuine_stat_baseline_missing")
                if not include_odds:
                    report.update(
                        available=bool(report["baseline_stats"]),
                        input_scope="baseline_only_odds_disabled",
                    )
            if not include_odds:
                return
            histories = {}
            for prior in range(max(1, week - self.history_weeks), week):
                histories[prior] = await fetch(
                    ("stats", season, prior),
                    lambda prior=prior: self.sleeper.get_player_stats(season, prior),
                )
            for offset in range(0, len(valid), 10):
                chunk = valid[offset : offset + 10]
                names = list(dict.fromkeys(row["name"] for row in chunk))
                # Duplicate names with different teams are still independently verified below.
                context = {row["name"]: {"team": row["team"]} for row in chunk}
                teams = list(dict.fromkeys(row["team"] for row in chunk))
                odds, odds_at = await fetch(
                    (
                        "odds_with_games",
                        tuple((row["player_key"], str(row["kickoff"])) for row in chunk),
                    ),
                    lambda names=names, context=context, teams=teams: self.odds_fetcher(
                        players=names,
                        teams=teams,
                        scope="next_game",
                        markets=[*PLAYER_MARKETS, *TEAM_MARKETS],
                        player_context=context,
                    ),
                )
                quotes = odds.get("results", []) if isinstance(odds, Mapping) else []
                if isinstance(odds, Mapping):
                    warnings.extend(str(item) for item in odds.get("warnings", []))
                for row in chunk:
                    report = reports[str(row["player_key"])]
                    sid = str(row["sleeper_id"])
                    report["source_fetched_at"]["odds"] = odds_at.isoformat() if odds_at else None
                    game_quotes = self._match_game_quotes(row, quotes)
                    events = {str(quote["event_id"]) for quote in game_quotes}
                    if len(events) == 1:
                        report["event_id"] = next(iter(events))
                        report["game_quotes"] = game_quotes
                        event = game_quotes[0]["event"]
                        side = next(
                            (
                                side
                                for side in ("home", "away")
                                if _team_keys(row["team"])
                                & (
                                    _team_keys(event.get(f"{side}_team_key"))
                                    | _team_keys(event.get(f"{side}_team"))
                                )
                            ),
                            None,
                        )
                        report["event_team_key"] = event.get(f"{side}_team_key") if side else None
                    elif len(events) > 1:
                        report["unavailable_reasons"].append("ambiguous_game_market_event")
                    matched = self._match_quotes(row, quotes)
                    if report.get("event_id"):
                        matched = [
                            quote
                            for quote in matched
                            if str(quote["event_id"]) == report["event_id"]
                        ]
                    bindings = {(str(q["event_id"]), str(q["provider_entity_id"])) for q in matched}
                    if len(bindings) != 1:
                        report["unavailable_reasons"].append(
                            "ambiguous_provider_identity"
                            if bindings
                            else "provider_identity_or_game_missing"
                        )
                        continue
                    event_id, player_id = next(iter(bindings))
                    report.update(
                        event_id=event_id, player_id=player_id, kickoff=row["kickoff"].isoformat()
                    )
                    report["identity_provenance"] = (
                        "exact_full_name_team_pair_kickoff_unique_provider_id"
                    )
                    for prior, (payload, known) in histories.items():
                        actual = payload.get(sid, {}) if isinstance(payload, Mapping) else {}
                        if known is None or not isinstance(actual, Mapping):
                            continue
                        if (
                            actual.get("stats_source") != "sleeper_api"
                            or str(actual.get("season", season)) != str(season)
                            or str(actual.get("week", prior)) != str(prior)
                        ):
                            continue
                        for stat, value in _stats(actual).items():
                            report["observations"].append(
                                {
                                    "player_id": player_id,
                                    "stat": stat,
                                    "value": value,
                                    "period": "full_game",
                                    "period_id": f"{season}:regular:{prior}",
                                    "season": season,
                                    "week": prior,
                                    "season_type": "regular",
                                    "known_at": known.isoformat(),
                                    "source": "sleeper_api",
                                    "history_mode": "live_prior_week_actuals",
                                }
                            )
                    report["raw_quotes"] = matched

        try:
            await asyncio.wait_for(gather(), timeout=self.timeout)
        except asyncio.TimeoutError:
            warnings.append("collection_deadline_exceeded")
        finished = _time(self.now())
        assert finished is not None
        for report in reports.values():
            report["as_of"] = finished.isoformat()
            if report.get("player_id"):
                report["market_evidence"] = assess_player_markets(
                    report.pop("raw_quotes", []),
                    event_id=report["event_id"],
                    player_id=report["player_id"],
                    kickoff=_time(report["kickoff"]),
                    as_of=finished,
                )
                report["available"] = bool(
                    report["market_evidence"]["available"] and report["baseline_stats"]
                )
        return {
            "as_of": finished.isoformat(),
            "players": reports,
            "warnings": list(dict.fromkeys(warnings)),
            "provider_calls": calls,
            "live_current_period": {"season": season, "week": week},
        }

    @staticmethod
    def _match_game_quotes(identity: Mapping[str, Any], quotes: Any) -> list[dict]:
        if not isinstance(quotes, list):
            return []
        matched = []
        seen = set()
        for quote in quotes:
            if not isinstance(quote, Mapping) or quote.get("market_key") not in TEAM_MARKETS:
                continue
            event = quote.get("event", {})
            if not isinstance(event, Mapping):
                continue
            pair = [
                _team_keys(event.get(f"{side}_team_key")) | _team_keys(event.get(f"{side}_team"))
                for side in ("home", "away")
            ]
            expected = [_team_keys(identity["team"]), _team_keys(identity["opponent"])]
            if not (
                (pair[0] & expected[0] and pair[1] & expected[1])
                or (pair[1] & expected[0] and pair[0] & expected[1])
            ):
                continue
            if (
                not quote.get("event_id")
                or quote.get("scope") != "next_game"
                or _time(event.get("commence_time")) != identity["kickoff"]
                or (
                    identity.get("event_id") and str(quote["event_id"]) != str(identity["event_id"])
                )
            ):
                continue
            fingerprint = json.dumps(
                {
                    key: value
                    for key, value in quote.items()
                    if key not in {"query", "entity_type", "matched_name"}
                },
                sort_keys=True,
                default=str,
            )
            if fingerprint not in seen:
                seen.add(fingerprint)
                matched.append(dict(quote))
        return matched

    @staticmethod
    def _match_quotes(identity: Mapping[str, Any], quotes: Any) -> list[dict]:
        if not isinstance(quotes, list):
            return []
        matches = []
        for quote in quotes:
            if not isinstance(quote, Mapping):
                continue
            event = quote.get("event", {})
            if not isinstance(event, Mapping):
                continue
            pair = [
                _team_keys(event.get(f"{side}_team_key")) | _team_keys(event.get(f"{side}_team"))
                for side in ("home", "away")
            ]
            expected = [_team_keys(identity["team"]), _team_keys(identity["opponent"])]
            if not (
                (pair[0] & expected[0] and pair[1] & expected[1])
                or (pair[1] & expected[0] and pair[0] & expected[1])
            ):
                continue
            if (
                _name(quote.get("subject")) != _name(identity["name"])
                or not quote.get("provider_entity_id")
                or not quote.get("event_id")
                or _time(event.get("commence_time")) != identity["kickoff"]
                or (
                    identity.get("event_id") and str(quote["event_id"]) != str(identity["event_id"])
                )
                or (
                    identity.get("provider_entity_id")
                    and str(quote["provider_entity_id"]) != str(identity["provider_entity_id"])
                )
            ):
                continue
            matches.append(dict(quote))
        return matches
