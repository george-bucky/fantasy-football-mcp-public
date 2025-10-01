"""
Draft-specific data models for the Fantasy Football MCP Draft Assistant.

This module defines all data structures needed for draft evaluation and recommendations,
including draft state, pick evaluations, and recommendation objects.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

from .player import Player, Position


class DraftStrategy(str, Enum):
    """Available draft strategies."""

    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"


class PositionalNeed(str, Enum):
    """Positional need levels for roster construction."""

    CRITICAL = "critical"  # Zero players at position
    HIGH = "high"  # Below optimal roster construction
    MEDIUM = "medium"  # At optimal level
    LOW = "low"  # Above optimal level
    SATURATED = "saturated"  # Excess players


class DraftTier(int, Enum):
    """Player tiers for draft evaluation."""

    ELITE = 1  # Tier 1 - Elite players
    STUD = 2  # Tier 2 - Stud players
    SOLID = 3  # Tier 3 - Solid players
    FLEX = 4  # Tier 4 - Flex/depth players
    BENCH = 5  # Tier 5 - Bench/flyer players


@dataclass
class DraftPosition:
    """Represents a draft position and round information."""

    overall_pick: int
    round_number: int
    pick_in_round: int
    picks_until_next: int
    is_snake_draft: bool = True


@dataclass
class RosterNeed:
    """Represents positional needs for roster construction."""

    position: Position
    need_level: PositionalNeed
    current_count: int
    optimal_count: int
    starter_slots: int
    bye_week_conflicts: int = 0


@dataclass
class PlayerEvaluation:
    """Complete evaluation of a player for draft purposes."""

    player: Player
    overall_score: float
    vorp_score: float
    scarcity_score: float
    need_score: float
    bye_week_score: float
    risk_score: float
    upside_score: float
    tier: DraftTier
    adp: Optional[float] = None
    projected_points: Optional[float] = None
    replacement_level: Optional[float] = None
    injury_risk: Optional[float] = None
    consistency_score: Optional[float] = None


@dataclass
class OpportunityCost:
    """Analysis of opportunity cost for waiting vs taking a player."""

    player: Player
    survival_probability: float
    cost_of_waiting: float
    expected_value_next_round: float
    recommendation: str  # "take_now", "can_wait", "risky_wait"


@dataclass
class PositionalRun:
    """Detection and analysis of positional runs."""

    position: Position
    recent_picks: int
    is_hot_run: bool
    run_intensity: str  # "emerging", "hot", "cooling"
    recommendation: str


class DraftRecommendation(BaseModel):
    """Main recommendation object returned by draft evaluator."""

    player: Dict[str, Any]  # Player dict to avoid circular imports
    overall_score: float = Field(..., description="Combined evaluation score (0-100)")
    rank: int = Field(..., description="Ranking among available players")
    tier: DraftTier = Field(..., description="Player tier classification")

    # Score breakdowns
    vorp_score: float = Field(..., description="Value Over Replacement Player score")
    scarcity_score: float = Field(..., description="Positional scarcity score")
    need_score: float = Field(..., description="Roster need score")
    bye_week_score: float = Field(..., description="Bye week distribution score")
    risk_score: float = Field(..., description="Injury/performance risk score")
    upside_score: float = Field(..., description="Ceiling/upside potential score")

    # Contextual information
    projected_points: Optional[float] = Field(None, description="Season projection")
    adp: Optional[float] = Field(None, description="Average Draft Position")
    position_rank: Optional[int] = Field(None, description="Rank within position")

    # Analysis
    reasoning: str = Field(..., description="Human-readable explanation")
    opportunity_cost: Optional[Dict[str, Any]] = Field(None, description="Wait vs take analysis")
    positional_context: Optional[str] = Field(None, description="Position-specific insights")

    class Config:
        use_enum_values = True


class DraftState(BaseModel):
    """Current state of the draft and roster."""

    league_key: str = Field(..., description="Yahoo league identifier")
    draft_position: DraftPosition = Field(..., description="Current draft position")
    current_roster: List[Dict[str, Any]] = Field(
        default_factory=list, description="Currently drafted players"
    )
    available_players: List[Dict[str, Any]] = Field(
        default_factory=list, description="Remaining available players"
    )

    # Roster analysis
    roster_needs: List[RosterNeed] = Field(
        default_factory=list, description="Positional needs assessment"
    )
    bye_week_distribution: Dict[int, int] = Field(
        default_factory=dict, description="Bye weeks by count"
    )

    # Draft context
    total_rounds: int = Field(default=16, description="Total draft rounds")
    picks_remaining: int = Field(..., description="Remaining picks for user")
    strategy: DraftStrategy = Field(
        default=DraftStrategy.BALANCED, description="Selected draft strategy"
    )

    # Analysis flags
    positional_runs: List[PositionalRun] = Field(
        default_factory=list, description="Detected positional runs"
    )
    draft_phase: str = Field(..., description="early, middle, or late draft phase")


class DraftAnalysis(BaseModel):
    """Comprehensive analysis of the current draft situation."""

    draft_state: DraftState
    top_recommendations: List[DraftRecommendation] = Field(
        ..., description="Top N recommended picks"
    )

    # Strategic insights
    key_insights: List[str] = Field(default_factory=list, description="Important strategic notes")
    positional_priorities: Dict[str, float] = Field(
        default_factory=dict, description="Position priority scores"
    )
    risk_factors: List[str] = Field(default_factory=list, description="Potential concerns")

    # Context
    analysis_timestamp: datetime = Field(default_factory=datetime.now)
    strategy_weights: Dict[str, float] = Field(
        default_factory=dict, description="Applied strategy weights"
    )

    class Config:
        use_enum_values = True


@dataclass
class StrategyWeights:
    """Weights for different factors in draft evaluation."""

    vorp: float = 0.30
    scarcity: float = 0.25
    need: float = 0.20
    bye_week: float = 0.10
    risk: float = 0.10
    upside: float = 0.05

    def __post_init__(self):
        """Validate weights sum to 1.0."""
        total = sum([self.vorp, self.scarcity, self.need, self.bye_week, self.risk, self.upside])
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Strategy weights must sum to 1.0, got {total}")


# Predefined strategy weight configurations
STRATEGY_WEIGHTS = {
    DraftStrategy.CONSERVATIVE: StrategyWeights(
        vorp=0.35, scarcity=0.25, need=0.25, bye_week=0.10, risk=0.05, upside=0.0
    ),
    DraftStrategy.AGGRESSIVE: StrategyWeights(
        vorp=0.25, scarcity=0.20, need=0.15, bye_week=0.05, risk=-0.05, upside=0.40
    ),
    DraftStrategy.BALANCED: StrategyWeights(
        vorp=0.30, scarcity=0.25, need=0.20, bye_week=0.10, risk=0.10, upside=0.05
    ),
}


# Position requirements for standard roster construction
STANDARD_ROSTER_REQUIREMENTS = {
    Position.QB: {"starters": 1, "optimal_total": 2, "max_useful": 3},
    Position.RB: {"starters": 2, "optimal_total": 5, "max_useful": 7},
    Position.WR: {"starters": 2, "optimal_total": 5, "max_useful": 7},
    Position.TE: {"starters": 1, "optimal_total": 2, "max_useful": 3},
    Position.K: {"starters": 1, "optimal_total": 1, "max_useful": 2},
    Position.DEF: {"starters": 1, "optimal_total": 1, "max_useful": 2},
}

# Flex position can be filled by RB/WR/TE
FLEX_POSITIONS = [Position.RB, Position.WR, Position.TE]

# Injury risk multipliers by position
POSITION_INJURY_RISK = {
    Position.QB: 1.0,
    Position.RB: 1.5,  # Higher injury risk
    Position.WR: 1.2,
    Position.TE: 1.1,
    Position.K: 0.5,  # Lower injury risk
    Position.DEF: 0.5,
}

# Age-based risk adjustments
AGE_RISK_THRESHOLDS = {
    Position.QB: 35,
    Position.RB: 30,
    Position.WR: 32,
    Position.TE: 32,
    Position.K: 40,
    Position.DEF: None,  # Not applicable
}
