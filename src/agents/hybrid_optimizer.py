"""
Hybrid Lineup Optimizer combining mathematical optimization with LLM enhancement.

This module provides the main interface for the hybrid optimization system,
seamlessly integrating mathematical optimization with intelligent LLM analysis
to provide the best of both worlds.
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any, Union

from ..models.player import Player, Position
from ..models.lineup import Lineup, LineupRecommendation, OptimizationStrategy, LineupConstraints
from ..models.matchup import MatchupAnalysis
from .optimization import OptimizationAgent
from .llm_enhancement import LLMEnhancementEngine, EnhancementContext, LLMAnalysis

logger = logging.getLogger(__name__)


class HybridOptimizationResult:
    """Enhanced result from hybrid optimization combining math and LLM insights."""

    def __init__(
        self,
        optimal_lineup: Lineup,
        mathematical_analysis: Dict[str, Any],
        llm_analysis: LLMAnalysis,
        alternatives: List[Dict[str, Any]] = None,
        edge_cases: List[Any] = None,
        strategy_adaptations: Dict[str, Any] = None,
    ):
        self.optimal_lineup = optimal_lineup
        self.mathematical_analysis = mathematical_analysis
        self.llm_analysis = llm_analysis
        self.alternatives = alternatives or []
        self.edge_cases = edge_cases or []
        self.strategy_adaptations = strategy_adaptations or {}

        # Combined metrics
        self.overall_confidence = self._calculate_overall_confidence()
        self.recommendation_strength = self._calculate_recommendation_strength()

    def _calculate_overall_confidence(self) -> float:
        """Calculate overall confidence combining math and LLM confidence."""
        math_confidence = self.mathematical_analysis.get("confidence_score", 0.5)
        llm_confidence = self.llm_analysis.confidence_score

        # Weighted average (60% math, 40% LLM)
        return (math_confidence * 0.6) + (llm_confidence * 0.4)

    def _calculate_recommendation_strength(self) -> str:
        """Calculate overall recommendation strength."""
        confidence = self.overall_confidence

        if confidence >= 0.8:
            return "Strong"
        elif confidence >= 0.6:
            return "Moderate"
        else:
            return "Weak"

    def get_explanation(self) -> str:
        """Get comprehensive explanation combining math and LLM insights."""
        return self.llm_analysis.primary_recommendation

    def get_key_insights(self) -> List[str]:
        """Get key insights from both mathematical and LLM analysis."""
        insights = []

        # Add mathematical insights
        math_recs = self.mathematical_analysis.get("recommendations", [])
        insights.extend([f"[Math] {rec}" for rec in math_recs])

        # Add LLM insights
        for insight in self.llm_analysis.key_insights:
            insights.append(f"[LLM] {insight.reasoning}")

        return insights

    def get_risk_assessment(self) -> Dict[str, Any]:
        """Get comprehensive risk assessment."""
        return {
            "overall_risk": self.llm_analysis.risk_assessment.get("overall_risk", "Unknown"),
            "risk_factors": self.llm_analysis.risk_assessment.get("risk_factors", []),
            "mitigation_strategies": self.llm_analysis.risk_assessment.get(
                "mitigation_strategies", []
            ),
            "confidence": self.overall_confidence,
        }


class HybridLineupOptimizer:
    """
    Hybrid lineup optimizer that combines mathematical optimization with LLM enhancement.

    This class provides the main interface for the hybrid optimization system,
    seamlessly integrating the speed and precision of mathematical optimization
    with the intelligence and reasoning of LLM analysis.
    """

    def __init__(self, llm_api_key: str, max_workers: int = None, enable_llm: bool = True):
        """
        Initialize the hybrid optimizer.

        Args:
            llm_api_key: OpenAI API key for LLM enhancement
            max_workers: Maximum number of workers for mathematical optimization
            enable_llm: Whether to enable LLM enhancement (can be disabled for testing)
        """
        self.logger = logging.getLogger(__name__)
        self.enable_llm = enable_llm

        # Initialize mathematical optimizer
        self.math_optimizer = OptimizationAgent(max_workers=max_workers)

        # Initialize LLM enhancement engine
        if enable_llm:
            self.llm_engine = LLMEnhancementEngine(llm_api_key)
        else:
            self.llm_engine = None

        # Performance tracking
        self.optimization_stats = {
            "total_optimizations": 0,
            "successful_optimizations": 0,
            "llm_enhancements": 0,
            "average_optimization_time": 0.0,
            "math_only_fallbacks": 0,
        }

    async def optimize_lineup(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        strategy: OptimizationStrategy = OptimizationStrategy.BALANCED,
        context: Optional[Dict[str, Any]] = None,
        use_llm: bool = True,
    ) -> HybridOptimizationResult:
        """
        Optimize lineup using hybrid mathematical + LLM approach.

        Args:
            players: Available players for selection
            constraints: Lineup construction constraints
            strategy: Optimization strategy
            context: Additional context (week, season, contest type, etc.)
            use_llm: Whether to use LLM enhancement (overrides global setting)

        Returns:
            HybridOptimizationResult with comprehensive analysis
        """
        start_time = datetime.now()
        self.logger.info(f"Starting hybrid lineup optimization with {len(players)} players")

        try:
            # Step 1: Mathematical optimization
            math_result = await self._perform_mathematical_optimization(
                players, constraints, strategy
            )

            if not math_result or not math_result.optimal_lineup:
                raise ValueError("Mathematical optimization failed")

            # Step 2: LLM enhancement (if enabled)
            llm_analysis = None
            alternatives = []
            edge_cases = []
            strategy_adaptations = {}

            if use_llm and self.llm_engine:
                try:
                    llm_analysis, alternatives, edge_cases, strategy_adaptations = (
                        await self._perform_llm_enhancement(
                            math_result, players, strategy, constraints, context
                        )
                    )
                    self.optimization_stats["llm_enhancements"] += 1
                except Exception as e:
                    self.logger.warning(
                        f"LLM enhancement failed: {e}, continuing with math-only result"
                    )
                    self.optimization_stats["math_only_fallbacks"] += 1
                    llm_analysis = self._create_fallback_llm_analysis(math_result)
            else:
                llm_analysis = self._create_fallback_llm_analysis(math_result)

            # Step 3: Create hybrid result
            hybrid_result = HybridOptimizationResult(
                optimal_lineup=math_result.optimal_lineup,
                mathematical_analysis=self._extract_mathematical_analysis(math_result),
                llm_analysis=llm_analysis,
                alternatives=alternatives,
                edge_cases=edge_cases,
                strategy_adaptations=strategy_adaptations,
            )

            # Update performance stats
            self._update_performance_stats(start_time, True)

            self.logger.info(
                f"Hybrid optimization completed successfully - "
                f"Confidence: {hybrid_result.overall_confidence:.2f}, "
                f"Strength: {hybrid_result.recommendation_strength}"
            )

            return hybrid_result

        except Exception as e:
            self.logger.error(f"Hybrid optimization failed: {e}")
            self._update_performance_stats(start_time, False)
            raise

    async def get_lineup_explanation(
        self,
        lineup: Lineup,
        players: List[Player],
        strategy: OptimizationStrategy,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Get detailed explanation for a specific lineup."""
        if not self.llm_engine:
            return "LLM enhancement not available. Please review mathematical optimization results."

        enhancement_context = self._create_enhancement_context(context)

        try:
            return await self.llm_engine.generate_explanation(
                lineup, players, strategy, enhancement_context
            )
        except Exception as e:
            self.logger.error(f"Explanation generation failed: {e}")
            return "Explanation generation failed. Please review the lineup manually."

    async def suggest_alternatives(
        self,
        current_lineup: Lineup,
        available_players: List[Player],
        strategy: OptimizationStrategy,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Suggest alternative lineup constructions."""
        if not self.llm_engine:
            return []

        enhancement_context = self._create_enhancement_context(context)

        try:
            return await self.llm_engine.suggest_alternatives(
                current_lineup, available_players, strategy, enhancement_context
            )
        except Exception as e:
            self.logger.error(f"Alternative suggestion failed: {e}")
            return []

    async def analyze_edge_cases(
        self, lineup: Lineup, players: List[Player], context: Optional[Dict[str, Any]] = None
    ) -> List[Any]:
        """Analyze potential edge cases in lineup construction."""
        if not self.llm_engine:
            return []

        enhancement_context = self._create_enhancement_context(context)

        try:
            return await self.llm_engine.handle_edge_cases(lineup, players, enhancement_context)
        except Exception as e:
            self.logger.error(f"Edge case analysis failed: {e}")
            return []

    async def adapt_strategy(
        self,
        current_strategy: OptimizationStrategy,
        market_conditions: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Adapt strategy based on current conditions."""
        if not self.llm_engine:
            return {"adaptations": [], "reasoning": "LLM enhancement not available"}

        enhancement_context = self._create_enhancement_context(context)

        try:
            return await self.llm_engine.adapt_strategy(
                current_strategy, market_conditions, enhancement_context
            )
        except Exception as e:
            self.logger.error(f"Strategy adaptation failed: {e}")
            return {"adaptations": [], "reasoning": "Strategy adaptation failed"}

    async def _perform_mathematical_optimization(
        self, players: List[Player], constraints: LineupConstraints, strategy: OptimizationStrategy
    ) -> LineupRecommendation:
        """Perform mathematical optimization using existing system."""
        self.logger.info("Performing mathematical optimization")

        return await self.math_optimizer.optimize_lineup(
            players=players,
            constraints=constraints,
            strategy=strategy,
            objective="maximize_points",  # Default objective
            use_genetic_algorithm=True,
            max_alternatives=3,
        )

    async def _perform_llm_enhancement(
        self,
        math_result: LineupRecommendation,
        players: List[Player],
        strategy: OptimizationStrategy,
        constraints: LineupConstraints,
        context: Optional[Dict[str, Any]],
    ) -> Tuple[Any, List[Dict[str, Any]], List[Any], Dict[str, Any]]:
        """Perform LLM enhancement of mathematical results."""
        self.logger.info("Performing LLM enhancement")

        # Create enhancement context
        enhancement_context = self._create_enhancement_context(context)

        # Prepare mathematical result for LLM analysis
        math_analysis = self._extract_mathematical_analysis(math_result)

        # Get comprehensive LLM analysis
        llm_analysis = await self.llm_engine.enhance_lineup_analysis(
            math_analysis, players, strategy, constraints.__dict__, enhancement_context
        )

        # Get alternative suggestions
        alternatives = await self.llm_engine.suggest_alternatives(
            math_result.optimal_lineup, players, strategy, enhancement_context
        )

        # Get edge case analysis
        edge_cases = await self.llm_engine.handle_edge_cases(
            math_result.optimal_lineup, players, enhancement_context
        )

        # Get strategy adaptations
        market_conditions = context.get("market_conditions", {}) if context else {}
        strategy_adaptations = await self.llm_engine.adapt_strategy(
            strategy, market_conditions, enhancement_context
        )

        return llm_analysis, alternatives, edge_cases, strategy_adaptations

    def _create_enhancement_context(self, context: Optional[Dict[str, Any]]) -> EnhancementContext:
        """Create enhancement context from provided context."""
        if not context:
            context = {}

        return EnhancementContext(
            week=context.get("week", 1),
            season=context.get("season", 2024),
            contest_type=context.get("contest_type", "GPP"),
            bankroll_percentage=context.get("bankroll_percentage"),
            user_preferences=context.get("user_preferences", {}),
            market_conditions=context.get("market_conditions", {}),
            recent_performance=context.get("recent_performance", {}),
        )

    def _extract_mathematical_analysis(self, math_result: LineupRecommendation) -> Dict[str, Any]:
        """Extract mathematical analysis data for LLM processing."""
        return {
            "optimal_lineup": {
                "total_projected_points": float(math_result.optimal_lineup.total_projected_points),
                "total_salary": math_result.optimal_lineup.total_salary,
                "salary_remaining": math_result.optimal_lineup.salary_remaining,
                "confidence_score": float(math_result.optimal_lineup.confidence_score),
                "starters": {
                    slot.position.value: {
                        "name": slot.player.name if slot.player else "Empty",
                        "position": slot.position.value,
                        "team": slot.player.team.value if slot.player else "Unknown",
                        "projected_points": (
                            float(slot.player.projections.projected_fantasy_points)
                            if slot.player and slot.player.projections
                            else 0.0
                        ),
                        "salary": slot.salary_used,
                    }
                    for slot in math_result.optimal_lineup.slots
                },
            },
            "alternatives": [
                {
                    "lineup": alt.lineup,
                    "reason": alt.reason,
                    "point_difference": float(alt.point_difference),
                    "confidence": float(alt.confidence),
                }
                for alt in math_result.alternatives
            ],
            "reasoning": math_result.reasoning,
            "key_factors": math_result.key_factors,
            "strategy": math_result.strategy.value,
            "risk_level": math_result.risk_level,
            "upside_potential": math_result.upside_potential,
            "floor_assessment": math_result.floor_assessment,
            "overall_confidence": float(math_result.overall_confidence),
        }

    def _create_fallback_llm_analysis(self, math_result: LineupRecommendation) -> Any:
        """Create fallback LLM analysis when LLM enhancement fails."""
        from .llm_enhancement import LLMAnalysis, LLMInsight

        return LLMAnalysis(
            primary_recommendation=f"Mathematical optimization completed using {math_result.strategy.value} strategy. LLM analysis unavailable.",
            key_insights=[
                LLMInsight(
                    insight_type="mathematical_only",
                    confidence=0.5,
                    reasoning="Using mathematical optimization results only",
                    impact_score=0.5,
                    actionable=False,
                )
            ],
            alternative_considerations=[
                "Consider manual review of mathematical optimization results"
            ],
            risk_assessment={
                "overall_risk": math_result.risk_level,
                "risk_factors": [],
                "mitigation_strategies": [],
            },
            market_analysis={
                "ownership_implications": "Unknown",
                "leverage_opportunities": [],
                "game_environment": "Unknown",
            },
            edge_cases=["LLM analysis unavailable"],
            confidence_score=0.5,
            reasoning_chain=["Mathematical optimization completed", "LLM analysis failed"],
        )

    def _update_performance_stats(self, start_time: datetime, success: bool):
        """Update performance tracking statistics."""
        duration = (datetime.now() - start_time).total_seconds()

        self.optimization_stats["total_optimizations"] += 1
        if success:
            self.optimization_stats["successful_optimizations"] += 1

        # Update average optimization time
        total = self.optimization_stats["total_optimizations"]
        current_avg = self.optimization_stats["average_optimization_time"]
        self.optimization_stats["average_optimization_time"] = (
            current_avg * (total - 1) + duration
        ) / total

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        stats = self.optimization_stats.copy()

        if stats["total_optimizations"] > 0:
            stats["success_rate"] = stats["successful_optimizations"] / stats["total_optimizations"]
            stats["llm_enhancement_rate"] = stats["llm_enhancements"] / stats["total_optimizations"]
            stats["math_only_fallback_rate"] = (
                stats["math_only_fallbacks"] / stats["total_optimizations"]
            )
        else:
            stats["success_rate"] = 0.0
            stats["llm_enhancement_rate"] = 0.0
            stats["math_only_fallback_rate"] = 0.0

        return stats

    def enable_llm_enhancement(self, enable: bool = True):
        """Enable or disable LLM enhancement."""
        self.enable_llm = enable
        self.logger.info(f"LLM enhancement {'enabled' if enable else 'disabled'}")

    def is_llm_available(self) -> bool:
        """Check if LLM enhancement is available."""
        return self.enable_llm and self.llm_engine is not None


# Convenience function for easy integration
async def optimize_lineup_hybrid(
    players: List[Player],
    constraints: LineupConstraints,
    strategy: OptimizationStrategy = OptimizationStrategy.BALANCED,
    llm_api_key: str = None,
    context: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
) -> HybridOptimizationResult:
    """
    Convenience function for hybrid lineup optimization.

    Args:
        players: Available players for selection
        constraints: Lineup construction constraints
        strategy: Optimization strategy
        llm_api_key: OpenAI API key (required if use_llm=True)
        context: Additional context
        use_llm: Whether to use LLM enhancement

    Returns:
        HybridOptimizationResult with comprehensive analysis
    """
    optimizer = HybridLineupOptimizer(
        llm_api_key=llm_api_key or "", enable_llm=use_llm and llm_api_key is not None
    )

    return await optimizer.optimize_lineup(
        players=players,
        constraints=constraints,
        strategy=strategy,
        context=context,
        use_llm=use_llm,
    )
