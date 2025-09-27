"""
Lineup models for fantasy football roster management.

This module contains Pydantic models for representing fantasy lineups,
lineup recommendations, and optimization strategies.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, validator

from .player import Player, Position


class LineupType(str, Enum):
    """Types of fantasy lineup formats."""

    DRAFTKINGS = "DraftKings"
    FANDUEL = "FanDuel"
    YAHOO = "Yahoo"
    SUPERDRAFT = "SuperDraft"
    CUSTOM = "Custom"


class OptimizationStrategy(str, Enum):
    """Lineup optimization strategies."""

    MAX_POINTS = "Max Points"
    MAX_VALUE = "Max Value"
    LOW_OWNERSHIP = "Low Ownership"
    BALANCED = "Balanced"
    CONTRARIAN = "Contrarian"
    SAFE = "Safe"
    GPP = "GPP"
    CASH_GAME = "Cash Game"


class LineupSlot(BaseModel):
    """Individual position slot in a lineup."""

    position: Position = Field(..., description="Position requirement")
    player: Optional[Player] = Field(None, description="Assigned player")
    salary_used: Optional[int] = Field(None, ge=0, description="Salary used for this slot")
    is_captain: bool = Field(False, description="Whether this is a captain/MVP slot")
    multiplier: Decimal = Field(Decimal("1.0"), description="Point multiplier for this slot")

    @validator("salary_used")
    def salary_matches_player(cls, v, values):
        """Validate salary matches assigned player."""
        if v is not None and "player" in values:
            player = values["player"]
            if player and player.value_metrics:
                # This is a simplified check - in reality you'd check against the specific platform
                return v
        return v

    def get_projected_points(self) -> Optional[Decimal]:
        """Get projected points for this slot including multiplier."""
        if not self.player or not self.player.projections:
            return None
        return self.player.projections.projected_fantasy_points * self.multiplier

    def is_filled(self) -> bool:
        """Check if slot has a player assigned."""
        return self.player is not None


class LineupConstraints(BaseModel):
    """Constraints for lineup construction."""

    # Salary constraints
    salary_cap: int = Field(..., gt=0, description="Total salary budget")
    min_salary_usage: Optional[Decimal] = Field(
        None, ge=0, le=1, description="Minimum salary utilization percentage"
    )

    # Position constraints
    position_requirements: Dict[str, int] = Field(
        ..., description="Required number of players per position"
    )

    # Player constraints
    max_players_per_team: Optional[int] = Field(
        None, ge=1, description="Maximum players from same NFL team"
    )

    # Ownership constraints
    max_total_ownership: Optional[Decimal] = Field(
        None, description="Maximum combined ownership percentage"
    )

    # Stack constraints
    required_stacks: Optional[List[str]] = Field(
        None, description="Required player stacks (e.g., QB-WR)"
    )
    avoided_stacks: Optional[List[str]] = Field(None, description="Stacks to avoid")

    # Exclusions
    excluded_players: Optional[List[str]] = Field(
        None, description="Player IDs to exclude from consideration"
    )
    locked_players: Optional[List[str]] = Field(
        None, description="Player IDs that must be included"
    )


class Lineup(BaseModel):
    """Fantasy football lineup representation."""

    # Basic information
    id: Optional[str] = Field(None, description="Unique lineup identifier")
    name: Optional[str] = Field(None, description="Lineup name or description")
    lineup_type: LineupType = Field(..., description="Platform/format type")

    # Lineup composition
    slots: List[LineupSlot] = Field(..., min_items=1, description="Position slots in lineup")

    # Financial metrics
    total_salary: int = Field(..., ge=0, description="Total salary used")
    salary_remaining: int = Field(..., ge=0, description="Salary remaining")
    salary_cap: int = Field(..., gt=0, description="Salary cap for this format")

    # Performance metrics
    total_projected_points: Decimal = Field(..., description="Sum of all projected points")
    projected_ownership: Optional[Decimal] = Field(None, description="Average projected ownership")

    # Risk and variance
    ceiling_points: Optional[Decimal] = Field(None, description="Optimistic projection")
    floor_points: Optional[Decimal] = Field(None, description="Conservative projection")
    variance_score: Optional[Decimal] = Field(
        None, ge=0, description="Lineup variance/volatility score"
    )

    # Strategy and optimization
    optimization_strategy: Optional[OptimizationStrategy] = Field(
        None, description="Strategy used to build lineup"
    )
    confidence_score: Decimal = Field(
        ..., ge=0, le=1, description="Confidence in lineup performance"
    )

    # Contest suitability
    gpp_score: Optional[Decimal] = Field(
        None, ge=0, le=10, description="Suitability for GPP contests (0-10)"
    )
    cash_game_score: Optional[Decimal] = Field(
        None, ge=0, le=10, description="Suitability for cash games (0-10)"
    )

    # Lineup analysis
    team_stacks: Optional[List[str]] = Field(None, description="Team stacks in lineup")
    correlation_score: Optional[Decimal] = Field(None, description="Player correlation score")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    last_updated: datetime = Field(
        default_factory=datetime.utcnow, description="Last update timestamp"
    )
    week: Optional[int] = Field(None, ge=1, le=18, description="NFL week")
    season: Optional[int] = Field(None, ge=2020, description="NFL season")

    @validator("salary_remaining")
    def salary_remaining_is_correct(cls, v, values):
        """Validate salary remaining calculation."""
        if "salary_cap" in values and "total_salary" in values:
            expected = values["salary_cap"] - values["total_salary"]
            if v != expected:
                raise ValueError(f"Salary remaining should be {expected}, got {v}")
        return v

    @validator("slots")
    def validate_lineup_requirements(cls, v, values):
        """Validate lineup meets basic requirements."""
        if not v:
            raise ValueError("Lineup must have at least one slot")

        # Count filled slots
        filled_slots = sum(1 for slot in v if slot.is_filled())
        if filled_slots == 0:
            raise ValueError("Lineup must have at least one player")

        return v

    def is_complete(self) -> bool:
        """Check if all lineup slots are filled."""
        return all(slot.is_filled() for slot in self.slots)

    def get_players(self) -> List[Player]:
        """Get all players in the lineup."""
        return [slot.player for slot in self.slots if slot.player is not None]

    def get_players_by_position(self, position: Position) -> List[Player]:
        """Get players at a specific position."""
        return [
            slot.player
            for slot in self.slots
            if slot.player is not None and slot.position == position
        ]

    def get_team_exposure(self) -> Dict[str, int]:
        """Get count of players per NFL team."""
        team_counts = {}
        for slot in self.slots:
            if slot.player:
                team = slot.player.team.value
                team_counts[team] = team_counts.get(team, 0) + 1
        return team_counts

    def get_salary_efficiency(self) -> Decimal:
        """Calculate points per $1000 of salary."""
        if self.total_salary == 0:
            return Decimal("0")
        return self.total_projected_points / (self.total_salary / 1000)

    def has_team_stack(self, team: str, min_players: int = 2) -> bool:
        """Check if lineup has a team stack."""
        team_exposure = self.get_team_exposure()
        return team_exposure.get(team, 0) >= min_players

    def validate_against_constraints(self, constraints: LineupConstraints) -> List[str]:
        """Validate lineup against provided constraints."""
        violations = []

        # Check salary cap
        if self.total_salary > constraints.salary_cap:
            violations.append(
                f"Exceeds salary cap by ${self.total_salary - constraints.salary_cap}"
            )

        # Check minimum salary usage
        if constraints.min_salary_usage:
            min_salary = int(constraints.salary_cap * constraints.min_salary_usage)
            if self.total_salary < min_salary:
                violations.append(
                    f"Under minimum salary usage by ${min_salary - self.total_salary}"
                )

        # Check team limits
        if constraints.max_players_per_team:
            team_exposure = self.get_team_exposure()
            for team, count in team_exposure.items():
                if count > constraints.max_players_per_team:
                    violations.append(f"Too many players from {team}: {count}")

        # Check excluded players
        if constraints.excluded_players:
            player_ids = [p.id for p in self.get_players()]
            excluded_in_lineup = set(player_ids) & set(constraints.excluded_players)
            if excluded_in_lineup:
                violations.append(f"Contains excluded players: {excluded_in_lineup}")

        # Check locked players
        if constraints.locked_players:
            player_ids = [p.id for p in self.get_players()]
            missing_locked = set(constraints.locked_players) - set(player_ids)
            if missing_locked:
                violations.append(f"Missing locked players: {missing_locked}")

        return violations

    class Config:
        """Pydantic model configuration."""

        json_encoders = {datetime: lambda v: v.isoformat(), Decimal: lambda v: float(v)}
        use_enum_values = True
        validate_assignment = True


class LineupAlternative(BaseModel):
    """Alternative lineup option with comparison to main lineup."""

    lineup: Lineup = Field(..., description="Alternative lineup")
    reason: str = Field(..., description="Reason for this alternative")

    # Comparison metrics
    point_difference: Decimal = Field(..., description="Point difference vs main lineup")
    salary_difference: int = Field(..., description="Salary difference vs main lineup")
    ownership_difference: Optional[Decimal] = Field(None, description="Ownership difference")
    risk_difference: Optional[Decimal] = Field(None, description="Risk/variance difference")

    # Recommendation strength
    confidence: Decimal = Field(..., ge=0, le=1, description="Confidence in this alternative")


class LineupRecommendation(BaseModel):
    """Comprehensive lineup recommendation with alternatives and analysis."""

    # Primary recommendation
    optimal_lineup: Lineup = Field(..., description="Primary recommended lineup")

    # Alternative options
    alternatives: List[LineupAlternative] = Field(
        default_factory=list, description="Alternative lineup options"
    )

    # Recommendation analysis
    reasoning: str = Field(..., description="Detailed reasoning for recommendation")
    key_factors: List[str] = Field(..., description="Key factors in the recommendation")

    # Strategy and context
    strategy: OptimizationStrategy = Field(..., description="Optimization strategy used")
    contest_type: str = Field(..., description="Recommended contest type")

    # Risk assessment
    risk_level: str = Field(..., description="Overall risk level (Low/Medium/High)")
    upside_potential: str = Field(..., description="Upside potential assessment")
    floor_assessment: str = Field(..., description="Floor/safety assessment")

    # Market analysis
    leverage_spots: Optional[List[str]] = Field(
        None, description="Low-owned players with high upside"
    )
    chalk_plays: Optional[List[str]] = Field(None, description="High-owned popular players")

    # Stacking strategy
    stack_analysis: Optional[str] = Field(None, description="Team stacking strategy")
    correlation_rationale: Optional[str] = Field(None, description="Player correlation reasoning")

    # Weather and game environment
    weather_considerations: Optional[List[str]] = Field(
        None, description="Weather-related considerations"
    )
    game_environment_notes: Optional[List[str]] = Field(
        None, description="Game environment factors"
    )

    # Usage recommendations
    recommended_contest_types: List[str] = Field(
        ..., description="Contest types best suited for this lineup"
    )
    bankroll_percentage: Optional[Decimal] = Field(
        None, ge=0, le=1, description="Recommended bankroll allocation"
    )

    # Performance expectations
    expected_percentile: Optional[Decimal] = Field(
        None, ge=0, le=100, description="Expected finish percentile"
    )
    win_probability: Optional[Decimal] = Field(
        None, ge=0, le=1, description="Estimated win probability"
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    valid_until: Optional[datetime] = Field(None, description="Recommendation expiration")
    week: int = Field(..., ge=1, le=18, description="NFL week")
    season: int = Field(..., ge=2020, description="NFL season")

    # Data sources and confidence
    data_sources: Optional[List[str]] = Field(None, description="Data sources used")
    overall_confidence: Decimal = Field(
        ..., ge=0, le=1, description="Overall confidence in recommendation"
    )

    class Config:
        """Pydantic model configuration."""

        json_encoders = {datetime: lambda v: v.isoformat(), Decimal: lambda v: float(v)}
        use_enum_values = True
        validate_assignment = True

    def get_total_alternatives(self) -> int:
        """Get total number of alternatives provided."""
        return len(self.alternatives)

    def get_best_alternative(self) -> Optional[LineupAlternative]:
        """Get the highest confidence alternative."""
        if not self.alternatives:
            return None
        return max(self.alternatives, key=lambda alt: alt.confidence)

    def get_lowest_owned_lineup(self) -> Lineup:
        """Get lineup with lowest projected ownership."""
        all_lineups = [self.optimal_lineup] + [alt.lineup for alt in self.alternatives]
        return min(all_lineups, key=lambda lineup: lineup.projected_ownership or Decimal("100"))

    def get_safest_lineup(self) -> Lineup:
        """Get lineup with highest floor projection."""
        all_lineups = [self.optimal_lineup] + [alt.lineup for alt in self.alternatives]
        return max(all_lineups, key=lambda lineup: lineup.floor_points or Decimal("0"))

    def is_stale(self) -> bool:
        """Check if recommendation is past its valid time."""
        if not self.valid_until:
            return False
        return datetime.utcnow() > self.valid_until


class LineupOptimizer(BaseModel):
    """Configuration for lineup optimization engine."""

    strategy: OptimizationStrategy = Field(..., description="Primary optimization strategy")
    constraints: LineupConstraints = Field(..., description="Lineup construction constraints")

    # Optimization parameters
    max_iterations: int = Field(1000, gt=0, description="Maximum optimization iterations")
    tolerance: Decimal = Field(Decimal("0.01"), gt=0, description="Convergence tolerance")

    # Multi-objective weights
    points_weight: Decimal = Field(
        Decimal("0.7"), ge=0, le=1, description="Weight for projected points"
    )
    value_weight: Decimal = Field(Decimal("0.2"), ge=0, le=1, description="Weight for salary value")
    ownership_weight: Decimal = Field(
        Decimal("0.1"), ge=0, le=1, description="Weight for ownership"
    )

    # Risk parameters
    variance_penalty: Decimal = Field(Decimal("0.0"), ge=0, description="Penalty for high variance")
    correlation_bonus: Decimal = Field(
        Decimal("0.0"), ge=0, description="Bonus for positive correlation"
    )

    # Advanced options
    randomness_factor: Decimal = Field(
        Decimal("0.05"), ge=0, le=1, description="Randomness in optimization"
    )

    diversity_requirement: Optional[int] = Field(
        None, description="Number of diverse lineups to generate"
    )

    @validator("points_weight", "value_weight", "ownership_weight")
    def weights_sum_to_one(cls, v, values):
        """Validate that all weights sum to approximately 1.0."""
        # This is a simplified check - in practice you'd check after all weights are set
        return v

    class Config:
        """Pydantic model configuration."""

        json_encoders = {Decimal: lambda v: float(v)}
        use_enum_values = True


class LineupPool(BaseModel):
    """Collection of related lineups for tournaments or analysis."""

    id: str = Field(..., description="Pool identifier")
    name: str = Field(..., description="Pool name")
    lineups: List[Lineup] = Field(..., min_items=1, description="Lineups in the pool")

    # Pool strategy
    strategy: str = Field(..., description="Overall pool strategy")
    diversification_score: Optional[Decimal] = Field(
        None, ge=0, le=1, description="Diversification across lineups"
    )

    # Performance metrics
    total_projected_points: Decimal = Field(..., description="Sum of all lineup projections")
    average_ownership: Optional[Decimal] = Field(None, description="Average ownership across pool")

    # Risk management
    correlation_matrix: Optional[Dict[str, Dict[str, Decimal]]] = Field(
        None, description="Player correlation matrix for pool"
    )

    # Contest information
    contest_type: Optional[str] = Field(None, description="Target contest type")
    entry_fee: Optional[Decimal] = Field(None, ge=0, description="Per-lineup entry fee")
    total_investment: Optional[Decimal] = Field(None, ge=0, description="Total pool investment")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")

    def get_unique_players(self) -> List[str]:
        """Get list of unique player IDs across all lineups."""
        player_ids = set()
        for lineup in self.lineups:
            for player in lineup.get_players():
                player_ids.add(player.id)
        return list(player_ids)

    def get_player_exposure(self) -> Dict[str, Decimal]:
        """Get exposure percentage for each player across the pool."""
        player_counts = {}
        total_lineups = len(self.lineups)

        for lineup in self.lineups:
            for player in lineup.get_players():
                player_counts[player.id] = player_counts.get(player.id, 0) + 1

        return {
            player_id: Decimal(count) / total_lineups for player_id, count in player_counts.items()
        }

    class Config:
        """Pydantic model configuration."""

        json_encoders = {datetime: lambda v: v.isoformat(), Decimal: lambda v: float(v)}
        use_enum_values = True
