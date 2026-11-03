"""Pregame probability evidence from exact, timestamped sportsbook quotes.

A fair probability at a threshold is not an expected stat value. This module
deliberately does not fabricate a distribution, fantasy projection, source weight
or touchdown count. Numerical projection effects need a separately validated
distribution policy. No provider calls or credentials are used here.
"""

from __future__ import annotations

import copy
import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

STAT_MARKETS = {
    "player_pass_yds": "passing_yards",
    "player_pass_tds": "passing_touchdowns",
    "player_rush_yds": "rushing_yards",
    "player_reception_yds": "receiving_yards",
    "player_receptions": "receptions",
    "player_anytime_td": "at_least_one_touchdown",
}
_FORMAT_SOURCES = frozenset({"provider", "propline_documented_default"})
_QUOTED_BOOK_CONTRACTS = frozenset(
    {"bovada", "draftkings", "fanduel", "betmgm", "betrivers", "pinnacle", "underdog"}
)
_PRICING_SOURCES = frozenset({"provider", "propline_documented_contract"})
SYNTHETIC_PRICE_FLAGS = ("synthetic_price", "is_synthetic", "price_is_synthetic")


def quote_pricing_semantics(row: Mapping[str, Any]) -> tuple[str, str]:
    """Separate single-leg prices from DFS placeholders using provenance, not price.

    PropLine documents PrizePicks +100/+100 as synthetic. Underdog's actual
    two-way prices already include its payout multiplier and remain usable.
    https://prop-line.com/docs (Bookmakers and Get Odds examples).
    """
    book = str(row.get("bookmaker_key") or "").strip().casefold()
    if book == "prizepicks":
        return "synthetic_dfs", "propline_documented_contract"
    if any(
        row.get(key) is True
        or (isinstance(row.get(key), str) and row[key].casefold() in {"true", "synthetic"})
        for key in SYNTHETIC_PRICE_FLAGS
    ):
        return "synthetic_dfs", "provider"
    explicit = row.get("pricing_semantics")
    if explicit is not None:
        source = row.get("pricing_semantics_source")
        if (
            explicit == "quoted_single_leg"
            and isinstance(source, str)
            and source in _PRICING_SOURCES
        ):
            return "quoted_single_leg", source
        if explicit in ("synthetic", "synthetic_dfs"):
            return "synthetic_dfs", "provider"
        return "unknown", "unavailable"
    if book in _QUOTED_BOOK_CONTRACTS:
        return "quoted_single_leg", "propline_documented_contract"
    return "unknown", "unavailable"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(timezone.utc)


def implied_probability(price: Any, odds_format: str) -> float:
    """Convert a verified odds format; never guess a format from the number."""
    number = _number(price)
    if number is None:
        raise ValueError("Invalid finite price")
    if odds_format == "american" and abs(number) >= 100:
        return 100 / (number + 100) if number > 0 else -number / (-number + 100)
    if odds_format == "decimal" and number > 1:
        return 1 / number
    raise ValueError("Invalid or unsupported odds format/price")


def _quote_reason(
    row: Mapping[str, Any],
    *,
    event_id: str,
    player_id: str,
    kickoff: datetime,
    as_of: datetime,
    period: str,
    max_age_seconds: float,
) -> str | None:
    if str(row.get("event_id") or "") != event_id:
        return "event_mismatch"
    if str(row.get("provider_entity_id") or "") != player_id:
        return "player_id_mismatch"
    if row.get("scope") != "next_game":
        return "not_next_game"
    period_verified = row.get("period_source") == "provider" or (
        row.get("period_source") == "propline_documented_contract"
        and row.get("period_reference") == "https://prop-line.com/docs"
        and period == "full_game"
    )
    if row.get("period") != period or not period_verified:
        return "unverified_period"
    if row.get("market_suspended_at") is not None and row.get("market_suspended_at") != "":
        return "market_suspended"
    event = row.get("event")
    if not isinstance(event, Mapping) or _timestamp(event.get("commence_time")) != kickoff:
        return "kickoff_mismatch"
    format_source = row.get("odds_format_source")
    if not isinstance(format_source, str) or format_source not in _FORMAT_SOURCES:
        return "unverified_odds_format"
    market = row.get("market_key")
    if not isinstance(market, str) or market not in STAT_MARKETS:
        return "unsupported_player_market"
    if not isinstance(row.get("bookmaker_key"), str) or not row["bookmaker_key"].strip():
        return "missing_bookmaker"
    pricing, _ = quote_pricing_semantics(row)
    if pricing == "synthetic_dfs":
        return "synthetic_price_not_single_leg_odds"
    if pricing != "quoted_single_leg":
        return "unverified_pricing_semantics"
    # Fetch time establishes the as-of snapshot; provider time establishes quote freshness.
    fetched = _timestamp(row.get("quote_fetched_at"))
    observed = _timestamp(row.get("provider_observed_at"))
    if fetched is None or observed is None:
        return "missing_quote_time"
    if fetched > as_of or observed > as_of or observed > fetched:
        return "future_quote"
    if (as_of - fetched).total_seconds() > max_age_seconds or (
        as_of - observed
    ).total_seconds() > max_age_seconds:
        return "stale_quote"
    for key in ("book_updated_at", "last_change_at"):
        if row.get(key) is not None:
            value = _timestamp(row[key])
            if value is None or value > as_of or value > fetched:
                return "invalid_quote_time"
    try:
        implied_probability(row.get("price"), str(row.get("odds_format") or ""))
    except ValueError:
        return "invalid_price"
    return None


def assess_player_markets(
    rows: Sequence[Mapping[str, Any]],
    *,
    event_id: str,
    player_id: str,
    kickoff: datetime,
    as_of: datetime,
    period: str = "full_game",
    max_age_seconds: float = 300,
) -> dict[str, Any]:
    """Build auditable fair-probability constraints; no projection adjustment is applied.

    IDs must be established by the caller's validated mapping. Name matches alone
    are insufficient. Only one exact event, full-game period and pregame snapshot
    are accepted. Integer-line push semantics are deliberately unsupported.
    """
    kickoff_time, decision_time = _timestamp(kickoff), _timestamp(as_of)
    age = _number(max_age_seconds)
    if (
        not isinstance(event_id, str)
        or not event_id.strip()
        or not isinstance(player_id, str)
        or not player_id.strip()
        or kickoff_time is None
        or decision_time is None
        or age is None
        or age <= 0
        or period != "full_game"
    ):
        raise ValueError("Verified event/player IDs, aware times and a positive age limit required")
    rejected: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, float | None], list[Mapping[str, Any]]] = defaultdict(list)
    raw_quotes: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            rejected.append({"row": index, "reason": "invalid_quote"})
            continue
        if decision_time >= kickoff_time:
            rejected.append({"row": index, "reason": "game_started"})
            continue
        reason = _quote_reason(
            row,
            event_id=event_id,
            player_id=player_id,
            kickoff=kickoff_time,
            as_of=decision_time,
            period=period,
            max_age_seconds=age,
        )
        if reason:
            rejected.append({"row": index, "reason": reason})
            continue
        market = row["market_key"]
        selection = str(row.get("selection") or "").strip().casefold()
        if market == "player_anytime_td":
            if selection not in {"yes", "no"}:
                rejected.append({"row": index, "reason": "missing_exhaustive_td_pair"})
                continue
            line = None
        else:
            line = _number(row.get("line"))
            if selection not in {"over", "under"} or line is None or line < 0:
                rejected.append({"row": index, "reason": "invalid_threshold_outcome"})
                continue
            if line.is_integer():
                rejected.append({"row": index, "reason": "push_probability_unknown"})
                continue
        raw_quote = copy.deepcopy(dict(row))
        pricing, pricing_source = quote_pricing_semantics(row)
        raw_quote.update({"pricing_semantics": pricing, "pricing_semantics_source": pricing_source})
        raw_quotes.append(raw_quote)
        groups[(row["bookmaker_key"], market, line)].append(row)

    probabilities: list[dict[str, Any]] = []
    for (book, market, line), quotes in sorted(groups.items()):
        expected = {"yes", "no"} if market == "player_anytime_td" else {"over", "under"}
        by_side: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in quotes:
            by_side[str(row["selection"]).strip().casefold()].append(row)
        if set(by_side) != expected:
            rejected.append(
                {"bookmaker_key": book, "market_key": market, "reason": "incomplete_pair"}
            )
            continue
        # Duplicate delivery is harmless; conflicting prices or snapshots cannot be mixed.
        unique = {
            side: {
                (
                    str(row["price"]),
                    row["odds_format"],
                    row["quote_fetched_at"],
                    row["provider_observed_at"],
                )
                for row in values
            }
            for side, values in by_side.items()
        }
        snapshots = {(row["quote_fetched_at"], row["provider_observed_at"]) for row in quotes}
        if any(len(values) != 1 for values in unique.values()) or len(snapshots) != 1:
            rejected.append(
                {"bookmaker_key": book, "market_key": market, "reason": "conflicting_pair"}
            )
            continue
        formats = {row["odds_format"] for row in quotes}
        if len(formats) != 1:
            rejected.append(
                {"bookmaker_key": book, "market_key": market, "reason": "mixed_pair_format"}
            )
            continue
        implied = {
            side: implied_probability(values[0]["price"], values[0]["odds_format"])
            for side, values in by_side.items()
        }
        overround = sum(implied.values())
        if overround < 1 or overround >= 2:
            rejected.append(
                {"bookmaker_key": book, "market_key": market, "reason": "invalid_overround"}
            )
            continue
        first = "yes" if market == "player_anytime_td" else "over"
        second = "no" if first == "yes" else "under"
        probabilities.append(
            {
                "bookmaker_key": book,
                "market_key": market,
                "stat": STAT_MARKETS[market],
                "threshold": line,
                "probabilities": {
                    first: implied[first] / overround,
                    second: implied[second] / overround,
                },
                "margin_removal": "proportional_two_outcome",
                "calibrated": False,
                "pricing_semantics": "quoted_single_leg",
                "pricing_semantics_source": quote_pricing_semantics(quotes[0])[1],
                "quoted_overround": overround - 1,
                "semantics": (
                    "probability_at_least_one_not_expected_count"
                    if first == "yes"
                    else "probability_threshold_not_expected_value"
                ),
                "quote_fetched_at": quotes[0]["quote_fetched_at"],
                "provider_observed_at": quotes[0]["provider_observed_at"],
            }
        )

    invalid_book_markets: set[tuple[str, str]] = set()
    by_book_market: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in probabilities:
        if item["threshold"] is not None:
            by_book_market[(item["bookmaker_key"], item["market_key"])].append(item)
    for (book, market), values in by_book_market.items():
        ordered = sorted(values, key=lambda value: value["threshold"])
        if any(
            right["probabilities"]["over"] > left["probabilities"]["over"]
            for left, right in zip(ordered, ordered[1:])
        ):
            invalid_book_markets.add((book, market))
            rejected.append(
                {"bookmaker_key": book, "market_key": market, "reason": "non_monotone_thresholds"}
            )
    probabilities = [
        item
        for item in probabilities
        if (item["bookmaker_key"], item["market_key"]) not in invalid_book_markets
    ]

    consensus_groups: dict[tuple[str, float | None], list[dict[str, Any]]] = defaultdict(list)
    for item in probabilities:
        consensus_groups[(item["market_key"], item["threshold"])].append(item)
    constraints = []
    for (market, threshold), values in sorted(consensus_groups.items()):
        side = "yes" if market == "player_anytime_td" else "over"
        fair = [value["probabilities"][side] for value in values]
        constraints.append(
            {
                "market_key": market,
                "stat": STAT_MARKETS[market],
                "threshold": threshold,
                "side": side,
                "fair_probability": statistics.median(fair),
                "probability_semantics": "proportional_margin_removed_estimate",
                "calibrated": False,
                "aggregation": "median_of_book_probabilities_at_same_threshold",
                "book_count": len(values),
                "probability_range": [min(fair), max(fair)],
                "independent_sample_size": None,
                "expected_stat": None,
            }
        )
    invalid_consensus_markets: set[str] = set()
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in constraints:
        if item["threshold"] is not None:
            by_market[item["market_key"]].append(item)
    for market, values in by_market.items():
        ordered = sorted(values, key=lambda value: value["threshold"])
        if any(
            right["fair_probability"] > left["fair_probability"]
            for left, right in zip(ordered, ordered[1:])
        ):
            invalid_consensus_markets.add(market)
            rejected.append({"market_key": market, "reason": "non_monotone_consensus"})
    constraints = [
        item for item in constraints if item["market_key"] not in invalid_consensus_markets
    ]
    return {
        "available": bool(constraints),
        "applied": False,
        "event_id": event_id,
        "player_id": player_id,
        "period": period,
        "as_of": decision_time.isoformat(),
        "probabilities": probabilities,
        "quantile_constraints": constraints,
        "raw_quotes": raw_quotes,
        "rejected": rejected,
        "coverage": {
            "markets": sorted({item["market_key"] for item in constraints}),
            "complete_fantasy_projection": False,
        },
        "expected_stat": None,
        "model_status": "unavailable_no_validated_distribution",
        "unavailable_reasons": [
            "No validated stat-distribution policy; threshold probabilities are not expected stat values"
        ],
    }
