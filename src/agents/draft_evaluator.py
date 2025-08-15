"""
Draft Evaluation Agent for Fantasy Football MCP Server.

This module implements the core draft evaluation logic using advanced statistical
analysis to recommend optimal draft picks during live fantasy football drafts.
"""

import asyncio
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import asdict
import statistics

from loguru import logger

from models.draft import (
    DraftStrategy, DraftAnalysis, DraftRecommendation, DraftState, DraftTier,
    PlayerEvaluation, RosterNeed, PositionalNeed, PositionalRun, OpportunityCost,
    StrategyWeights, STRATEGY_WEIGHTS, STANDARD_ROSTER_REQUIREMENTS, FLEX_POSITIONS,
    POSITION_INJURY_RISK, AGE_RISK_THRESHOLDS, DraftPosition
)
from models.player import Player, Position
from .data_fetcher import DataFetcherAgent
from .cache_manager import CacheManager
from config.settings import Settings


class DraftEvaluatorAgent:
    """
    Advanced draft evaluation agent that provides real-time draft recommendations
    using multi-factor statistical analysis.
    """
    
    def __init__(self, settings: Settings, cache_manager: CacheManager, data_fetcher: DataFetcherAgent):
        """Initialize the draft evaluator with required dependencies."""
        self.settings = settings
        self.cache_manager = cache_manager
        self.data_fetcher = data_fetcher
        
        # Draft evaluation parameters
        self.replacement_level_cache: Dict[Position, float] = {}
        self.adp_data: Dict[str, float] = {}
        self.tier_boundaries: Dict[Position, List[float]] = {}
        
        logger.info("Draft Evaluator Agent initialized")
    
    async def get_draft_recommendation(
        self, 
        league_key: str, 
        strategy: DraftStrategy = DraftStrategy.BALANCED,
        num_recommendations: int = 10,
        current_pick: Optional[int] = None
    ) -> DraftAnalysis:
        """
        Get the top draft recommendations for the current draft state.
        
        Args:
            league_key: Yahoo league identifier
            strategy: Draft strategy to apply
            num_recommendations: Number of top recommendations to return
            current_pick: Current overall pick number (if known)
            
        Returns:
            DraftAnalysis with top recommendations and insights
        """
        try:
            # Build current draft state
            draft_state = await self._build_draft_state(league_key, strategy, current_pick)
            
            # Get available players and current roster
            available_players = await self.data_fetcher.get_available_players(league_key)
            current_roster = await self._get_current_roster(league_key)
            
            # Evaluate all available players
            evaluations = await self._evaluate_available_players(
                available_players, draft_state, current_roster
            )
            
            # Sort by overall score and take top N
            top_evaluations = sorted(evaluations, key=lambda x: x.overall_score, reverse=True)[:num_recommendations]
            
            # Convert to recommendations
            recommendations = [
                await self._create_recommendation(eval_data, idx + 1) 
                for idx, eval_data in enumerate(top_evaluations)
            ]
            
            # Generate strategic insights
            insights = await self._generate_strategic_insights(draft_state, recommendations)
            
            return DraftAnalysis(
                draft_state=draft_state,
                top_recommendations=recommendations,
                key_insights=insights['key_insights'],
                positional_priorities=insights['positional_priorities'],
                risk_factors=insights['risk_factors'],
                strategy_weights=asdict(STRATEGY_WEIGHTS[strategy])
            )
            
        except Exception as e:
            logger.error(f"Failed to get draft recommendation for league {league_key}: {e}")
            raise
    
    async def analyze_draft_state(
        self, 
        league_key: str, 
        strategy: DraftStrategy = DraftStrategy.BALANCED
    ) -> Dict[str, Any]:
        """
        Analyze the current draft state and roster needs.
        
        Args:
            league_key: Yahoo league identifier  
            strategy: Draft strategy for analysis
            
        Returns:
            Comprehensive draft state analysis
        """
        try:
            draft_state = await self._build_draft_state(league_key, strategy)
            current_roster = await self._get_current_roster(league_key)
            
            analysis = {
                "roster_summary": await self._analyze_roster_composition(current_roster),
                "positional_needs": [asdict(need) for need in draft_state.roster_needs],
                "bye_week_analysis": self._analyze_bye_weeks(current_roster),
                "draft_phase": draft_state.draft_phase,
                "strategic_recommendations": await self._get_phase_strategy_recommendations(draft_state),
                "positional_runs": [asdict(run) for run in draft_state.positional_runs]
            }
            
            return {
                "status": "success",
                "league_key": league_key,
                "analysis": analysis,
                "strategy": strategy.value
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze draft state for league {league_key}: {e}")
            return {
                "status": "error", 
                "error": str(e)
            }
    
    async def _build_draft_state(
        self, 
        league_key: str, 
        strategy: DraftStrategy,
        current_pick: Optional[int] = None
    ) -> DraftState:
        """Build comprehensive draft state from available data."""
        
        # Get league info to understand draft setup
        league_info = await self.data_fetcher.get_league_info(league_key)
        current_roster = await self._get_current_roster(league_key)
        
        # Determine draft position (mock if not available)
        if current_pick:
            draft_pos = self._calculate_draft_position(current_pick, league_info.get('num_teams', 12))
        else:
            draft_pos = DraftPosition(
                overall_pick=len(current_roster) + 1,
                round_number=math.ceil((len(current_roster) + 1) / league_info.get('num_teams', 12)),
                pick_in_round=((len(current_roster)) % league_info.get('num_teams', 12)) + 1,
                picks_until_next=league_info.get('num_teams', 12) - 1  # Assume snake draft
            )
        
        # Analyze roster needs
        roster_needs = await self._analyze_roster_needs(current_roster)
        
        # Detect positional runs (mock for now - would need recent draft picks)
        positional_runs = await self._detect_positional_runs(league_key)
        
        # Determine draft phase
        draft_phase = self._determine_draft_phase(draft_pos.round_number)
        
        return DraftState(
            league_key=league_key,
            draft_position=draft_pos,
            current_roster=[self._player_to_dict(p) for p in current_roster],
            roster_needs=roster_needs,
            bye_week_distribution=self._analyze_bye_weeks(current_roster),
            picks_remaining=16 - draft_pos.round_number,  # Assume 16 round draft
            strategy=strategy,
            positional_runs=positional_runs,
            draft_phase=draft_phase
        )
    
    async def _evaluate_available_players(
        self, 
        available_players: List[Player], 
        draft_state: DraftState, 
        current_roster: List[Player]
    ) -> List[PlayerEvaluation]:
        """Evaluate all available players using multi-factor analysis."""
        
        strategy_weights = STRATEGY_WEIGHTS[draft_state.strategy]
        evaluations = []
        
        # Calculate replacement levels for all positions
        await self._calculate_replacement_levels(available_players)
        
        for player in available_players[:200]:  # Limit to top 200 for performance
            try:
                eval_data = await self._evaluate_single_player(
                    player, draft_state, current_roster, strategy_weights
                )
                evaluations.append(eval_data)
            except Exception as e:
                logger.warning(f"Failed to evaluate player {player.name}: {e}")
                continue
        
        return evaluations
    
    async def _evaluate_single_player(
        self, 
        player: Player, 
        draft_state: DraftState, 
        current_roster: List[Player],
        strategy_weights: StrategyWeights
    ) -> PlayerEvaluation:
        """Perform comprehensive evaluation of a single player."""
        
        # Core calculations
        vorp_score = await self._calculate_vorp(player)
        scarcity_score = await self._calculate_positional_scarcity(player, draft_state)
        need_score = self._calculate_roster_need_score(player, draft_state.roster_needs)
        bye_week_score = self._calculate_bye_week_score(player, current_roster)
        risk_score = self._calculate_risk_score(player)
        upside_score = self._calculate_upside_score(player)
        
        # Apply strategy weights
        overall_score = (
            (vorp_score * strategy_weights.vorp) +
            (scarcity_score * strategy_weights.scarcity) +
            (need_score * strategy_weights.need) +
            (bye_week_score * strategy_weights.bye_week) +
            (risk_score * strategy_weights.risk) +
            (upside_score * strategy_weights.upside)
        )
        
        # Determine tier
        tier = self._determine_player_tier(player, overall_score)
        
        return PlayerEvaluation(
            player=player,
            overall_score=max(0, min(100, overall_score)),  # Clamp to 0-100
            vorp_score=vorp_score,
            scarcity_score=scarcity_score,
            need_score=need_score,
            bye_week_score=bye_week_score,
            risk_score=risk_score,
            upside_score=upside_score,
            tier=tier,
            projected_points=getattr(player, 'projected_points', None),
            replacement_level=self.replacement_level_cache.get(player.position, 0)
        )
    
    async def _calculate_vorp(self, player: Player) -> float:
        """Calculate Value Over Replacement Player score."""
        projected_points = getattr(player, 'projected_points', 0)
        replacement_level = self.replacement_level_cache.get(player.position, 0)
        
        vorp = max(0, projected_points - replacement_level)
        
        # Normalize to 0-100 scale (assuming max VORP is around 100 points)
        return min(100, (vorp / 100) * 100)
    
    async def _calculate_positional_scarcity(self, player: Player, draft_state: DraftState) -> float:
        """Calculate positional scarcity score based on remaining quality players."""
        
        # Find positional need for this player
        position_need = None
        for need in draft_state.roster_needs:
            if need.position == player.position:
                position_need = need
                break
        
        if not position_need:
            return 50  # Neutral if position not found
        
        # Base scarcity on need level
        need_multipliers = {
            PositionalNeed.CRITICAL: 100,
            PositionalNeed.HIGH: 80,
            PositionalNeed.MEDIUM: 60,
            PositionalNeed.LOW: 30,
            PositionalNeed.SATURATED: 10
        }
        
        base_scarcity = need_multipliers[position_need.need_level]
        
        # Adjust for draft position (scarcity increases in later rounds)
        draft_round = draft_state.draft_position.round_number
        round_multiplier = 1 + (draft_round - 1) * 0.1  # 10% increase per round
        
        return min(100, base_scarcity * round_multiplier)
    
    def _calculate_roster_need_score(self, player: Player, roster_needs: List[RosterNeed]) -> float:
        """Calculate how much the team needs this player's position."""
        
        for need in roster_needs:
            if need.position == player.position:
                need_scores = {
                    PositionalNeed.CRITICAL: 100,
                    PositionalNeed.HIGH: 75,
                    PositionalNeed.MEDIUM: 50,
                    PositionalNeed.LOW: 25,
                    PositionalNeed.SATURATED: 0
                }
                
                base_score = need_scores[need.need_level]
                
                # Bonus for bye week conflicts (need extra depth)
                bye_bonus = min(20, need.bye_week_conflicts * 5)
                
                return min(100, base_score + bye_bonus)
        
        return 50  # Default neutral score
    
    def _calculate_bye_week_score(self, player: Player, current_roster: List[Player]) -> float:
        """Calculate penalty/bonus for bye week distribution."""
        
        player_bye = getattr(player, 'bye_week', None)
        if not player_bye:
            return 0
        
        # Count existing players with same bye week
        bye_conflicts = sum(1 for p in current_roster if getattr(p, 'bye_week', None) == player_bye)
        
        if bye_conflicts >= 3:
            return -20  # Heavy penalty
        elif bye_conflicts == 2:
            return -10  # Moderate penalty  
        elif bye_conflicts == 1:
            return -5   # Light penalty
        else:
            return 0    # No penalty
    
    def _calculate_risk_score(self, player: Player) -> float:
        """Calculate injury and performance risk score."""
        
        risk_factors = []
        
        # Age risk
        age = getattr(player, 'age', 28)
        age_threshold = AGE_RISK_THRESHOLDS.get(player.position, 32)
        if age_threshold and age > age_threshold:
            age_penalty = (age - age_threshold) * -3
            risk_factors.append(age_penalty)
        
        # Injury history risk  
        games_missed = getattr(player, 'games_missed_last_2_years', 0)
        injury_penalty = games_missed * -2
        risk_factors.append(injury_penalty)
        
        # Position-based injury risk
        position_risk = POSITION_INJURY_RISK.get(player.position, 1.0)
        position_penalty = (position_risk - 1.0) * -10
        risk_factors.append(position_penalty)
        
        # Current injury status
        injury_status = getattr(player, 'injury_status', None)
        if injury_status in ['questionable', 'doubtful']:
            risk_factors.append(-15)
        elif injury_status == 'out':
            risk_factors.append(-30)
        
        total_risk = sum(risk_factors)
        
        # Convert to positive score (lower risk = higher score)
        return max(0, min(100, 50 - total_risk))
    
    def _calculate_upside_score(self, player: Player) -> float:
        """Calculate ceiling/upside potential score."""
        
        # For now, use simple heuristics
        upside_factors = []
        
        # Young player bonus (more upside potential)
        age = getattr(player, 'age', 28) 
        if age < 25:
            upside_factors.append(20)
        elif age < 27:
            upside_factors.append(10)
        
        # High volatility can mean high upside
        volatility = getattr(player, 'volatility', 0.5)
        if volatility > 0.7:
            upside_factors.append(15)
        elif volatility > 0.6:
            upside_factors.append(10)
        
        # Breakout candidate indicators (would need more sophisticated analysis)
        # For now, assume newer players have more upside
        years_pro = getattr(player, 'years_pro', 5)
        if years_pro <= 2:
            upside_factors.append(15)
        elif years_pro <= 3:
            upside_factors.append(10)
        
        return min(100, sum(upside_factors))
    
    def _determine_player_tier(self, player: Player, overall_score: float) -> DraftTier:
        """Assign player to a tier based on overall score."""
        
        if overall_score >= 85:
            return DraftTier.ELITE
        elif overall_score >= 70:
            return DraftTier.STUD  
        elif overall_score >= 55:
            return DraftTier.SOLID
        elif overall_score >= 40:
            return DraftTier.FLEX
        else:
            return DraftTier.BENCH
    
    async def _calculate_replacement_levels(self, available_players: List[Player]) -> None:
        """Calculate replacement level values for each position."""
        
        position_players = {}
        for player in available_players:
            if player.position not in position_players:
                position_players[player.position] = []
            position_players[player.position].append(getattr(player, 'projected_points', 0))
        
        for position, point_projections in position_players.items():
            if not point_projections:
                self.replacement_level_cache[position] = 0
                continue
                
            # Sort descending
            sorted_projections = sorted(point_projections, reverse=True)
            
            # Replacement level is roughly the 24th best player at skill positions
            # Adjust based on typical starter requirements
            replacement_indices = {
                Position.QB: 12,   # 12th best QB
                Position.RB: 24,  # 24th best RB  
                Position.WR: 30,  # 30th best WR
                Position.TE: 12,  # 12th best TE
                Position.K: 12,   # 12th best K
                Position.DST: 12  # 12th best DST
            }
            
            replacement_idx = replacement_indices.get(position, 24)
            replacement_idx = min(replacement_idx, len(sorted_projections) - 1)
            
            self.replacement_level_cache[position] = sorted_projections[replacement_idx]
    
    async def _analyze_roster_needs(self, current_roster: List[Player]) -> List[RosterNeed]:
        """Analyze current roster to determine positional needs."""
        
        position_counts = {}
        bye_week_counts = {}
        
        for player in current_roster:
            pos = player.position
            position_counts[pos] = position_counts.get(pos, 0) + 1
            
            bye_week = getattr(player, 'bye_week', None)
            if bye_week:
                if pos not in bye_week_counts:
                    bye_week_counts[pos] = {}
                bye_week_counts[pos][bye_week] = bye_week_counts[pos].get(bye_week, 0) + 1
        
        roster_needs = []
        
        for position, requirements in STANDARD_ROSTER_REQUIREMENTS.items():
            current_count = position_counts.get(position, 0)
            optimal_count = requirements['optimal_total']
            starter_slots = requirements['starters']
            
            # Determine need level
            if current_count == 0:
                need_level = PositionalNeed.CRITICAL
            elif current_count < starter_slots:
                need_level = PositionalNeed.HIGH
            elif current_count < optimal_count:
                need_level = PositionalNeed.MEDIUM
            elif current_count < requirements['max_useful']:
                need_level = PositionalNeed.LOW
            else:
                need_level = PositionalNeed.SATURATED
            
            # Calculate bye week conflicts
            bye_conflicts = 0
            if position in bye_week_counts:
                for bye_week, count in bye_week_counts[position].items():
                    if count >= 2:  # 2+ players with same bye = conflict
                        bye_conflicts += count - 1
            
            roster_needs.append(RosterNeed(
                position=position,
                need_level=need_level,
                current_count=current_count,
                optimal_count=optimal_count,
                starter_slots=starter_slots,
                bye_week_conflicts=bye_conflicts
            ))
        
        return roster_needs
    
    def _analyze_bye_weeks(self, current_roster: List[Player]) -> Dict[int, int]:
        """Analyze bye week distribution in current roster."""
        
        bye_week_counts = {}
        for player in current_roster:
            bye_week = getattr(player, 'bye_week', None)
            if bye_week:
                bye_week_counts[bye_week] = bye_week_counts.get(bye_week, 0) + 1
        
        return bye_week_counts
    
    def _calculate_draft_position(self, overall_pick: int, num_teams: int) -> DraftPosition:
        """Calculate draft position information from overall pick."""
        
        round_number = math.ceil(overall_pick / num_teams)
        
        if round_number % 2 == 1:  # Odd round
            pick_in_round = ((overall_pick - 1) % num_teams) + 1
            picks_until_next = (2 * num_teams) - pick_in_round
        else:  # Even round (snake)
            pick_in_round = num_teams - ((overall_pick - 1) % num_teams)  
            picks_until_next = pick_in_round - 1 + num_teams
        
        return DraftPosition(
            overall_pick=overall_pick,
            round_number=round_number,
            pick_in_round=pick_in_round,
            picks_until_next=picks_until_next,
            is_snake_draft=True
        )
    
    def _determine_draft_phase(self, round_number: int) -> str:
        """Determine what phase of the draft we're in."""
        
        if round_number <= 3:
            return "early"
        elif round_number <= 8:
            return "middle"
        else:
            return "late"
    
    async def _detect_positional_runs(self, league_key: str) -> List[PositionalRun]:
        """Detect if any positions are being drafted heavily (mock implementation)."""
        
        # This would require access to recent draft picks from other teams
        # For now, return empty list
        # In a real implementation, you'd analyze the last 6-10 picks
        
        return []
    
    async def _get_current_roster(self, league_key: str) -> List[Player]:
        """Get the current roster for the user's team."""
        
        try:
            roster_data = await self.data_fetcher.get_roster(league_key)
            return roster_data.get('players', [])
        except Exception as e:
            logger.warning(f"Could not fetch current roster for league {league_key}: {e}")
            return []
    
    async def _create_recommendation(self, evaluation: PlayerEvaluation, rank: int) -> DraftRecommendation:
        """Convert PlayerEvaluation to DraftRecommendation."""
        
        # Generate reasoning text
        reasoning_parts = []
        
        if evaluation.vorp_score > 70:
            reasoning_parts.append(f"Elite VORP ({evaluation.vorp_score:.1f})")
        elif evaluation.vorp_score > 50:
            reasoning_parts.append(f"Strong VORP ({evaluation.vorp_score:.1f})")
        
        if evaluation.need_score > 75:
            reasoning_parts.append("Critical positional need")
        elif evaluation.need_score > 50:
            reasoning_parts.append("Addresses roster need")
        
        if evaluation.risk_score < 40:
            reasoning_parts.append("Higher injury risk")
        elif evaluation.risk_score > 70:
            reasoning_parts.append("Low injury risk")
        
        if evaluation.upside_score > 60:
            reasoning_parts.append("High upside potential")
        
        reasoning = ", ".join(reasoning_parts) if reasoning_parts else "Solid value pick"
        
        return DraftRecommendation(
            player=self._player_to_dict(evaluation.player),
            overall_score=evaluation.overall_score,
            rank=rank,
            tier=evaluation.tier,
            vorp_score=evaluation.vorp_score,
            scarcity_score=evaluation.scarcity_score, 
            need_score=evaluation.need_score,
            bye_week_score=evaluation.bye_week_score,
            risk_score=evaluation.risk_score,
            upside_score=evaluation.upside_score,
            projected_points=evaluation.projected_points,
            reasoning=reasoning
        )
    
    def _player_to_dict(self, player: Player) -> Dict[str, Any]:
        """Convert Player object to dictionary representation."""
        
        return {
            "name": player.name,
            "position": player.position.value if hasattr(player.position, 'value') else str(player.position),
            "team": player.team.value if hasattr(player.team, 'value') else str(player.team),
            "player_id": getattr(player, 'player_id', None),
            "bye_week": getattr(player, 'bye_week', None),
            "projected_points": getattr(player, 'projected_points', None),
            "age": getattr(player, 'age', None)
        }
    
    async def _generate_strategic_insights(
        self, 
        draft_state: DraftState, 
        recommendations: List[DraftRecommendation]
    ) -> Dict[str, Any]:
        """Generate strategic insights and analysis."""
        
        insights = {
            "key_insights": [],
            "positional_priorities": {},
            "risk_factors": []
        }
        
        # Key insights based on draft phase
        if draft_state.draft_phase == "early":
            insights["key_insights"].append("Early draft: Prioritize best player available and elite tier players")
        elif draft_state.draft_phase == "middle": 
            insights["key_insights"].append("Mid draft: Balance positional needs with player value")
        else:
            insights["key_insights"].append("Late draft: Focus on upside players and bye week management")
        
        # Positional priority analysis
        critical_needs = [need for need in draft_state.roster_needs if need.need_level == PositionalNeed.CRITICAL]
        if critical_needs:
            positions = [str(need.position.value) for need in critical_needs]
            insights["key_insights"].append(f"Critical needs: {', '.join(positions)}")
        
        # Calculate positional priorities
        for need in draft_state.roster_needs:
            priority_scores = {
                PositionalNeed.CRITICAL: 100,
                PositionalNeed.HIGH: 75,
                PositionalNeed.MEDIUM: 50,
                PositionalNeed.LOW: 25,
                PositionalNeed.SATURATED: 10
            }
            insights["positional_priorities"][str(need.position.value)] = priority_scores[need.need_level]
        
        # Risk factors
        if draft_state.picks_remaining <= 3:
            insights["risk_factors"].append("Running out of picks - avoid risky players")
        
        if any(len(conflicts) >= 3 for conflicts in draft_state.bye_week_distribution.values()):
            insights["risk_factors"].append("Bye week clustering detected - diversify bye weeks")
        
        return insights
    
    async def _get_phase_strategy_recommendations(self, draft_state: DraftState) -> List[str]:
        """Get strategy recommendations based on draft phase."""
        
        recommendations = []
        
        if draft_state.draft_phase == "early":
            recommendations.append("Target tier 1 and tier 2 players regardless of position")
            recommendations.append("Don't reach for positional needs yet") 
            recommendations.append("Consider QB early if elite option available")
        
        elif draft_state.draft_phase == "middle":
            recommendations.append("Start addressing critical positional needs")
            recommendations.append("Look for value players that fell in tier")
            recommendations.append("Consider stacking strategy if applicable")
        
        else:  # late draft
            recommendations.append("Prioritize high-upside players over safe floors")
            recommendations.append("Target handcuffs for your key players") 
            recommendations.append("Stream K/DST - don't draft too early")
        
        return recommendations
    
    async def _analyze_roster_composition(self, current_roster: List[Player]) -> Dict[str, Any]:
        """Analyze current roster composition."""
        
        position_counts = {}
        total_projected = 0
        
        for player in current_roster:
            pos = str(player.position.value) if hasattr(player.position, 'value') else str(player.position)
            position_counts[pos] = position_counts.get(pos, 0) + 1
            total_projected += getattr(player, 'projected_points', 0)
        
        return {
            "total_players": len(current_roster),
            "position_breakdown": position_counts,
            "total_projected_points": total_projected,
            "average_projected": total_projected / max(1, len(current_roster))
        }