"""
Aggressive lineup strategy for fantasy football.

This strategy prioritizes ceiling projections and upside potential, targeting players
with high-variance and boom potential. Ideal for large-field tournaments and
situations where differentiation and upside are critical.
"""

from decimal import Decimal
from typing import Dict, List, Optional

from ..models.player import Player, Position
from ..models.matchup import MatchupAnalysis
from .base import BaseLineupStrategy, StrategyConfig, StrategyType, WeightAdjustment, PlayerScore


class AggressiveStrategy(BaseLineupStrategy):
    """
    Aggressive lineup strategy emphasizing ceiling projections and upside potential.

    This strategy is designed for:
    - Large-field GPP tournaments
    - High-stakes contests requiring differentiation
    - Players seeking maximum upside over safety
    - Situations where boom/bust variance is acceptable

    Key characteristics:
    - Heavy weight on ceiling projections
    - Preference for high-variance players
    - Contrarian ownership tendencies
    - Aggressive stacking strategies
    - Leverage spots and breakout candidates
    """

    @property
    def strategy_type(self) -> StrategyType:
        """Get the strategy type."""
        return StrategyType.AGGRESSIVE

    @property
    def name(self) -> str:
        """Get the strategy name."""
        return "Aggressive Ceiling-Based"

    @property
    def description(self) -> str:
        """Get the strategy description."""
        return (
            "Prioritizes high-ceiling players with significant upside potential. "
            "Embraces variance and contrarian plays to maximize tournament equity. "
            "Optimized for large-field GPPs and differentiation-focused lineup construction."
        )

    def _get_default_config(self) -> StrategyConfig:
        """Get default configuration for aggressive strategy."""

        # Aggressive weight adjustments
        weight_adjustments = WeightAdjustment(
            # Heavy emphasis on ceiling, moderate on projection, minimal on floor
            ceiling_weight=Decimal("0.5"),
            projection_weight=Decimal("0.3"),
            floor_weight=Decimal("0.2"),
            # Strong value considerations for leverage
            value_weight=Decimal("0.3"),
            # Contrarian ownership preference
            ownership_weight=Decimal("-0.2"),  # Negative = prefer low ownership
            # Minimal consistency emphasis, strong upside chasing
            consistency_weight=Decimal("0.1"),
            upside_weight=Decimal("0.4"),
            # Heavy matchup and game script considerations
            matchup_weight=Decimal("0.4"),
            game_script_weight=Decimal("0.3"),
            # Position-specific modifiers for upside
            position_modifiers={
                Position.QB.value: Decimal("1.2"),  # QBs have high ceiling potential
                Position.RB.value: Decimal("0.9"),  # RBs often capped by volume
                Position.WR.value: Decimal("1.3"),  # WRs have highest boom potential
                Position.TE.value: Decimal("1.1"),  # TEs can have big games
                Position.K.value: Decimal("0.8"),  # Kickers limited upside
                Position.DEF.value: Decimal("1.1"),  # Defenses can have big days
            },
        )

        return StrategyConfig(
            name=self.name,
            strategy_type=self.strategy_type,
            description=self.description,
            weight_adjustments=weight_adjustments,
            risk_tolerance=Decimal("0.8"),  # High risk tolerance
            variance_preference=Decimal("0.9"),  # Strong preference for high variance
            cash_game_optimized=False,
            gpp_optimized=True,
            stack_preference=Decimal("0.7"),  # Strong stacking preference
            correlation_bonus=Decimal("0.3"),  # Significant correlation bonus
            weather_penalty=Decimal("0.1"),  # Minimal weather penalty (upside focused)
        )

    def score_player(
        self,
        player: Player,
        matchup_analysis: Optional[MatchupAnalysis] = None,
        context: Optional[Dict] = None,
    ) -> PlayerScore:
        """
        Score a player using aggressive strategy principles.

        Emphasizes ceiling projections, upside potential, and leverage opportunities
        while accepting higher variance and bust risk.
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

        # Ceiling component (heavily weighted)
        ceiling_component = Decimal("0")
        if player.projections.ceiling_points:
            ceiling_component = player.projections.ceiling_points * weights.ceiling_weight
        else:
            # Estimate ceiling as 150% of projection if not available
            ceiling_component = base_score * Decimal("1.5") * weights.ceiling_weight

        # Floor component (lightly weighted)
        floor_component = Decimal("0")
        if player.projections.floor_points:
            floor_component = player.projections.floor_points * weights.floor_weight
        else:
            # Estimate floor as 60% of projection if not available
            floor_component = base_score * Decimal("0.6") * weights.floor_weight

        # Value component (important for leverage)
        value_component = Decimal("0")
        if player.value_metrics and weights.value_weight > 0:
            projected_value = player.get_projected_value()
            if projected_value:
                # Reward high value plays more aggressively
                value_component = (
                    min(projected_value * Decimal("1.2"), Decimal("12")) * weights.value_weight
                )

        # Ownership component (contrarian preference)
        ownership_component = self.calculate_ownership_adjustment(player)

        # Matchup component (heavily weighted)
        matchup_component = self.calculate_matchup_bonus(player, matchup_analysis)

        # Calculate total adjusted score
        adjusted_score = (
            projection_component
            + ceiling_component
            + floor_component
            + value_component
            + ownership_component
            + matchup_component
        )

        # Apply upside bonus/penalty
        upside_score = self._calculate_upside_score(player)
        upside_adjustment = upside_score * weights.upside_weight
        adjusted_score += upside_adjustment

        # Apply game script adjustment (more aggressive)
        game_script_adjustment = self.calculate_game_script_adjustment(
            player, matchup_analysis
        ) * Decimal("1.5")
        adjusted_score += game_script_adjustment

        # Apply aggressive-specific adjustments
        aggressive_adjustments = self._apply_aggressive_adjustments(player, matchup_analysis)
        adjusted_score += aggressive_adjustments["adjustment"]

        # Build score breakdown
        boost_factors = aggressive_adjustments["boost_factors"]
        penalty_factors = aggressive_adjustments["penalty_factors"]

        # Add general boost factors
        if ceiling_component > projection_component:
            boost_factors.append("High ceiling projection")
        if upside_score > Decimal("0.7"):
            boost_factors.append("Significant upside potential")
        if ownership_component > Decimal("0.05"):
            boost_factors.append("Low ownership leverage")
        if (
            player.value_metrics
            and player.get_projected_value()
            and player.get_projected_value() > Decimal("6")
        ):
            boost_factors.append("Strong value play")

        # Add general penalty factors
        if player.projections.confidence_score < Decimal("0.4"):
            penalty_factors.append("Low projection confidence")

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
            consistency_score=self._calculate_consistency_score(player),
            boost_factors=boost_factors,
            penalty_factors=penalty_factors,
        )

    def _calculate_upside_score(self, player: Player) -> Decimal:
        """
        Calculate upside potential score for a player.

        Based on ceiling-to-projection ratio, breakout potential,
        and situational upside factors.
        """
        if not player.projections:
            return Decimal("0.5")

        upside_score = Decimal("0.5")  # Base score

        # Factor 1: Ceiling-to-projection ratio
        if player.projections.ceiling_points:
            ceiling_ratio = (
                player.projections.ceiling_points / player.projections.projected_fantasy_points
            )
            # Higher ceiling ratio = more upside
            upside_boost = min((ceiling_ratio - Decimal("1.2")) * Decimal("0.5"), Decimal("0.3"))
            upside_score += max(Decimal("0"), upside_boost)

        # Factor 2: Low confidence can indicate upside if player hits
        if player.projections.confidence_score < Decimal("0.6"):
            upside_score += Decimal("0.1")

        # Factor 3: Position-specific upside factors
        if player.position == Position.WR:
            # WRs have highest upside variance
            upside_score += Decimal("0.1")
        elif player.position == Position.QB:
            # QBs can have explosive games
            upside_score += Decimal("0.05")
        elif player.position == Position.TE:
            # TEs can have boom weeks
            upside_score += Decimal("0.05")

        # Factor 4: Young players with breakout potential
        if player.years_pro and player.years_pro <= 3:
            upside_score += Decimal("0.05")

        # Factor 5: Recent form suggesting upside
        if (
            player.last_game_stats
            and player.last_game_stats.fantasy_points
            and player.projections.projected_fantasy_points > 0
            and player.last_game_stats.fantasy_points
            > player.projections.projected_fantasy_points * Decimal("1.2")
        ):
            upside_score += Decimal("0.1")

        return max(Decimal("0"), min(Decimal("1"), upside_score))

    def _calculate_variance_score(self, player: Player) -> Optional[Decimal]:
        """Calculate variance score for a player (0=low variance, 1=high variance)."""
        if not player.projections:
            return None

        if player.projections.floor_points and player.projections.ceiling_points:
            variance = player.projections.ceiling_points - player.projections.floor_points
            projection = player.projections.projected_fantasy_points

            if projection > 0:
                return min(Decimal("1"), variance / projection)

        # For aggressive strategy, assume higher variance is better
        # Use inverse of confidence as variance proxy
        if player.projections.confidence_score:
            return Decimal("1") - player.projections.confidence_score

        return Decimal("0.7")  # Default high variance

    def _calculate_consistency_score(self, player: Player) -> Decimal:
        """
        Calculate consistency score (for information, not heavily weighted in aggressive).
        """
        if not player.projections:
            return Decimal("0.5")

        # For aggressive strategy, we still track consistency but don't prioritize it
        consistency = player.projections.confidence_score or Decimal("0.5")

        # Adjust based on variance (high variance = low consistency)
        if player.projections.floor_points and player.projections.ceiling_points:
            variance = player.projections.ceiling_points - player.projections.floor_points
            projection = player.projections.projected_fantasy_points

            if projection > 0:
                variance_ratio = variance / projection
                consistency *= Decimal("2") - variance_ratio  # Penalize high variance

        return max(Decimal("0"), min(Decimal("1"), consistency))

    def _apply_aggressive_adjustments(
        self, player: Player, matchup_analysis: Optional[MatchupAnalysis]
    ) -> Dict:
        """Apply aggressive-specific adjustments and rationale."""
        adjustment = Decimal("0")
        boost_factors = []
        penalty_factors = []

        # Bonus for young/breakout candidates
        if player.years_pro and player.years_pro <= 2:
            adjustment += Decimal("0.08")
            boost_factors.append("Young player breakout potential")
        elif player.years_pro and player.years_pro <= 4:
            adjustment += Decimal("0.04")
            boost_factors.append("Developing player upside")

        # Bonus for players coming off big games (momentum/confidence)
        if (
            player.last_game_stats
            and player.last_game_stats.fantasy_points
            and player.last_game_stats.fantasy_points >= Decimal("20")
        ):
            adjustment += Decimal("0.06")
            boost_factors.append("Recent explosive performance")

        # Bonus for players in pace-up spots
        if matchup_analysis:
            pace = matchup_analysis.matchup.get_pace_projection()
            if pace == "Fast":
                adjustment += Decimal("0.05")
                boost_factors.append("High-pace game environment")

        # Bonus for players in high-total games
        if (
            matchup_analysis
            and matchup_analysis.matchup.get_total_projected_points()
            and matchup_analysis.matchup.get_total_projected_points() >= Decimal("50")
        ):
            adjustment += Decimal("0.07")
            boost_factors.append("High-total game script")

        # Bonus for players in volatile matchups (more upside potential)
        if matchup_analysis and matchup_analysis.volatility_rating >= 7:
            adjustment += Decimal("0.05")
            boost_factors.append("High-variance game environment")

        # Bonus for contrarian plays in expected blowouts
        if matchup_analysis:
            blowout_prob = matchup_analysis.get_blowout_probability()
            if blowout_prob > Decimal("0.3"):
                # Favor players from the losing team (garbage time upside)
                player_team_prob = (
                    matchup_analysis.home_win_probability
                    if player.team == matchup_analysis.matchup.home_team
                    else matchup_analysis.away_win_probability
                )

                if player_team_prob < Decimal("0.4"):
                    if player.position in [Position.QB, Position.WR, Position.TE]:
                        adjustment += Decimal("0.06")
                        boost_factors.append("Garbage time upside potential")

        # Bonus for players with target/touch upside
        if player.season_stats and player.position in [Position.WR, Position.TE]:
            games_played = player.season_stats.games_played or 1
            if (
                player.season_stats.targets
                and player.season_stats.targets / games_played >= 6
                and player.season_stats.targets / games_played <= 10
            ):
                adjustment += Decimal("0.04")
                boost_factors.append("Target share growth potential")

        # Penalty for capped ceiling situations
        if (
            matchup_analysis
            and matchup_analysis.matchup.game_environment
            and matchup_analysis.matchup.game_environment.is_weather_concern()
        ):
            # Weather caps upside more than hurts floors
            adjustment -= Decimal("0.04")
            penalty_factors.append("Weather caps upside potential")

        # Penalty for players in heavy chalk situations (unless they're truly elite)
        if (
            player.value_metrics
            and player.value_metrics.projected_ownership
            and player.value_metrics.projected_ownership > Decimal("30")
            and player.projections
            and player.projections.projected_fantasy_points < Decimal("20")
        ):
            adjustment -= Decimal("0.03")
            penalty_factors.append("High ownership without elite projection")

        # Bonus for players in revenge/narrative spots
        if player.news_notes:
            narrative_keywords = ["revenge", "former team", "bounce back", "return"]
            if any(
                keyword in note.lower()
                for note in player.news_notes
                for keyword in narrative_keywords
            ):
                adjustment += Decimal("0.02")
                boost_factors.append("Narrative/revenge game angle")

        # Position-specific aggressive adjustments
        if player.position == Position.QB:
            # Bonus for QBs with rushing upside
            if (
                player.season_stats
                and player.season_stats.rushing_attempts
                and player.season_stats.games_played
                and player.season_stats.rushing_attempts / player.season_stats.games_played >= 5
            ):
                adjustment += Decimal("0.05")
                boost_factors.append("Rushing upside for QB")

        elif player.position == Position.RB:
            # Bonus for pass-catching backs in negative game scripts
            if (
                player.season_stats
                and player.season_stats.targets
                and player.season_stats.games_played
                and player.season_stats.targets / player.season_stats.games_played >= 4
            ):
                adjustment += Decimal("0.03")
                boost_factors.append("Pass-catching RB upside")

        elif player.position == Position.WR:
            # Bonus for deep threat receivers
            if (
                player.season_stats
                and player.season_stats.receiving_yards
                and player.season_stats.receptions
                and player.season_stats.receptions > 0
            ):
                yards_per_reception = (
                    player.season_stats.receiving_yards / player.season_stats.receptions
                )
                if yards_per_reception >= Decimal("15"):
                    adjustment += Decimal("0.04")
                    boost_factors.append("Deep threat/big play upside")

        return {
            "adjustment": adjustment,
            "boost_factors": boost_factors,
            "penalty_factors": penalty_factors,
        }

    def get_position_allocation_preferences(self) -> Dict[str, Decimal]:
        """
        Get aggressive strategy position allocation preferences.

        Returns position preference weights for portfolio construction.
        """
        return {
            Position.QB.value: Decimal("1.2"),  # QBs have high ceiling potential
            Position.RB.value: Decimal("0.8"),  # RBs often volume-capped
            Position.WR.value: Decimal("1.4"),  # WRs highest boom potential
            Position.TE.value: Decimal("1.1"),  # TEs can have explosive weeks
            Position.K.value: Decimal("0.7"),  # Kickers limited upside
            Position.DEF.value: Decimal("1.0"),  # Defenses can boom but unpredictable
        }

    def get_recommended_contest_types(self) -> List[str]:
        """Get contest types best suited for this strategy."""
        return [
            "Large-field GPPs",
            "High-stakes tournaments",
            "Millionaire Makers",
            "Single-entry tournaments",
            "Satellite qualifiers",
        ]

    def get_stack_recommendations(self, matchup_analysis: Optional[MatchupAnalysis]) -> List[str]:
        """Get stacking recommendations for aggressive strategy."""
        recommendations = []

        # Aggressive stacking focuses on correlated upside
        recommendations.extend(
            [
                "Full game stacks (QB + 2+ receivers from same team)",
                "Bring-back stacks (opposing team players)",
                "4+ player correlation stacks",
                "Leverage stacks with low-owned players",
            ]
        )

        if matchup_analysis:
            # Look for high-upside game environments
            total_proj = matchup_analysis.matchup.get_total_projected_points()
            if total_proj and total_proj >= Decimal("48"):
                recommendations.append("Full game stack in high-total shootout")

            if matchup_analysis.volatility_rating >= 7:
                recommendations.append("Leverage volatile game with contrarian stacks")

            if matchup_analysis.is_close_game():
                recommendations.append("Bring-back stack in projected close game")

        return recommendations

    def get_leverage_opportunities(
        self, players: List[Player], matchup_analyses: Optional[List[MatchupAnalysis]] = None
    ) -> List[Dict]:
        """
        Identify specific leverage opportunities for aggressive strategy.

        Returns list of leverage spots with reasoning.
        """
        opportunities = []

        for player in players:
            if not player.projections or not player.value_metrics:
                continue

            leverage_score = Decimal("0")
            reasons = []

            # Low ownership + high ceiling
            ownership = player.value_metrics.projected_ownership or Decimal("50")
            if ownership < Decimal("10") and player.projections.ceiling_points:
                if player.projections.ceiling_points >= Decimal("25"):
                    leverage_score += Decimal("0.8")
                    reasons.append("Low ownership with high ceiling")

            # Value + upside combination
            value = player.get_projected_value()
            if value and value >= Decimal("5") and ownership < Decimal("15"):
                leverage_score += Decimal("0.6")
                reasons.append("Strong value with low ownership")

            # Recent struggles creating leverage
            if (
                player.last_game_stats
                and player.last_game_stats.fantasy_points
                and player.last_game_stats.fantasy_points < Decimal("8")
                and player.projections.projected_fantasy_points >= Decimal("12")
            ):
                leverage_score += Decimal("0.4")
                reasons.append("Bounce-back spot after poor performance")

            if leverage_score >= Decimal("0.5") and reasons:
                opportunities.append(
                    {
                        "player": player,
                        "leverage_score": leverage_score,
                        "reasons": reasons,
                        "ownership": ownership,
                        "ceiling": player.projections.ceiling_points,
                    }
                )

        # Sort by leverage score descending
        return sorted(opportunities, key=lambda x: x["leverage_score"], reverse=True)
