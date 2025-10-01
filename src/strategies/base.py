"""
Base strategy interface for fantasy football lineup optimization.

This module provides the abstract base class that all lineup strategies must implement,
defining the common interface for player scoring, weight adjustments, and strategy configuration.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from ..models.player import Player, Position
from ..models.matchup import MatchupAnalysis
from ..models.lineup import LineupConstraints, OptimizationStrategy


class StrategyType(str, Enum):
    """Available lineup strategy types."""

    CONSERVATIVE = "Conservative"
    AGGRESSIVE = "Aggressive"
    BALANCED = "Balanced"
    CUSTOM = "Custom"


class WeightAdjustment(BaseModel):
    """Weight adjustment configuration for different factors."""

    # Core projection weights
    floor_weight: Decimal = Field(
        Decimal("0.0"), ge=0, le=1, description="Weight for floor projection"
    )
    ceiling_weight: Decimal = Field(
        Decimal("0.0"), ge=0, le=1, description="Weight for ceiling projection"
    )
    projection_weight: Decimal = Field(
        Decimal("1.0"), ge=0, le=1, description="Weight for base projection"
    )

    # Value and efficiency weights
    value_weight: Decimal = Field(Decimal("0.0"), ge=0, le=1, description="Weight for salary value")
    ownership_weight: Decimal = Field(
        Decimal("0.0"), ge=-1, le=1, description="Weight for ownership (negative = contrarian)"
    )

    # Risk and variance weights
    consistency_weight: Decimal = Field(
        Decimal("0.0"), ge=0, le=1, description="Weight for consistency/low variance"
    )
    upside_weight: Decimal = Field(
        Decimal("0.0"), ge=0, le=1, description="Weight for upside potential"
    )

    # Matchup-specific weights
    matchup_weight: Decimal = Field(
        Decimal("0.0"), ge=0, le=1, description="Weight for matchup favorability"
    )
    game_script_weight: Decimal = Field(
        Decimal("0.0"), ge=0, le=1, description="Weight for game script predictions"
    )

    # Position-specific modifiers
    position_modifiers: Dict[str, Decimal] = Field(
        default_factory=dict, description="Position-specific weight modifiers"
    )


class StrategyConfig(BaseModel):
    """Configuration settings for a lineup strategy."""

    # Strategy identification
    name: str = Field(..., description="Strategy name")
    strategy_type: StrategyType = Field(..., description="Strategy type")
    description: str = Field(..., description="Strategy description")

    # Weight adjustments
    weight_adjustments: WeightAdjustment = Field(..., description="Factor weight adjustments")

    # Risk preferences
    risk_tolerance: Decimal = Field(
        Decimal("0.5"), ge=0, le=1, description="Risk tolerance (0=ultra-safe, 1=max-risk)"
    )
    variance_preference: Decimal = Field(
        Decimal("0.5"),
        ge=0,
        le=1,
        description="Variance preference (0=low-variance, 1=high-variance)",
    )

    # Contest type optimization
    gpp_optimized: bool = Field(False, description="Optimized for GPP contests")
    cash_game_optimized: bool = Field(False, description="Optimized for cash games")

    # Stacking preferences
    stack_preference: Decimal = Field(
        Decimal("0.0"), ge=0, le=1, description="Preference for team stacking"
    )
    correlation_bonus: Decimal = Field(
        Decimal("0.0"), ge=0, le=1, description="Bonus for positively correlated players"
    )

    # Weather and environment considerations
    weather_penalty: Decimal = Field(
        Decimal("0.0"), ge=0, le=1, description="Penalty for adverse weather conditions"
    )

    class Config:
        """Pydantic model configuration."""

        json_encoders = {Decimal: lambda v: float(v)}


class PlayerScore(BaseModel):
    """Detailed scoring breakdown for a player."""

    player_id: str = Field(..., description="Player identifier")
    base_score: Decimal = Field(..., description="Base projected score")
    adjusted_score: Decimal = Field(..., description="Strategy-adjusted score")

    # Component scores
    projection_component: Decimal = Field(Decimal("0"), description="Projection component")
    floor_component: Decimal = Field(Decimal("0"), description="Floor component")
    ceiling_component: Decimal = Field(Decimal("0"), description="Ceiling component")
    value_component: Decimal = Field(Decimal("0"), description="Value component")
    ownership_component: Decimal = Field(Decimal("0"), description="Ownership component")
    matchup_component: Decimal = Field(Decimal("0"), description="Matchup component")

    # Risk metrics
    variance_score: Optional[Decimal] = Field(None, description="Variance/volatility score")
    consistency_score: Optional[Decimal] = Field(None, description="Consistency score")

    # Reasoning
    boost_factors: List[str] = Field(default_factory=list, description="Factors boosting score")
    penalty_factors: List[str] = Field(default_factory=list, description="Factors penalizing score")

    class Config:
        """Pydantic model configuration."""

        json_encoders = {Decimal: lambda v: float(v)}


class BaseLineupStrategy(ABC):
    """
    Abstract base class for fantasy football lineup strategies.

    This class defines the interface that all strategy implementations must follow,
    providing methods for player scoring, weight adjustments, and strategy configuration.
    """

    def __init__(self, config: Optional[StrategyConfig] = None):
        """Initialize strategy with optional configuration."""
        self.config = config or self._get_default_config()
        self._validate_config()

    @property
    @abstractmethod
    def strategy_type(self) -> StrategyType:
        """Get the strategy type."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the strategy name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Get the strategy description."""
        pass

    @abstractmethod
    def _get_default_config(self) -> StrategyConfig:
        """Get default configuration for this strategy."""
        pass

    def _validate_config(self) -> None:
        """Validate strategy configuration."""
        if not self.config:
            raise ValueError("Strategy configuration is required")

        # Validate weight adjustments sum appropriately
        weights = self.config.weight_adjustments
        total_core_weights = (
            weights.floor_weight + weights.ceiling_weight + weights.projection_weight
        )

        if total_core_weights == 0:
            raise ValueError("At least one core projection weight must be non-zero")

    @abstractmethod
    def score_player(
        self,
        player: Player,
        matchup_analysis: Optional[MatchupAnalysis] = None,
        context: Optional[Dict] = None,
    ) -> PlayerScore:
        """
        Score a player according to this strategy.

        Args:
            player: Player to score
            matchup_analysis: Optional matchup analysis for context
            context: Optional additional context (weather, injury updates, etc.)

        Returns:
            PlayerScore with detailed scoring breakdown
        """
        pass

    def adjust_weights_for_position(
        self, position: Position, base_weights: WeightAdjustment
    ) -> WeightAdjustment:
        """
        Adjust weights based on player position.

        Args:
            position: Player position
            base_weights: Base weight configuration

        Returns:
            Position-adjusted weight configuration
        """
        adjusted = base_weights.copy(deep=True)

        # Apply position-specific modifiers if configured
        if position.value in base_weights.position_modifiers:
            modifier = base_weights.position_modifiers[position.value]

            # Apply modifier to relevant weights
            adjusted.projection_weight *= modifier
            adjusted.ceiling_weight *= modifier
            adjusted.floor_weight *= modifier

        return adjusted

    def get_strategy_name(self) -> str:
        """Get the strategy name."""
        return self.name

    def calculate_matchup_bonus(
        self, player: Player, matchup_analysis: Optional[MatchupAnalysis]
    ) -> Decimal:
        """
        Calculate matchup-based bonus for a player.

        Args:
            player: Player to analyze
            matchup_analysis: Matchup analysis data

        Returns:
            Matchup bonus multiplier
        """
        if not matchup_analysis or not player.opponent:
            return Decimal("0")

        bonus = Decimal("0")

        # Check if player's team has favorable matchup conditions
        player_team_analysis = None
        if player.team == matchup_analysis.matchup.home_team:
            player_team_analysis = matchup_analysis.home_team_analysis
        elif player.team == matchup_analysis.matchup.away_team:
            player_team_analysis = matchup_analysis.away_team_analysis

        if player_team_analysis:
            # Boost for players in favorable matchups
            if any(
                "favorable" in matchup.lower()
                for matchup in player_team_analysis.favorable_matchups
            ):
                bonus += Decimal("0.1")

            # Penalty for players in concerning matchups
            if any(
                "concern" in matchup.lower() for matchup in player_team_analysis.concerning_matchups
            ):
                bonus -= Decimal("0.1")

        # Game script considerations
        if matchup_analysis.expected_game_script:
            if "high-scoring" in matchup_analysis.expected_game_script.lower():
                bonus += Decimal("0.05")
            elif "low-scoring" in matchup_analysis.expected_game_script.lower():
                bonus -= Decimal("0.05")

        return bonus * self.config.weight_adjustments.matchup_weight

    def calculate_weather_penalty(
        self, player: Player, matchup_analysis: Optional[MatchupAnalysis]
    ) -> Decimal:
        """
        Calculate weather-based penalty for a player.

        Args:
            player: Player to analyze
            matchup_analysis: Matchup analysis data

        Returns:
            Weather penalty (negative value)
        """
        if not matchup_analysis or not matchup_analysis.matchup.game_environment:
            return Decimal("0")

        environment = matchup_analysis.matchup.game_environment
        penalty = Decimal("0")

        if environment.is_weather_concern():
            # Base weather penalty
            if environment.weather_impact_score:
                penalty = environment.weather_impact_score / 10
            else:
                penalty = Decimal("0.1")

            # Position-specific weather impact
            if player.position in [Position.QB, Position.WR, Position.TE]:
                # Passing game affected more by weather
                penalty *= Decimal("1.2")
            elif player.position == Position.K:
                # Kickers heavily affected by wind/weather
                penalty *= Decimal("1.5")
            elif player.position == Position.RB:
                # Running game less affected
                penalty *= Decimal("0.8")

        return -penalty * self.config.weather_penalty

    def calculate_game_script_adjustment(
        self, player: Player, matchup_analysis: Optional[MatchupAnalysis]
    ) -> Decimal:
        """
        Calculate game script-based adjustment for a player.

        Args:
            player: Player to analyze
            matchup_analysis: Matchup analysis data

        Returns:
            Game script adjustment
        """
        if not matchup_analysis:
            return Decimal("0")

        adjustment = Decimal("0")

        # Determine if player's team is likely to be ahead or behind
        is_home_team = player.team == matchup_analysis.matchup.home_team
        win_probability = (
            matchup_analysis.home_win_probability
            if is_home_team
            else matchup_analysis.away_win_probability
        )

        # Adjust based on expected game script
        if win_probability > Decimal("0.6"):
            # Likely to be ahead - benefits RBs, hurts WRs/TEs slightly
            if player.position == Position.RB:
                adjustment += Decimal("0.05")
            elif player.position in [Position.WR, Position.TE]:
                adjustment -= Decimal("0.02")
        elif win_probability < Decimal("0.4"):
            # Likely to be behind - benefits passing game
            if player.position in [Position.QB, Position.WR, Position.TE]:
                adjustment += Decimal("0.05")
            elif player.position == Position.RB:
                adjustment -= Decimal("0.02")

        # High-variance games benefit ceiling plays
        if matchup_analysis.volatility_rating >= 7:
            adjustment += Decimal("0.03") * self.config.variance_preference

        return adjustment * self.config.weight_adjustments.game_script_weight

    def calculate_ownership_adjustment(self, player: Player) -> Decimal:
        """
        Calculate ownership-based adjustment for a player.

        Args:
            player: Player to analyze

        Returns:
            Ownership adjustment
        """
        if not player.value_metrics or player.value_metrics.projected_ownership is None:
            return Decimal("0")

        ownership = player.value_metrics.projected_ownership / 100  # Convert to 0-1 scale
        ownership_weight = self.config.weight_adjustments.ownership_weight

        if ownership_weight > 0:
            # Positive weight = prefer higher ownership (chalk)
            return ownership * ownership_weight
        else:
            # Negative weight = prefer lower ownership (contrarian)
            return (Decimal("1") - ownership) * abs(ownership_weight)

    def get_optimization_weights(self) -> Dict[str, Decimal]:
        """
        Get the optimization weights for this strategy.

        Returns:
            Dictionary of optimization weights
        """
        return {
            "points": self.config.weight_adjustments.projection_weight,
            "value": self.config.weight_adjustments.value_weight,
            "ownership": abs(self.config.weight_adjustments.ownership_weight),
            "floor": self.config.weight_adjustments.floor_weight,
            "ceiling": self.config.weight_adjustments.ceiling_weight,
            "matchup": self.config.weight_adjustments.matchup_weight,
            "consistency": self.config.weight_adjustments.consistency_weight,
            "upside": self.config.weight_adjustments.upside_weight,
        }

    def is_suitable_for_contest_type(self, contest_type: str) -> bool:
        """
        Check if strategy is suitable for a specific contest type.

        Args:
            contest_type: Contest type (e.g., "GPP", "Cash", "Tournament")

        Returns:
            True if strategy is suitable for contest type
        """
        contest_lower = contest_type.lower()

        if "gpp" in contest_lower or "tournament" in contest_lower:
            return self.config.gpp_optimized or self.config.variance_preference > 0.6
        elif "cash" in contest_lower or "double" in contest_lower:
            return self.config.cash_game_optimized or self.config.variance_preference < 0.4

        return True  # Default to suitable for all types

    def __str__(self) -> str:
        """String representation of the strategy."""
        return f"{self.name} ({self.strategy_type.value})"

    def __repr__(self) -> str:
        """Detailed string representation."""
        return f"<{self.__class__.__name__}(name='{self.name}', type='{self.strategy_type.value}')>"
