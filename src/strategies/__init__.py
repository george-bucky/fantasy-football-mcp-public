"""
Fantasy football lineup strategies module.

This module provides various lineup construction strategies for different
contest types and risk preferences. Each strategy implements a common
interface while optimizing for different objectives.

Available strategies:
- ConservativeStrategy: Floor-focused, risk-averse lineup construction
- AggressiveStrategy: Ceiling-focused, high-upside tournament strategy
- BalancedStrategy: Risk/reward optimized, versatile approach

Strategy Selection Guide:
- Cash games & 50/50s: ConservativeStrategy
- Large GPPs & tournaments: AggressiveStrategy
- Mixed contests & medium fields: BalancedStrategy
"""

from .base import BaseLineupStrategy, StrategyConfig, StrategyType, WeightAdjustment, PlayerScore
from .conservative import ConservativeStrategy
from .aggressive import AggressiveStrategy
from .balanced import BalancedStrategy

__all__ = [
    # Base classes and types
    "BaseLineupStrategy",
    "StrategyConfig",
    "StrategyType",
    "WeightAdjustment",
    "PlayerScore",
    # Concrete strategy implementations
    "ConservativeStrategy",
    "AggressiveStrategy",
    "BalancedStrategy",
]

# Strategy registry for dynamic instantiation
STRATEGY_REGISTRY = {
    StrategyType.CONSERVATIVE: ConservativeStrategy,
    StrategyType.AGGRESSIVE: AggressiveStrategy,
    StrategyType.BALANCED: BalancedStrategy,
}


def get_strategy(strategy_type: StrategyType, config: StrategyConfig = None) -> BaseLineupStrategy:
    """
    Factory function to create strategy instances.

    Args:
        strategy_type: The type of strategy to create
        config: Optional strategy configuration

    Returns:
        Initialized strategy instance

    Raises:
        ValueError: If strategy_type is not supported
    """
    if strategy_type not in STRATEGY_REGISTRY:
        raise ValueError(f"Unsupported strategy type: {strategy_type}")

    strategy_class = STRATEGY_REGISTRY[strategy_type]
    return strategy_class(config=config)


def get_available_strategies() -> list[str]:
    """
    Get list of available strategy names.

    Returns:
        List of strategy type names
    """
    return [strategy_type.value for strategy_type in STRATEGY_REGISTRY.keys()]


def get_strategy_for_contest_type(contest_type: str) -> StrategyType:
    """
    Get recommended strategy type for a contest type.

    Args:
        contest_type: Contest type string (e.g., "GPP", "Cash", "Tournament")

    Returns:
        Recommended strategy type
    """
    contest_lower = contest_type.lower()

    # GPP/Tournament -> Aggressive
    if any(
        keyword in contest_lower
        for keyword in ["gpp", "tournament", "millionaire", "large", "high-stakes"]
    ):
        return StrategyType.AGGRESSIVE

    # Cash games -> Conservative
    if any(
        keyword in contest_lower for keyword in ["cash", "50/50", "double", "head-to-head", "safe"]
    ):
        return StrategyType.CONSERVATIVE

    # Default to balanced for mixed/unknown contest types
    return StrategyType.BALANCED
