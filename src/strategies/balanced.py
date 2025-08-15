"""
Balanced lineup strategy for fantasy football.

This strategy optimizes the risk/reward ratio, balancing floor and ceiling considerations
while maintaining value efficiency. Suitable for a variety of contest types and provides
a well-rounded approach to lineup construction.
"""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from ..models.player import Player, Position
from ..models.matchup import MatchupAnalysis
from .base import BaseLineupStrategy, StrategyConfig, StrategyType, WeightAdjustment, PlayerScore


class BalancedStrategy(BaseLineupStrategy):
    """
    Balanced lineup strategy optimizing risk/reward ratio.
    
    This strategy is designed for:
    - Mixed contest portfolios
    - Players seeking optimal risk/reward balance
    - Versatile lineups suitable for multiple contest types
    - Situations where neither pure safety nor pure upside is optimal
    
    Key characteristics:
    - Balanced weighting of floor, projection, and ceiling
    - Optimal risk/reward ratio optimization
    - Value-conscious player selection
    - Moderate stacking strategies
    - Adaptable to different game environments
    """
    
    @property
    def strategy_type(self) -> StrategyType:
        """Get the strategy type."""
        return StrategyType.BALANCED
    
    @property
    def name(self) -> str:
        """Get the strategy name."""
        return "Balanced Risk/Reward"
    
    @property
    def description(self) -> str:
        """Get the strategy description."""
        return (
            "Optimizes the risk/reward ratio by balancing floor safety with ceiling upside. "
            "Considers value efficiency and matchup factors to build versatile lineups "
            "suitable for various contest types while maintaining optimal risk exposure."
        )
    
    def _get_default_config(self) -> StrategyConfig:
        """Get default configuration for balanced strategy."""
        
        # Balanced weight adjustments
        weight_adjustments = WeightAdjustment(
            # Balanced emphasis across floor, projection, and ceiling
            floor_weight=Decimal('0.3'),
            projection_weight=Decimal('0.4'),
            ceiling_weight=Decimal('0.3'),
            
            # Strong value considerations
            value_weight=Decimal('0.25'),
            
            # Neutral ownership preference (slight contrarian lean)
            ownership_weight=Decimal('-0.05'),
            
            # Balanced consistency and upside considerations
            consistency_weight=Decimal('0.25'),
            upside_weight=Decimal('0.25'),
            
            # Moderate matchup considerations
            matchup_weight=Decimal('0.3'),
            game_script_weight=Decimal('0.25'),
            
            # Position-specific modifiers for balance
            position_modifiers={
                Position.QB.value: Decimal('1.0'),    # Neutral QB weighting
                Position.RB.value: Decimal('1.05'),   # Slight RB preference for reliability
                Position.WR.value: Decimal('1.0'),    # Neutral WR weighting
                Position.TE.value: Decimal('1.0'),    # Neutral TE weighting
                Position.K.value: Decimal('0.95'),    # Slight K discount for variance
                Position.DEF.value: Decimal('1.0'),   # Neutral DEF weighting
            }
        )
        
        return StrategyConfig(
            name=self.name,
            strategy_type=self.strategy_type,
            description=self.description,
            weight_adjustments=weight_adjustments,
            risk_tolerance=Decimal('0.5'),      # Moderate risk tolerance
            variance_preference=Decimal('0.5'), # Balanced variance preference
            cash_game_optimized=True,
            gpp_optimized=True,
            stack_preference=Decimal('0.4'),    # Moderate stacking preference
            correlation_bonus=Decimal('0.2'),   # Moderate correlation bonus
            weather_penalty=Decimal('0.2'),     # Moderate weather penalty
        )
    
    def score_player(
        self, 
        player: Player, 
        matchup_analysis: Optional[MatchupAnalysis] = None,
        context: Optional[Dict] = None
    ) -> PlayerScore:
        """
        Score a player using balanced strategy principles.
        
        Optimizes risk/reward ratio by balancing floor safety, ceiling upside,
        value efficiency, and matchup considerations.
        """
        if not player.projections:
            # Cannot score player without projections
            return PlayerScore(
                player_id=player.id,
                base_score=Decimal('0'),
                adjusted_score=Decimal('0'),
                boost_factors=["No projections available"],
                penalty_factors=[]
            )
        
        # Get position-adjusted weights
        weights = self.adjust_weights_for_position(
            player.position, 
            self.config.weight_adjustments
        )
        
        # Start with base projection
        base_score = player.projections.projected_fantasy_points
        
        # Calculate component scores
        projection_component = base_score * weights.projection_weight
        
        # Floor component (moderately weighted)
        floor_component = Decimal('0')
        if player.projections.floor_points:
            floor_component = player.projections.floor_points * weights.floor_weight
        else:
            # Estimate floor as 65% of projection if not available
            floor_component = base_score * Decimal('0.65') * weights.floor_weight
        
        # Ceiling component (moderately weighted)
        ceiling_component = Decimal('0')
        if player.projections.ceiling_points:
            ceiling_component = player.projections.ceiling_points * weights.ceiling_weight
        else:
            # Estimate ceiling as 140% of projection if not available
            ceiling_component = base_score * Decimal('1.4') * weights.ceiling_weight
        
        # Value component (important for balanced approach)
        value_component = Decimal('0')
        if player.value_metrics and weights.value_weight > 0:
            projected_value = player.get_projected_value()
            if projected_value:
                # Balance value consideration with risk
                value_component = min(projected_value * Decimal('1.1'), Decimal('11')) * weights.value_weight
        
        # Ownership component (slight contrarian preference)
        ownership_component = self.calculate_ownership_adjustment(player)
        
        # Matchup component
        matchup_component = self.calculate_matchup_bonus(player, matchup_analysis)
        
        # Calculate total adjusted score
        adjusted_score = (
            projection_component + 
            floor_component + 
            ceiling_component + 
            value_component + 
            ownership_component + 
            matchup_component
        )
        
        # Apply risk/reward optimization
        risk_reward_score = self._calculate_risk_reward_score(player)
        risk_reward_adjustment = risk_reward_score * Decimal('0.15')  # Moderate weight
        adjusted_score += risk_reward_adjustment
        
        # Apply balanced consistency and upside adjustments
        consistency_score = self._calculate_consistency_score(player)
        upside_score = self._calculate_upside_score(player)
        
        consistency_adjustment = consistency_score * weights.consistency_weight
        upside_adjustment = upside_score * weights.upside_weight
        adjusted_score += consistency_adjustment + upside_adjustment
        
        # Apply weather penalty (moderate)
        weather_penalty = self.calculate_weather_penalty(player, matchup_analysis)
        adjusted_score += weather_penalty
        
        # Apply game script adjustment
        game_script_adjustment = self.calculate_game_script_adjustment(player, matchup_analysis)
        adjusted_score += game_script_adjustment
        
        # Apply balanced-specific adjustments
        balanced_adjustments = self._apply_balanced_adjustments(player, matchup_analysis)
        adjusted_score += balanced_adjustments['adjustment']
        
        # Build score breakdown
        boost_factors = balanced_adjustments['boost_factors']
        penalty_factors = balanced_adjustments['penalty_factors']
        
        # Add general boost factors
        if risk_reward_score > Decimal('0.7'):
            boost_factors.append("Optimal risk/reward ratio")
        if consistency_score > Decimal('0.6') and upside_score > Decimal('0.6'):
            boost_factors.append("Strong floor with upside potential")
        if player.value_metrics and player.get_projected_value() and player.get_projected_value() > Decimal('5.5'):
            boost_factors.append("Good value efficiency")
        
        # Add general penalty factors
        if risk_reward_score < Decimal('0.3'):
            penalty_factors.append("Poor risk/reward profile")
        if weather_penalty < Decimal('-0.05'):
            penalty_factors.append("Weather impact concerns")
        
        return PlayerScore(
            player_id=player.id,
            base_score=base_score,
            adjusted_score=max(adjusted_score, Decimal('0')),  # Ensure non-negative
            projection_component=projection_component,
            floor_component=floor_component,
            ceiling_component=ceiling_component,
            value_component=value_component,
            ownership_component=ownership_component,
            matchup_component=matchup_component,
            variance_score=self._calculate_variance_score(player),
            consistency_score=consistency_score,
            boost_factors=boost_factors,
            penalty_factors=penalty_factors
        )
    
    def _calculate_risk_reward_score(self, player: Player) -> Decimal:
        """
        Calculate risk/reward optimization score for a player.
        
        Balances upside potential against downside risk to find optimal
        risk-adjusted expected value.
        """
        if not player.projections:
            return Decimal('0.5')
        
        base_projection = player.projections.projected_fantasy_points
        floor = player.projections.floor_points or (base_projection * Decimal('0.65'))
        ceiling = player.projections.ceiling_points or (base_projection * Decimal('1.4'))
        
        # Calculate risk metrics
        downside_risk = base_projection - floor
        upside_potential = ceiling - base_projection
        
        if downside_risk <= 0:
            downside_risk = Decimal('0.01')  # Avoid division by zero
        
        # Risk/reward ratio = upside potential / downside risk
        risk_reward_ratio = upside_potential / downside_risk
        
        # Normalize to 0-1 scale (higher is better)
        # Optimal ratio is around 1.5-2.0 (more upside than downside)
        if risk_reward_ratio >= Decimal('2.0'):
            return Decimal('1.0')
        elif risk_reward_ratio >= Decimal('1.5'):
            return Decimal('0.8')
        elif risk_reward_ratio >= Decimal('1.0'):
            return Decimal('0.6')
        elif risk_reward_ratio >= Decimal('0.7'):
            return Decimal('0.4')
        else:
            return Decimal('0.2')
    
    def _calculate_consistency_score(self, player: Player) -> Decimal:
        """Calculate consistency score for a player."""
        if not player.projections:
            return Decimal('0.5')
        
        consistency_score = Decimal('0.5')  # Base score
        
        # Factor 1: Projection confidence
        confidence_boost = (player.projections.confidence_score - Decimal('0.5')) * Decimal('0.3')
        consistency_score += confidence_boost
        
        # Factor 2: Floor-to-projection ratio (higher floor = more consistent)
        if player.projections.floor_points:
            floor_ratio = player.projections.floor_points / player.projections.projected_fantasy_points
            consistency_boost = (floor_ratio - Decimal('0.6')) * Decimal('0.4')
            consistency_score += max(Decimal('0'), consistency_boost)
        
        # Factor 3: Injury status
        if not player.is_injured():
            consistency_score += Decimal('0.1')
        else:
            consistency_score -= Decimal('0.15')
        
        # Factor 4: Position-specific consistency
        if player.position in [Position.QB, Position.TE]:
            consistency_score += Decimal('0.05')  # Generally more consistent
        elif player.position == Position.WR:
            consistency_score -= Decimal('0.05')  # More volatile
        
        return max(Decimal('0'), min(Decimal('1'), consistency_score))
    
    def _calculate_upside_score(self, player: Player) -> Decimal:
        """Calculate upside potential score for a player."""
        if not player.projections:
            return Decimal('0.5')
        
        upside_score = Decimal('0.5')  # Base score
        
        # Factor 1: Ceiling-to-projection ratio
        if player.projections.ceiling_points:
            ceiling_ratio = player.projections.ceiling_points / player.projections.projected_fantasy_points
            upside_boost = (ceiling_ratio - Decimal('1.2')) * Decimal('0.3')
            upside_score += max(Decimal('0'), upside_boost)
        
        # Factor 2: Recent upside demonstrations
        if (player.last_game_stats and 
            player.last_game_stats.fantasy_points and 
            player.projections.projected_fantasy_points > 0 and
            player.last_game_stats.fantasy_points > player.projections.projected_fantasy_points * Decimal('1.3')):
            upside_score += Decimal('0.1')
        
        # Factor 3: Position upside potential
        if player.position == Position.WR:
            upside_score += Decimal('0.1')  # High upside position
        elif player.position == Position.QB:
            upside_score += Decimal('0.05')  # Moderate upside
        elif player.position == Position.TE:
            upside_score += Decimal('0.05')  # Boom potential
        
        # Factor 4: Value upside (underpriced relative to projection)
        if player.value_metrics:
            projected_value = player.get_projected_value()
            if projected_value and projected_value >= Decimal('6'):
                upside_score += Decimal('0.1')
        
        return max(Decimal('0'), min(Decimal('1'), upside_score))
    
    def _calculate_variance_score(self, player: Player) -> Optional[Decimal]:
        """Calculate variance score for a player (0=low variance, 1=high variance)."""
        if not player.projections:
            return None
        
        if player.projections.floor_points and player.projections.ceiling_points:
            variance = player.projections.ceiling_points - player.projections.floor_points
            projection = player.projections.projected_fantasy_points
            
            if projection > 0:
                return min(Decimal('1'), variance / projection)
        
        # Use bust probability as variance proxy if available
        if player.projections.bust_probability:
            return player.projections.bust_probability
        
        return Decimal('0.5')  # Default moderate variance
    
    def _apply_balanced_adjustments(
        self, 
        player: Player, 
        matchup_analysis: Optional[MatchupAnalysis]
    ) -> Dict:
        """Apply balanced-specific adjustments and rationale."""
        adjustment = Decimal('0')
        boost_factors = []
        penalty_factors = []
        
        # Bonus for optimal experience level (not too young, not too old)
        if player.years_pro:
            if 3 <= player.years_pro <= 8:
                adjustment += Decimal('0.03')
                boost_factors.append("Optimal experience level")
            elif player.years_pro <= 1:
                adjustment -= Decimal('0.02')
                penalty_factors.append("Inexperience factor")
            elif player.years_pro >= 12:
                adjustment -= Decimal('0.01')
                penalty_factors.append("Age/decline concerns")
        
        # Bonus for players with consistent target/touch share
        if player.season_stats and player.position in [Position.WR, Position.TE, Position.RB]:
            games_played = player.season_stats.games_played or 1
            
            if player.position in [Position.WR, Position.TE]:
                if player.season_stats.targets:
                    target_share = player.season_stats.targets / games_played
                    if 7 <= target_share <= 12:  # Optimal range
                        adjustment += Decimal('0.04')
                        boost_factors.append("Consistent target share")
            elif player.position == Position.RB:
                if player.season_stats.rushing_attempts:
                    attempt_share = player.season_stats.rushing_attempts / games_played
                    if 12 <= attempt_share <= 18:  # Optimal range
                        adjustment += Decimal('0.04')
                        boost_factors.append("Consistent touch share")
        
        # Bonus for home field advantage (moderate)
        if player.home_away == "Home":
            adjustment += Decimal('0.015')
            boost_factors.append("Home field advantage")
        
        # Penalty for players in injury-prone situations
        if player.is_injured():
            if (player.injury_report and 
                player.injury_report.severity_score and 
                player.injury_report.severity_score >= 3):
                penalty = min(Decimal('0.15'), player.injury_report.severity_score * Decimal('0.02'))
                adjustment -= penalty
                penalty_factors.append("Injury risk concern")
        
        # Balanced game script considerations
        if matchup_analysis:
            player_team_analysis = None
            if player.team == matchup_analysis.matchup.home_team:
                player_team_analysis = matchup_analysis.home_team_analysis
            elif player.team == matchup_analysis.matchup.away_team:
                player_team_analysis = matchup_analysis.away_team_analysis
            
            if player_team_analysis:
                # Moderate adjustments for game script
                if "balanced" in player_team_analysis.likely_game_script.lower():
                    adjustment += Decimal('0.02')
                    boost_factors.append("Balanced game script")
                elif "extreme" in player_team_analysis.likely_game_script.lower():
                    adjustment -= Decimal('0.02')
                    penalty_factors.append("Extreme game script variance")
        
        # Bonus for players in moderate-total games (not too high, not too low)
        if (matchup_analysis and 
            matchup_analysis.matchup.get_total_projected_points()):
            total = matchup_analysis.matchup.get_total_projected_points()
            if Decimal('44') <= total <= Decimal('48'):
                adjustment += Decimal('0.02')
                boost_factors.append("Optimal game total range")
            elif total < Decimal('40') or total > Decimal('52'):
                adjustment -= Decimal('0.01')
                penalty_factors.append("Non-optimal game total")
        
        # Volume opportunity adjustments
        if (matchup_analysis and 
            matchup_analysis.key_injuries):
            # Check if key injuries create opportunity
            position_injuries = [
                inj for inj in matchup_analysis.key_injuries 
                if player.position.value.lower() in inj.lower()
            ]
            if position_injuries:
                adjustment += Decimal('0.03')
                boost_factors.append("Volume opportunity from injuries")
        
        # Balanced ownership sweet spot
        if player.value_metrics and player.value_metrics.projected_ownership:
            ownership = player.value_metrics.projected_ownership
            if Decimal('8') <= ownership <= Decimal('25'):
                adjustment += Decimal('0.02')
                boost_factors.append("Optimal ownership range")
            elif ownership >= Decimal('40'):
                adjustment -= Decimal('0.02')
                penalty_factors.append("Excessive ownership")
        
        # Weather considerations (balanced approach)
        if (matchup_analysis and 
            matchup_analysis.matchup.game_environment and
            matchup_analysis.matchup.game_environment.venue_type and
            matchup_analysis.matchup.game_environment.venue_type.value == "Dome"):
            adjustment += Decimal('0.01')
            boost_factors.append("Dome game consistency")
        
        return {
            'adjustment': adjustment,
            'boost_factors': boost_factors,
            'penalty_factors': penalty_factors
        }
    
    def optimize_lineup_balance(
        self, 
        potential_players: List[Player], 
        constraints: Dict
    ) -> Dict[str, Decimal]:
        """
        Optimize overall lineup balance across risk/reward spectrum.
        
        Returns recommended allocation weights for balanced approach.
        """
        allocation = {
            'high_floor_players': Decimal('0.4'),    # 40% safe plays
            'medium_risk_players': Decimal('0.4'),   # 40% balanced plays  
            'high_upside_players': Decimal('0.2'),   # 20% upside plays
        }
        
        # Adjust based on contest type if provided
        contest_type = constraints.get('contest_type', '').lower()
        
        if 'cash' in contest_type or 'double' in contest_type:
            # More conservative for cash games
            allocation['high_floor_players'] = Decimal('0.5')
            allocation['medium_risk_players'] = Decimal('0.4')
            allocation['high_upside_players'] = Decimal('0.1')
        elif 'gpp' in contest_type or 'tournament' in contest_type:
            # More aggressive for tournaments
            allocation['high_floor_players'] = Decimal('0.3')
            allocation['medium_risk_players'] = Decimal('0.4')
            allocation['high_upside_players'] = Decimal('0.3')
        
        return allocation
    
    def get_position_allocation_preferences(self) -> Dict[str, Decimal]:
        """
        Get balanced strategy position allocation preferences.
        """
        return {
            Position.QB.value: Decimal('1.0'),     # Balanced QB approach
            Position.RB.value: Decimal('1.05'),    # Slight RB preference for consistency
            Position.WR.value: Decimal('1.0'),     # Balanced WR approach
            Position.TE.value: Decimal('1.0'),     # Balanced TE approach
            Position.K.value: Decimal('0.95'),     # Slight K discount for unpredictability
            Position.DEF.value: Decimal('1.0'),    # Balanced DEF approach
        }
    
    def get_recommended_contest_types(self) -> List[str]:
        """Get contest types best suited for this strategy."""
        return [
            "Mixed contest portfolios",
            "Medium-field GPPs (100-1000 entries)",
            "Balanced cash/GPP approach",
            "Multi-entry tournaments",
            "Weekly qualifiers"
        ]
    
    def get_stack_recommendations(self, matchup_analysis: Optional[MatchupAnalysis]) -> List[str]:
        """Get stacking recommendations for balanced strategy."""
        recommendations = []
        
        # Balanced stacking approach
        recommendations.extend([
            "2-3 player mini-stacks for correlation",
            "QB + primary WR combinations",
            "Moderate bring-back components",
            "Avoid over-correlation (4+ same team)"
        ])
        
        if matchup_analysis:
            # Adapt to game environment
            total_proj = matchup_analysis.matchup.get_total_projected_points()
            if total_proj and Decimal('46') <= total_proj <= Decimal('50'):
                recommendations.append("Standard QB + WR stack in moderate-total game")
            
            if matchup_analysis.is_close_game():
                recommendations.append("Light bring-back stack in close game")
                
            if matchup_analysis.volatility_rating <= 5:
                recommendations.append("Conservative stacking in low-variance environment")
        
        return recommendations
    
    def calculate_portfolio_balance(
        self, 
        scored_players: List[Tuple[Player, PlayerScore]]
    ) -> Dict[str, Decimal]:
        """
        Calculate balance metrics for a portfolio of players.
        
        Returns balance scores and recommendations.
        """
        if not scored_players:
            return {}
        
        # Categorize players by risk profile
        high_floor = []
        balanced_risk = []
        high_upside = []
        
        for player, score in scored_players:
            variance = score.variance_score or Decimal('0.5')
            consistency = score.consistency_score or Decimal('0.5')
            
            if consistency >= Decimal('0.7') and variance <= Decimal('0.3'):
                high_floor.append((player, score))
            elif variance >= Decimal('0.7') or (score.ceiling_component > score.floor_component * Decimal('1.5')):
                high_upside.append((player, score))
            else:
                balanced_risk.append((player, score))
        
        total_players = len(scored_players)
        
        return {
            'high_floor_percentage': Decimal(len(high_floor)) / total_players,
            'balanced_risk_percentage': Decimal(len(balanced_risk)) / total_players,
            'high_upside_percentage': Decimal(len(high_upside)) / total_players,
            'overall_balance_score': self._calculate_overall_balance_score(
                len(high_floor), len(balanced_risk), len(high_upside)
            ),
            'recommendations': self._get_balance_recommendations(
                len(high_floor), len(balanced_risk), len(high_upside), total_players
            )
        }
    
    def _calculate_overall_balance_score(
        self, 
        high_floor_count: int, 
        balanced_count: int, 
        high_upside_count: int
    ) -> Decimal:
        """Calculate overall balance score for a lineup."""
        total = high_floor_count + balanced_count + high_upside_count
        if total == 0:
            return Decimal('0')
        
        # Ideal distribution for balanced strategy
        ideal_floor_pct = Decimal('0.4')
        ideal_balanced_pct = Decimal('0.4')
        ideal_upside_pct = Decimal('0.2')
        
        # Actual distribution
        actual_floor_pct = Decimal(high_floor_count) / total
        actual_balanced_pct = Decimal(balanced_count) / total
        actual_upside_pct = Decimal(high_upside_count) / total
        
        # Calculate deviation from ideal
        floor_deviation = abs(actual_floor_pct - ideal_floor_pct)
        balanced_deviation = abs(actual_balanced_pct - ideal_balanced_pct)
        upside_deviation = abs(actual_upside_pct - ideal_upside_pct)
        
        total_deviation = floor_deviation + balanced_deviation + upside_deviation
        
        # Convert to 0-1 score (lower deviation = higher score)
        return max(Decimal('0'), Decimal('1') - (total_deviation / Decimal('2')))
    
    def _get_balance_recommendations(
        self, 
        high_floor_count: int, 
        balanced_count: int, 
        high_upside_count: int, 
        total_count: int
    ) -> List[str]:
        """Get recommendations for improving portfolio balance."""
        recommendations = []
        
        if total_count == 0:
            return recommendations
        
        floor_pct = high_floor_count / total_count
        balanced_pct = balanced_count / total_count
        upside_pct = high_upside_count / total_count
        
        if floor_pct < 0.3:
            recommendations.append("Consider adding more high-floor players for stability")
        elif floor_pct > 0.6:
            recommendations.append("Too many safe players - add more upside")
        
        if balanced_pct < 0.2:
            recommendations.append("Add more balanced risk/reward players")
        elif balanced_pct > 0.6:
            recommendations.append("Consider more extreme plays (safer or higher upside)")
        
        if upside_pct < 0.1:
            recommendations.append("Add upside players for tournament equity")
        elif upside_pct > 0.4:
            recommendations.append("Too much risk - add safer players")
        
        if not recommendations:
            recommendations.append("Good risk/reward balance achieved")
        
        return recommendations