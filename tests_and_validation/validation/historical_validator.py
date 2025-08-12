#!/usr/bin/env python3
"""
Historical Model Validator for Fantasy Football Lineup Optimizer

Validates our statistical model against historical NFL data to measure:
- Prediction accuracy
- Tier system effectiveness
- Matchup scoring correlation
- Momentum prediction accuracy
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
from scipy import stats
import nfl_data_py as nfl

# Add parent directory to path to import our modules
sys.path.append(str(Path(__file__).parent.parent.parent))

from lineup_optimizer import LineupOptimizer, Player
from matchup_analyzer import MatchupAnalyzer


@dataclass
class ValidationResult:
    """Results from a validation run."""
    season: int
    week: int
    predicted_scores: Dict[str, float]
    actual_scores: Dict[str, float]
    lineup_accuracy: float
    tier_accuracy: float
    matchup_correlation: float
    momentum_accuracy: float
    strategy_performance: Dict[str, float]


class ModelValidator:
    """Validates the fantasy football model against historical data."""
    
    def __init__(self):
        self.optimizer = LineupOptimizer()
        self.matchup_analyzer = MatchupAnalyzer()
        self.historical_data = {}
        self.validation_results = []
        
    async def load_historical_data(self, seasons: List[int]) -> pd.DataFrame:
        """
        Load historical NFL data for specified seasons.
        
        Args:
            seasons: List of seasons to load (e.g., [2023, 2024])
            
        Returns:
            DataFrame with weekly player stats and fantasy points
        """
        print(f"Loading historical data for seasons: {seasons}")
        
        try:
            # Import weekly data with fantasy points
            df = nfl.import_weekly_data(seasons)
            
            # Store in cache
            self.historical_data = df
            
            # Save to local cache for faster future loads
            cache_path = Path(__file__).parent.parent / "data" / "historical_data.parquet"
            cache_path.parent.mkdir(exist_ok=True)
            df.to_parquet(cache_path)
            
            print(f"Loaded {len(df)} player-week records")
            return df
            
        except Exception as e:
            print(f"Error loading historical data: {e}")
            
            # Try to load from cache
            cache_path = Path(__file__).parent.parent / "data" / "historical_data.parquet"
            if cache_path.exists():
                print("Loading from cache...")
                self.historical_data = pd.read_parquet(cache_path)
                return self.historical_data
            
            raise
    
    def calculate_player_momentum(self, player_name: str, week: int, 
                                 historical_df: pd.DataFrame) -> float:
        """
        Calculate momentum score based on recent performance.
        
        Args:
            player_name: Player's name
            week: Current week number
            historical_df: Historical data
            
        Returns:
            Momentum score (0-100)
        """
        # Get last 3-5 games
        player_data = historical_df[
            (historical_df['player_display_name'] == player_name) &
            (historical_df['week'] < week) &
            (historical_df['week'] >= max(1, week - 5))
        ].sort_values('week', ascending=False)
        
        if len(player_data) < 2:
            return 50.0  # Neutral
        
        recent_scores = player_data['fantasy_points_ppr'].values.tolist()
        
        # Use our optimizer's momentum calculation
        return self.optimizer.calculate_momentum(recent_scores)
    
    async def backtest_week(self, season: int, week: int, 
                          roster: List[str]) -> ValidationResult:
        """
        Backtest our model for a specific week.
        
        Args:
            season: NFL season
            week: Week number
            roster: List of player names on roster
            
        Returns:
            ValidationResult with metrics
        """
        print(f"Backtesting Season {season}, Week {week}")
        
        # Filter historical data
        week_data = self.historical_data[
            (self.historical_data['season'] == season) &
            (self.historical_data['week'] == week)
        ]
        
        # Create Player objects for roster
        players = []
        for player_name in roster:
            player_week = week_data[week_data['player_display_name'] == player_name]
            
            if player_week.empty:
                continue
                
            row = player_week.iloc[0]
            
            # Get previous week for projections (simulate real-time)
            prev_week = self.historical_data[
                (self.historical_data['season'] == season) &
                (self.historical_data['week'] == week - 1) &
                (self.historical_data['player_display_name'] == player_name)
            ]
            
            # Create player with "projections" (using previous week as proxy)
            player = Player(
                name=player_name,
                position=row['position'],
                team=row['recent_team'],
                opponent=row['opponent_team'] if 'opponent_team' in row else "",
                yahoo_projection=prev_week['fantasy_points_ppr'].values[0] if not prev_week.empty else 15.0,
                sleeper_projection=prev_week['fantasy_points_ppr'].values[0] * 0.95 if not prev_week.empty else 14.0
            )
            
            # Add momentum
            player.momentum_score = self.calculate_player_momentum(
                player_name, week, self.historical_data
            )
            
            # Calculate recent scores for floor/ceiling
            recent_games = self.historical_data[
                (self.historical_data['player_display_name'] == player_name) &
                (self.historical_data['week'] < week) &
                (self.historical_data['week'] >= max(1, week - 3))
            ]
            
            if not recent_games.empty:
                player.recent_scores = recent_games['fantasy_points_ppr'].values.tolist()
            
            players.append(player)
        
        # Enhance with our analysis
        players = await self.optimizer.enhance_with_external_data(players)
        
        # Get optimal lineup for each strategy
        strategy_results = {}
        for strategy in ["balanced", "matchup_heavy", "expert_consensus"]:
            lineup = self.optimizer.optimize_lineup(players, strategy)
            
            # Calculate predicted vs actual scores
            predicted_total = sum(p.composite_score for p in lineup['starters'].values())
            
            actual_total = 0
            for pos, player in lineup['starters'].items():
                actual_week = week_data[week_data['player_display_name'] == player.name]
                if not actual_week.empty:
                    actual_total += actual_week['fantasy_points_ppr'].values[0]
            
            strategy_results[strategy] = {
                'predicted': predicted_total,
                'actual': actual_total,
                'accuracy': 1 - abs(predicted_total - actual_total) / actual_total if actual_total > 0 else 0
            }
        
        # Calculate tier accuracy
        tier_accuracy = await self.validate_tier_rankings(players, week_data)
        
        # Calculate matchup correlation
        matchup_correlation = self.calculate_matchup_correlation(players, week_data)
        
        # Build result
        result = ValidationResult(
            season=season,
            week=week,
            predicted_scores={p.name: p.composite_score for p in players},
            actual_scores={
                row['player_display_name']: row['fantasy_points_ppr'] 
                for _, row in week_data.iterrows() 
                if row['player_display_name'] in roster
            },
            lineup_accuracy=strategy_results['balanced']['accuracy'],
            tier_accuracy=tier_accuracy,
            matchup_correlation=matchup_correlation,
            momentum_accuracy=0.0,  # TODO: Implement
            strategy_performance={k: v['accuracy'] for k, v in strategy_results.items()}
        )
        
        self.validation_results.append(result)
        return result
    
    async def validate_tier_rankings(self, players: List[Player], 
                                    actual_data: pd.DataFrame) -> float:
        """
        Validate that higher tier players score more points.
        
        Returns:
            Accuracy score (0-1)
        """
        tier_order = ["elite", "stud", "solid", "flex", "bench"]
        correct_rankings = 0
        total_comparisons = 0
        
        for i, tier1 in enumerate(tier_order[:-1]):
            for tier2 in tier_order[i+1:]:
                # Get players in each tier
                tier1_players = [p for p in players if p.player_tier == tier1]
                tier2_players = [p for p in players if p.player_tier == tier2]
                
                if not tier1_players or not tier2_players:
                    continue
                
                # Get actual scores
                tier1_scores = []
                for p in tier1_players:
                    actual = actual_data[actual_data['player_display_name'] == p.name]
                    if not actual.empty:
                        tier1_scores.append(actual['fantasy_points_ppr'].values[0])
                
                tier2_scores = []
                for p in tier2_players:
                    actual = actual_data[actual_data['player_display_name'] == p.name]
                    if not actual.empty:
                        tier2_scores.append(actual['fantasy_points_ppr'].values[0])
                
                if tier1_scores and tier2_scores:
                    # Check if tier1 average > tier2 average
                    if np.mean(tier1_scores) > np.mean(tier2_scores):
                        correct_rankings += 1
                    total_comparisons += 1
        
        return correct_rankings / total_comparisons if total_comparisons > 0 else 0.0
    
    def calculate_matchup_correlation(self, players: List[Player], 
                                     actual_data: pd.DataFrame) -> float:
        """
        Calculate correlation between matchup scores and actual performance.
        
        Returns:
            Spearman correlation coefficient
        """
        matchup_scores = []
        actual_scores = []
        
        for player in players:
            actual = actual_data[actual_data['player_display_name'] == player.name]
            if not actual.empty and player.matchup_score > 0:
                matchup_scores.append(player.matchup_score)
                actual_scores.append(actual['fantasy_points_ppr'].values[0])
        
        if len(matchup_scores) < 3:
            return 0.0
        
        correlation, _ = stats.spearmanr(matchup_scores, actual_scores)
        return correlation if not np.isnan(correlation) else 0.0
    
    async def run_season_validation(self, season: int, 
                                  start_week: int = 1, 
                                  end_week: int = 17) -> Dict:
        """
        Run validation for an entire season.
        
        Args:
            season: NFL season to validate
            start_week: First week to test
            end_week: Last week to test
            
        Returns:
            Summary statistics
        """
        print(f"\nValidating Season {season} (Weeks {start_week}-{end_week})")
        print("=" * 60)
        
        # Sample roster (would be loaded from Yahoo in production)
        sample_roster = [
            "Josh Allen", "Lamar Jackson",
            "Christian McCaffrey", "Saquon Barkley", "Tony Pollard",
            "CeeDee Lamb", "Tyreek Hill", "AJ Brown", "Mike Evans",
            "Travis Kelce", "Mark Andrews",
            "Harrison Butker",
            "Buffalo Bills", "Baltimore Ravens"
        ]
        
        weekly_results = []
        
        for week in range(start_week, end_week + 1):
            try:
                result = await self.backtest_week(season, week, sample_roster)
                weekly_results.append(result)
                
                print(f"Week {week}: Accuracy={result.lineup_accuracy:.2%}, "
                      f"Tier={result.tier_accuracy:.2%}, "
                      f"Matchup Corr={result.matchup_correlation:.2f}")
                      
            except Exception as e:
                print(f"Error processing week {week}: {e}")
                continue
        
        # Calculate season summary
        if weekly_results:
            summary = {
                'season': season,
                'weeks_tested': len(weekly_results),
                'avg_lineup_accuracy': np.mean([r.lineup_accuracy for r in weekly_results]),
                'avg_tier_accuracy': np.mean([r.tier_accuracy for r in weekly_results]),
                'avg_matchup_correlation': np.mean([r.matchup_correlation for r in weekly_results]),
                'best_strategy': self._find_best_strategy(weekly_results),
                'confidence_interval': self._calculate_confidence_interval(weekly_results)
            }
            
            print(f"\nSeason {season} Summary:")
            print(f"  Average Lineup Accuracy: {summary['avg_lineup_accuracy']:.2%}")
            print(f"  Average Tier Accuracy: {summary['avg_tier_accuracy']:.2%}")
            print(f"  Average Matchup Correlation: {summary['avg_matchup_correlation']:.3f}")
            print(f"  Best Strategy: {summary['best_strategy']}")
            
            return summary
        
        return {}
    
    def _find_best_strategy(self, results: List[ValidationResult]) -> str:
        """Find which strategy performed best overall."""
        strategy_scores = {}
        
        for result in results:
            for strategy, score in result.strategy_performance.items():
                if strategy not in strategy_scores:
                    strategy_scores[strategy] = []
                strategy_scores[strategy].append(score)
        
        avg_scores = {s: np.mean(scores) for s, scores in strategy_scores.items()}
        return max(avg_scores, key=avg_scores.get)
    
    def _calculate_confidence_interval(self, results: List[ValidationResult], 
                                      confidence: float = 0.95) -> Tuple[float, float]:
        """Calculate confidence interval for accuracy."""
        accuracies = [r.lineup_accuracy for r in results]
        
        if len(accuracies) < 2:
            return (0.0, 0.0)
        
        mean = np.mean(accuracies)
        std = np.std(accuracies, ddof=1)
        n = len(accuracies)
        
        # Calculate confidence interval
        margin = stats.t.ppf((1 + confidence) / 2, n - 1) * (std / np.sqrt(n))
        
        return (mean - margin, mean + margin)
    
    def generate_report(self, output_path: str = "validation_report.json"):
        """Generate validation report."""
        report = {
            'generated_at': datetime.now().isoformat(),
            'total_weeks_tested': len(self.validation_results),
            'results': [
                {
                    'season': r.season,
                    'week': r.week,
                    'lineup_accuracy': r.lineup_accuracy,
                    'tier_accuracy': r.tier_accuracy,
                    'matchup_correlation': r.matchup_correlation,
                    'best_strategy': max(r.strategy_performance, key=r.strategy_performance.get)
                }
                for r in self.validation_results
            ]
        }
        
        output_file = Path(__file__).parent.parent / "data" / output_path
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\nReport saved to: {output_file}")
        return report


async def main():
    """Run validation for testing."""
    validator = ModelValidator()
    
    # Load historical data
    await validator.load_historical_data([2023, 2024])
    
    # Run validation for 2023 season
    summary = await validator.run_season_validation(2023, start_week=1, end_week=5)
    
    # Generate report
    validator.generate_report()
    
    return summary


if __name__ == "__main__":
    asyncio.run(main())