"""
User Interaction Engine for Fantasy Football Lineup Optimization.

This module provides interactive capabilities for users to explore different
scenarios, ask "what if" questions, and get dynamic lineup adjustments
with intelligent reasoning.
"""

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any, Union
from enum import Enum

from ..models.player import Player, Position
from ..models.lineup import Lineup, OptimizationStrategy, LineupConstraints
from .llm_enhancement import LLMEnhancementEngine, EnhancementContext
from .hybrid_optimizer import HybridLineupOptimizer

logger = logging.getLogger(__name__)


class InteractionType(str, Enum):
    """Types of user interactions supported."""
    WHAT_IF_PLAYER = "what_if_player"
    WHAT_IF_STRATEGY = "what_if_strategy"
    WHAT_IF_CONSTRAINTS = "what_if_constraints"
    EXPLAIN_DECISION = "explain_decision"
    COMPARE_ALTERNATIVES = "compare_alternatives"
    SUGGEST_IMPROVEMENTS = "suggest_improvements"
    ANALYZE_RISK = "analyze_risk"
    MARKET_ANALYSIS = "market_analysis"


class UserInteraction:
    """Represents a user interaction request."""
    
    def __init__(
        self,
        interaction_type: InteractionType,
        question: str,
        context: Dict[str, Any],
        current_lineup: Optional[Lineup] = None,
        available_players: Optional[List[Player]] = None
    ):
        self.interaction_type = interaction_type
        self.question = question
        self.context = context
        self.current_lineup = current_lineup
        self.available_players = available_players
        self.timestamp = datetime.now()


class InteractionResponse:
    """Response to a user interaction."""
    
    def __init__(
        self,
        answer: str,
        confidence: float,
        supporting_data: Dict[str, Any] = None,
        follow_up_questions: List[str] = None,
        actionable_insights: List[str] = None
    ):
        self.answer = answer
        self.confidence = confidence
        self.supporting_data = supporting_data or {}
        self.follow_up_questions = follow_up_questions or []
        self.actionable_insights = actionable_insights or []
        self.timestamp = datetime.now()


class UserInteractionEngine:
    """
    Engine for handling user interactions and dynamic lineup analysis.
    
    This engine allows users to explore different scenarios, ask questions,
    and get intelligent responses about lineup decisions and alternatives.
    """
    
    def __init__(self, hybrid_optimizer: HybridLineupOptimizer):
        """Initialize the user interaction engine."""
        self.hybrid_optimizer = hybrid_optimizer
        self.llm_engine = hybrid_optimizer.llm_engine
        self.logger = logging.getLogger(__name__)
        
        # Interaction history for context
        self.interaction_history: List[Tuple[UserInteraction, InteractionResponse]] = []
        
        # Performance tracking
        self.interaction_stats = {
            'total_interactions': 0,
            'successful_interactions': 0,
            'average_response_time': 0.0,
            'interaction_types': {}
        }
    
    async def handle_interaction(
        self,
        interaction: UserInteraction
    ) -> InteractionResponse:
        """
        Handle a user interaction and provide intelligent response.
        
        Args:
            interaction: User interaction request
            
        Returns:
            InteractionResponse with answer and insights
        """
        start_time = datetime.now()
        self.logger.info(f"Handling {interaction.interaction_type.value} interaction")
        
        try:
            # Route to appropriate handler
            if interaction.interaction_type == InteractionType.WHAT_IF_PLAYER:
                response = await self._handle_what_if_player(interaction)
            elif interaction.interaction_type == InteractionType.WHAT_IF_STRATEGY:
                response = await self._handle_what_if_strategy(interaction)
            elif interaction.interaction_type == InteractionType.WHAT_IF_CONSTRAINTS:
                response = await self._handle_what_if_constraints(interaction)
            elif interaction.interaction_type == InteractionType.EXPLAIN_DECISION:
                response = await self._handle_explain_decision(interaction)
            elif interaction.interaction_type == InteractionType.COMPARE_ALTERNATIVES:
                response = await self._handle_compare_alternatives(interaction)
            elif interaction.interaction_type == InteractionType.SUGGEST_IMPROVEMENTS:
                response = await self._handle_suggest_improvements(interaction)
            elif interaction.interaction_type == InteractionType.ANALYZE_RISK:
                response = await self._handle_analyze_risk(interaction)
            elif interaction.interaction_type == InteractionType.MARKET_ANALYSIS:
                response = await self._handle_market_analysis(interaction)
            else:
                response = InteractionResponse(
                    answer="I don't understand that type of interaction.",
                    confidence=0.0
                )
            
            # Store interaction in history
            self.interaction_history.append((interaction, response))
            
            # Update performance stats
            self._update_interaction_stats(start_time, True, interaction.interaction_type)
            
            return response
            
        except Exception as e:
            self.logger.error(f"Interaction handling failed: {e}")
            self._update_interaction_stats(start_time, False, interaction.interaction_type)
            
            return InteractionResponse(
                answer=f"I encountered an error processing your request: {str(e)}",
                confidence=0.0
            )
    
    async def _handle_what_if_player(self, interaction: UserInteraction) -> InteractionResponse:
        """Handle 'what if I use player X instead' scenarios."""
        
        if not interaction.current_lineup or not interaction.available_players:
            return InteractionResponse(
                answer="I need the current lineup and available players to analyze player substitutions.",
                confidence=0.0
            )
        
        # Extract player information from question
        player_name = self._extract_player_name_from_question(interaction.question)
        if not player_name:
            return InteractionResponse(
                answer="I couldn't identify which player you're asking about. Please specify the player name.",
                confidence=0.0
            )
        
        # Find the player
        target_player = None
        for player in interaction.available_players:
            if player_name.lower() in player.name.lower():
                target_player = player
                break
        
        if not target_player:
            return InteractionResponse(
                answer=f"I couldn't find a player named '{player_name}' in the available players.",
                confidence=0.0
            )
        
        # Analyze the substitution
        analysis = await self._analyze_player_substitution(
            interaction.current_lineup, target_player, interaction.available_players
        )
        
        return InteractionResponse(
            answer=analysis["answer"],
            confidence=analysis["confidence"],
            supporting_data=analysis["data"],
            follow_up_questions=analysis["follow_ups"],
            actionable_insights=analysis["insights"]
        )
    
    async def _handle_what_if_strategy(self, interaction: UserInteraction) -> InteractionResponse:
        """Handle 'what if I use a different strategy' scenarios."""
        
        # Extract strategy from question
        strategy_name = self._extract_strategy_from_question(interaction.question)
        if not strategy_name:
            return InteractionResponse(
                answer="I couldn't identify which strategy you're asking about. Please specify the strategy name.",
                confidence=0.0
            )
        
        # Find the strategy
        try:
            new_strategy = OptimizationStrategy(strategy_name)
        except ValueError:
            return InteractionResponse(
                answer=f"I don't recognize the strategy '{strategy_name}'. Available strategies are: {', '.join([s.value for s in OptimizationStrategy])}",
                confidence=0.0
            )
        
        # Analyze strategy change
        analysis = await self._analyze_strategy_change(
            interaction.current_lineup, new_strategy, interaction.available_players
        )
        
        return InteractionResponse(
            answer=analysis["answer"],
            confidence=analysis["confidence"],
            supporting_data=analysis["data"],
            follow_up_questions=analysis["follow_ups"],
            actionable_insights=analysis["insights"]
        )
    
    async def _handle_what_if_constraints(self, interaction: UserInteraction) -> InteractionResponse:
        """Handle 'what if I change constraints' scenarios."""
        
        # Extract constraint changes from question
        constraint_changes = self._extract_constraint_changes(interaction.question)
        if not constraint_changes:
            return InteractionResponse(
                answer="I couldn't identify what constraints you want to change. Please specify the constraint changes.",
                confidence=0.0
            )
        
        # Analyze constraint changes
        analysis = await self._analyze_constraint_changes(
            interaction.current_lineup, constraint_changes, interaction.available_players
        )
        
        return InteractionResponse(
            answer=analysis["answer"],
            confidence=analysis["confidence"],
            supporting_data=analysis["data"],
            follow_up_questions=analysis["follow_ups"],
            actionable_insights=analysis["insights"]
        )
    
    async def _handle_explain_decision(self, interaction: UserInteraction) -> InteractionResponse:
        """Handle requests to explain specific lineup decisions."""
        
        if not interaction.current_lineup:
            return InteractionResponse(
                answer="I need the current lineup to explain the decisions.",
                confidence=0.0
            )
        
        # Generate explanation
        explanation = await self.hybrid_optimizer.get_lineup_explanation(
            interaction.current_lineup,
            interaction.available_players or [],
            OptimizationStrategy.BALANCED,  # Default strategy
            interaction.context
        )
        
        return InteractionResponse(
            answer=explanation,
            confidence=0.8,
            supporting_data={"lineup": interaction.current_lineup.__dict__},
            follow_up_questions=[
                "Would you like me to suggest any improvements?",
                "Are there any specific players you'd like me to analyze?",
                "Would you like to see alternative lineup constructions?"
            ]
        )
    
    async def _handle_compare_alternatives(self, interaction: UserInteraction) -> InteractionResponse:
        """Handle requests to compare different lineup alternatives."""
        
        if not interaction.current_lineup or not interaction.available_players:
            return InteractionResponse(
                answer="I need the current lineup and available players to suggest alternatives.",
                confidence=0.0
            )
        
        # Get alternative suggestions
        alternatives = await self.hybrid_optimizer.suggest_alternatives(
            interaction.current_lineup,
            interaction.available_players,
            OptimizationStrategy.BALANCED,  # Default strategy
            interaction.context
        )
        
        if not alternatives:
            return InteractionResponse(
                answer="I couldn't generate any meaningful alternatives with the current data.",
                confidence=0.0
            )
        
        # Format comparison
        comparison_text = self._format_alternatives_comparison(alternatives, interaction.current_lineup)
        
        return InteractionResponse(
            answer=comparison_text,
            confidence=0.7,
            supporting_data={"alternatives": alternatives},
            follow_up_questions=[
                "Would you like me to explain any of these alternatives in more detail?",
                "Are there specific aspects of the alternatives you'd like me to analyze?"
            ]
        )
    
    async def _handle_suggest_improvements(self, interaction: UserInteraction) -> InteractionResponse:
        """Handle requests for lineup improvement suggestions."""
        
        if not interaction.current_lineup or not interaction.available_players:
            return InteractionResponse(
                answer="I need the current lineup and available players to suggest improvements.",
                confidence=0.0
            )
        
        # Analyze current lineup for improvement opportunities
        improvements = await self._analyze_improvement_opportunities(
            interaction.current_lineup, interaction.available_players
        )
        
        return InteractionResponse(
            answer=improvements["answer"],
            confidence=improvements["confidence"],
            supporting_data=improvements["data"],
            follow_up_questions=improvements["follow_ups"],
            actionable_insights=improvements["insights"]
        )
    
    async def _handle_analyze_risk(self, interaction: UserInteraction) -> InteractionResponse:
        """Handle requests for risk analysis."""
        
        if not interaction.current_lineup:
            return InteractionResponse(
                answer="I need the current lineup to analyze risk.",
                confidence=0.0
            )
        
        # Perform risk analysis
        risk_analysis = await self._perform_risk_analysis(interaction.current_lineup)
        
        return InteractionResponse(
            answer=risk_analysis["answer"],
            confidence=risk_analysis["confidence"],
            supporting_data=risk_analysis["data"],
            follow_up_questions=risk_analysis["follow_ups"],
            actionable_insights=risk_analysis["insights"]
        )
    
    async def _handle_market_analysis(self, interaction: UserInteraction) -> InteractionResponse:
        """Handle requests for market analysis."""
        
        if not interaction.current_lineup:
            return InteractionResponse(
                answer="I need the current lineup to analyze market conditions.",
                confidence=0.0
            )
        
        # Perform market analysis
        market_analysis = await self._perform_market_analysis(interaction.current_lineup)
        
        return InteractionResponse(
            answer=market_analysis["answer"],
            confidence=market_analysis["confidence"],
            supporting_data=market_analysis["data"],
            follow_up_questions=market_analysis["follow_ups"],
            actionable_insights=market_analysis["insights"]
        )
    
    def _extract_player_name_from_question(self, question: str) -> Optional[str]:
        """Extract player name from user question."""
        # Simple extraction - could be enhanced with NLP
        question_lower = question.lower()
        
        # Look for patterns like "what if I use [player]" or "instead of [player]"
        import re
        
        # Pattern 1: "what if I use [player]"
        match = re.search(r'what if i use (.+?)(?:\s|$)', question_lower)
        if match:
            return match.group(1).strip()
        
        # Pattern 2: "instead of [player]"
        match = re.search(r'instead of (.+?)(?:\s|$)', question_lower)
        if match:
            return match.group(1).strip()
        
        # Pattern 3: "replace [player]"
        match = re.search(r'replace (.+?)(?:\s|$)', question_lower)
        if match:
            return match.group(1).strip()
        
        return None
    
    def _extract_strategy_from_question(self, question: str) -> Optional[str]:
        """Extract strategy name from user question."""
        question_lower = question.lower()
        
        # Look for strategy names
        for strategy in OptimizationStrategy:
            if strategy.value.lower() in question_lower:
                return strategy.value
        
        return None
    
    def _extract_constraint_changes(self, question: str) -> Dict[str, Any]:
        """Extract constraint changes from user question."""
        # This would be enhanced with more sophisticated NLP
        changes = {}
        
        question_lower = question.lower()
        
        # Look for salary changes
        import re
        salary_match = re.search(r'salary.*?(\d+)', question_lower)
        if salary_match:
            changes['salary_cap'] = int(salary_match.group(1))
        
        # Look for ownership changes
        ownership_match = re.search(r'ownership.*?(\d+)', question_lower)
        if ownership_match:
            changes['max_ownership'] = int(ownership_match.group(1))
        
        return changes
    
    async def _analyze_player_substitution(
        self,
        current_lineup: Lineup,
        target_player: Player,
        available_players: List[Player]
    ) -> Dict[str, Any]:
        """Analyze the impact of substituting a player."""
        
        # Find which player would be replaced
        replacement_candidates = []
        for slot in current_lineup.slots:
            if (slot.player and 
                slot.position == target_player.position and
                slot.player.id != target_player.id):
                replacement_candidates.append(slot.player)
        
        if not replacement_candidates:
            return {
                "answer": f"{target_player.name} plays {target_player.position.value}, but there's no {target_player.position.value} in your current lineup to replace.",
                "confidence": 0.8,
                "data": {},
                "follow_ups": [],
                "insights": []
            }
        
        # Analyze the substitution
        current_player = replacement_candidates[0]  # Take first match
        
        # Calculate point difference
        current_points = current_player.get_best_projection() if hasattr(current_player, 'get_best_projection') else 0
        target_points = target_player.get_best_projection() if hasattr(target_player, 'get_best_projection') else 0
        point_diff = target_points - current_points
        
        # Generate analysis
        if point_diff > 0:
            answer = f"Substituting {target_player.name} for {current_player.name} would increase your projected points by {point_diff:.1f}. {target_player.name} has a higher projection ({target_points:.1f} vs {current_points:.1f})."
            confidence = 0.8
        elif point_diff < 0:
            answer = f"Substituting {target_player.name} for {current_player.name} would decrease your projected points by {abs(point_diff):.1f}. {current_player.name} has a higher projection ({current_points:.1f} vs {target_points:.1f})."
            confidence = 0.8
        else:
            answer = f"Substituting {target_player.name} for {current_player.name} would have minimal impact on projected points. Both players have similar projections."
            confidence = 0.6
        
        return {
            "answer": answer,
            "confidence": confidence,
            "data": {
                "current_player": current_player.name,
                "target_player": target_player.name,
                "point_difference": point_diff,
                "current_projection": current_points,
                "target_projection": target_points
            },
            "follow_ups": [
                "Would you like me to analyze the matchup implications?",
                "Should I consider the salary impact of this change?",
                "Are there other players you'd like me to compare?"
            ],
            "insights": [
                f"Point impact: {point_diff:+.1f}",
                f"Salary impact: ${getattr(target_player, 'salary', 0) - getattr(current_player, 'salary', 0):+d}"
            ]
        }
    
    async def _analyze_strategy_change(
        self,
        current_lineup: Lineup,
        new_strategy: OptimizationStrategy,
        available_players: List[Player]
    ) -> Dict[str, Any]:
        """Analyze the impact of changing strategy."""
        
        # This would involve re-optimizing with the new strategy
        # For now, provide a conceptual analysis
        
        answer = f"Changing to a {new_strategy.value} strategy would shift the optimization focus. This strategy typically emphasizes different factors in player selection."
        confidence = 0.6
        
        return {
            "answer": answer,
            "confidence": confidence,
            "data": {"new_strategy": new_strategy.value},
            "follow_ups": [
                "Would you like me to re-optimize the lineup with this strategy?",
                "Should I explain the key differences between strategies?"
            ],
            "insights": [
                f"Strategy change to: {new_strategy.value}",
                "Consider re-optimizing for best results"
            ]
        }
    
    async def _analyze_constraint_changes(
        self,
        current_lineup: Lineup,
        constraint_changes: Dict[str, Any],
        available_players: List[Player]
    ) -> Dict[str, Any]:
        """Analyze the impact of changing constraints."""
        
        changes_text = []
        for key, value in constraint_changes.items():
            changes_text.append(f"{key}: {value}")
        
        answer = f"Changing constraints ({', '.join(changes_text)}) would affect lineup construction. The current lineup may no longer be optimal under these new constraints."
        confidence = 0.7
        
        return {
            "answer": answer,
            "confidence": confidence,
            "data": {"constraint_changes": constraint_changes},
            "follow_ups": [
                "Would you like me to re-optimize with these new constraints?",
                "Should I analyze the impact on each position?"
            ],
            "insights": [
                "Constraint changes may require re-optimization",
                "Current lineup validity needs verification"
            ]
        }
    
    def _format_alternatives_comparison(
        self,
        alternatives: List[Dict[str, Any]],
        current_lineup: Lineup
    ) -> str:
        """Format alternatives comparison for user."""
        
        comparison = "Here are some alternative lineup constructions:\n\n"
        
        for i, alt in enumerate(alternatives[:3], 1):  # Show top 3
            comparison += f"**Alternative {i}:**\n"
            comparison += f"Reason: {alt.get('reason', 'N/A')}\n"
            comparison += f"Point difference: {alt.get('point_difference', 0):+.1f}\n"
            comparison += f"Confidence: {alt.get('confidence', 0):.1f}\n\n"
        
        return comparison
    
    async def _analyze_improvement_opportunities(
        self,
        current_lineup: Lineup,
        available_players: List[Player]
    ) -> Dict[str, Any]:
        """Analyze opportunities for lineup improvement."""
        
        # Find potential improvements
        improvements = []
        
        # Check for low-projection players
        for slot in current_lineup.slots:
            if slot.player:
                current_proj = slot.player.get_best_projection() if hasattr(slot.player, 'get_best_projection') else 0
                
                # Find better alternatives
                better_players = [
                    p for p in available_players
                    if (p.position == slot.position and 
                        p.id != slot.player.id and
                        p.get_best_projection() > current_proj)
                ]
                
                if better_players:
                    best_alt = max(better_players, key=lambda x: x.get_best_projection())
                    improvement = best_alt.get_best_projection() - current_proj
                    improvements.append({
                        "position": slot.position.value,
                        "current_player": slot.player.name,
                        "better_player": best_alt.name,
                        "improvement": improvement
                    })
        
        if improvements:
            answer = f"I found {len(improvements)} potential improvements. The biggest opportunity is replacing {improvements[0]['current_player']} with {improvements[0]['better_player']} for a {improvements[0]['improvement']:.1f} point gain."
            confidence = 0.8
        else:
            answer = "Your current lineup appears to be well-optimized. I don't see any obvious improvement opportunities with the available players."
            confidence = 0.6
        
        return {
            "answer": answer,
            "confidence": confidence,
            "data": {"improvements": improvements},
            "follow_ups": [
                "Would you like me to show the complete improved lineup?",
                "Should I analyze the risk implications of these changes?"
            ],
            "insights": [f"Found {len(improvements)} improvement opportunities"]
        }
    
    async def _perform_risk_analysis(self, current_lineup: Lineup) -> Dict[str, Any]:
        """Perform comprehensive risk analysis."""
        
        # Analyze various risk factors
        risk_factors = []
        
        # Check for injury risks
        injured_players = [slot.player for slot in current_lineup.slots 
                          if slot.player and slot.player.is_injured()]
        if injured_players:
            risk_factors.append(f"Injury concerns: {len(injured_players)} players")
        
        # Check for high-variance players
        high_variance = []
        for slot in current_lineup.slots:
            if slot.player and hasattr(slot.player, 'consistency_score'):
                if slot.player.consistency_score < 0.4:
                    high_variance.append(slot.player.name)
        
        if high_variance:
            risk_factors.append(f"High-variance players: {', '.join(high_variance)}")
        
        # Check for ownership concentration
        high_owned = [slot.player for slot in current_lineup.slots
                     if (slot.player and 
                         slot.player.value_metrics and
                         slot.player.value_metrics.projected_ownership and
                         slot.player.value_metrics.projected_ownership > 30)]
        
        if len(high_owned) >= 4:
            risk_factors.append("High ownership concentration (4+ players >30%)")
        
        # Generate risk assessment
        if len(risk_factors) == 0:
            answer = "Your lineup has a low risk profile. No major risk factors identified."
            confidence = 0.8
        elif len(risk_factors) <= 2:
            answer = f"Your lineup has moderate risk. Key concerns: {'; '.join(risk_factors)}"
            confidence = 0.7
        else:
            answer = f"Your lineup has high risk. Multiple concerns: {'; '.join(risk_factors)}"
            confidence = 0.8
        
        return {
            "answer": answer,
            "confidence": confidence,
            "data": {"risk_factors": risk_factors},
            "follow_ups": [
                "Would you like me to suggest risk mitigation strategies?",
                "Should I analyze the upside potential to balance the risk?"
            ],
            "insights": [f"Identified {len(risk_factors)} risk factors"]
        }
    
    async def _perform_market_analysis(self, current_lineup: Lineup) -> Dict[str, Any]:
        """Perform market analysis of the lineup."""
        
        # Analyze ownership patterns
        ownership_analysis = []
        total_ownership = 0
        ownership_count = 0
        
        for slot in current_lineup.slots:
            if (slot.player and 
                slot.player.value_metrics and
                slot.player.value_metrics.projected_ownership):
                ownership = slot.player.value_metrics.projected_ownership
                total_ownership += ownership
                ownership_count += 1
                
                if ownership > 40:
                    ownership_analysis.append(f"{slot.player.name}: {ownership:.1f}% (High)")
                elif ownership < 10:
                    ownership_analysis.append(f"{slot.player.name}: {ownership:.1f}% (Low)")
        
        avg_ownership = total_ownership / ownership_count if ownership_count > 0 else 0
        
        # Generate market analysis
        if avg_ownership > 30:
            market_profile = "High ownership (chalky)"
            leverage = "Limited differentiation potential"
        elif avg_ownership < 15:
            market_profile = "Low ownership (contrarian)"
            leverage = "High differentiation potential"
        else:
            market_profile = "Balanced ownership"
            leverage = "Moderate differentiation potential"
        
        answer = f"Your lineup has a {market_profile} profile with an average ownership of {avg_ownership:.1f}%. {leverage}."
        confidence = 0.7
        
        return {
            "answer": answer,
            "confidence": confidence,
            "data": {
                "average_ownership": avg_ownership,
                "market_profile": market_profile,
                "ownership_breakdown": ownership_analysis
            },
            "follow_ups": [
                "Would you like me to suggest more contrarian alternatives?",
                "Should I analyze the leverage opportunities?"
            ],
            "insights": [f"Average ownership: {avg_ownership:.1f}%", f"Profile: {market_profile}"]
        }
    
    def _update_interaction_stats(
        self,
        start_time: datetime,
        success: bool,
        interaction_type: InteractionType
    ):
        """Update interaction performance statistics."""
        duration = (datetime.now() - start_time).total_seconds()
        
        self.interaction_stats['total_interactions'] += 1
        if success:
            self.interaction_stats['successful_interactions'] += 1
        
        # Update interaction type counts
        type_key = interaction_type.value
        self.interaction_stats['interaction_types'][type_key] = (
            self.interaction_stats['interaction_types'].get(type_key, 0) + 1
        )
        
        # Update average response time
        total = self.interaction_stats['total_interactions']
        current_avg = self.interaction_stats['average_response_time']
        self.interaction_stats['average_response_time'] = (
            (current_avg * (total - 1) + duration) / total
        )
    
    def get_interaction_history(self) -> List[Tuple[UserInteraction, InteractionResponse]]:
        """Get the history of user interactions."""
        return self.interaction_history.copy()
    
    def get_interaction_stats(self) -> Dict[str, Any]:
        """Get interaction performance statistics."""
        stats = self.interaction_stats.copy()
        
        if stats['total_interactions'] > 0:
            stats['success_rate'] = stats['successful_interactions'] / stats['total_interactions']
        else:
            stats['success_rate'] = 0.0
        
        return stats
    
    def clear_interaction_history(self):
        """Clear the interaction history."""
        self.interaction_history.clear()
        self.logger.info("Interaction history cleared")


# Convenience functions for easy interaction handling
async def ask_what_if_player(
    interaction_engine: UserInteractionEngine,
    question: str,
    current_lineup: Lineup,
    available_players: List[Player],
    context: Dict[str, Any] = None
) -> InteractionResponse:
    """Convenience function for 'what if player' questions."""
    interaction = UserInteraction(
        interaction_type=InteractionType.WHAT_IF_PLAYER,
        question=question,
        context=context or {},
        current_lineup=current_lineup,
        available_players=available_players
    )
    
    return await interaction_engine.handle_interaction(interaction)


async def explain_lineup_decision(
    interaction_engine: UserInteractionEngine,
    current_lineup: Lineup,
    available_players: List[Player],
    context: Dict[str, Any] = None
) -> InteractionResponse:
    """Convenience function for explaining lineup decisions."""
    interaction = UserInteraction(
        interaction_type=InteractionType.EXPLAIN_DECISION,
        question="Explain the lineup decisions",
        context=context or {},
        current_lineup=current_lineup,
        available_players=available_players
    )
    
    return await interaction_engine.handle_interaction(interaction)