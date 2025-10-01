"""
Decision Agent for synthesizing fantasy football recommendations.

This module provides the DecisionAgent class that synthesizes insights from
other agents into actionable, data-driven recommendations with explanations.
"""

import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union, Any

from ..models.player import Player, Position, InjuryStatus, PlayerProjections
from ..models.lineup import (
    Lineup,
    LineupRecommendation,
    LineupAlternative,
    OptimizationStrategy,
    LineupType,
    LineupConstraints,
)
from ..models.matchup import Matchup, MatchupAnalysis, TeamAnalysis


class RiskToleranceProfile(str, Enum):
    """User risk tolerance profiles for decision making."""

    CONSERVATIVE = "Conservative"
    MODERATE = "Moderate"
    AGGRESSIVE = "Aggressive"
    TOURNAMENT = "Tournament"
    CASH_GAME = "Cash Game"


class DecisionFactor(str, Enum):
    """Factors that influence fantasy decisions."""

    PROJECTION = "Projection"
    VALUE = "Value"
    MATCHUP = "Matchup"
    OWNERSHIP = "Ownership"
    INJURY_RISK = "Injury Risk"
    WEATHER = "Weather"
    GAME_SCRIPT = "Game Script"
    CORRELATION = "Correlation"
    VARIANCE = "Variance"
    RECENCY = "Recency"


class DecisionNode:
    """Node in a decision tree for complex scenario analysis."""

    def __init__(
        self,
        condition: str,
        weight: Decimal,
        outcome_positive: Union[str, "DecisionNode"],
        outcome_negative: Union[str, "DecisionNode"],
        confidence: Decimal = Decimal("0.8"),
    ):
        self.condition = condition
        self.weight = weight
        self.outcome_positive = outcome_positive
        self.outcome_negative = outcome_negative
        self.confidence = confidence
        self.children = []

    def evaluate(self, context: Dict[str, Any]) -> Tuple[str, Decimal]:
        """Evaluate the decision node given context."""
        # This is a simplified evaluation - in practice would be more sophisticated
        condition_met = self._evaluate_condition(context)

        if condition_met:
            if isinstance(self.outcome_positive, str):
                return self.outcome_positive, self.confidence
            else:
                return self.outcome_positive.evaluate(context)
        else:
            if isinstance(self.outcome_negative, str):
                return self.outcome_negative, self.confidence
            else:
                return self.outcome_negative.evaluate(context)

    def _evaluate_condition(self, context: Dict[str, Any]) -> bool:
        """Evaluate if condition is met (simplified implementation)."""
        # In practice, this would parse and evaluate complex conditions
        return True  # Placeholder


class MultiCriteriaScore:
    """Multi-criteria decision analysis score."""

    def __init__(self):
        self.factors: Dict[DecisionFactor, Decimal] = {}
        self.weights: Dict[DecisionFactor, Decimal] = {}
        self.total_score: Optional[Decimal] = None
        self.confidence: Optional[Decimal] = None

    def add_factor(self, factor: DecisionFactor, score: Decimal, weight: Decimal):
        """Add a weighted factor to the analysis."""
        self.factors[factor] = score
        self.weights[factor] = weight

    def calculate_score(self) -> Decimal:
        """Calculate weighted total score."""
        if not self.factors:
            return Decimal("0")

        total_weighted = sum(self.factors[factor] * self.weights[factor] for factor in self.factors)
        total_weight = sum(self.weights.values())

        if total_weight == 0:
            return Decimal("0")

        self.total_score = total_weighted / total_weight
        return self.total_score

    def get_top_factors(self, n: int = 3) -> List[Tuple[DecisionFactor, Decimal]]:
        """Get top contributing factors."""
        factor_contributions = [
            (factor, self.factors[factor] * self.weights[factor]) for factor in self.factors
        ]
        return sorted(factor_contributions, key=lambda x: x[1], reverse=True)[:n]


class DecisionExplanation:
    """Explanation for a decision with supporting reasoning."""

    def __init__(self, decision: str, confidence: Decimal):
        self.decision = decision
        self.confidence = confidence
        self.primary_reasons: List[str] = []
        self.supporting_data: Dict[str, Any] = {}
        self.risk_factors: List[str] = []
        self.alternative_considerations: List[str] = []
        self.key_assumptions: List[str] = []

    def add_reason(self, reason: str, data: Optional[Dict[str, Any]] = None):
        """Add a primary reason for the decision."""
        self.primary_reasons.append(reason)
        if data:
            self.supporting_data.update(data)

    def add_risk(self, risk: str):
        """Add a risk factor to consider."""
        self.risk_factors.append(risk)

    def add_alternative(self, alternative: str):
        """Add an alternative consideration."""
        self.alternative_considerations.append(alternative)

    def add_assumption(self, assumption: str):
        """Add a key assumption."""
        self.key_assumptions.append(assumption)

    def to_readable_text(self) -> str:
        """Convert explanation to human-readable text."""
        lines = [f"Decision: {self.decision}"]
        lines.append(f"Confidence: {float(self.confidence):.1%}")
        lines.append("")

        if self.primary_reasons:
            lines.append("Key Reasons:")
            for reason in self.primary_reasons:
                lines.append(f"• {reason}")
            lines.append("")

        if self.risk_factors:
            lines.append("Risk Factors:")
            for risk in self.risk_factors:
                lines.append(f"• {risk}")
            lines.append("")

        if self.alternative_considerations:
            lines.append("Alternative Considerations:")
            for alt in self.alternative_considerations:
                lines.append(f"• {alt}")

        return "\n".join(lines)


class DecisionAgent:
    """
    Agent for synthesizing insights into actionable fantasy football recommendations.

    Provides multi-criteria decision analysis with confidence scoring,
    risk assessment, and human-readable explanations.
    """

    def __init__(
        self,
        risk_tolerance: RiskToleranceProfile = RiskToleranceProfile.MODERATE,
        league_settings: Optional[Dict[str, Any]] = None,
    ):
        self.risk_tolerance = risk_tolerance
        self.league_settings = league_settings or {}
        self.logger = logging.getLogger(__name__)

        # Default factor weights by risk profile
        self._factor_weights = self._get_default_weights()

        # Decision trees for complex scenarios
        self._decision_trees = self._build_decision_trees()

    def _get_default_weights(self) -> Dict[DecisionFactor, Decimal]:
        """Get default factor weights based on risk tolerance."""
        base_weights = {
            DecisionFactor.PROJECTION: Decimal("0.25"),
            DecisionFactor.VALUE: Decimal("0.15"),
            DecisionFactor.MATCHUP: Decimal("0.20"),
            DecisionFactor.OWNERSHIP: Decimal("0.10"),
            DecisionFactor.INJURY_RISK: Decimal("0.10"),
            DecisionFactor.WEATHER: Decimal("0.05"),
            DecisionFactor.GAME_SCRIPT: Decimal("0.10"),
            DecisionFactor.CORRELATION: Decimal("0.05"),
        }

        # Adjust weights based on risk tolerance
        if self.risk_tolerance == RiskToleranceProfile.CONSERVATIVE:
            base_weights[DecisionFactor.PROJECTION] = Decimal("0.35")
            base_weights[DecisionFactor.INJURY_RISK] = Decimal("0.15")
            base_weights[DecisionFactor.VARIANCE] = Decimal("0.05")
            base_weights[DecisionFactor.OWNERSHIP] = Decimal("0.05")

        elif self.risk_tolerance == RiskToleranceProfile.AGGRESSIVE:
            base_weights[DecisionFactor.VARIANCE] = Decimal("0.15")
            base_weights[DecisionFactor.OWNERSHIP] = Decimal("0.15")
            base_weights[DecisionFactor.VALUE] = Decimal("0.20")
            base_weights[DecisionFactor.PROJECTION] = Decimal("0.20")

        elif self.risk_tolerance == RiskToleranceProfile.TOURNAMENT:
            base_weights[DecisionFactor.VARIANCE] = Decimal("0.20")
            base_weights[DecisionFactor.OWNERSHIP] = Decimal("0.20")
            base_weights[DecisionFactor.CORRELATION] = Decimal("0.15")
            base_weights[DecisionFactor.PROJECTION] = Decimal("0.15")

        elif self.risk_tolerance == RiskToleranceProfile.CASH_GAME:
            base_weights[DecisionFactor.PROJECTION] = Decimal("0.40")
            base_weights[DecisionFactor.INJURY_RISK] = Decimal("0.15")
            base_weights[DecisionFactor.VARIANCE] = Decimal("0.05")
            base_weights[DecisionFactor.OWNERSHIP] = Decimal("0.05")

        return base_weights

    def _build_decision_trees(self) -> Dict[str, DecisionNode]:
        """Build decision trees for complex scenarios."""
        trees = {}

        # Injury impact decision tree
        injury_tree = DecisionNode(
            condition="injury_severity > 7",
            weight=Decimal("0.8"),
            outcome_positive="Avoid - high injury risk",
            outcome_negative=DecisionNode(
                condition="injury_severity > 3 AND position_depth < 2",
                weight=Decimal("0.6"),
                outcome_positive="Consider with caution - moderate risk",
                outcome_negative="Proceed normally - low injury impact",
            ),
        )
        trees["injury_impact"] = injury_tree

        # Weather impact decision tree
        weather_tree = DecisionNode(
            condition="weather_impact > 6 AND position IN ['K', 'WR']",
            weight=Decimal("0.9"),
            outcome_positive="Strongly avoid - severe weather impact",
            outcome_negative=DecisionNode(
                condition="weather_impact > 3 AND game_total < 40",
                weight=Decimal("0.7"),
                outcome_positive="Consider downgrading - moderate weather concern",
                outcome_negative="Weather not a significant factor",
            ),
        )
        trees["weather_impact"] = weather_tree

        return trees

    def synthesize_lineup_decision(
        self,
        player_pool: List[Player],
        constraints: LineupConstraints,
        matchup_analyses: List[MatchupAnalysis],
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> LineupRecommendation:
        """
        Synthesize optimal lineup recommendation from player pool and analysis.

        Args:
            player_pool: Available players to choose from
            constraints: Lineup construction constraints
            matchup_analyses: Game analyses for context
            user_preferences: User-specific preferences

        Returns:
            Comprehensive lineup recommendation with alternatives
        """
        self.logger.info(f"Synthesizing lineup decision for {len(player_pool)} players")

        # Score all players using multi-criteria analysis
        player_scores = {}
        for player in player_pool:
            score = self._score_player_for_lineup(player, matchup_analyses)
            player_scores[player.id] = score

        # Build optimal lineup using scored players
        optimal_lineup = self._build_optimal_lineup(player_pool, player_scores, constraints)

        # Generate alternatives with different strategies
        alternatives = self._generate_lineup_alternatives(
            player_pool, player_scores, constraints, optimal_lineup
        )

        # Create comprehensive recommendation
        recommendation = LineupRecommendation(
            optimal_lineup=optimal_lineup,
            alternatives=alternatives,
            reasoning=self._generate_lineup_reasoning(optimal_lineup, player_scores),
            key_factors=self._extract_key_factors(player_scores),
            strategy=self._determine_strategy(),
            contest_type=self._recommend_contest_type(optimal_lineup),
            risk_level=self._assess_lineup_risk(optimal_lineup),
            upside_potential=self._assess_upside(optimal_lineup),
            floor_assessment=self._assess_floor(optimal_lineup),
            recommended_contest_types=self._get_recommended_contests(optimal_lineup),
            overall_confidence=self._calculate_lineup_confidence(optimal_lineup, player_scores),
            week=self._get_current_week(),
            season=self._get_current_season(),
        )

        return recommendation

    def analyze_matchup(self, matchup: Matchup, player_context: List[Player]) -> MatchupAnalysis:
        """
        Analyze matchup for fantasy implications.

        Args:
            matchup: The matchup to analyze
            player_context: Relevant players in the matchup

        Returns:
            Comprehensive matchup analysis
        """
        self.logger.info(f"Analyzing matchup: {matchup.home_team} vs {matchup.away_team}")

        # Analyze each team
        home_analysis = self._analyze_team_in_matchup(
            matchup.home_team, matchup, player_context, is_home=True
        )
        away_analysis = self._analyze_team_in_matchup(
            matchup.away_team, matchup, player_context, is_home=False
        )

        # Calculate win probabilities
        home_win_prob, away_win_prob = self._calculate_win_probabilities(matchup)

        # Generate key factors
        key_factors = self._identify_matchup_factors(matchup, player_context)

        # Build comprehensive analysis
        analysis = MatchupAnalysis(
            matchup=matchup,
            summary=self._generate_matchup_summary(matchup, home_analysis, away_analysis),
            key_storylines=self._extract_storylines(matchup),
            home_win_probability=home_win_prob,
            away_win_probability=away_win_prob,
            expected_game_script=self._predict_game_script(matchup, home_win_prob),
            pace_projection=matchup.get_pace_projection() or "Average",
            competitiveness_rating=self._rate_competitiveness(home_win_prob, away_win_prob),
            home_team_analysis=home_analysis,
            away_team_analysis=away_analysis,
            key_factors=key_factors,
            stack_recommendations=self._recommend_stacks(matchup, player_context),
            contrarian_plays=self._identify_contrarian_plays(matchup, player_context),
            dfs_game_theory=self._analyze_dfs_game_theory(matchup, player_context),
            projected_ownership_impact=self._predict_ownership_patterns(matchup, player_context),
            risk_factors=self._identify_risk_factors(matchup),
            analysis_confidence=self._calculate_matchup_confidence(matchup),
            volatility_rating=self._assess_volatility(matchup),
            data_completeness=self._assess_data_quality(matchup),
            analyst_notes=self._generate_analyst_notes(matchup),
        )

        return analysis

    def analyze_trade(
        self,
        players_giving: List[Player],
        players_receiving: List[Player],
        team_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a potential trade scenario.

        Args:
            players_giving: Players being traded away
            players_receiving: Players being acquired
            team_context: Current team composition and needs

        Returns:
            Trade analysis with recommendation
        """
        self.logger.info(
            f"Analyzing trade: giving {len(players_giving)}, receiving {len(players_receiving)}"
        )

        # Calculate value for each side
        giving_value = self._calculate_trade_value(players_giving, team_context)
        receiving_value = self._calculate_trade_value(players_receiving, team_context)

        # Multi-criteria analysis
        trade_score = MultiCriteriaScore()

        # Value differential
        value_diff = receiving_value["total"] - giving_value["total"]
        trade_score.add_factor(
            DecisionFactor.VALUE, self._normalize_score(value_diff, -20, 20), Decimal("0.3")
        )

        # Team needs fulfillment
        needs_score = self._assess_team_needs_fulfillment(
            players_giving, players_receiving, team_context
        )
        trade_score.add_factor(DecisionFactor.PROJECTION, needs_score, Decimal("0.25"))

        # Risk assessment
        risk_diff = receiving_value["risk"] - giving_value["risk"]
        trade_score.add_factor(
            DecisionFactor.INJURY_RISK,
            Decimal("1") - self._normalize_score(risk_diff, -5, 5),
            Decimal("0.2"),
        )

        # Schedule strength
        schedule_diff = receiving_value["schedule"] - giving_value["schedule"]
        trade_score.add_factor(
            DecisionFactor.MATCHUP, self._normalize_score(schedule_diff, -10, 10), Decimal("0.15")
        )

        # Calculate final score
        final_score = trade_score.calculate_score()
        confidence = self._calculate_trade_confidence(giving_value, receiving_value)

        # Generate explanation
        explanation = self._generate_trade_explanation(
            players_giving,
            players_receiving,
            giving_value,
            receiving_value,
            final_score,
            confidence,
        )

        return {
            "recommendation": self._make_trade_recommendation(final_score),
            "confidence": confidence,
            "score": final_score,
            "value_differential": value_diff,
            "giving_analysis": giving_value,
            "receiving_analysis": receiving_value,
            "explanation": explanation,
            "key_factors": trade_score.get_top_factors(),
            "timeline_recommendation": self._recommend_trade_timing(players_receiving),
        }

    def analyze_injury_impact(
        self,
        injured_player: Player,
        replacement_candidates: List[Player],
        matchup_context: Optional[MatchupAnalysis] = None,
    ) -> Dict[str, Any]:
        """
        Analyze impact of player injury and recommend replacements.

        Args:
            injured_player: Player with injury concern
            replacement_candidates: Potential replacement players
            matchup_context: Matchup analysis for context

        Returns:
            Injury impact analysis with replacement recommendations
        """
        self.logger.info(f"Analyzing injury impact for {injured_player.name}")

        if not injured_player.injury_report:
            return {
                "severity": "No injury reported",
                "impact": "None",
                "recommendation": "No action needed",
                "confidence": Decimal("1.0"),
            }

        # Assess injury severity and impact
        severity_score = self._assess_injury_severity(injured_player)
        impact_assessment = self._assess_injury_impact(injured_player, matchup_context)

        # Use decision tree for injury decisions
        decision_context = {
            "injury_severity": severity_score,
            "position_depth": self._assess_position_depth(injured_player, replacement_candidates),
            "game_importance": matchup_context.competitiveness_rating if matchup_context else 5,
            "time_until_game": self._calculate_time_until_game(injured_player),
        }

        tree_result, tree_confidence = self._decision_trees["injury_impact"].evaluate(
            decision_context
        )

        # Score replacement candidates
        replacement_scores = []
        for candidate in replacement_candidates:
            if candidate.position == injured_player.position:
                score = self._score_replacement_candidate(
                    candidate, injured_player, matchup_context
                )
                replacement_scores.append((candidate, score))

        # Sort by score
        replacement_scores.sort(key=lambda x: x[1].total_score or 0, reverse=True)

        # Generate comprehensive analysis
        explanation = DecisionExplanation(tree_result, tree_confidence)

        explanation.add_reason(
            f"Injury severity assessed as {severity_score}/10",
            {"severity_factors": impact_assessment["factors"]},
        )

        if replacement_scores:
            top_replacement = replacement_scores[0]
            explanation.add_reason(
                f"Best replacement option: {top_replacement[0].name}",
                {"replacement_score": float(top_replacement[1].total_score or 0)},
            )

        explanation.add_assumption(
            f"Current injury status: {injured_player.injury_report.status.value}"
        )

        if injured_player.injury_report.estimated_return:
            explanation.add_assumption(
                f"Estimated return: {injured_player.injury_report.estimated_return}"
            )

        return {
            "injured_player": injured_player.name,
            "injury_status": injured_player.injury_report.status.value,
            "severity_score": severity_score,
            "impact_assessment": impact_assessment,
            "decision": tree_result,
            "confidence": tree_confidence,
            "replacement_recommendations": [
                {
                    "player": candidate.name,
                    "score": float(score.total_score or 0),
                    "reasoning": self._generate_replacement_reasoning(candidate, score),
                }
                for candidate, score in replacement_scores[:3]  # Top 3
            ],
            "explanation": explanation.to_readable_text(),
            "monitoring_points": self._get_injury_monitoring_points(injured_player),
        }

    def _score_player_for_lineup(
        self, player: Player, matchup_analyses: List[MatchupAnalysis]
    ) -> MultiCriteriaScore:
        """Score a player for lineup inclusion using multiple criteria."""
        score = MultiCriteriaScore()

        # Projection score
        if player.projections:
            proj_score = self._normalize_score(
                float(player.projections.projected_fantasy_points), 0, 30
            )
            score.add_factor(
                DecisionFactor.PROJECTION,
                proj_score,
                self._factor_weights[DecisionFactor.PROJECTION],
            )

        # Value score
        if player.value_metrics and player.value_metrics.points_per_dollar:
            value_score = self._normalize_score(float(player.value_metrics.points_per_dollar), 1, 6)
            score.add_factor(
                DecisionFactor.VALUE, value_score, self._factor_weights[DecisionFactor.VALUE]
            )

        # Matchup score
        matchup_score = self._get_matchup_score(player, matchup_analyses)
        if matchup_score:
            score.add_factor(
                DecisionFactor.MATCHUP, matchup_score, self._factor_weights[DecisionFactor.MATCHUP]
            )

        # Ownership factor (inverse for tournaments)
        if player.value_metrics and player.value_metrics.projected_ownership:
            ownership_factor = self._get_ownership_factor(
                float(player.value_metrics.projected_ownership)
            )
            score.add_factor(
                DecisionFactor.OWNERSHIP,
                ownership_factor,
                self._factor_weights[DecisionFactor.OWNERSHIP],
            )

        # Injury risk
        injury_risk = self._assess_injury_risk_score(player)
        score.add_factor(
            DecisionFactor.INJURY_RISK,
            Decimal("1") - injury_risk,  # Invert so higher is better
            self._factor_weights[DecisionFactor.INJURY_RISK],
        )

        score.calculate_score()
        return score

    def _normalize_score(
        self, value: Union[float, Decimal], min_val: float, max_val: float
    ) -> Decimal:
        """Normalize a value to 0-1 scale."""
        value = float(value)
        if max_val <= min_val:
            return Decimal("0.5")

        normalized = (value - min_val) / (max_val - min_val)
        return Decimal(str(max(0, min(1, normalized))))

    def _get_matchup_score(
        self, player: Player, matchup_analyses: List[MatchupAnalysis]
    ) -> Optional[Decimal]:
        """Get matchup favorability score for player."""
        # Find relevant matchup
        relevant_analysis = None
        for analysis in matchup_analyses:
            if (
                analysis.matchup.home_team == player.team
                or analysis.matchup.away_team == player.team
            ):
                relevant_analysis = analysis
                break

        if not relevant_analysis:
            return None

        # Simple matchup scoring based on game total and pace
        base_score = Decimal("0.5")

        # High-scoring games favor skill positions
        if relevant_analysis.matchup.get_total_projected_points():
            total_points = relevant_analysis.matchup.get_total_projected_points()
            if total_points >= 48:
                base_score += Decimal("0.2")
            elif total_points <= 40:
                base_score -= Decimal("0.1")

        # Fast pace favors all positions
        if relevant_analysis.pace_projection == "Fast":
            base_score += Decimal("0.1")
        elif relevant_analysis.pace_projection == "Slow":
            base_score -= Decimal("0.1")

        return max(Decimal("0"), min(Decimal("1"), base_score))

    def _get_ownership_factor(self, ownership_pct: float) -> Decimal:
        """Get ownership factor based on risk tolerance."""
        if self.risk_tolerance in [
            RiskToleranceProfile.TOURNAMENT,
            RiskToleranceProfile.AGGRESSIVE,
        ]:
            # Prefer lower ownership in tournaments
            return Decimal("1") - self._normalize_score(ownership_pct, 0, 30)
        else:
            # Don't penalize high ownership in cash games
            return Decimal("0.7")

    def _assess_injury_risk_score(self, player: Player) -> Decimal:
        """Assess injury risk as a score from 0-1 (1 = highest risk)."""
        if not player.injury_report:
            return Decimal("0.1")  # Baseline risk

        status = player.injury_report.status
        risk_mapping = {
            InjuryStatus.HEALTHY: Decimal("0.1"),
            InjuryStatus.QUESTIONABLE: Decimal("0.3"),
            InjuryStatus.DOUBTFUL: Decimal("0.7"),
            InjuryStatus.OUT: Decimal("1.0"),
            InjuryStatus.IR: Decimal("1.0"),
            InjuryStatus.PUP: Decimal("1.0"),
            InjuryStatus.COVID: Decimal("0.5"),
            InjuryStatus.SUSPENDED: Decimal("1.0"),
        }

        return risk_mapping.get(status, Decimal("0.3"))

    def _build_optimal_lineup(
        self,
        player_pool: List[Player],
        player_scores: Dict[str, MultiCriteriaScore],
        constraints: LineupConstraints,
    ) -> Lineup:
        """Build optimal lineup from scored players (simplified implementation)."""
        # This is a simplified greedy approach
        # In practice, would use more sophisticated optimization

        from ..models.lineup import LineupSlot

        # Sort players by score within each position
        position_players = {}
        for player in player_pool:
            if player.position not in position_players:
                position_players[player.position] = []
            position_players[player.position].append(
                (player, player_scores[player.id].total_score or Decimal("0"))
            )

        # Sort each position by score
        for position in position_players:
            position_players[position].sort(key=lambda x: x[1], reverse=True)

        # Build lineup slots (simplified for demonstration)
        slots = []
        total_salary = 0
        total_projected_points = Decimal("0")

        # Basic lineup structure (customize based on constraints)
        basic_structure = {
            Position.QB: 1,
            Position.RB: 2,
            Position.WR: 3,
            Position.TE: 1,
            Position.K: 1,
            Position.DEF: 1,
        }

        for position, count in basic_structure.items():
            if position in position_players:
                for i in range(min(count, len(position_players[position]))):
                    player, score = position_players[position][i]

                    # Check salary constraint
                    player_salary = 0
                    if player.value_metrics and player.value_metrics.draftkings_salary:
                        player_salary = player.value_metrics.draftkings_salary

                    if total_salary + player_salary <= constraints.salary_cap:
                        slot = LineupSlot(
                            position=position, player=player, salary_used=player_salary
                        )
                        slots.append(slot)
                        total_salary += player_salary

                        if player.projections:
                            total_projected_points += player.projections.projected_fantasy_points

        # Create lineup object
        lineup = Lineup(
            lineup_type=LineupType.DRAFTKINGS,  # Default
            slots=slots,
            total_salary=total_salary,
            salary_remaining=constraints.salary_cap - total_salary,
            salary_cap=constraints.salary_cap,
            total_projected_points=total_projected_points,
            confidence_score=self._calculate_lineup_confidence_simple(slots, player_scores),
            week=self._get_current_week(),
            season=self._get_current_season(),
        )

        return lineup

    def _generate_lineup_alternatives(
        self,
        player_pool: List[Player],
        player_scores: Dict[str, MultiCriteriaScore],
        constraints: LineupConstraints,
        optimal_lineup: Lineup,
    ) -> List[LineupAlternative]:
        """Generate alternative lineup options."""
        alternatives = []

        # Alternative 1: Value-focused lineup
        value_lineup = self._build_value_focused_lineup(player_pool, constraints)
        if value_lineup:
            alternatives.append(
                LineupAlternative(
                    lineup=value_lineup,
                    reason="Value-focused build prioritizing points per dollar",
                    point_difference=value_lineup.total_projected_points
                    - optimal_lineup.total_projected_points,
                    salary_difference=value_lineup.total_salary - optimal_lineup.total_salary,
                    confidence=Decimal("0.75"),
                )
            )

        # Alternative 2: Low-ownership contrarian lineup
        contrarian_lineup = self._build_contrarian_lineup(player_pool, constraints)
        if contrarian_lineup:
            alternatives.append(
                LineupAlternative(
                    lineup=contrarian_lineup,
                    reason="Contrarian build with low-owned players for tournaments",
                    point_difference=contrarian_lineup.total_projected_points
                    - optimal_lineup.total_projected_points,
                    salary_difference=contrarian_lineup.total_salary - optimal_lineup.total_salary,
                    confidence=Decimal("0.65"),
                )
            )

        # Alternative 3: Safe floor lineup
        safe_lineup = self._build_safe_lineup(player_pool, constraints)
        if safe_lineup:
            alternatives.append(
                LineupAlternative(
                    lineup=safe_lineup,
                    reason="Conservative build emphasizing floor and safety",
                    point_difference=safe_lineup.total_projected_points
                    - optimal_lineup.total_projected_points,
                    salary_difference=safe_lineup.total_salary - optimal_lineup.total_salary,
                    confidence=Decimal("0.85"),
                )
            )

        return alternatives

    def _calculate_lineup_confidence_simple(
        self, slots: List, player_scores: Dict[str, MultiCriteriaScore]
    ) -> Decimal:
        """Calculate simple lineup confidence score."""
        if not slots:
            return Decimal("0")

        total_confidence = Decimal("0")
        for slot in slots:
            if slot.player and slot.player.id in player_scores:
                # Use projection confidence if available
                if slot.player.projections:
                    total_confidence += slot.player.projections.confidence_score
                else:
                    total_confidence += Decimal("0.7")  # Default

        return total_confidence / len(slots)

    def _generate_lineup_reasoning(
        self, lineup: Lineup, player_scores: Dict[str, MultiCriteriaScore]
    ) -> str:
        """Generate human-readable reasoning for lineup."""
        reasons = []

        # Analyze lineup composition
        players = lineup.get_players()
        avg_projected = lineup.total_projected_points / len(players) if players else 0

        reasons.append(
            f"Projected {float(lineup.total_projected_points):.1f} points from {len(players)} players"
        )
        reasons.append(f"Salary utilization: ${lineup.total_salary:,} of ${lineup.salary_cap:,}")

        # Identify key plays
        top_players = []
        for slot in lineup.slots:
            if slot.player and slot.player.projections:
                top_players.append(
                    (slot.player.name, float(slot.player.projections.projected_fantasy_points))
                )

        top_players.sort(key=lambda x: x[1], reverse=True)

        if top_players:
            reasons.append(
                f"Anchored by {top_players[0][0]} ({top_players[0][1]:.1f} projected points)"
            )

        # Team exposure analysis
        team_exposure = lineup.get_team_exposure()
        if team_exposure:
            max_team = max(team_exposure.items(), key=lambda x: x[1])
            if max_team[1] > 1:
                reasons.append(f"Highest team exposure: {max_team[1]} players from {max_team[0]}")

        return " • ".join(reasons)

    # Placeholder methods for core functionality
    def _extract_key_factors(self, player_scores: Dict[str, MultiCriteriaScore]) -> List[str]:
        """Extract key factors from player scoring."""
        return ["Projections", "Value", "Matchups", "Ownership"]

    def _determine_strategy(self) -> OptimizationStrategy:
        """Determine optimization strategy based on risk tolerance."""
        strategy_mapping = {
            RiskToleranceProfile.CONSERVATIVE: OptimizationStrategy.SAFE,
            RiskToleranceProfile.MODERATE: OptimizationStrategy.BALANCED,
            RiskToleranceProfile.AGGRESSIVE: OptimizationStrategy.GPP,
            RiskToleranceProfile.TOURNAMENT: OptimizationStrategy.CONTRARIAN,
            RiskToleranceProfile.CASH_GAME: OptimizationStrategy.CASH_GAME,
        }
        return strategy_mapping.get(self.risk_tolerance, OptimizationStrategy.BALANCED)

    def _recommend_contest_type(self, lineup: Lineup) -> str:
        """Recommend contest type based on lineup characteristics."""
        if self.risk_tolerance == RiskToleranceProfile.CASH_GAME:
            return "Cash Games"
        elif self.risk_tolerance == RiskToleranceProfile.TOURNAMENT:
            return "GPP Tournaments"
        else:
            return "Mixed"

    def _assess_lineup_risk(self, lineup: Lineup) -> str:
        """Assess overall lineup risk level."""
        risk_factors = 0

        for slot in lineup.slots:
            if slot.player and slot.player.is_injured():
                risk_factors += 1

        if lineup.variance_score and lineup.variance_score > 7:
            risk_factors += 1

        if risk_factors >= 3:
            return "High"
        elif risk_factors >= 1:
            return "Medium"
        else:
            return "Low"

    def _assess_upside(self, lineup: Lineup) -> str:
        """Assess upside potential."""
        if lineup.ceiling_points:
            upside = lineup.ceiling_points - lineup.total_projected_points
            if upside >= 20:
                return "Very High"
            elif upside >= 10:
                return "High"
            elif upside >= 5:
                return "Moderate"
            else:
                return "Low"
        return "Moderate"

    def _assess_floor(self, lineup: Lineup) -> str:
        """Assess floor/safety."""
        if lineup.floor_points:
            floor_ratio = lineup.floor_points / lineup.total_projected_points
            if floor_ratio >= 0.8:
                return "Very Safe"
            elif floor_ratio >= 0.7:
                return "Safe"
            elif floor_ratio >= 0.6:
                return "Moderate"
            else:
                return "Risky"
        return "Moderate"

    def _get_recommended_contests(self, lineup: Lineup) -> List[str]:
        """Get recommended contest types."""
        contests = []

        risk_level = self._assess_lineup_risk(lineup)
        upside = self._assess_upside(lineup)

        if risk_level == "Low":
            contests.extend(["50/50", "Double-ups", "Head-to-head"])

        if upside in ["High", "Very High"]:
            contests.extend(["GPP", "Tournaments", "Millionaire Maker"])

        if risk_level == "Medium":
            contests.append("Small field tournaments")

        return contests or ["Mixed contests"]

    def _calculate_lineup_confidence(
        self, lineup: Lineup, player_scores: Dict[str, MultiCriteriaScore]
    ) -> Decimal:
        """Calculate overall lineup confidence."""
        return lineup.confidence_score  # Use existing confidence

    def _get_current_week(self) -> int:
        """Get current NFL week (placeholder)."""
        return 1

    def _get_current_season(self) -> int:
        """Get current NFL season (placeholder)."""
        return 2024

    # Additional placeholder methods for alternative lineup strategies
    def _build_value_focused_lineup(
        self, player_pool: List[Player], constraints: LineupConstraints
    ) -> Optional[Lineup]:
        """Build lineup focused on value plays."""
        # Placeholder implementation
        return None

    def _build_contrarian_lineup(
        self, player_pool: List[Player], constraints: LineupConstraints
    ) -> Optional[Lineup]:
        """Build contrarian low-ownership lineup."""
        # Placeholder implementation
        return None

    def _build_safe_lineup(
        self, player_pool: List[Player], constraints: LineupConstraints
    ) -> Optional[Lineup]:
        """Build conservative safe lineup."""
        # Placeholder implementation
        return None

    # Matchup analysis methods (simplified implementations)
    def _analyze_team_in_matchup(
        self, team, matchup: Matchup, player_context: List[Player], is_home: bool
    ) -> TeamAnalysis:
        """Analyze team performance in specific matchup."""
        return TeamAnalysis(
            team=team,
            key_strengths=["Strong offense", "Good matchup"],
            key_weaknesses=["Injury concerns", "Poor recent form"],
            favorable_matchups=["WR vs weak secondary"],
            concerning_matchups=["RB vs strong run defense"],
            players_to_target=["Star QB", "Top WR"],
            players_to_avoid=["Injured RB"],
            likely_game_script="Competitive throughout",
            volume_expectations={"QB": "High", "RB": "Medium", "WR": "High"},
            ceiling_scenario="Blowout win with big plays",
            floor_scenario="Close loss in low-scoring game",
            most_likely_scenario="Competitive game with moderate scoring",
        )

    def _calculate_win_probabilities(self, matchup: Matchup) -> Tuple[Decimal, Decimal]:
        """Calculate win probabilities for teams."""
        # Simplified calculation based on betting lines or team strength
        if matchup.betting_lines and matchup.betting_lines.home_win_probability:
            home_prob = matchup.betting_lines.home_win_probability
            away_prob = Decimal("1") - home_prob
        else:
            # Default to roughly even
            home_prob = Decimal("0.52")  # Slight home field advantage
            away_prob = Decimal("0.48")

        return home_prob, away_prob

    def _identify_matchup_factors(self, matchup: Matchup, player_context: List[Player]) -> List:
        """Identify key factors affecting the matchup."""
        from ..models.matchup import MatchupFactor

        factors = []

        # Weather factor
        if matchup.is_weather_game():
            factors.append(
                MatchupFactor(
                    name="Weather",
                    description="Adverse weather conditions expected",
                    impact_rating=Decimal("-2"),
                    confidence=Decimal("0.8"),
                    affects_home_team=True,
                    affects_away_team=True,
                    category="Weather",
                )
            )

        # Add more factors based on analysis
        return factors

    def _generate_matchup_summary(
        self, matchup: Matchup, home_analysis: TeamAnalysis, away_analysis: TeamAnalysis
    ) -> str:
        """Generate matchup summary."""
        return f"{matchup.away_team.value} at {matchup.home_team.value} - Competitive divisional matchup with playoff implications"

    def _extract_storylines(self, matchup: Matchup) -> List[str]:
        """Extract key storylines."""
        return [
            "Division rivalry game",
            "Revenge game for former players",
            "Weather could be a factor",
        ]

    def _predict_game_script(self, matchup: Matchup, home_win_prob: Decimal) -> str:
        """Predict likely game script."""
        if home_win_prob > 0.65:
            return "Home team takes early lead and controls"
        elif home_win_prob < 0.35:
            return "Away team likely to lead and control pace"
        else:
            return "Back-and-forth competitive game throughout"

    def _rate_competitiveness(self, home_win_prob: Decimal, away_win_prob: Decimal) -> Decimal:
        """Rate expected game competitiveness."""
        diff = abs(home_win_prob - away_win_prob)
        return Decimal("10") - (diff * 20)  # Scale 0-10, closer games = higher rating

    def _recommend_stacks(self, matchup: Matchup, player_context: List[Player]) -> List[str]:
        """Recommend player stacks."""
        return [
            f"{matchup.home_team.value} QB + WR",
            f"{matchup.away_team.value} skill position stack",
        ]

    def _identify_contrarian_plays(
        self, matchup: Matchup, player_context: List[Player]
    ) -> List[str]:
        """Identify contrarian plays."""
        return ["Low-owned WR2", "Backup RB with opportunity"]

    def _analyze_dfs_game_theory(self, matchup: Matchup, player_context: List[Player]) -> str:
        """Analyze DFS game theory implications."""
        return "High-total game creates leverage opportunities with lower-owned correlation plays"

    def _predict_ownership_patterns(self, matchup: Matchup, player_context: List[Player]) -> str:
        """Predict ownership patterns."""
        return "Star QB will be highly owned, creating value in complementary pieces"

    def _identify_risk_factors(self, matchup: Matchup) -> List[str]:
        """Identify primary risk factors."""
        risks = []

        if matchup.is_weather_game():
            risks.append("Severe weather conditions")

        if matchup.key_injuries:
            risks.append("Key injury concerns")

        return risks

    def _calculate_matchup_confidence(self, matchup: Matchup) -> Decimal:
        """Calculate confidence in matchup analysis."""
        base_confidence = Decimal("0.75")

        # Adjust based on data completeness
        if matchup.data_sources and len(matchup.data_sources) >= 3:
            base_confidence += Decimal("0.1")

        if matchup.historical_matchup:
            base_confidence += Decimal("0.05")

        return min(Decimal("1"), base_confidence)

    def _assess_volatility(self, matchup: Matchup) -> Decimal:
        """Assess expected outcome volatility."""
        base_volatility = Decimal("5")

        if matchup.is_weather_game():
            base_volatility += Decimal("2")

        if matchup.key_injuries:
            base_volatility += Decimal("1")

        return min(Decimal("10"), base_volatility)

    def _assess_data_quality(self, matchup: Matchup) -> Decimal:
        """Assess completeness of underlying data."""
        completeness = Decimal("0.8")  # Base completeness

        if matchup.betting_lines:
            completeness += Decimal("0.1")

        if matchup.game_environment:
            completeness += Decimal("0.05")

        if matchup.home_team_stats and matchup.away_team_stats:
            completeness += Decimal("0.05")

        return min(Decimal("1"), completeness)

    def _generate_analyst_notes(self, matchup: Matchup) -> str:
        """Generate additional analyst notes."""
        return "Monitor injury reports and weather updates leading up to kickoff"

    # Trade analysis helper methods (simplified)
    def _calculate_trade_value(
        self, players: List[Player], team_context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate trade value for a group of players."""
        total_value = sum(
            float(p.projections.projected_fantasy_points) if p.projections else 0 for p in players
        )

        return {
            "total": total_value,
            "risk": sum(float(self._assess_injury_risk_score(p)) for p in players),
            "schedule": 5.0,  # Placeholder schedule strength
            "players": [p.name for p in players],
        }

    def _assess_team_needs_fulfillment(
        self, giving: List[Player], receiving: List[Player], team_context: Optional[Dict[str, Any]]
    ) -> Decimal:
        """Assess how well trade fulfills team needs."""
        return Decimal("0.7")  # Placeholder

    def _calculate_trade_confidence(
        self, giving_value: Dict[str, Any], receiving_value: Dict[str, Any]
    ) -> Decimal:
        """Calculate confidence in trade analysis."""
        return Decimal("0.8")  # Placeholder

    def _generate_trade_explanation(
        self,
        players_giving: List[Player],
        players_receiving: List[Player],
        giving_value: Dict[str, Any],
        receiving_value: Dict[str, Any],
        final_score: Decimal,
        confidence: Decimal,
    ) -> DecisionExplanation:
        """Generate trade explanation."""
        if final_score > 0.6:
            decision = "Accept Trade"
        elif final_score > 0.4:
            decision = "Consider Trade"
        else:
            decision = "Decline Trade"

        explanation = DecisionExplanation(decision, confidence)

        value_diff = receiving_value["total"] - giving_value["total"]
        if value_diff > 0:
            explanation.add_reason(f"Gaining {value_diff:.1f} projected points")
        else:
            explanation.add_reason(f"Losing {abs(value_diff):.1f} projected points")

        return explanation

    def _make_trade_recommendation(self, score: Decimal) -> str:
        """Make trade recommendation based on score."""
        if score >= Decimal("0.7"):
            return "Strongly Accept"
        elif score >= Decimal("0.6"):
            return "Accept"
        elif score >= Decimal("0.4"):
            return "Consider"
        else:
            return "Decline"

    def _recommend_trade_timing(self, receiving_players: List[Player]) -> str:
        """Recommend timing for trade execution."""
        return "Execute before next waiver period"

    # Injury analysis helper methods
    def _assess_injury_severity(self, player: Player) -> int:
        """Assess injury severity on 1-10 scale."""
        if not player.injury_report:
            return 1

        if player.injury_report.severity_score:
            return player.injury_report.severity_score

        # Map status to severity
        status_severity = {
            InjuryStatus.HEALTHY: 1,
            InjuryStatus.QUESTIONABLE: 3,
            InjuryStatus.DOUBTFUL: 7,
            InjuryStatus.OUT: 9,
            InjuryStatus.IR: 10,
            InjuryStatus.PUP: 10,
            InjuryStatus.COVID: 5,
            InjuryStatus.SUSPENDED: 8,
        }

        return status_severity.get(player.injury_report.status, 3)

    def _assess_injury_impact(
        self, player: Player, matchup_context: Optional[MatchupAnalysis]
    ) -> Dict[str, Any]:
        """Assess injury impact on performance."""
        factors = []

        if player.injury_report:
            factors.append(f"Status: {player.injury_report.status.value}")

            if player.injury_report.body_part:
                factors.append(f"Injury: {player.injury_report.body_part}")

            if player.injury_report.practice_participation:
                factors.append(f"Practice: {player.injury_report.practice_participation}")

        return {
            "factors": factors,
            "expected_impact": "Moderate reduction in performance",
            "timeline": "Monitor throughout week",
        }

    def _assess_position_depth(self, player: Player, candidates: List[Player]) -> int:
        """Assess depth at player's position."""
        same_position = [p for p in candidates if p.position == player.position]
        return len(same_position)

    def _calculate_time_until_game(self, player: Player) -> int:
        """Calculate hours until game (placeholder)."""
        return 48  # Placeholder

    def _score_replacement_candidate(
        self, candidate: Player, injured_player: Player, matchup_context: Optional[MatchupAnalysis]
    ) -> MultiCriteriaScore:
        """Score replacement candidate."""
        score = MultiCriteriaScore()

        # Projection comparison
        if candidate.projections and injured_player.projections:
            proj_ratio = (
                candidate.projections.projected_fantasy_points
                / injured_player.projections.projected_fantasy_points
            )
            score.add_factor(DecisionFactor.PROJECTION, proj_ratio, Decimal("0.4"))

        # Availability (injury status)
        availability = Decimal("1") - self._assess_injury_risk_score(candidate)
        score.add_factor(DecisionFactor.INJURY_RISK, availability, Decimal("0.3"))

        # Value
        if candidate.value_metrics and candidate.value_metrics.points_per_dollar:
            value_score = self._normalize_score(
                float(candidate.value_metrics.points_per_dollar), 1, 6
            )
            score.add_factor(DecisionFactor.VALUE, value_score, Decimal("0.2"))

        # Matchup
        if matchup_context:
            matchup_score = self._get_matchup_score(candidate, [matchup_context])
            if matchup_score:
                score.add_factor(DecisionFactor.MATCHUP, matchup_score, Decimal("0.1"))

        score.calculate_score()
        return score

    def _generate_replacement_reasoning(self, candidate: Player, score: MultiCriteriaScore) -> str:
        """Generate reasoning for replacement recommendation."""
        reasons = []

        if candidate.projections:
            reasons.append(
                f"{float(candidate.projections.projected_fantasy_points):.1f} projected points"
            )

        if not candidate.is_injured():
            reasons.append("healthy and available")

        top_factors = score.get_top_factors(2)
        for factor, contribution in top_factors:
            reasons.append(f"strong {factor.value.lower()}")

        return " - ".join(reasons)

    def _get_injury_monitoring_points(self, player: Player) -> List[str]:
        """Get key monitoring points for injured player."""
        points = []

        points.append("Monitor practice reports throughout week")
        points.append("Check for any setbacks or improvements")

        if player.injury_report and player.injury_report.estimated_return:
            points.append(f"Expected return: {player.injury_report.estimated_return}")

        points.append("Have backup options ready")

        return points
