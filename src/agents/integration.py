"""
Integration module for the hybrid fantasy football optimization system.

This module provides the main interface for integrating the mathematical
optimization system with the LLM enhancement layer, creating a seamless
user experience that combines the best of both approaches.
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any, Union

from ..models.player import Player, Position
from ..models.lineup import Lineup, LineupRecommendation, OptimizationStrategy, LineupConstraints
from ..models.matchup import MatchupAnalysis
from .hybrid_optimizer import HybridLineupOptimizer, HybridOptimizationResult
from .user_interaction_engine import UserInteractionEngine, UserInteraction, InteractionType, InteractionResponse
from .llm_enhancement import EnhancementContext

logger = logging.getLogger(__name__)


class FantasyFootballAssistant:
    """
    Main assistant class that provides a unified interface for fantasy football
    lineup optimization with both mathematical precision and intelligent reasoning.
    
    This class serves as the primary interface for users to interact with the
    hybrid optimization system, providing methods for optimization, analysis,
    and interactive exploration.
    """
    
    def __init__(
        self,
        llm_api_key: str,
        max_workers: int = None,
        enable_llm: bool = True
    ):
        """
        Initialize the fantasy football assistant.
        
        Args:
            llm_api_key: OpenAI API key for LLM enhancement
            max_workers: Maximum number of workers for mathematical optimization
            enable_llm: Whether to enable LLM enhancement
        """
        self.logger = logging.getLogger(__name__)
        
        # Initialize core components
        self.hybrid_optimizer = HybridLineupOptimizer(
            llm_api_key=llm_api_key,
            max_workers=max_workers,
            enable_llm=enable_llm
        )
        
        self.interaction_engine = UserInteractionEngine(self.hybrid_optimizer)
        
        # Session state
        self.current_lineup: Optional[Lineup] = None
        self.available_players: List[Player] = []
        self.current_strategy: OptimizationStrategy = OptimizationStrategy.BALANCED
        self.current_constraints: Optional[LineupConstraints] = None
        self.session_context: Dict[str, Any] = {}
        
        # Performance tracking
        self.session_stats = {
            'optimizations_performed': 0,
            'interactions_handled': 0,
            'session_start_time': datetime.now(),
            'total_optimization_time': 0.0,
            'total_interaction_time': 0.0
        }
    
    async def optimize_lineup(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        strategy: OptimizationStrategy = OptimizationStrategy.BALANCED,
        context: Optional[Dict[str, Any]] = None,
        use_llm: bool = True
    ) -> HybridOptimizationResult:
        """
        Optimize lineup using hybrid mathematical + LLM approach.
        
        Args:
            players: Available players for selection
            constraints: Lineup construction constraints
            strategy: Optimization strategy
            context: Additional context (week, season, contest type, etc.)
            use_llm: Whether to use LLM enhancement
            
        Returns:
            HybridOptimizationResult with comprehensive analysis
        """
        start_time = datetime.now()
        self.logger.info("Starting lineup optimization")
        
        try:
            # Update session state
            self.available_players = players
            self.current_strategy = strategy
            self.current_constraints = constraints
            self.session_context.update(context or {})
            
            # Perform optimization
            result = await self.hybrid_optimizer.optimize_lineup(
                players=players,
                constraints=constraints,
                strategy=strategy,
                context=context,
                use_llm=use_llm
            )
            
            # Update session state with result
            self.current_lineup = result.optimal_lineup
            
            # Update session stats
            optimization_time = (datetime.now() - start_time).total_seconds()
            self.session_stats['optimizations_performed'] += 1
            self.session_stats['total_optimization_time'] += optimization_time
            
            self.logger.info(f"Lineup optimization completed in {optimization_time:.2f} seconds")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Lineup optimization failed: {e}")
            raise
    
    async def ask_question(
        self,
        question: str,
        interaction_type: Optional[InteractionType] = None
    ) -> InteractionResponse:
        """
        Ask a question about the current lineup or optimization.
        
        Args:
            question: User's question
            interaction_type: Type of interaction (auto-detected if None)
            
        Returns:
            InteractionResponse with answer and insights
        """
        start_time = datetime.now()
        self.logger.info(f"Handling user question: {question}")
        
        try:
            # Auto-detect interaction type if not provided
            if interaction_type is None:
                interaction_type = self._detect_interaction_type(question)
            
            # Create interaction
            interaction = UserInteraction(
                interaction_type=interaction_type,
                question=question,
                context=self.session_context,
                current_lineup=self.current_lineup,
                available_players=self.available_players
            )
            
            # Handle interaction
            response = await self.interaction_engine.handle_interaction(interaction)
            
            # Update session stats
            interaction_time = (datetime.now() - start_time).total_seconds()
            self.session_stats['interactions_handled'] += 1
            self.session_stats['total_interaction_time'] += interaction_time
            
            self.logger.info(f"Question answered in {interaction_time:.2f} seconds")
            
            return response
            
        except Exception as e:
            self.logger.error(f"Question handling failed: {e}")
            return InteractionResponse(
                answer=f"I encountered an error processing your question: {str(e)}",
                confidence=0.0
            )
    
    async def get_lineup_explanation(self) -> str:
        """Get detailed explanation of the current lineup."""
        if not self.current_lineup:
            return "No lineup available. Please run optimization first."
        
        try:
            return await self.hybrid_optimizer.get_lineup_explanation(
                self.current_lineup,
                self.available_players,
                self.current_strategy,
                self.session_context
            )
        except Exception as e:
            self.logger.error(f"Explanation generation failed: {e}")
            return "Explanation generation failed. Please review the lineup manually."
    
    async def suggest_alternatives(self) -> List[Dict[str, Any]]:
        """Get alternative lineup suggestions."""
        if not self.current_lineup:
            return []
        
        try:
            return await self.hybrid_optimizer.suggest_alternatives(
                self.current_lineup,
                self.available_players,
                self.current_strategy,
                self.session_context
            )
        except Exception as e:
            self.logger.error(f"Alternative suggestion failed: {e}")
            return []
    
    async def analyze_edge_cases(self) -> List[Any]:
        """Analyze potential edge cases in the current lineup."""
        if not self.current_lineup:
            return []
        
        try:
            return await self.hybrid_optimizer.analyze_edge_cases(
                self.current_lineup,
                self.available_players,
                self.session_context
            )
        except Exception as e:
            self.logger.error(f"Edge case analysis failed: {e}")
            return []
    
    async def adapt_strategy(
        self,
        market_conditions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Adapt strategy based on current market conditions."""
        try:
            return await self.hybrid_optimizer.adapt_strategy(
                self.current_strategy,
                market_conditions,
                self.session_context
            )
        except Exception as e:
            self.logger.error(f"Strategy adaptation failed: {e}")
            return {"adaptations": [], "reasoning": "Strategy adaptation failed"}
    
    def _detect_interaction_type(self, question: str) -> InteractionType:
        """Auto-detect the type of interaction from the question."""
        question_lower = question.lower()
        
        # Player substitution questions
        if any(phrase in question_lower for phrase in [
            "what if i use", "instead of", "replace", "substitute", "switch to"
        ]):
            return InteractionType.WHAT_IF_PLAYER
        
        # Strategy questions
        if any(phrase in question_lower for phrase in [
            "strategy", "approach", "optimize for", "focus on"
        ]):
            return InteractionType.WHAT_IF_STRATEGY
        
        # Constraint questions
        if any(phrase in question_lower for phrase in [
            "salary", "budget", "constraint", "limit"
        ]):
            return InteractionType.WHAT_IF_CONSTRAINTS
        
        # Explanation questions
        if any(phrase in question_lower for phrase in [
            "explain", "why", "reason", "rationale", "decision"
        ]):
            return InteractionType.EXPLAIN_DECISION
        
        # Comparison questions
        if any(phrase in question_lower for phrase in [
            "compare", "alternative", "different", "other options"
        ]):
            return InteractionType.COMPARE_ALTERNATIVES
        
        # Improvement questions
        if any(phrase in question_lower for phrase in [
            "improve", "better", "optimize", "enhance"
        ]):
            return InteractionType.SUGGEST_IMPROVEMENTS
        
        # Risk questions
        if any(phrase in question_lower for phrase in [
            "risk", "safe", "dangerous", "volatile"
        ]):
            return InteractionType.ANALYZE_RISK
        
        # Market questions
        if any(phrase in question_lower for phrase in [
            "market", "ownership", "popular", "contrarian"
        ]):
            return InteractionType.MARKET_ANALYSIS
        
        # Default to explanation
        return InteractionType.EXPLAIN_DECISION
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of the current session."""
        session_duration = (datetime.now() - self.session_stats['session_start_time']).total_seconds()
        
        return {
            "session_duration_minutes": session_duration / 60,
            "optimizations_performed": self.session_stats['optimizations_performed'],
            "interactions_handled": self.session_stats['interactions_handled'],
            "average_optimization_time": (
                self.session_stats['total_optimization_time'] / 
                max(1, self.session_stats['optimizations_performed'])
            ),
            "average_interaction_time": (
                self.session_stats['total_interaction_time'] / 
                max(1, self.session_stats['interactions_handled'])
            ),
            "current_strategy": self.current_strategy.value if self.current_strategy else None,
            "has_current_lineup": self.current_lineup is not None,
            "available_players_count": len(self.available_players),
            "llm_enabled": self.hybrid_optimizer.is_llm_available()
        }
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics."""
        optimizer_stats = self.hybrid_optimizer.get_performance_stats()
        interaction_stats = self.interaction_engine.get_interaction_stats()
        
        return {
            "optimizer_stats": optimizer_stats,
            "interaction_stats": interaction_stats,
            "session_stats": self.session_summary()
        }
    
    def clear_session(self):
        """Clear the current session state."""
        self.current_lineup = None
        self.available_players = []
        self.current_strategy = OptimizationStrategy.BALANCED
        self.current_constraints = None
        self.session_context = {}
        
        # Reset session stats
        self.session_stats = {
            'optimizations_performed': 0,
            'interactions_handled': 0,
            'session_start_time': datetime.now(),
            'total_optimization_time': 0.0,
            'total_interaction_time': 0.0
        }
        
        # Clear interaction history
        self.interaction_engine.clear_interaction_history()
        
        self.logger.info("Session cleared")
    
    def update_context(self, context_updates: Dict[str, Any]):
        """Update the session context with new information."""
        self.session_context.update(context_updates)
        self.logger.info(f"Context updated: {list(context_updates.keys())}")


# Convenience functions for easy integration
async def create_fantasy_assistant(
    llm_api_key: str,
    max_workers: int = None,
    enable_llm: bool = True
) -> FantasyFootballAssistant:
    """Create a new fantasy football assistant instance."""
    return FantasyFootballAssistant(
        llm_api_key=llm_api_key,
        max_workers=max_workers,
        enable_llm=enable_llm
    )


async def quick_optimize(
    players: List[Player],
    constraints: LineupConstraints,
    strategy: OptimizationStrategy = OptimizationStrategy.BALANCED,
    llm_api_key: str = None,
    context: Optional[Dict[str, Any]] = None
) -> HybridOptimizationResult:
    """
    Quick optimization function for one-off lineup optimization.
    
    Args:
        players: Available players for selection
        constraints: Lineup construction constraints
        strategy: Optimization strategy
        llm_api_key: OpenAI API key (required for LLM enhancement)
        context: Additional context
        
    Returns:
        HybridOptimizationResult with comprehensive analysis
    """
    assistant = await create_fantasy_assistant(
        llm_api_key=llm_api_key or "",
        enable_llm=llm_api_key is not None
    )
    
    return await assistant.optimize_lineup(
        players=players,
        constraints=constraints,
        strategy=strategy,
        context=context
    )


# Example usage and testing functions
async def example_usage():
    """Example of how to use the fantasy football assistant."""
    
    # This would be replaced with actual player data
    from ..models.player import Player, Position, Team
    from ..models.lineup import LineupConstraints
    
    # Create sample players (in real usage, these would come from your data sources)
    sample_players = [
        Player(
            id="1",
            name="Josh Allen",
            position=Position.QB,
            team=Team.BUF,
            season=2024,
            week=1
        ),
        # ... more players
    ]
    
    # Create constraints
    constraints = LineupConstraints(
        salary_cap=50000,
        position_requirements={
            "QB": 1,
            "RB": 2,
            "WR": 2,
            "TE": 1,
            "FLEX": 1,
            "K": 1,
            "DEF": 1
        }
    )
    
    # Create assistant (you would provide your actual API key)
    assistant = await create_fantasy_assistant(
        llm_api_key="your-api-key-here",
        enable_llm=True
    )
    
    # Optimize lineup
    result = await assistant.optimize_lineup(
        players=sample_players,
        constraints=constraints,
        strategy=OptimizationStrategy.BALANCED,
        context={"week": 1, "season": 2024, "contest_type": "GPP"}
    )
    
    print(f"Optimization completed with {result.overall_confidence:.2f} confidence")
    print(f"Recommendation strength: {result.recommendation_strength}")
    print(f"Explanation: {result.get_explanation()}")
    
    # Ask questions about the lineup
    response = await assistant.ask_question(
        "What if I use CMC instead of the current RB?"
    )
    print(f"Question response: {response.answer}")
    
    # Get alternatives
    alternatives = await assistant.suggest_alternatives()
    print(f"Found {len(alternatives)} alternatives")
    
    # Get session summary
    summary = assistant.get_session_summary()
    print(f"Session summary: {summary}")


if __name__ == "__main__":
    # Run example if executed directly
    asyncio.run(example_usage())