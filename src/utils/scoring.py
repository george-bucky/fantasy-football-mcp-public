"""
Fantasy Football scoring calculations and value analysis functions.
"""

from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
import numpy as np
from scipy import stats
import math
from .constants import Platform, SCORING_SYSTEMS, POSITION_SCARCITY, ROSTER_POSITIONS


@dataclass
class PlayerStats:
    """Container for player statistics"""

    # Passing
    passing_yards: int = 0
    passing_tds: int = 0
    interceptions: int = 0
    completions: int = 0
    passing_attempts: int = 0
    passing_fumbles_lost: int = 0
    passing_two_point: int = 0

    # Rushing
    rushing_yards: int = 0
    rushing_tds: int = 0
    rushing_attempts: int = 0
    rushing_fumbles_lost: int = 0
    rushing_two_point: int = 0

    # Receiving
    receiving_yards: int = 0
    receiving_tds: int = 0
    receptions: int = 0
    targets: int = 0
    receiving_fumbles_lost: int = 0
    receiving_two_point: int = 0

    # Kicking
    pat_made: int = 0
    pat_attempted: int = 0
    fg_made_0_39: int = 0
    fg_attempted_0_39: int = 0
    fg_made_40_49: int = 0
    fg_attempted_40_49: int = 0
    fg_made_50_plus: int = 0
    fg_attempted_50_plus: int = 0

    # Defense/Special Teams
    points_allowed: int = 0
    yards_allowed: int = 0
    sacks: int = 0
    def_interceptions: int = 0
    fumble_recoveries: int = 0
    safeties: int = 0
    def_tds: int = 0
    blocked_kicks: int = 0

    # Additional context
    game_script: float = 0.0  # Positive = winning, negative = losing
    weather_score: float = 1.0  # 1.0 = neutral, <1.0 = adverse
    injury_status: str = "healthy"  # healthy, questionable, doubtful, out


@dataclass
class ProjectionInput:
    """Input for player projections"""

    mean_points: float
    std_dev: float
    floor: float
    ceiling: float
    ownership: float
    salary: int
    position: str
    team: str
    opponent: str
    game_environment: Dict[str, Any]


def calculate_fantasy_points(
    stats: PlayerStats, platform: Platform = Platform.DRAFTKINGS, position: str = "FLEX"
) -> float:
    """
    Calculate fantasy points for a player based on their stats and platform scoring.

    Args:
        stats: PlayerStats object containing all relevant statistics
        platform: Fantasy platform for scoring rules
        position: Player position for position-specific scoring

    Returns:
        Total fantasy points as a float
    """
    if platform not in SCORING_SYSTEMS:
        raise ValueError(f"Unsupported platform: {platform}")

    scoring = SCORING_SYSTEMS[platform]
    total_points = 0.0

    # Passing points
    if stats.passing_yards > 0 or stats.passing_tds > 0:
        passing_scoring = scoring["passing"]
        total_points += stats.passing_yards / passing_scoring["yards_per_point"]
        total_points += stats.passing_tds * passing_scoring["td"]
        total_points += stats.interceptions * passing_scoring["interception"]
        total_points += stats.passing_fumbles_lost * passing_scoring["fumble_lost"]
        total_points += stats.passing_two_point * passing_scoring["two_point"]
        total_points += stats.completions * passing_scoring.get("completions", 0)

        # Yardage bonuses
        if stats.passing_yards >= 300:
            total_points += passing_scoring.get("300_yard_bonus", 0)
        if stats.passing_yards >= 400:
            total_points += passing_scoring.get("400_yard_bonus", 0)

    # Rushing points
    if stats.rushing_yards > 0 or stats.rushing_tds > 0:
        rushing_scoring = scoring["rushing"]
        total_points += stats.rushing_yards / rushing_scoring["yards_per_point"]
        total_points += stats.rushing_tds * rushing_scoring["td"]
        total_points += stats.rushing_fumbles_lost * rushing_scoring["fumble_lost"]
        total_points += stats.rushing_two_point * rushing_scoring["two_point"]

        # Yardage bonuses
        if stats.rushing_yards >= 100:
            total_points += rushing_scoring.get("100_yard_bonus", 0)
        if stats.rushing_yards >= 200:
            total_points += rushing_scoring.get("200_yard_bonus", 0)

    # Receiving points
    if stats.receiving_yards > 0 or stats.receiving_tds > 0 or stats.receptions > 0:
        receiving_scoring = scoring["receiving"]
        total_points += stats.receiving_yards / receiving_scoring["yards_per_point"]
        total_points += stats.receiving_tds * receiving_scoring["td"]
        total_points += stats.receptions * receiving_scoring["reception"]
        total_points += stats.receiving_fumbles_lost * receiving_scoring["fumble_lost"]
        total_points += stats.receiving_two_point * receiving_scoring["two_point"]

        # Yardage bonuses
        if stats.receiving_yards >= 100:
            total_points += receiving_scoring.get("100_yard_bonus", 0)
        if stats.receiving_yards >= 200:
            total_points += receiving_scoring.get("200_yard_bonus", 0)

    # Kicking points
    if position == "K" and any(
        [stats.pat_made, stats.fg_made_0_39, stats.fg_made_40_49, stats.fg_made_50_plus]
    ):
        kicking_scoring = scoring["kicking"]
        total_points += stats.pat_made * kicking_scoring["pat"]
        total_points += stats.fg_made_0_39 * kicking_scoring["fg_0_39"]
        total_points += stats.fg_made_40_49 * kicking_scoring["fg_40_49"]
        total_points += stats.fg_made_50_plus * kicking_scoring["fg_50_plus"]

        # Missed field goals (if platform penalizes)
        total_fg_misses = (
            (stats.fg_attempted_0_39 - stats.fg_made_0_39)
            + (stats.fg_attempted_40_49 - stats.fg_made_40_49)
            + (stats.fg_attempted_50_plus - stats.fg_made_50_plus)
        )
        total_points += total_fg_misses * kicking_scoring.get("fg_miss", 0)

    # Defense/Special Teams points
    if position == "DST":
        defense_scoring = scoring["defense"]

        # Points allowed scoring (tiered)
        if stats.points_allowed == 0:
            total_points += defense_scoring["points_allowed_0"]
        elif 1 <= stats.points_allowed <= 6:
            total_points += defense_scoring["points_allowed_1_6"]
        elif 7 <= stats.points_allowed <= 13:
            total_points += defense_scoring["points_allowed_7_13"]
        elif 14 <= stats.points_allowed <= 20:
            total_points += defense_scoring["points_allowed_14_20"]
        elif 21 <= stats.points_allowed <= 27:
            total_points += defense_scoring["points_allowed_21_27"]
        elif 28 <= stats.points_allowed <= 34:
            total_points += defense_scoring["points_allowed_28_34"]
        else:  # 35+
            total_points += defense_scoring["points_allowed_35_plus"]

        # Defensive stats
        total_points += stats.sacks * defense_scoring["sack"]
        total_points += stats.def_interceptions * defense_scoring["interception"]
        total_points += stats.fumble_recoveries * defense_scoring["fumble_recovery"]
        total_points += stats.safeties * defense_scoring["safety"]
        total_points += stats.def_tds * defense_scoring["td"]
        total_points += stats.blocked_kicks * defense_scoring["blocked_kick"]

    return round(total_points, 2)


def project_points(
    projection_input: ProjectionInput, confidence_level: float = 0.68, num_simulations: int = 10000
) -> Dict[str, float]:
    """
    Project fantasy points with confidence intervals using Monte Carlo simulation.

    Args:
        projection_input: ProjectionInput with mean, std_dev, etc.
        confidence_level: Confidence level for intervals (0.68 = 1 std dev)
        num_simulations: Number of Monte Carlo simulations

    Returns:
        Dictionary with projection statistics
    """
    # Create normal distribution for base projection
    base_distribution = stats.norm(loc=projection_input.mean_points, scale=projection_input.std_dev)

    # Adjust for game environment factors
    environment_multiplier = 1.0
    env = projection_input.game_environment

    # Weather adjustments
    if env.get("weather_score", 1.0) < 0.8:
        if projection_input.position in ["QB", "WR", "TE"]:
            environment_multiplier *= 0.9  # Passing game hurt more
        elif projection_input.position == "K":
            environment_multiplier *= 0.85  # Kickers hurt most

    # Game script adjustments
    game_script = env.get("game_script", 0.0)
    if projection_input.position == "RB" and game_script > 7:
        environment_multiplier *= 1.1  # Positive game script helps RBs
    elif projection_input.position in ["QB", "WR"] and game_script < -7:
        environment_multiplier *= 1.1  # Negative game script helps passing

    # Vegas total adjustments
    vegas_total = env.get("vegas_total", 45.0)
    if vegas_total > 50:
        environment_multiplier *= 1.05
    elif vegas_total < 40:
        environment_multiplier *= 0.95

    # Run Monte Carlo simulation
    simulated_points = base_distribution.rvs(num_simulations) * environment_multiplier

    # Ensure non-negative points and apply floor/ceiling constraints
    simulated_points = np.maximum(simulated_points, 0)
    simulated_points = np.minimum(simulated_points, projection_input.ceiling * 1.2)
    simulated_points = np.maximum(simulated_points, projection_input.floor * 0.8)

    # Calculate percentiles
    percentiles = [5, 10, 25, 50, 75, 90, 95]
    percentile_values = np.percentile(simulated_points, percentiles)

    # Calculate confidence interval
    alpha = 1 - confidence_level
    lower_bound = np.percentile(simulated_points, (alpha / 2) * 100)
    upper_bound = np.percentile(simulated_points, (1 - alpha / 2) * 100)

    return {
        "mean": float(np.mean(simulated_points)),
        "median": float(np.median(simulated_points)),
        "std_dev": float(np.std(simulated_points)),
        "floor": float(projection_input.floor),
        "ceiling": float(projection_input.ceiling),
        "confidence_lower": float(lower_bound),
        "confidence_upper": float(upper_bound),
        "p5": float(percentile_values[0]),
        "p10": float(percentile_values[1]),
        "p25": float(percentile_values[2]),
        "p50": float(percentile_values[3]),
        "p75": float(percentile_values[4]),
        "p90": float(percentile_values[5]),
        "p95": float(percentile_values[6]),
        "boom_probability": float(np.mean(simulated_points > projection_input.ceiling * 0.9)),
        "bust_probability": float(np.mean(simulated_points < projection_input.floor * 1.1)),
        "environment_multiplier": float(environment_multiplier),
    }


def calculate_value(
    projected_points: float, salary: int, position: str, platform: Platform = Platform.DRAFTKINGS
) -> Dict[str, float]:
    """
    Calculate various value metrics for a player.

    Args:
        projected_points: Projected fantasy points
        salary: Player salary
        position: Player position
        platform: Fantasy platform

    Returns:
        Dictionary of value metrics
    """
    if salary <= 0:
        raise ValueError("Salary must be positive")

    # Basic points per dollar
    ppd = projected_points / (salary / 1000)  # Points per $1K

    # Position-adjusted value using scarcity multiplier
    position_multiplier = POSITION_SCARCITY.get(position, 1.0)
    adjusted_ppd = ppd * position_multiplier

    # Platform-specific salary expectations
    roster_config = ROSTER_POSITIONS.get(platform, ROSTER_POSITIONS[Platform.DRAFTKINGS])
    salary_cap = roster_config.get("salary_cap", 50000)

    if salary_cap:
        # Expected salary for average points at position
        avg_salary_per_position = salary_cap / roster_config["roster_size"]
        salary_efficiency = projected_points / (salary / avg_salary_per_position)
    else:
        salary_efficiency = ppd  # Season-long leagues

    # Value tier classification
    if ppd >= 3.5:
        value_tier = "elite"
        tier_score = 5
    elif ppd >= 3.0:
        value_tier = "great"
        tier_score = 4
    elif ppd >= 2.5:
        value_tier = "good"
        tier_score = 3
    elif ppd >= 2.0:
        value_tier = "average"
        tier_score = 2
    else:
        value_tier = "poor"
        tier_score = 1

    return {
        "points_per_dollar": round(ppd, 3),
        "adjusted_points_per_dollar": round(adjusted_ppd, 3),
        "salary_efficiency": round(salary_efficiency, 3),
        "value_tier": value_tier,
        "tier_score": tier_score,
        "position_multiplier": position_multiplier,
        "salary_percentage": round((salary / salary_cap * 100) if salary_cap else 0, 1),
    }


def calculate_ownership_leverage(
    projected_ownership: float,
    projected_points: float,
    ceiling_points: float,
    game_type: str = "tournament",
) -> Dict[str, float]:
    """
    Calculate ownership leverage for tournament play.

    Args:
        projected_ownership: Expected ownership percentage (0-100)
        projected_points: Mean projected points
        ceiling_points: 90th percentile projection
        game_type: "tournament" or "cash"

    Returns:
        Dictionary with leverage metrics
    """
    # Leverage calculation: (Ceiling - Mean) / Ownership
    # Higher is better for tournaments
    leverage = (ceiling_points - projected_points) / max(projected_ownership, 1.0)

    # Ownership bucket classification
    if projected_ownership >= 30:
        ownership_bucket = "chalk"
    elif projected_ownership >= 20:
        ownership_bucket = "popular"
    elif projected_ownership >= 10:
        ownership_bucket = "moderate"
    elif projected_ownership >= 5:
        ownership_bucket = "low"
    else:
        ownership_bucket = "contrarian"

    # Tournament utility score
    if game_type == "tournament":
        # Reward high ceiling and low ownership
        utility_score = (ceiling_points / max(projected_ownership, 5.0)) * 10

        # Bonus for contrarian plays with decent floor
        if projected_ownership < 10 and projected_points > 8:
            utility_score *= 1.2
    else:
        # Cash games prefer consistency regardless of ownership
        utility_score = projected_points - (ceiling_points - projected_points) * 0.5

    # Leverage tier
    if leverage >= 1.0:
        leverage_tier = "elite"
    elif leverage >= 0.5:
        leverage_tier = "good"
    elif leverage >= 0.25:
        leverage_tier = "average"
    else:
        leverage_tier = "poor"

    return {
        "leverage": round(leverage, 3),
        "ownership_bucket": ownership_bucket,
        "utility_score": round(utility_score, 2),
        "leverage_tier": leverage_tier,
        "contrarian_boost": 1.2 if projected_ownership < 10 else 1.0,
        "chalk_penalty": 0.9 if projected_ownership > 30 and game_type == "tournament" else 1.0,
    }


def position_scarcity_multiplier(
    position: str, weekly_rankings: List[float], replacement_level: float = None
) -> Dict[str, float]:
    """
    Calculate position scarcity multiplier based on weekly performance distribution.

    Args:
        position: Player position
        weekly_rankings: List of fantasy points for position this week
        replacement_level: Points threshold for replacement level player

    Returns:
        Dictionary with scarcity metrics
    """
    if not weekly_rankings:
        return {"multiplier": POSITION_SCARCITY.get(position, 1.0)}

    weekly_rankings = sorted(weekly_rankings, reverse=True)

    # Calculate replacement level if not provided
    if replacement_level is None:
        # Use 24th ranked player as replacement (roughly waiver wire)
        replacement_idx = min(23, len(weekly_rankings) - 1)
        replacement_level = (
            weekly_rankings[replacement_idx] if replacement_idx < len(weekly_rankings) else 0
        )

    # Standard deviation of position
    std_dev = np.std(weekly_rankings) if len(weekly_rankings) > 1 else 0

    # Top tier threshold (typically top 12 players)
    top_tier_size = min(12, len(weekly_rankings) // 2)
    top_tier_avg = np.mean(weekly_rankings[:top_tier_size]) if top_tier_size > 0 else 0

    # Calculate scarcity based on drop-off from top tier to replacement
    if replacement_level > 0:
        scarcity_ratio = top_tier_avg / replacement_level
    else:
        scarcity_ratio = 2.0  # Default if no replacement level data

    # Adjust multiplier based on scarcity ratio
    base_multiplier = POSITION_SCARCITY.get(position, 1.0)

    if scarcity_ratio >= 2.5:
        dynamic_multiplier = base_multiplier * 1.3  # Very scarce
    elif scarcity_ratio >= 2.0:
        dynamic_multiplier = base_multiplier * 1.2  # Scarce
    elif scarcity_ratio >= 1.5:
        dynamic_multiplier = base_multiplier * 1.1  # Moderately scarce
    else:
        dynamic_multiplier = base_multiplier * 0.95  # Not scarce

    # Volatility adjustment
    if std_dev > 5.0:  # High volatility
        volatility_multiplier = 1.1
    elif std_dev < 2.0:  # Low volatility
        volatility_multiplier = 0.95
    else:
        volatility_multiplier = 1.0

    final_multiplier = dynamic_multiplier * volatility_multiplier

    return {
        "multiplier": round(final_multiplier, 3),
        "base_multiplier": base_multiplier,
        "scarcity_ratio": round(scarcity_ratio, 2),
        "volatility": round(std_dev, 2),
        "replacement_level": round(replacement_level, 1),
        "top_tier_avg": round(top_tier_avg, 1),
        "tier": _get_scarcity_tier(scarcity_ratio),
    }


def _get_scarcity_tier(scarcity_ratio: float) -> str:
    """Helper function to classify scarcity tier"""
    if scarcity_ratio >= 2.5:
        return "very_scarce"
    elif scarcity_ratio >= 2.0:
        return "scarce"
    elif scarcity_ratio >= 1.5:
        return "moderate"
    else:
        return "abundant"


def calculate_correlation_boost(
    player1_projection: float,
    player2_projection: float,
    correlation_coefficient: float,
    stack_type: str = "qb_wr",
) -> Dict[str, float]:
    """
    Calculate correlation boost for stacked players.

    Args:
        player1_projection: First player's projected points
        player2_projection: Second player's projected points
        correlation_coefficient: Historical correlation between positions
        stack_type: Type of stack (qb_wr, qb_te, etc.)

    Returns:
        Dictionary with correlation metrics
    """
    # Base correlation boost based on stack type
    base_boosts = {
        "qb_wr": 1.15,
        "qb_te": 1.12,
        "qb_wr_wr": 1.08,
        "rb_dst": 0.95,  # Negative correlation
        "bring_back": 1.05,
    }

    base_boost = base_boosts.get(stack_type, 1.0)

    # Adjust based on actual correlation coefficient
    correlation_adjustment = 1.0 + (correlation_coefficient * 0.2)

    # Combined projections get boost if both players projected well
    combined_projection = player1_projection + player2_projection

    # Higher combined projections get bigger boosts
    if combined_projection > 35:
        projection_boost = 1.1
    elif combined_projection > 25:
        projection_boost = 1.05
    else:
        projection_boost = 1.0

    final_boost = base_boost * correlation_adjustment * projection_boost

    return {
        "correlation_boost": round(final_boost, 3),
        "base_boost": base_boost,
        "correlation_coefficient": correlation_coefficient,
        "combined_projection": round(combined_projection, 1),
        "projection_boost": projection_boost,
        "stack_type": stack_type,
    }


def calculate_game_environment_impact(
    vegas_total: float, spread: float, weather_conditions: Dict[str, Any], pace_factor: float = 1.0
) -> Dict[str, float]:
    """
    Calculate game environment impact on player projections.

    Args:
        vegas_total: Over/under total points
        spread: Point spread (positive for favorites)
        weather_conditions: Dict with wind, temp, precipitation
        pace_factor: Team pace relative to league average

    Returns:
        Dictionary with environment impact factors
    """
    # Vegas total impact
    if vegas_total >= 52:
        total_multiplier = 1.1  # High-scoring expected
    elif vegas_total >= 47:
        total_multiplier = 1.05
    elif vegas_total >= 42:
        total_multiplier = 1.0
    elif vegas_total >= 38:
        total_multiplier = 0.95
    else:
        total_multiplier = 0.9  # Low-scoring expected

    # Spread impact (game script)
    abs_spread = abs(spread)
    if abs_spread >= 10:
        spread_factor = 0.95  # Blowout potential
    elif abs_spread >= 7:
        spread_factor = 0.98
    else:
        spread_factor = 1.0  # Competitive game

    # Weather impact
    weather_multiplier = 1.0
    wind_speed = weather_conditions.get("wind_speed", 0)
    precipitation = weather_conditions.get("precipitation", 0)
    temperature = weather_conditions.get("temperature", 70)

    # Wind impact (affects passing and kicking most)
    if wind_speed >= 20:
        weather_multiplier *= 0.85
    elif wind_speed >= 15:
        weather_multiplier *= 0.92
    elif wind_speed >= 10:
        weather_multiplier *= 0.97

    # Precipitation impact
    if precipitation >= 0.25:  # Heavy rain/snow
        weather_multiplier *= 0.9
    elif precipitation >= 0.1:  # Light precipitation
        weather_multiplier *= 0.95

    # Temperature impact (extreme cold)
    if temperature <= 20:
        weather_multiplier *= 0.92
    elif temperature <= 32:
        weather_multiplier *= 0.96

    # Pace factor impact
    pace_multiplier = 0.8 + (pace_factor * 0.4)  # Scale around 1.0

    # Combined environment score
    environment_score = total_multiplier * spread_factor * weather_multiplier * pace_multiplier

    return {
        "environment_score": round(environment_score, 3),
        "vegas_total_impact": total_multiplier,
        "spread_impact": spread_factor,
        "weather_impact": round(weather_multiplier, 3),
        "pace_impact": round(pace_multiplier, 3),
        "game_script_favorable": abs_spread < 7,
        "weather_concerns": weather_multiplier < 0.95,
        "pace_category": (
            "fast" if pace_factor > 1.1 else "slow" if pace_factor < 0.9 else "average"
        ),
    }
