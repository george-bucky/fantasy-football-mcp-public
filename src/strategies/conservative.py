"""
Conservative lineup strategy for fantasy football.

This strategy prioritizes consistency and floor projections, targeting players
with reliable production and minimal bust risk. Ideal for cash games and
risk-averse lineup construction.
"""

from decimal import Decimal
from typing import Dict, List, Optional

from ..models.player import Player, Position
from ..models.matchup import MatchupAnalysis
from .base import BaseLineupStrategy, StrategyConfig, StrategyType, WeightAdjustment, PlayerScore


class ConservativeStrategy(BaseLineupStrategy):
    """
    Conservative lineup strategy emphasizing floor projections and consistency.

    This strategy is designed for:
    - Cash games and double-ups
    - Risk-averse players
    - Lineups targeting consistent performance over upside
    - Tournaments where a solid floor is preferred over boom/bust potential

    Key characteristics:
    - Heavy weight on floor projections
    - Penalty for high-variance players
    - Preference for established, consistent performers
    - Conservative position allocation
    - Weather-sensitive adjustments
    """

    @property
    def strategy_type(self) -> StrategyType:
        """Get the strategy type."""
        return StrategyType.CONSERVATIVE

    @property
    def name(self) -> str:
        """Get the strategy name."""
        return "Conservative Floor-Based"

    @property
    def description(self) -> str:
        """Get the strategy description."""
        return (
            "Prioritizes consistent performers with high floor projections. "
            "Minimizes bust risk and variance while targeting reliable production. "
            "Optimized for cash games and risk-averse lineup construction."
        )

    def _get_default_config(self) -> StrategyConfig:
        """Get default configuration for conservative strategy."""

        # Conservative weight adjustments
        weight_adjustments = WeightAdjustment(
            # Heavy emphasis on floor, moderate on projection, minimal on ceiling
            floor_weight=Decimal("0.5"),
            projection_weight=Decimal("0.4"),
            ceiling_weight=Decimal("0.1"),
            # Value considerations for efficiency
            value_weight=Decimal("0.2"),
            # Slight preference for higher ownership (chalk plays are often safer)
            ownership_weight=Decimal("0.1"),
            # Strong emphasis on consistency, minimal upside chasing
            consistency_weight=Decimal("0.4"),
            upside_weight=Decimal("0.1"),
            # Moderate matchup considerations
            matchup_weight=Decimal("0.3"),
            game_script_weight=Decimal("0.2"),
            # Position-specific modifiers
            position_modifiers={
                Position.QB.value: Decimal("1.1"),  # QBs tend to be more consistent
                Position.RB.value: Decimal("1.0"),  # Standard weighting
                Position.WR.value: Decimal("0.9"),  # WRs can be more volatile
                Position.TE.value: Decimal("1.05"),  # TEs often have decent floors
                Position.K.value: Decimal("1.2"),  # Target consistent kickers
                Position.DEF.value: Decimal("1.1"),  # Target reliable defenses
            },
        )

        return StrategyConfig(
            name=self.name,
            strategy_type=self.strategy_type,
            description=self.description,
            weight_adjustments=weight_adjustments,
            risk_tolerance=Decimal("0.2"),  # Very low risk tolerance
            variance_preference=Decimal("0.1"),  # Strong preference for low variance
            cash_game_optimized=True,
            gpp_optimized=False,
            stack_preference=Decimal("0.2"),  # Light stacking preference
            correlation_bonus=Decimal("0.1"),  # Minimal correlation bonus
            weather_penalty=Decimal("0.3"),  # Moderate weather penalty
        )

    def score_player(
        self,
        player: Player,
        matchup_analysis: Optional[MatchupAnalysis] = None,
        context: Optional[Dict] = None,
    ) -> PlayerScore:
        """
        Score a player using conservative strategy principles.

        Emphasizes floor projections, consistency metrics, and risk mitigation
        while penalizing high-variance situations.
        """
        if not player.projections:
            # Cannot score player without projections
            return PlayerScore(
                player_id=player.id,
                base_score=Decimal("0"),
                adjusted_score=Decimal("0"),
                boost_factors=["No projections available"],
                penalty_factors=[],
            )

        # Get position-adjusted weights
        weights = self.adjust_weights_for_position(player.position, self.config.weight_adjustments)

        # Start with base projection
        base_score = player.projections.projected_fantasy_points

        # Calculate component scores
        projection_component = base_score * weights.projection_weight

        # Floor component (heavily weighted)
        floor_component = Decimal("0")
        if player.projections.floor_points:
            floor_component = player.projections.floor_points * weights.floor_weight
        else:
            # Estimate floor as 70% of projection if not available
            floor_component = base_score * Decimal("0.7") * weights.floor_weight

        # Ceiling component (lightly weighted)
        ceiling_component = Decimal("0")
        if player.projections.ceiling_points:
            ceiling_component = player.projections.ceiling_points * weights.ceiling_weight
        else:
            # Estimate ceiling as 130% of projection if not available
            ceiling_component = base_score * Decimal("1.3") * weights.ceiling_weight

        # Value component
        value_component = Decimal("0")
        if player.value_metrics and weights.value_weight > 0:
            projected_value = player.get_projected_value()
            if projected_value:
                # Normalize value score (points per $1000)
                value_component = min(projected_value, Decimal("10")) * weights.value_weight

        # Ownership component (conservative prefers chalk)
        ownership_component = self.calculate_ownership_adjustment(player)

        # Matchup component
        matchup_component = self.calculate_matchup_bonus(player, matchup_analysis)

        # Calculate total adjusted score
        adjusted_score = (
            projection_component
            + floor_component
            + ceiling_component
            + value_component
            + ownership_component
            + matchup_component
        )

        # Apply consistency bonus/penalty
        consistency_score = self._calculate_consistency_score(player)
        consistency_adjustment = consistency_score * weights.consistency_weight
        adjusted_score += consistency_adjustment

        # Apply weather penalty
        weather_penalty = self.calculate_weather_penalty(player, matchup_analysis)
        adjusted_score += weather_penalty

        # Apply game script adjustment
        game_script_adjustment = self.calculate_game_script_adjustment(player, matchup_analysis)
        adjusted_score += game_script_adjustment

        # Apply conservative-specific adjustments
        conservative_adjustments = self._apply_conservative_adjustments(player, matchup_analysis)
        adjusted_score += conservative_adjustments["adjustment"]

        # Build score breakdown
        boost_factors = conservative_adjustments["boost_factors"]
        penalty_factors = conservative_adjustments["penalty_factors"]

        # Add general boost factors
        if floor_component > projection_component:
            boost_factors.append("Strong floor projection")
        if consistency_score > Decimal("0.7"):
            boost_factors.append("High consistency score")
        if (
            player.value_metrics
            and player.get_projected_value()
            and player.get_projected_value() > Decimal("5")
        ):
            boost_factors.append("Excellent value play")

        # Add general penalty factors
        if player.projections.bust_probability and player.projections.bust_probability > Decimal(
            "0.3"
        ):
            penalty_factors.append("High bust probability")
        if weather_penalty < Decimal("-0.1"):
            penalty_factors.append("Weather concerns")

        return PlayerScore(
            player_id=player.id,
            base_score=base_score,
            adjusted_score=max(adjusted_score, Decimal("0")),  # Ensure non-negative
            projection_component=projection_component,
            floor_component=floor_component,
            ceiling_component=ceiling_component,
            value_component=value_component,
            ownership_component=ownership_component,
            matchup_component=matchup_component,
            variance_score=self._calculate_variance_score(player),
            consistency_score=consistency_score,
            boost_factors=boost_factors,
            penalty_factors=penalty_factors,
        )

    def _calculate_consistency_score(self, player: Player) -> Decimal:
        """
        Calculate consistency score for a player.

        Based on variance between floor and ceiling, confidence score,
        and historical performance patterns.
        """
        if not player.projections:
            return Decimal("0.5")

        consistency_score = Decimal("0.5")  # Base score

        # Factor 1: Projection confidence
        confidence_boost = (player.projections.confidence_score - Decimal("0.5")) * Decimal("0.3")
        consistency_score += confidence_boost

        # Factor 2: Floor-to-ceiling variance (lower variance = higher consistency)
        if player.projections.floor_points and player.projections.ceiling_points:
            variance = player.projections.ceiling_points - player.projections.floor_points
            projection_range = player.projections.projected_fantasy_points

            if projection_range > 0:
                variance_ratio = variance / projection_range
                # Lower variance ratio = higher consistency
                consistency_boost = max(Decimal("0"), (Decimal("1") - variance_ratio)) * Decimal(
                    "0.3"
                )
                consistency_score += consistency_boost

        # Factor 3: Injury status (healthy players are more consistent)
        if not player.is_injured():
            consistency_score += Decimal("0.1")
        else:
            consistency_score -= Decimal("0.2")

        # Factor 4: Position-specific consistency factors
        if player.position == Position.QB:
            # QBs tend to be more consistent
            consistency_score += Decimal("0.1")
        elif player.position in [Position.WR, Position.TE]:
            # WRs/TEs can be more volatile
            consistency_score -= Decimal("0.05")

        return max(Decimal("0"), min(Decimal("1"), consistency_score))

    def _calculate_variance_score(self, player: Player) -> Optional[Decimal]:
        """Calculate variance score for a player (0=low variance, 1=high variance)."""
        if not player.projections:
            return None

        if player.projections.floor_points and player.projections.ceiling_points:
            variance = player.projections.ceiling_points - player.projections.floor_points
            projection = player.projections.projected_fantasy_points

            if projection > 0:
                return min(Decimal("1"), variance / projection)

        # Estimate variance based on bust probability if available
        if player.projections.bust_probability:
            return player.projections.bust_probability

        return Decimal("0.5")  # Default moderate variance

    def _apply_conservative_adjustments(
        self, player: Player, matchup_analysis: Optional[MatchupAnalysis]
    ) -> Dict:
        """Apply conservative-specific adjustments and rationale."""
        adjustment = Decimal("0")
        boost_factors = []
        penalty_factors = []

        # Bonus for established veterans
        if player.years_pro and player.years_pro >= 5:
            adjustment += Decimal("0.05")
            boost_factors.append("Veteran experience")
        elif player.years_pro and player.years_pro <= 1:
            adjustment -= Decimal("0.03")
            penalty_factors.append("Rookie/young player volatility")

        # Penalty for players with recent injuries
        if player.is_injured():
            severity_penalty = Decimal("0.1")
            if (
                player.injury_report
                and player.injury_report.severity_score
                and player.injury_report.severity_score >= 5
            ):
                severity_penalty = Decimal("0.2")

            adjustment -= severity_penalty
            penalty_factors.append("Injury concerns")

        # Bonus for home field advantage in conservative plays
        if player.home_away == "Home":
            adjustment += Decimal("0.02")
            boost_factors.append("Home field advantage")

        # Penalty for players in negative game scripts
        if matchup_analysis:
            player_team_analysis = None
            if player.team == matchup_analysis.matchup.home_team:
                player_team_analysis = matchup_analysis.home_team_analysis
            elif player.team == matchup_analysis.matchup.away_team:
                player_team_analysis = matchup_analysis.away_team_analysis

            if player_team_analysis:
                # Check for negative game script indicators
                if "trailing" in player_team_analysis.likely_game_script.lower():
                    if player.position == Position.RB:
                        adjustment -= Decimal("0.05")
                        penalty_factors.append("Negative game script for RB")
                elif "leading" in player_team_analysis.likely_game_script.lower():
                    if player.position == Position.RB:
                        adjustment += Decimal("0.03")
                        boost_factors.append("Positive game script for RB")

        # Bonus for players with high target share/touch share consistency
        if player.season_stats and player.position in [Position.WR, Position.TE, Position.RB]:
            games_played = player.season_stats.games_played or 1

            if player.position in [Position.WR, Position.TE]:
                if player.season_stats.targets and player.season_stats.targets / games_played >= 8:
                    adjustment += Decimal("0.03")
                    boost_factors.append("High target share")
            elif player.position == Position.RB:
                if (
                    player.season_stats.rushing_attempts
                    and player.season_stats.rushing_attempts / games_played >= 15
                ):
                    adjustment += Decimal("0.03")
                    boost_factors.append("High touch share")

        # Penalty for players in high-variance matchups
        if matchup_analysis and matchup_analysis.volatility_rating >= 7:
            adjustment -= Decimal("0.02")
            penalty_factors.append("High-variance game environment")

        # Bonus for players in dome games (more predictable conditions)
        if (
            matchup_analysis
            and matchup_analysis.matchup.game_environment
            and matchup_analysis.matchup.game_environment.venue_type
            and matchup_analysis.matchup.game_environment.venue_type.value
            in ["Dome", "Retractable"]
        ):
            adjustment += Decimal("0.01")
            boost_factors.append("Dome game (controlled environment)")

        return {
            "adjustment": adjustment,
            "boost_factors": boost_factors,
            "penalty_factors": penalty_factors,
        }

    def get_position_allocation_preferences(self) -> Dict[str, Decimal]:
        """
        Get conservative strategy position allocation preferences.

        Returns position preference weights for portfolio construction.
        """
        return {
            Position.QB.value: Decimal("1.0"),  # Standard QB allocation
            Position.RB.value: Decimal("1.1"),  # Slight preference for RB consistency
            Position.WR.value: Decimal("0.9"),  # Lower preference due to volatility
            Position.TE.value: Decimal("1.05"),  # TEs often provide steady floors
            Position.K.value: Decimal("1.0"),  # Standard kicker allocation
            Position.DEF.value: Decimal("1.0"),  # Standard defense allocation
        }

    def get_recommended_contest_types(self) -> List[str]:
        """Get contest types best suited for this strategy."""
        return [
            "Cash Games",
            "Double Ups",
            "Head-to-Head",
            "50/50s",
            "Small Field GPPs (under 100 entries)",
        ]

    def get_stack_recommendations(self, matchup_analysis: Optional[MatchupAnalysis]) -> List[str]:
        """Get stacking recommendations for conservative strategy."""
        recommendations = []

        # Conservative stacking focuses on safe, proven combinations
        recommendations.extend(
            [
                "QB + Top WR from high-total games",
                "RB + Defense from same team (positive game script)",
                "Avoid complex 4+ player stacks",
                "Target mini-stacks (2 players) over full stacks",
            ]
        )

        if matchup_analysis:
            # Look for games with consistent scoring environments
            total_proj = matchup_analysis.matchup.get_total_projected_points()
            if total_proj and total_proj >= Decimal("45"):
                recommendations.append("Consider QB + WR stack in high-total game")

        return recommendations
