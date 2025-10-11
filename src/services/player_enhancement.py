"""Player enhancement service for projection adjustments and context.

This module provides enhancements to player data including:
- Bye week detection and projection zeroing
- Recent performance stats (last 1-3 weeks)
- Breakout/trending/declining flags
- Adjusted projections based on recent reality
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class RecentPerformance:
    """Recent performance metrics for a player."""

    weeks_analyzed: int
    avg_points: float
    total_points: float
    weeks_data: List[Dict[str, Any]]
    trend: str  # "improving", "declining", "stable"


@dataclass
class EnhancedPlayerData:
    """Enhanced player data with context and flags."""

    on_bye: bool
    recent_performance: Optional[RecentPerformance]
    performance_flags: List[str]
    adjusted_projection: Optional[float]
    recommendation_override: Optional[str]
    context_message: str


def detect_bye_week(player_bye: Any, current_week: int) -> bool:
    """Detect if player is on bye this week.

    Args:
        player_bye: Bye week from player data (could be int, str, None, or "N/A")
        current_week: Current NFL week number

    Returns:
        True if player is on bye this week
    """
    # Handle None or "N/A" cases
    if player_bye is None or player_bye == "N/A" or player_bye == "":
        return False

    logger.debug(
        "detect_bye_week: raw_bye=%r (type=%s) current_week=%s",
        player_bye,
        type(player_bye).__name__,
        current_week,
    )

    # Handle string representations
    if isinstance(player_bye, str):
        try:
            bye_week = int(player_bye)
        except (ValueError, TypeError):
            logger.warning("Unable to parse bye week string: %r", player_bye)
            return False
    elif isinstance(player_bye, (int, float)):
        bye_week = int(player_bye)
    else:
        logger.warning(
            "Unexpected bye week type: %s = %r", type(player_bye).__name__, player_bye
        )
        return False

    # Validate bye week is in valid range
    if not (1 <= bye_week <= 18):
        logger.warning("Bye week %s out of valid range (1-18)", bye_week)
        return False

    on_bye = bye_week == current_week
    logger.debug(
        "detect_bye_week: normalized_bye=%s matches_current=%s",
        bye_week,
        on_bye,
    )
    return on_bye


def calculate_recent_avg(stats_list: List[Dict[str, Any]]) -> float:
    """Calculate average fantasy points from recent stats.

    Args:
        stats_list: List of stat dictionaries with 'pts_ppr' or 'pts' field

    Returns:
        Average points per game
    """
    if not stats_list:
        return 0.0

    total_points = 0.0
    valid_weeks = 0

    for week_stats in stats_list:
        # Try PPR first, then standard
        points = week_stats.get("pts_ppr") or week_stats.get("pts", 0)
        if isinstance(points, (int, float)) and points > 0:
            total_points += float(points)
            valid_weeks += 1

    return total_points / valid_weeks if valid_weeks > 0 else 0.0


def calculate_performance_trend(recent_stats: List[Tuple[int, float]]) -> str:
    """Calculate if player is trending up, down, or stable.

    Args:
        recent_stats: List of (week, points) tuples in chronological order

    Returns:
        "improving", "declining", or "stable"
    """
    if len(recent_stats) < 2:
        return "stable"

    # Compare most recent week to average of previous weeks
    recent_week_points = recent_stats[-1][1]
    previous_weeks_avg = sum(pts for _, pts in recent_stats[:-1]) / len(recent_stats[:-1])

    if previous_weeks_avg == 0:
        return "stable"

    change_pct = (recent_week_points - previous_weeks_avg) / previous_weeks_avg

    if change_pct > 0.25:  # 25% improvement
        return "improving"
    elif change_pct < -0.25:  # 25% decline
        return "declining"
    else:
        return "stable"


def calculate_breakout_score(recent_avg: float, projection: float, recent_high: float) -> List[str]:
    """Calculate performance flags based on recent stats vs projection.

    Args:
        recent_avg: Average points over recent weeks
        projection: Current Sleeper projection
        recent_high: Highest single-game performance in recent weeks

    Returns:
        List of flag strings like ["BREAKOUT", "TRENDING_UP"]
    """
    flags = []

    if projection == 0:
        return flags

    # Breakout: Recent average significantly exceeds projection
    if recent_avg > projection * 1.5:
        flags.append("BREAKOUT_CANDIDATE")

    # Strong performer: Recent average moderately exceeds projection
    elif recent_avg > projection * 1.2:
        flags.append("TRENDING_UP")

    # Declining: Recent average well below projection
    elif recent_avg < projection * 0.7 and recent_avg > 0:
        flags.append("DECLINING_ROLE")

    # Underperforming: Recent average below projection
    elif recent_avg < projection * 0.85 and recent_avg > 0:
        flags.append("UNDERPERFORMING")

    # High ceiling: Recent high game shows explosive potential
    if recent_high > projection * 2.0:
        flags.append("HIGH_CEILING")

    # Consistency: Steady performance
    if recent_avg > 0 and all(
        [
            recent_high / recent_avg < 1.5 if recent_avg > 0 else False,
            recent_avg > projection * 0.9,
            recent_avg < projection * 1.1,
        ]
    ):
        flags.append("CONSISTENT")

    return flags


async def get_recent_stats(
    sleeper_api, sleeper_id: str, season: int, current_week: int, lookback: int = 3
) -> Optional[RecentPerformance]:
    """Fetch recent actual stats for a player from Sleeper API.

    Args:
        sleeper_api: SleeperAPI instance
        sleeper_id: Player's Sleeper ID
        season: NFL season year
        current_week: Current week number
        lookback: Number of weeks to look back (default: 3)

    Returns:
        RecentPerformance object or None if no stats available
    """
    if not sleeper_id or current_week < 1:
        logger.debug(
            "get_recent_stats: skipping stats fetch sleeper_id=%r current_week=%s",
            sleeper_id,
            current_week,
        )
        return None

    logger.debug(
        "get_recent_stats: sleeper_id=%s season=%s current_week=%s lookback=%s",
        sleeper_id,
        season,
        current_week,
        lookback,
    )

    weeks_data = []
    points_by_week = []

    # Fetch stats for last N weeks (going backwards from current_week - 1)
    for i in range(1, lookback + 1):
        week = current_week - i
        if week < 1:
            break

        logger.debug(
            "get_recent_stats: requesting stats sleeper_id=%s season=%s week=%s",
            sleeper_id,
            season,
            week,
        )

        try:
            stats = await sleeper_api.get_player_stats(season, week)
            if stats and sleeper_id in stats:
                week_stats = stats[sleeper_id]
                points = week_stats.get("pts_ppr") or week_stats.get("pts", 0)
                if isinstance(points, (int, float)):
                    weeks_data.append({"week": week, "stats": week_stats, "points": float(points)})
                    points_by_week.append((week, float(points)))
                    logger.debug(
                        "get_recent_stats: captured points=%s sleeper_id=%s week=%s",
                        points,
                        sleeper_id,
                        week,
                    )
                else:
                    logger.debug(
                        "get_recent_stats: non-numeric points sleeper_id=%s week=%s payload_keys=%s",
                        sleeper_id,
                        week,
                        list(week_stats.keys()),
                    )
            else:
                logger.debug(
                    "get_recent_stats: no stats entry sleeper_id=%s week=%s",
                    sleeper_id,
                    week,
                )
        except Exception:
            logger.exception(
                "get_recent_stats: error fetching stats sleeper_id=%s season=%s week=%s",
                sleeper_id,
                season,
                week,
            )
            continue

    if not weeks_data:
        logger.debug(
            "get_recent_stats: no recent data sleeper_id=%s current_week=%s lookback=%s",
            sleeper_id,
            current_week,
            lookback,
        )
        return None

    # Calculate metrics
    avg_points = calculate_recent_avg([w["stats"] for w in weeks_data])
    total_points = sum(w["points"] for w in weeks_data)
    trend = calculate_performance_trend(points_by_week)

    return RecentPerformance(
        weeks_analyzed=len(weeks_data),
        avg_points=avg_points,
        total_points=total_points,
        weeks_data=weeks_data,
        trend=trend,
    )


async def enhance_player_with_context(
    player: Any,
    current_week: int,
    season: int,
    sleeper_api,
) -> EnhancedPlayerData:
    """Main enhancement function - adds bye week detection, recent stats, and flags.

    Args:
        player: Player object (from lineup_optimizer)
        current_week: Current NFL week
        season: Current NFL season
        sleeper_api: SleeperAPI instance for stats fetching

    Returns:
        EnhancedPlayerData with all context and flags
    """
    # Initialize defaults
    on_bye = False
    recent_performance = None
    performance_flags = []
    adjusted_projection = None
    recommendation_override = None
    context_message = ""

    # Check bye week with validation
    player_bye = getattr(player, "bye", None)
    
    # Log if bye week data is missing for debugging
    if player_bye is None:
        player_name = getattr(player, "name", "Unknown")
        # Only log once per session to avoid spam (in production, use proper logging)
        # print(f"Debug: No bye week data available for {player_name}")
    
    on_bye = detect_bye_week(player_bye, current_week)
    logger.debug(
        "enhance_player_with_context: player=%s bye=%r current_week=%s on_bye=%s",
        getattr(player, "name", "Unknown"),
        player_bye,
        current_week,
        on_bye,
    )

    if on_bye:
        recommendation_override = "BYE WEEK - DO NOT START"
        context_message = f"Player is on bye Week {player_bye}"
        adjusted_projection = 0.0
        performance_flags.append("ON_BYE")

        return EnhancedPlayerData(
            on_bye=True,
            recent_performance=None,
            performance_flags=performance_flags,
            adjusted_projection=0.0,
            recommendation_override=recommendation_override,
            context_message=context_message,
        )

    # Get recent performance stats
    sleeper_id = getattr(player, "sleeper_id", None)
    if sleeper_id:
        try:
            recent_performance = await get_recent_stats(
                sleeper_api, sleeper_id, season, current_week, lookback=3
            )
        except Exception:
            logger.exception("Error fetching recent stats for %s", player.name)

    # Calculate performance flags
    if recent_performance and recent_performance.avg_points > 0:
        projection = getattr(player, "sleeper_projection", 0) or 0
        recent_high = max((w["points"] for w in recent_performance.weeks_data), default=0)

        performance_flags = calculate_breakout_score(
            recent_performance.avg_points, projection, recent_high
        )

        # Add trend flag
        if recent_performance.trend == "improving":
            performance_flags.append("TRENDING_UP")
        elif recent_performance.trend == "declining":
            performance_flags.append("TRENDING_DOWN")

        # Adjust projection based on recent performance
        if "BREAKOUT_CANDIDATE" in performance_flags or "TRENDING_UP" in performance_flags:
            # Weight recent performance more heavily
            adjusted_projection = (projection * 0.4) + (recent_performance.avg_points * 0.6)
            context_message = (
                f"Recent breakout: averaging {recent_performance.avg_points:.1f} pts "
                f"over last {recent_performance.weeks_analyzed} weeks "
                f"(projection: {projection:.1f})"
            )
        elif "DECLINING_ROLE" in performance_flags:
            # Weight recent performance as warning
            adjusted_projection = (projection * 0.3) + (recent_performance.avg_points * 0.7)
            context_message = (
                f"Declining role: averaging {recent_performance.avg_points:.1f} pts "
                f"over last {recent_performance.weeks_analyzed} weeks "
                f"(projection: {projection:.1f})"
            )
        else:
            # Blend projections
            adjusted_projection = (projection * 0.7) + (recent_performance.avg_points * 0.3)
            context_message = (
                f"L{recent_performance.weeks_analyzed}W avg: "
                f"{recent_performance.avg_points:.1f} pts"
            )
    else:
        context_message = "No recent performance data available"

    return EnhancedPlayerData(
        on_bye=on_bye,
        recent_performance=recent_performance,
        performance_flags=performance_flags,
        adjusted_projection=adjusted_projection,
        recommendation_override=recommendation_override,
        context_message=context_message,
    )
