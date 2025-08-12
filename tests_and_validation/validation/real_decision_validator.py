#!/usr/bin/env python3
"""
Real Decision Validator - Focuses on borderline lineup decisions

This validator tests the model on the decisions that actually matter:
- FLEX spot decisions (RB3 vs WR3)
- Bye week replacements
- Similar-tier player comparisons
- NOT obvious starts like elite/stud players

The goal is to see if our matchup analysis and trending data
actually helps with the tough calls.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score
import nfl_data_py as nfl

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from lineup_optimizer import LineupOptimizer, Player
from matchup_analyzer import MatchupAnalyzer
from position_normalizer import position_normalizer


@dataclass
class DecisionResult:
    """Result of a single lineup decision."""
    week: int
    decision_type: str  # "flex", "rb2_vs_rb3", "wr2_vs_wr3", etc.
    player_a: str
    player_a_score: float
    player_a_actual: float
    player_b: str
    player_b_score: float
    player_b_actual: float
    model_choice: str  # player_a or player_b
    correct_choice: str  # who actually scored more
    was_correct: bool
    point_difference: float  # how much we gained/lost


@dataclass
class ValidationSummary:
    """Summary of validation results focused on real decisions."""
    total_decisions: int
    correct_decisions: int
    accuracy: float
    
    # By decision type
    flex_accuracy: float
    rb_decisions_accuracy: float
    wr_decisions_accuracy: float
    
    # Value metrics
    total_points_gained: float  # positive = good decisions
    avg_points_per_decision: float
    
    # Matchup impact
    matchup_helped_count: int  # times matchup correctly broke ties
    matchup_hurt_count: int    # times matchup led to wrong choice
    
    # Close calls (within 2 points)
    close_decisions: int
    close_decision_accuracy: float


class RealDecisionValidator:
    """Validator focused on borderline lineup decisions."""
    
    def __init__(self):
        self.optimizer = LineupOptimizer()
        self.matchup_analyzer = MatchupAnalyzer()
        self.historical_data = None
        self.decision_results = []
        
        # Define "decision zones" - where real choices happen
        self.projection_zones = {
            "flex_zone": (7, 14),      # FLEX-worthy players
            "streaming_zone": (5, 10),  # Waiver wire/streaming options
            "borderline_zone": (6, 12), # Could go either way
        }
        
    async def load_historical_data(self, seasons: List[int]) -> pd.DataFrame:
        """Load and cache historical data."""
        print(f"Loading historical data for seasons: {seasons}")
        
        try:
            cache_path = Path(__file__).parent.parent / "data" / "nfl_historical.parquet"
            if cache_path.exists():
                print("Loading from cache...")
                self.historical_data = pd.read_parquet(cache_path)
                self.historical_data = self.historical_data[
                    self.historical_data['season'].isin(seasons)
                ]
            else:
                self.historical_data = nfl.import_weekly_data(seasons)
                cache_path.parent.mkdir(exist_ok=True)
                self.historical_data.to_parquet(cache_path)
            
            print(f"Loaded {len(self.historical_data)} player-week records")
            return self.historical_data
            
        except Exception as e:
            print(f"Error loading data: {e}")
            raise
    
    def identify_decision_players(self, week_data: pd.DataFrame, 
                                 roster: List[str]) -> List[Tuple[str, float, str]]:
        """
        Identify players in the "decision zone" - not obvious starts or sits.
        
        Returns list of (player_name, projection, position) tuples.
        """
        decision_players = []
        
        for player_name in roster:
            player_data = week_data[week_data['player_display_name'] == player_name]
            
            if player_data.empty:
                continue
            
            player = player_data.iloc[0]
            projection = player.get('fantasy_points_ppr', 0)
            position = player.get('position', '')
            
            # Skip elite/stud tier (15+ points typically)
            if projection >= 15:
                continue
            
            # Skip obvious sits (under 5 points)
            if projection < 5:
                continue
            
            # Skip QBs and DEFs (usually 1 starter, no decision)
            if position in ['QB', 'DEF']:
                continue
            
            decision_players.append((player_name, projection, position))
        
        return decision_players
    
    async def evaluate_flex_decision(self, players: List[Player], 
                                    actuals: Dict[str, float]) -> Optional[DecisionResult]:
        """
        Evaluate FLEX spot decision - the most common tough call.
        
        Compare the model's FLEX choice vs next best bench player.
        """
        # Get players eligible for FLEX (RB/WR/TE)
        flex_eligible = [
            p for p in players 
            if p.position in ['RB', 'WR', 'TE']
            and p.player_tier not in ['elite', 'stud']  # Exclude auto-starts
        ]
        
        if len(flex_eligible) < 2:
            return None
        
        # Calculate flex_score for each player using position normalization
        for p in flex_eligible:
            base_proj = max(p.yahoo_projection, p.sleeper_projection, 0)
            flex_value = position_normalizer.get_flex_value(base_proj, p.position)
            p.flex_score = (flex_value * 10) + (p.composite_score * 0.01)
        
        # Sort by composite score initially
        flex_eligible.sort(key=lambda x: x.composite_score, reverse=True)
        
        # Assume top 2 RBs and top 2 WRs are locked starters
        # So FLEX decision is between next best players
        rbs = [p for p in flex_eligible if p.position == 'RB']
        wrs = [p for p in flex_eligible if p.position == 'WR']
        tes = [p for p in flex_eligible if p.position == 'TE']
        
        # Find FLEX candidates (3rd/4th best at each position)
        flex_candidates = []
        if len(rbs) > 2:
            flex_candidates.extend(rbs[2:4])  # RB3 and RB4
        if len(wrs) > 2:
            flex_candidates.extend(wrs[2:4])  # WR3 and WR4
        if len(tes) > 0:
            flex_candidates.append(tes[0])    # TE1 if not starting
        
        if len(flex_candidates) < 2:
            return None
        
        # Sort candidates by FLEX score (projection-weighted for cross-position comparison)
        flex_candidates.sort(key=lambda x: getattr(x, 'flex_score', x.composite_score), reverse=True)
        
        # Model chooses highest scoring candidate
        model_choice = flex_candidates[0]
        runner_up = flex_candidates[1]
        
        # Get actual scores
        choice_actual = actuals.get(model_choice.name, 0)
        runner_actual = actuals.get(runner_up.name, 0)
        
        # Who should have been chosen?
        correct_choice = model_choice.name if choice_actual >= runner_actual else runner_up.name
        
        return DecisionResult(
            week=0,  # Will be set by caller
            decision_type="flex",
            player_a=model_choice.name,
            player_a_score=model_choice.composite_score,
            player_a_actual=choice_actual,
            player_b=runner_up.name,
            player_b_score=runner_up.composite_score,
            player_b_actual=runner_actual,
            model_choice=model_choice.name,
            correct_choice=correct_choice,
            was_correct=(model_choice.name == correct_choice),
            point_difference=choice_actual - runner_actual
        )
    
    async def evaluate_position_decisions(self, players: List[Player], 
                                         position: str,
                                         actuals: Dict[str, float]) -> List[DecisionResult]:
        """
        Evaluate decisions within a position group (e.g., which RBs to start).
        
        Focus on RB2 vs RB3, WR2 vs WR3 decisions.
        """
        decisions = []
        
        # Get position players, excluding elites
        pos_players = [
            p for p in players 
            if p.position == position
            and p.player_tier not in ['elite', 'stud']
        ]
        
        if len(pos_players) < 2:
            return decisions
        
        # Sort by model score
        pos_players.sort(key=lambda x: x.composite_score, reverse=True)
        
        # For each adjacent pair, evaluate the decision
        for i in range(len(pos_players) - 1):
            player_a = pos_players[i]
            player_b = pos_players[i + 1]
            
            # Skip if projection difference is huge (>5 points)
            proj_diff = abs(player_a.yahoo_projection - player_b.yahoo_projection)
            if proj_diff > 5:
                continue
            
            # Get actual scores
            a_actual = actuals.get(player_a.name, 0)
            b_actual = actuals.get(player_b.name, 0)
            
            # Model chose player_a (higher composite score)
            correct_choice = player_a.name if a_actual >= b_actual else player_b.name
            
            decisions.append(DecisionResult(
                week=0,  # Will be set by caller
                decision_type=f"{position.lower()}_decision",
                player_a=player_a.name,
                player_a_score=player_a.composite_score,
                player_a_actual=a_actual,
                player_b=player_b.name,
                player_b_score=player_b.composite_score,
                player_b_actual=b_actual,
                model_choice=player_a.name,
                correct_choice=correct_choice,
                was_correct=(player_a.name == correct_choice),
                point_difference=a_actual - b_actual
            ))
        
        return decisions
    
    async def validate_week_decisions(self, season: int, week: int, 
                                     roster: List[str]) -> List[DecisionResult]:
        """
        Validate all lineup decisions for a specific week.
        
        Focus on borderline calls, not obvious starts.
        """
        print(f"  Evaluating decisions for Week {week}...")
        
        # Get week data
        week_data = self.historical_data[
            (self.historical_data['season'] == season) &
            (self.historical_data['week'] == week)
        ]
        
        # Create Player objects for decision-zone players
        decision_players = []
        actuals = {}
        
        for player_name in roster:
            player_week = week_data[week_data['player_display_name'] == player_name]
            
            if player_week.empty:
                continue
            
            player_stats = player_week.iloc[0]
            actual_points = player_stats['fantasy_points_ppr']
            actuals[player_name] = actual_points
            
            # Skip if this is an obvious start/sit
            if actual_points >= 15 or actual_points < 5:
                continue
            
            # Create player object
            player = Player(
                name=player_name,
                position=player_stats['position'],
                team=player_stats.get('recent_team', ''),
                opponent=player_stats.get('opponent_team', ''),
                yahoo_projection=actual_points * 0.9,  # Simulate projection
                sleeper_projection=actual_points * 0.95
            )
            
            decision_players.append(player)
        
        if len(decision_players) < 2:
            return []
        
        # Enhance with our analysis
        decision_players = await self.optimizer.enhance_with_external_data(decision_players)
        
        # Calculate composite scores and flex scores
        for player in decision_players:
            player.composite_score = self.optimizer.calculate_composite_score(player, "balanced")
            # Calculate flex_score using position normalization
            base_proj = max(player.yahoo_projection, player.sleeper_projection, 0)
            flex_value = position_normalizer.get_flex_value(base_proj, player.position)
            player.flex_score = (flex_value * 10) + (player.composite_score * 0.01)
        
        decisions = []
        
        # Evaluate FLEX decision
        flex_decision = await self.evaluate_flex_decision(decision_players, actuals)
        if flex_decision:
            flex_decision.week = week
            decisions.append(flex_decision)
        
        # Evaluate position group decisions
        for position in ['RB', 'WR']:
            pos_decisions = await self.evaluate_position_decisions(
                decision_players, position, actuals
            )
            for decision in pos_decisions:
                decision.week = week
                decisions.append(decision)
        
        return decisions
    
    def analyze_matchup_impact(self) -> Dict:
        """
        Analyze whether matchup analysis helped or hurt decisions.
        
        Compare decisions where matchup was the tiebreaker.
        """
        matchup_impact = {
            'helped': 0,
            'hurt': 0,
            'neutral': 0,
            'examples': []
        }
        
        for decision in self.decision_results:
            # Check if this was a close call (within 3 composite score points)
            score_diff = abs(decision.player_a_score - decision.player_b_score)
            
            if score_diff < 3:  # Close call where matchup might have mattered
                if decision.was_correct:
                    matchup_impact['helped'] += 1
                    if len(matchup_impact['examples']) < 3:
                        matchup_impact['examples'].append(
                            f"✅ Week {decision.week}: Correctly chose {decision.model_choice} "
                            f"over {decision.player_b} (+{abs(decision.point_difference):.1f} pts)"
                        )
                else:
                    matchup_impact['hurt'] += 1
                    if len(matchup_impact['examples']) < 3:
                        matchup_impact['examples'].append(
                            f"❌ Week {decision.week}: Wrongly chose {decision.model_choice} "
                            f"over {decision.correct_choice} (-{abs(decision.point_difference):.1f} pts)"
                        )
            else:
                matchup_impact['neutral'] += 1
        
        return matchup_impact
    
    async def run_validation(self, season: int, roster: List[str]) -> ValidationSummary:
        """
        Run validation focused on real lineup decisions.
        """
        print(f"\n{'='*60}")
        print(f"REAL DECISION VALIDATION - Season {season}")
        print(f"{'='*60}")
        print("Focusing on borderline lineup decisions (not obvious starts)\n")
        
        all_decisions = []
        
        # Validate weeks 5-17 (enough data to make decisions)
        for week in range(5, 18):
            week_decisions = await self.validate_week_decisions(season, week, roster)
            all_decisions.extend(week_decisions)
        
        self.decision_results = all_decisions
        
        if not all_decisions:
            print("No borderline decisions found to validate")
            return None
        
        # Calculate metrics
        correct = sum(1 for d in all_decisions if d.was_correct)
        total = len(all_decisions)
        accuracy = correct / total if total > 0 else 0
        
        # By decision type
        flex_decisions = [d for d in all_decisions if d.decision_type == "flex"]
        flex_accuracy = (
            sum(1 for d in flex_decisions if d.was_correct) / len(flex_decisions)
            if flex_decisions else 0
        )
        
        rb_decisions = [d for d in all_decisions if "rb" in d.decision_type]
        rb_accuracy = (
            sum(1 for d in rb_decisions if d.was_correct) / len(rb_decisions)
            if rb_decisions else 0
        )
        
        wr_decisions = [d for d in all_decisions if "wr" in d.decision_type]
        wr_accuracy = (
            sum(1 for d in wr_decisions if d.was_correct) / len(wr_decisions)
            if wr_decisions else 0
        )
        
        # Points gained/lost
        total_points = sum(d.point_difference for d in all_decisions if d.was_correct)
        total_points -= sum(abs(d.point_difference) for d in all_decisions if not d.was_correct)
        avg_points = total_points / total if total > 0 else 0
        
        # Close decisions (within 2 points actual)
        close_decisions = [
            d for d in all_decisions 
            if abs(d.player_a_actual - d.player_b_actual) <= 2
        ]
        close_correct = sum(1 for d in close_decisions if d.was_correct)
        close_accuracy = close_correct / len(close_decisions) if close_decisions else 0
        
        # Matchup impact
        matchup_impact = self.analyze_matchup_impact()
        
        summary = ValidationSummary(
            total_decisions=total,
            correct_decisions=correct,
            accuracy=accuracy,
            flex_accuracy=flex_accuracy,
            rb_decisions_accuracy=rb_accuracy,
            wr_decisions_accuracy=wr_accuracy,
            total_points_gained=total_points,
            avg_points_per_decision=avg_points,
            matchup_helped_count=matchup_impact['helped'],
            matchup_hurt_count=matchup_impact['hurt'],
            close_decisions=len(close_decisions),
            close_decision_accuracy=close_accuracy
        )
        
        # Print results
        print(f"\n{'='*60}")
        print("VALIDATION RESULTS - Borderline Decisions Only")
        print(f"{'='*60}\n")
        
        print(f"📊 Overall Performance:")
        print(f"  Total decisions evaluated: {total}")
        print(f"  Correct decisions: {correct}/{total} ({accuracy:.1%})")
        print(f"  Points gained/lost: {total_points:+.1f} total ({avg_points:+.2f} per decision)")
        
        print(f"\n🎯 Decision Type Breakdown:")
        if flex_decisions:
            print(f"  FLEX decisions: {len(flex_decisions)} total, {flex_accuracy:.1%} accurate")
        if rb_decisions:
            print(f"  RB decisions: {len(rb_decisions)} total, {rb_accuracy:.1%} accurate")
        if wr_decisions:
            print(f"  WR decisions: {len(wr_decisions)} total, {wr_accuracy:.1%} accurate")
        
        print(f"\n⚖️ Close Calls (within 2 pts actual):")
        print(f"  Total: {len(close_decisions)}")
        print(f"  Accuracy: {close_accuracy:.1%}")
        print(f"  {'Good' if close_accuracy >= 0.5 else 'Needs work'} at coin-flip decisions")
        
        print(f"\n🎲 Matchup Analysis Impact:")
        print(f"  Helped: {matchup_impact['helped']} decisions")
        print(f"  Hurt: {matchup_impact['hurt']} decisions")
        print(f"  Net: {matchup_impact['helped'] - matchup_impact['hurt']:+d}")
        
        if matchup_impact['examples']:
            print(f"\n  Examples:")
            for example in matchup_impact['examples']:
                print(f"    {example}")
        
        print(f"\n💡 Key Insights:")
        if accuracy >= 0.60:
            print(f"  ✅ Model is GOOD at borderline decisions ({accuracy:.1%} accuracy)")
        elif accuracy >= 0.55:
            print(f"  ⚠️ Model is DECENT at borderline decisions ({accuracy:.1%} accuracy)")
        else:
            print(f"  ❌ Model STRUGGLES with borderline decisions ({accuracy:.1%} accuracy)")
        
        if avg_points > 0:
            print(f"  ✅ Positive value: +{avg_points:.2f} points per decision")
        else:
            print(f"  ❌ Negative value: {avg_points:.2f} points per decision")
        
        if matchup_impact['helped'] > matchup_impact['hurt']:
            print(f"  ✅ Matchup analysis is helpful (net +{matchup_impact['helped'] - matchup_impact['hurt']} decisions)")
        else:
            print(f"  ❌ Matchup analysis may be hurting decisions")
        
        return summary
    
    def export_decisions(self, filepath: str = "real_decision_results.json"):
        """Export detailed decision results for analysis."""
        output = {
            'timestamp': datetime.now().isoformat(),
            'decisions': [
                {
                    'week': d.week,
                    'type': d.decision_type,
                    'choice': d.model_choice,
                    'alternative': d.player_b if d.model_choice == d.player_a else d.player_a,
                    'was_correct': d.was_correct,
                    'points_impact': float(d.point_difference) if d.was_correct else float(-abs(d.point_difference)),
                    'model_scores': {
                        d.player_a: float(d.player_a_score),
                        d.player_b: float(d.player_b_score)
                    },
                    'actual_scores': {
                        d.player_a: float(d.player_a_actual),
                        d.player_b: float(d.player_b_actual)
                    }
                }
                for d in self.decision_results
            ]
        }
        
        output_path = Path(__file__).parent.parent / "data" / filepath
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"\n💾 Detailed results saved to: {output_path}")


async def main():
    """Run real decision validation."""
    validator = RealDecisionValidator()
    
    # Realistic roster with mix of talent levels
    roster = [
        # Studs (these won't be evaluated - obvious starts)
        "Josh Allen", "Christian McCaffrey", "Tyreek Hill",
        
        # Borderline players (THESE are what we'll evaluate)
        "Tony Pollard", "Rachaad White", "Javonte Williams",  # RB2/3/4 decisions
        "Chris Olave", "Amari Cooper", "Christian Kirk",      # WR2/3/4 decisions
        "George Kittle", "Dallas Goedert",                    # TE decisions
        "Mike Evans", "DeAndre Hopkins", "Brandin Cooks",     # More WR depth
        "Dameon Pierce", "Brian Robinson Jr.",                # More RB depth
        
        # Defense/Kicker (usually not decisions)
        "Buffalo Bills", "Justin Tucker"
    ]
    
    # Load data
    await validator.load_historical_data([2023])
    
    # Run validation
    summary = await validator.run_validation(2023, roster)
    
    # Export detailed results
    if validator.decision_results:
        validator.export_decisions()
    
    return summary


if __name__ == "__main__":
    asyncio.run(main())