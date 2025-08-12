#!/usr/bin/env python3
"""
FLEX Decision Tester - Comprehensive testing for FLEX spot decisions

Tests various scenarios:
1. RB vs WR comparisons (most common FLEX decision)
2. WR vs TE comparisons  
3. RB vs TE comparisons
4. High-floor vs high-ceiling players
5. Elite matchup vs better player
6. Volume vs efficiency players
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import numpy as np
import pandas as pd
import nfl_data_py as nfl

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from lineup_optimizer import LineupOptimizer, Player
from matchup_analyzer import MatchupAnalyzer
from position_normalizer import position_normalizer


@dataclass
class FlexTestCase:
    """A specific FLEX decision test case."""
    name: str
    description: str
    player_a: Player
    player_b: Player
    expected_choice: str  # Name of player who should be chosen
    reasoning: str


@dataclass 
class FlexTestResult:
    """Result of a FLEX test case."""
    test_name: str
    passed: bool
    expected: str
    actual: str
    player_a_scores: Dict[str, float]  # projection, composite, flex scores
    player_b_scores: Dict[str, float]
    reasoning: str


class FlexDecisionTester:
    """Comprehensive tester for FLEX spot decisions."""
    
    def __init__(self):
        self.optimizer = LineupOptimizer()
        self.matchup_analyzer = MatchupAnalyzer()
        self.test_results = []
        
    async def setup(self):
        """Initialize matchup data."""
        await self.matchup_analyzer.load_defensive_rankings()
        
    def create_test_player(self, name: str, position: str, 
                          yahoo_proj: float, sleeper_proj: float,
                          team: str = "LAR", opponent: str = "SF",
                          recent_scores: List[float] = None) -> Player:
        """Helper to create test players."""
        player = Player(
            name=name,
            position=position,
            team=team,
            opponent=opponent,
            yahoo_projection=yahoo_proj,
            sleeper_projection=sleeper_proj,
            recent_scores=recent_scores or []
        )
        return player
    
    async def create_flex_test_cases(self) -> List[FlexTestCase]:
        """Create comprehensive test cases for FLEX decisions."""
        test_cases = []
        
        # Test 1: Similar projections, RB vs WR
        test_cases.append(FlexTestCase(
            name="Similar RB vs WR",
            description="Both project ~10 points, who gets FLEX?",
            player_a=self.create_test_player(
                "Test RB", "RB", 10.5, 10.0,
                team="LAR", opponent="CHI"  # Good matchup
            ),
            player_b=self.create_test_player(
                "Test WR", "WR", 10.2, 10.5,
                team="DAL", opponent="PIT"  # Tough matchup
            ),
            expected_choice="Test RB",
            reasoning="RB has slightly higher projection and better matchup"
        ))
        
        # Test 2: High projection TE vs lower RB
        test_cases.append(FlexTestCase(
            name="High TE vs Lower RB",
            description="TE projects 9 pts, RB projects 7 pts",
            player_a=self.create_test_player(
                "Elite TE", "TE", 9.0, 9.2,
                team="KC", opponent="LV"  # Good matchup
            ),
            player_b=self.create_test_player(
                "Backup RB", "RB", 7.0, 7.5,
                team="NYG", opponent="SF"  # Bad matchup
            ),
            expected_choice="Elite TE",
            reasoning="TE projects 2+ points higher, enough to overcome position bias"
        ))
        
        # Test 3: WR with elite matchup vs RB with bad matchup
        test_cases.append(FlexTestCase(
            name="Matchup Impact Test",
            description="How much do matchups matter for FLEX?",
            player_a=self.create_test_player(
                "WR Good Matchup", "WR", 8.5, 8.0,
                team="BUF", opponent="NYG"  # Elite matchup vs bad defense
            ),
            player_b=self.create_test_player(
                "RB Bad Matchup", "RB", 9.0, 9.5,
                team="HOU", opponent="BAL"  # Terrible matchup vs top defense
            ),
            expected_choice="RB Bad Matchup",
            reasoning="Higher projection should win even with worse matchup (70% projection weight)"
        ))
        
        # Test 4: Consistent floor vs boom/bust
        test_cases.append(FlexTestCase(
            name="Floor vs Ceiling",
            description="Consistent 8-10 pts vs volatile 5-15 pts",
            player_a=self.create_test_player(
                "Mr. Consistent", "RB", 9.0, 9.0,
                team="GB", opponent="CHI",
                recent_scores=[9.0, 8.5, 9.5, 8.0, 9.0]  # Very consistent
            ),
            player_b=self.create_test_player(
                "Boom or Bust", "WR", 9.5, 9.0,
                team="ARI", opponent="LAR", 
                recent_scores=[15.0, 3.0, 18.0, 4.0, 12.0]  # Very volatile
            ),
            expected_choice="Boom or Bust",
            reasoning="Slightly higher projection should win in standard strategy"
        ))
        
        # Test 5: Equal projections - tiebreaker test
        test_cases.append(FlexTestCase(
            name="Perfect Tie",
            description="Identical projections, what's the tiebreaker?",
            player_a=self.create_test_player(
                "RB Tie", "RB", 10.0, 10.0,
                team="MIN", opponent="DET"  # Neutral matchup
            ),
            player_b=self.create_test_player(
                "WR Tie", "WR", 10.0, 10.0,
                team="SEA", opponent="ARI"  # Neutral matchup
            ),
            expected_choice="RB Tie",  # Could go either way
            reasoning="With identical projections, composite factors decide"
        ))
        
        # Test 6: TE trap test - good TE that shouldn't beat decent RB/WR
        test_cases.append(FlexTestCase(
            name="TE Trap Avoidance",
            description="Ensure TEs don't incorrectly win FLEX",
            player_a=self.create_test_player(
                "Good TE", "TE", 7.5, 7.0,
                team="SF", opponent="ARI"  # Good matchup
            ),
            player_b=self.create_test_player(
                "Decent RB", "RB", 9.0, 8.5,
                team="IND", opponent="TEN"  # Average matchup
            ),
            expected_choice="Decent RB",
            reasoning="RB projects 1.5+ points higher, should easily win"
        ))
        
        # Test 7: Three-way FLEX decision
        test_cases.append(FlexTestCase(
            name="WR vs RB Close Call",
            description="Very close projections across positions",
            player_a=self.create_test_player(
                "WR3", "WR", 8.8, 9.2,
                team="CIN", opponent="CLE"
            ),
            player_b=self.create_test_player(
                "RB3", "RB", 9.0, 8.8,
                team="MIA", opponent="NE"
            ),
            expected_choice="WR3",  # Slight edge in projections
            reasoning="WR has slight projection edge (9.0 vs 8.9 avg)"
        ))
        
        # Test 8: Trending player test
        test_cases.append(FlexTestCase(
            name="Hot Hand Test",
            description="Player with momentum vs steady player",
            player_a=self.create_test_player(
                "Hot Player", "WR", 9.0, 9.0,
                team="PHI", opponent="WAS",
                recent_scores=[12.0, 14.0, 15.0]  # Trending up
            ),
            player_b=self.create_test_player(
                "Cold Player", "RB", 9.5, 9.5,
                team="ATL", opponent="CAR",
                recent_scores=[6.0, 5.0, 4.0]  # Trending down
            ),
            expected_choice="Cold Player",
            reasoning="Higher projection should still win despite cold streak"
        ))
        
        return test_cases
    
    async def run_test_case(self, test_case: FlexTestCase) -> FlexTestResult:
        """Run a single FLEX decision test case."""
        
        # Enhance players with matchup data
        players = [test_case.player_a, test_case.player_b]
        players = await self.optimizer.enhance_with_external_data(players)
        
        # Calculate all scores
        for player in players:
            player.composite_score = self.optimizer.calculate_composite_score(player, "balanced")
            # Calculate FLEX score using position normalization
            base_proj = max(player.yahoo_projection, player.sleeper_projection, 0)
            flex_value = position_normalizer.get_flex_value(base_proj, player.position)
            player.flex_score = (flex_value * 10) + (player.composite_score * 0.01)
        
        # Determine winner based on flex_score
        if test_case.player_a.flex_score > test_case.player_b.flex_score:
            actual_choice = test_case.player_a.name
        else:
            actual_choice = test_case.player_b.name
        
        passed = (actual_choice == test_case.expected_choice)
        
        result = FlexTestResult(
            test_name=test_case.name,
            passed=passed,
            expected=test_case.expected_choice,
            actual=actual_choice,
            player_a_scores={
                'projection': max(test_case.player_a.yahoo_projection, 
                                test_case.player_a.sleeper_projection),
                'composite': test_case.player_a.composite_score,
                'flex': test_case.player_a.flex_score,
                'matchup': test_case.player_a.matchup_score,
                'tier': test_case.player_a.player_tier
            },
            player_b_scores={
                'projection': max(test_case.player_b.yahoo_projection,
                                test_case.player_b.sleeper_projection),
                'composite': test_case.player_b.composite_score,
                'flex': test_case.player_b.flex_score,
                'matchup': test_case.player_b.matchup_score,
                'tier': test_case.player_b.player_tier
            },
            reasoning=test_case.reasoning
        )
        
        return result
    
    async def run_all_tests(self) -> Dict:
        """Run all FLEX test cases and summarize results."""
        await self.setup()
        
        print("\n" + "="*60)
        print("FLEX DECISION TEST SUITE")
        print("="*60)
        print("\nTesting FLEX scoring logic with various scenarios...\n")
        
        # Create and run test cases
        test_cases = await self.create_flex_test_cases()
        results = []
        
        for test_case in test_cases:
            result = await self.run_test_case(test_case)
            results.append(result)
            
            # Print result
            status = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"{status} - {result.test_name}")
            print(f"  Description: {test_case.description}")
            print(f"  Expected: {result.expected}, Got: {result.actual}")
            
            if not result.passed:
                print(f"  Player A ({test_case.player_a.name}):")
                print(f"    - Projection: {result.player_a_scores['projection']:.1f}")
                print(f"    - Composite: {result.player_a_scores['composite']:.1f}")
                print(f"    - FLEX Score: {result.player_a_scores['flex']:.1f}")
                print(f"    - Matchup: {result.player_a_scores['matchup']}")
                print(f"  Player B ({test_case.player_b.name}):")
                print(f"    - Projection: {result.player_b_scores['projection']:.1f}")
                print(f"    - Composite: {result.player_b_scores['composite']:.1f}")
                print(f"    - FLEX Score: {result.player_b_scores['flex']:.1f}")
                print(f"    - Matchup: {result.player_b_scores['matchup']}")
            
            print()
        
        # Calculate summary statistics
        total_tests = len(results)
        passed_tests = sum(1 for r in results if r.passed)
        pass_rate = passed_tests / total_tests if total_tests > 0 else 0
        
        # Group by test type
        rb_wr_tests = [r for r in results if "RB" in r.test_name and "WR" in r.test_name]
        te_tests = [r for r in results if "TE" in r.test_name]
        matchup_tests = [r for r in results if "Matchup" in r.test_name]
        
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"\n📊 Overall Results:")
        print(f"  Total Tests: {total_tests}")
        print(f"  Passed: {passed_tests}")
        print(f"  Failed: {total_tests - passed_tests}")
        print(f"  Pass Rate: {pass_rate:.1%}")
        
        print(f"\n🎯 Key Insights:")
        
        # Check if projection-weighting is working
        proj_weight_working = pass_rate >= 0.7
        if proj_weight_working:
            print(f"  ✅ Projection-weighted scoring is working correctly")
        else:
            print(f"  ❌ Issues with projection-weighted scoring")
        
        # Check TE trap
        te_pass_rate = sum(1 for r in te_tests if r.passed) / len(te_tests) if te_tests else 0
        if te_pass_rate >= 0.8:
            print(f"  ✅ TE trap fixed - TEs not incorrectly winning FLEX")
        else:
            print(f"  ❌ TE trap still present - TEs winning when they shouldn't")
        
        # Check if matchups have appropriate influence
        matchup_pass = sum(1 for r in matchup_tests if r.passed) / len(matchup_tests) if matchup_tests else 0
        if matchup_pass >= 0.8:
            print(f"  ✅ Matchup influence appropriately weighted")
        else:
            print(f"  ⚠️ Matchup influence may be too strong/weak")
        
        self.test_results = results
        
        return {
            'total_tests': total_tests,
            'passed': passed_tests,
            'failed': total_tests - passed_tests,
            'pass_rate': pass_rate,
            'results': results
        }
    
    def export_results(self, filepath: str = "flex_test_results.json"):
        """Export test results for analysis."""
        output = {
            'timestamp': datetime.now().isoformat(),
            'test_results': [
                {
                    'test_name': r.test_name,
                    'passed': r.passed,
                    'expected': r.expected,
                    'actual': r.actual,
                    'player_a_scores': r.player_a_scores,
                    'player_b_scores': r.player_b_scores,
                    'reasoning': r.reasoning
                }
                for r in self.test_results
            ]
        }
        
        output_path = Path(__file__).parent.parent / "data" / filepath
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"\n💾 Detailed results saved to: {output_path}")


async def main():
    """Run FLEX decision test suite."""
    tester = FlexDecisionTester()
    summary = await tester.run_all_tests()
    
    if tester.test_results:
        tester.export_results()
    
    # Return pass/fail for CI/CD
    return summary['pass_rate'] >= 0.75  # 75% pass rate minimum


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)