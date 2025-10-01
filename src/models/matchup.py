"""
Matchup models for fantasy football game analysis.

This module contains Pydantic models for representing NFL matchups,
game analysis, and betting/fantasy implications.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, validator

from .player import Team


class GameStatus(str, Enum):
    """NFL game status options."""

    SCHEDULED = "Scheduled"
    PREGAME = "Pregame"
    IN_PROGRESS = "In Progress"
    FINAL = "Final"
    POSTPONED = "Postponed"
    CANCELED = "Canceled"


class WeatherCondition(str, Enum):
    """Weather condition categories."""

    CLEAR = "Clear"
    PARTLY_CLOUDY = "Partly Cloudy"
    CLOUDY = "Cloudy"
    LIGHT_RAIN = "Light Rain"
    RAIN = "Rain"
    HEAVY_RAIN = "Heavy Rain"
    LIGHT_SNOW = "Light Snow"
    SNOW = "Snow"
    HEAVY_SNOW = "Heavy Snow"
    WINDY = "Windy"
    SEVERE = "Severe"


class VenueType(str, Enum):
    """Stadium venue types."""

    OUTDOOR = "Outdoor"
    DOME = "Dome"
    RETRACTABLE = "Retractable"


class GameEnvironment(BaseModel):
    """Environmental conditions for a game."""

    # Weather conditions
    temperature: Optional[int] = Field(None, description="Temperature in Fahrenheit")
    weather_condition: Optional[WeatherCondition] = Field(None, description="Weather condition")
    wind_speed: Optional[int] = Field(None, ge=0, description="Wind speed in mph")
    wind_direction: Optional[str] = Field(None, description="Wind direction")
    precipitation_chance: Optional[int] = Field(
        None, ge=0, le=100, description="Precipitation probability"
    )
    humidity: Optional[int] = Field(None, ge=0, le=100, description="Humidity percentage")

    # Venue information
    venue_type: Optional[VenueType] = Field(None, description="Stadium type")
    altitude: Optional[int] = Field(None, description="Altitude in feet")

    # Game timing
    is_prime_time: bool = Field(False, description="Prime time game")
    is_divisional: bool = Field(False, description="Divisional matchup")

    # Impact assessment
    weather_impact_score: Optional[Decimal] = Field(
        None, ge=0, le=10, description="Weather impact on fantasy (0=none, 10=severe)"
    )

    notes: Optional[str] = Field(None, description="Additional environmental notes")

    def is_weather_concern(self) -> bool:
        """Check if weather conditions are concerning for fantasy."""
        if self.weather_impact_score and self.weather_impact_score >= 5:
            return True

        concerning_conditions = [
            WeatherCondition.RAIN,
            WeatherCondition.HEAVY_RAIN,
            WeatherCondition.SNOW,
            WeatherCondition.HEAVY_SNOW,
            WeatherCondition.SEVERE,
        ]

        if self.weather_condition in concerning_conditions:
            return True

        if self.wind_speed and self.wind_speed >= 20:
            return True

        return False


class TeamStats(BaseModel):
    """Team performance statistics."""

    # Offensive stats
    points_per_game: Optional[Decimal] = Field(None, ge=0, description="Average points per game")
    total_yards_per_game: Optional[Decimal] = Field(None, ge=0, description="Total yards per game")
    passing_yards_per_game: Optional[Decimal] = Field(
        None, ge=0, description="Passing yards per game"
    )
    rushing_yards_per_game: Optional[Decimal] = Field(
        None, ge=0, description="Rushing yards per game"
    )
    turnovers_per_game: Optional[Decimal] = Field(None, ge=0, description="Turnovers per game")

    # Defensive stats
    points_allowed_per_game: Optional[Decimal] = Field(
        None, ge=0, description="Points allowed per game"
    )
    yards_allowed_per_game: Optional[Decimal] = Field(
        None, ge=0, description="Yards allowed per game"
    )
    passing_yards_allowed_per_game: Optional[Decimal] = Field(
        None, ge=0, description="Passing yards allowed"
    )
    rushing_yards_allowed_per_game: Optional[Decimal] = Field(
        None, ge=0, description="Rushing yards allowed"
    )
    takeaways_per_game: Optional[Decimal] = Field(None, ge=0, description="Takeaways per game")
    sacks_per_game: Optional[Decimal] = Field(None, ge=0, description="Sacks per game")

    # Efficiency metrics
    third_down_conversion_pct: Optional[Decimal] = Field(
        None, ge=0, le=100, description="Third down conversion percentage"
    )
    red_zone_efficiency: Optional[Decimal] = Field(
        None, ge=0, le=100, description="Red zone scoring percentage"
    )
    time_of_possession: Optional[str] = Field(None, description="Average time of possession")

    # Special teams
    kicking_accuracy: Optional[Decimal] = Field(
        None, ge=0, le=100, description="Field goal accuracy percentage"
    )

    # Recent form
    games_played: Optional[int] = Field(None, ge=0, description="Games played this season")
    last_5_record: Optional[str] = Field(None, description="Record in last 5 games")


class BettingLine(BaseModel):
    """Betting information for a matchup."""

    # Point spread
    spread: Optional[Decimal] = Field(None, description="Point spread (negative = favorite)")
    spread_team: Optional[Team] = Field(None, description="Team the spread applies to")

    # Total points
    over_under: Optional[Decimal] = Field(None, ge=0, description="Over/under total points")

    # Moneyline
    home_moneyline: Optional[int] = Field(None, description="Home team moneyline")
    away_moneyline: Optional[int] = Field(None, description="Away team moneyline")

    # Implied probabilities
    home_win_probability: Optional[Decimal] = Field(
        None, ge=0, le=1, description="Implied home win probability"
    )
    away_win_probability: Optional[Decimal] = Field(
        None, ge=0, le=1, description="Implied away win probability"
    )

    # Line movement
    opening_spread: Optional[Decimal] = Field(None, description="Opening point spread")
    opening_total: Optional[Decimal] = Field(None, description="Opening total")
    line_movement: Optional[str] = Field(None, description="Direction of line movement")

    # Betting percentages
    public_bet_percentage_spread: Optional[Decimal] = Field(
        None, ge=0, le=100, description="Public betting percentage on spread"
    )
    public_bet_percentage_total: Optional[Decimal] = Field(
        None, ge=0, le=100, description="Public betting percentage on over"
    )

    last_updated: datetime = Field(
        default_factory=datetime.utcnow, description="Last update timestamp"
    )

    def get_favorite(self) -> Optional[Team]:
        """Get the favored team based on spread."""
        if not self.spread or not self.spread_team:
            return None
        return self.spread_team if self.spread < 0 else None

    def get_underdog(self) -> Optional[Team]:
        """Get the underdog team based on spread."""
        if not self.spread or not self.spread_team:
            return None
        return None if self.spread < 0 else self.spread_team

    def is_pick_em(self) -> bool:
        """Check if game is essentially pick 'em (small spread)."""
        if not self.spread:
            return False
        return abs(self.spread) <= Decimal("2.5")


class HistoricalMatchup(BaseModel):
    """Historical data between two teams."""

    # Head-to-head record
    total_games: int = Field(..., ge=0, description="Total games played between teams")
    home_team_wins: int = Field(..., ge=0, description="Home team wins in series")
    away_team_wins: int = Field(..., ge=0, description="Away team wins in series")

    # Recent meetings
    last_meeting_date: Optional[datetime] = Field(None, description="Date of last meeting")
    last_meeting_score: Optional[str] = Field(None, description="Score of last meeting")
    recent_trend: Optional[str] = Field(None, description="Recent head-to-head trend")

    # Average statistics in matchups
    avg_total_points: Optional[Decimal] = Field(None, ge=0, description="Average total points")
    avg_home_score: Optional[Decimal] = Field(None, ge=0, description="Average home team score")
    avg_away_score: Optional[Decimal] = Field(None, ge=0, description="Average away team score")

    # Variance and trends
    high_scoring_games: int = Field(0, ge=0, description="Games over 50 total points")
    low_scoring_games: int = Field(0, ge=0, description="Games under 35 total points")
    overtime_games: int = Field(0, ge=0, description="Games that went to overtime")

    # Fantasy relevance
    avg_passing_yards_home: Optional[Decimal] = Field(
        None, description="Home team avg passing yards"
    )
    avg_rushing_yards_home: Optional[Decimal] = Field(
        None, description="Home team avg rushing yards"
    )
    avg_passing_yards_away: Optional[Decimal] = Field(
        None, description="Away team avg passing yards"
    )
    avg_rushing_yards_away: Optional[Decimal] = Field(
        None, description="Away team avg rushing yards"
    )


class Matchup(BaseModel):
    """NFL game matchup with comprehensive analysis data."""

    # Basic game information
    id: str = Field(..., description="Unique matchup identifier")
    week: int = Field(..., ge=1, le=18, description="NFL week")
    season: int = Field(..., ge=2020, description="NFL season")

    # Teams
    home_team: Team = Field(..., description="Home team")
    away_team: Team = Field(..., description="Away team")

    # Game details
    game_time: datetime = Field(..., description="Scheduled game time")
    venue: Optional[str] = Field(None, description="Stadium name")
    status: GameStatus = Field(GameStatus.SCHEDULED, description="Current game status")

    # Team statistics
    home_team_stats: Optional[TeamStats] = Field(None, description="Home team season stats")
    away_team_stats: Optional[TeamStats] = Field(None, description="Away team season stats")

    # Environmental factors
    game_environment: Optional[GameEnvironment] = Field(
        None, description="Game environment conditions"
    )

    # Betting information
    betting_lines: Optional[BettingLine] = Field(None, description="Betting lines and odds")

    # Historical context
    historical_matchup: Optional[HistoricalMatchup] = Field(
        None, description="Historical head-to-head data"
    )

    # Projections
    projected_home_score: Optional[Decimal] = Field(
        None, ge=0, description="Projected home team score"
    )
    projected_away_score: Optional[Decimal] = Field(
        None, ge=0, description="Projected away team score"
    )
    projected_total_points: Optional[Decimal] = Field(
        None, ge=0, description="Projected total points"
    )

    # Fantasy impact
    fantasy_relevance_score: Optional[Decimal] = Field(
        None, ge=0, le=10, description="Fantasy relevance score (0-10)"
    )

    # Key injuries and news
    key_injuries: Optional[List[str]] = Field(None, description="Key injury reports")
    news_notes: Optional[List[str]] = Field(None, description="Important news and notes")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    last_updated: datetime = Field(
        default_factory=datetime.utcnow, description="Last update timestamp"
    )
    data_sources: Optional[List[str]] = Field(None, description="Data sources used")

    def get_total_projected_points(self) -> Optional[Decimal]:
        """Get sum of projected team scores."""
        if self.projected_home_score is not None and self.projected_away_score is not None:
            return self.projected_home_score + self.projected_away_score
        return self.projected_total_points

    def get_projected_margin(self) -> Optional[Decimal]:
        """Get projected point margin (positive = home favorite)."""
        if self.projected_home_score is not None and self.projected_away_score is not None:
            return self.projected_home_score - self.projected_away_score
        return None

    def is_high_total(self) -> bool:
        """Check if projected as high-scoring game."""
        total = self.get_total_projected_points()
        if total is None:
            return False
        return total >= Decimal("50")

    def is_weather_game(self) -> bool:
        """Check if weather is expected to impact the game."""
        if not self.game_environment:
            return False
        return self.game_environment.is_weather_concern()

    def get_pace_projection(self) -> Optional[str]:
        """Get game pace projection based on team stats."""
        if not self.home_team_stats or not self.away_team_stats:
            return None

        # Simple pace assessment based on points per game
        home_ppg = self.home_team_stats.points_per_game or Decimal("20")
        away_ppg = self.away_team_stats.points_per_game or Decimal("20")
        avg_ppg = (home_ppg + away_ppg) / 2

        if avg_ppg >= Decimal("28"):
            return "Fast"
        elif avg_ppg >= Decimal("22"):
            return "Average"
        else:
            return "Slow"

    class Config:
        """Pydantic model configuration."""

        json_encoders = {datetime: lambda v: v.isoformat(), Decimal: lambda v: float(v)}
        use_enum_values = True
        validate_assignment = True


class MatchupFactor(BaseModel):
    """Individual factor in matchup analysis."""

    name: str = Field(..., description="Factor name")
    description: str = Field(..., description="Factor description")
    impact_rating: Decimal = Field(..., ge=-5, le=5, description="Impact rating (-5 to +5)")
    confidence: Decimal = Field(..., ge=0, le=1, description="Confidence in this factor")
    affects_home_team: bool = Field(..., description="Whether factor affects home team")
    affects_away_team: bool = Field(..., description="Whether factor affects away team")
    category: str = Field(..., description="Factor category (e.g., 'Weather', 'Injuries')")


class TeamAnalysis(BaseModel):
    """Analysis for one team in a matchup."""

    team: Team = Field(..., description="Team being analyzed")

    # Strengths and weaknesses
    key_strengths: List[str] = Field(..., description="Team's key strengths")
    key_weaknesses: List[str] = Field(..., description="Team's key weaknesses")

    # Matchup-specific factors
    favorable_matchups: List[str] = Field(..., description="Favorable position matchups")
    concerning_matchups: List[str] = Field(..., description="Concerning position matchups")

    # Fantasy implications
    players_to_target: List[str] = Field(..., description="Players to target in fantasy")
    players_to_avoid: List[str] = Field(..., description="Players to avoid in fantasy")

    # Game script predictions
    likely_game_script: str = Field(..., description="Expected game script for team")
    volume_expectations: Dict[str, str] = Field(..., description="Expected volume by position")

    # Confidence metrics
    ceiling_scenario: str = Field(..., description="Best-case scenario")
    floor_scenario: str = Field(..., description="Worst-case scenario")
    most_likely_scenario: str = Field(..., description="Most probable outcome")


class MatchupAnalysis(BaseModel):
    """Comprehensive analysis of an NFL matchup for fantasy purposes."""

    # Source matchup
    matchup: Matchup = Field(..., description="The matchup being analyzed")

    # Overall analysis
    summary: str = Field(..., description="Executive summary of the matchup")
    key_storylines: List[str] = Field(..., description="Key storylines to follow")

    # Win probability and game flow
    home_win_probability: Decimal = Field(
        ..., ge=0, le=1, description="Predicted home team win probability"
    )
    away_win_probability: Decimal = Field(
        ..., ge=0, le=1, description="Predicted away team win probability"
    )

    # Expected game flow
    expected_game_script: str = Field(..., description="Expected overall game flow")
    pace_projection: str = Field(..., description="Expected game pace")
    competitiveness_rating: Decimal = Field(
        ..., ge=0, le=10, description="Expected game competitiveness (0-10)"
    )

    # Team-specific analysis
    home_team_analysis: TeamAnalysis = Field(..., description="Home team analysis")
    away_team_analysis: TeamAnalysis = Field(..., description="Away team analysis")

    # Key factors
    key_factors: List[MatchupFactor] = Field(..., description="Key factors affecting the game")

    # Fantasy recommendations
    stack_recommendations: List[str] = Field(..., description="Recommended player stacks")
    contrarian_plays: List[str] = Field(..., description="Contrarian play suggestions")

    # DFS specific
    dfs_game_theory: str = Field(..., description="DFS game theory considerations")
    projected_ownership_impact: str = Field(..., description="Expected ownership patterns")

    # Betting and totals analysis
    spread_analysis: Optional[str] = Field(None, description="Point spread analysis")
    total_analysis: Optional[str] = Field(None, description="Over/under analysis")
    value_bets: Optional[List[str]] = Field(
        None, description="Potential value betting opportunities"
    )

    # Risk assessment
    risk_factors: List[str] = Field(..., description="Primary risk factors")
    weather_impact: Optional[str] = Field(None, description="Weather impact assessment")
    injury_impact: Optional[str] = Field(None, description="Injury impact on game")

    # Confidence and reliability
    analysis_confidence: Decimal = Field(
        ..., ge=0, le=1, description="Overall confidence in analysis"
    )

    volatility_rating: Decimal = Field(
        ..., ge=0, le=10, description="Expected outcome volatility (0-10)"
    )

    # Data quality
    data_completeness: Decimal = Field(
        ..., ge=0, le=1, description="Completeness of underlying data"
    )

    last_injury_check: Optional[datetime] = Field(None, description="Last injury report check")

    # Metadata
    analyst_notes: Optional[str] = Field(None, description="Additional analyst notes")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Analysis timestamp")
    analysis_version: str = Field("1.0", description="Analysis version")

    @validator("away_win_probability")
    def probabilities_sum_to_one(cls, v, values):
        """Validate win probabilities sum to approximately 1.0."""
        if "home_win_probability" in values:
            home_prob = values["home_win_probability"]
            total = home_prob + v
            if not (Decimal("0.98") <= total <= Decimal("1.02")):
                raise ValueError(f"Win probabilities must sum to ~1.0, got {total}")
        return v

    def get_projected_favorite(self) -> Team:
        """Get the projected favorite team."""
        return self.matchup.home_team if self.home_win_probability > 0.5 else self.matchup.away_team

    def get_projected_underdog(self) -> Team:
        """Get the projected underdog team."""
        return self.matchup.away_team if self.home_win_probability > 0.5 else self.matchup.home_team

    def is_close_game(self) -> bool:
        """Check if game is projected to be close."""
        return abs(self.home_win_probability - Decimal("0.5")) <= Decimal("0.1")

    def get_blowout_probability(self) -> Decimal:
        """Get probability of a blowout (>14 point margin)."""
        # Simplified calculation based on win probability extremes
        max_prob = max(self.home_win_probability, self.away_win_probability)
        if max_prob >= Decimal("0.75"):
            return (max_prob - Decimal("0.75")) * 2
        return Decimal("0")

    def get_high_variance_players(self) -> List[str]:
        """Get players with high variance potential."""
        high_variance = []

        # Add contrarian plays as high variance
        high_variance.extend(self.contrarian_plays)

        # Add players in expected blowout scenarios
        if self.get_blowout_probability() > Decimal("0.2"):
            # Add garbage time candidates from losing team
            losing_team_analysis = (
                self.away_team_analysis
                if self.home_win_probability > 0.6
                else self.home_team_analysis
            )
            high_variance.extend(losing_team_analysis.players_to_target)

        return list(set(high_variance))

    class Config:
        """Pydantic model configuration."""

        json_encoders = {datetime: lambda v: v.isoformat(), Decimal: lambda v: float(v)}
        use_enum_values = True
        validate_assignment = True


class WeeklyMatchupSummary(BaseModel):
    """Summary of all matchups for a given week."""

    week: int = Field(..., ge=1, le=18, description="NFL week")
    season: int = Field(..., ge=2020, description="NFL season")

    matchups: List[Matchup] = Field(..., description="All matchups for the week")
    analyses: List[MatchupAnalysis] = Field(..., description="Analysis for each matchup")

    # Week-level insights
    week_summary: str = Field(..., description="Overall week summary")
    top_games: List[str] = Field(..., description="Top games for fantasy")
    weather_concerns: List[str] = Field(..., description="Games with weather concerns")

    # Fantasy implications
    week_long_stacks: List[str] = Field(..., description="Best stacks for the week")
    value_plays: List[str] = Field(..., description="Top value plays")
    fade_candidates: List[str] = Field(..., description="Popular players to consider fading")

    # DFS strategy
    gpp_strategy: str = Field(..., description="GPP strategy for the week")
    cash_strategy: str = Field(..., description="Cash game strategy for the week")

    # Market analysis
    chalk_plays: List[str] = Field(..., description="Expected highly-owned players")
    leverage_spots: List[str] = Field(..., description="Low-owned upside players")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="Summary timestamp")

    def get_total_games(self) -> int:
        """Get total number of games for the week."""
        return len(self.matchups)

    def get_high_total_games(self) -> List[Matchup]:
        """Get games with high projected totals."""
        return [m for m in self.matchups if m.is_high_total()]

    def get_weather_games(self) -> List[Matchup]:
        """Get games with weather concerns."""
        return [m for m in self.matchups if m.is_weather_game()]

    def get_competitive_games(self) -> List[MatchupAnalysis]:
        """Get analyses for competitive games."""
        return [a for a in self.analyses if a.is_close_game()]

    class Config:
        """Pydantic model configuration."""

        json_encoders = {datetime: lambda v: v.isoformat(), Decimal: lambda v: float(v)}
        use_enum_values = True
