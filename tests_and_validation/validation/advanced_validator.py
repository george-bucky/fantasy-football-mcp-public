#!/usr/bin/env python3
"""
Advanced Model Validator with Holdout Validation and Comprehensive Metrics

Implements:
- Rolling holdout validation (train on weeks 1-N, predict N+1)
- Binary classification metrics for start/sit decisions
- Regression metrics for point predictions
- Per-position analysis
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
from sklearn.metrics import (
    mean_absolute_error, 
    mean_squared_error, 
    r2_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix
)
import nfl_data_py as nfl

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from lineup_optimizer import LineupOptimizer, Player
from matchup_analyzer import MatchupAnalyzer


@dataclass
class HoldoutValidationResult:
    """Results from a single holdout week validation."""
    season: int
    train_weeks: Tuple[int, int]  # (start_week, end_week)
    test_week: int
    
    # Regression metrics (point predictions)
    mae: float  # Mean Absolute Error
    rmse: float  # Root Mean Square Error
    r2: float  # R-squared
    
    # Binary classification metrics (start/sit)
    precision: float  # When we said "start", how often were they good?
    recall: float  # Of all good performances, how many did we identify?
    f1: float  # Harmonic mean of precision and recall
    
    # Decision value metrics
    avg_starter_score: float  # Average score of recommended starters
    avg_bench_score: float  # Average score of recommended bench
    decision_value: float  # Difference between starters and bench
    
    # Per-position breakdown
    position_metrics: Dict[str, Dict[str, float]]
    
    # Lineup performance
    recommended_lineup_score: float
    optimal_lineup_score: float
    lineup_efficiency: float  # recommended/optimal ratio


class AdvancedValidator:
    """Advanced validation with proper train/test splits and metrics."""
    
    def __init__(self):
        self.optimizer = LineupOptimizer()
        self.matchup_analyzer = MatchupAnalyzer()
        self.historical_data = None
        self.validation_results = []
        
    async def load_historical_data(self, seasons: List[int]) -> pd.DataFrame:
        """Load and cache historical data."""
        print(f"Loading historical data for seasons: {seasons}")
        
        try:
            # Try cache first
            cache_path = Path(__file__).parent.parent / "data" / "nfl_historical.parquet"
            if cache_path.exists():
                print("Loading from cache...")
                self.historical_data = pd.read_parquet(cache_path)
                # Filter to requested seasons
                self.historical_data = self.historical_data[
                    self.historical_data['season'].isin(seasons)
                ]
            else:
                # Load from API
                self.historical_data = nfl.import_weekly_data(seasons)
                # Cache for future use
                cache_path.parent.mkdir(exist_ok=True)
                self.historical_data.to_parquet(cache_path)
            
            print(f"Loaded {len(self.historical_data)} player-week records")
            return self.historical_data
            
        except Exception as e:
            print(f"Error loading data: {e}")
            raise
    
    def prepare_training_data(self, season: int, train_weeks: Tuple[int, int]) -> pd.DataFrame:
        """
        Prepare training data for model calibration.
        
        Returns aggregated stats for weeks in training range.
        """
        start_week, end_week = train_weeks
        
        train_data = self.historical_data[
            (self.historical_data['season'] == season) &
            (self.historical_data['week'] >= start_week) &
            (self.historical_data['week'] <= end_week)
        ]
        
        # Aggregate player statistics
        player_stats = train_data.groupby('player_display_name').agg({
            'fantasy_points_ppr': ['mean', 'std', 'min', 'max'],
            'position': 'first',
            'recent_team': 'last'
        }).reset_index()
        
        # Flatten column names
        player_stats.columns = ['_'.join(col).strip('_') for col in player_stats.columns.values]
        
        return player_stats
    
    def calculate_dynamic_tiers(self, train_data: pd.DataFrame) -> Dict[str, Dict[str, float]]:
        """
        Calculate position-specific tier thresholds from training data.
        """
        tiers = {}
        
        for position in ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']:
            pos_data = train_data[train_data['position_first'] == position]
            
            if len(pos_data) < 10:
                continue
            
            # Calculate percentiles
            scores = pos_data['fantasy_points_ppr_mean'].values
            percentiles = np.percentile(scores, [90, 75, 50, 25])
            
            tiers[position] = {
                'elite': percentiles[0],
                'stud': percentiles[1],
                'solid': percentiles[2],
                'flex': percentiles[3]
            }
        
        return tiers
    
    async def validate_holdout_week(self, season: int, train_weeks: Tuple[int, int], 
                                   test_week: int, roster: List[str]) -> HoldoutValidationResult:
        """
        Validate on a single holdout week.
        
        Train model on weeks 1-N, predict week N+1, compare to actual.
        """
        print(f"Validating Season {season}, Week {test_week} (trained on weeks {train_weeks[0]}-{train_weeks[1]})")
        
        # Prepare training data
        train_data = self.prepare_training_data(season, train_weeks)
        
        # Calculate dynamic tiers from training data
        dynamic_tiers = self.calculate_dynamic_tiers(train_data)
        self.optimizer.dynamic_thresholds = dynamic_tiers
        
        # Get test week data
        test_data = self.historical_data[
            (self.historical_data['season'] == season) &
            (self.historical_data['week'] == test_week)
        ]
        
        # Create Player objects with "projections" based on training data
        players = []
        predictions = {}
        actuals = {}
        
        for player_name in roster:
            # Get training stats for projection
            train_stats = train_data[train_data['player_display_name'] == player_name]
            
            if train_stats.empty:
                continue
            
            # Get actual test week performance
            test_performance = test_data[test_data['player_display_name'] == player_name]
            
            if test_performance.empty:
                continue
            
            stats = train_stats.iloc[0]
            actual = test_performance.iloc[0]
            
            # Create player with "projection" (using training mean)
            player = Player(
                name=player_name,
                position=stats['position_first'],
                team=actual['recent_team'] if 'recent_team' in actual else "",
                opponent=actual['opponent_team'] if 'opponent_team' in actual else "",
                yahoo_projection=stats['fantasy_points_ppr_mean'],
                sleeper_projection=stats['fantasy_points_ppr_mean'] * 0.95,  # Slight variation
            )
            
            # Add recent scores for momentum
            recent_weeks = self.historical_data[
                (self.historical_data['season'] == season) &
                (self.historical_data['week'] < test_week) &
                (self.historical_data['week'] >= max(1, test_week - 5)) &
                (self.historical_data['player_display_name'] == player_name)
            ].sort_values('week', ascending=False)
            
            if not recent_weeks.empty:
                player.recent_scores = recent_weeks['fantasy_points_ppr'].values.tolist()
            
            players.append(player)
            
            # Store for metrics calculation
            predictions[player_name] = player.yahoo_projection
            actuals[player_name] = actual['fantasy_points_ppr']
        
        if not players:
            print(f"No valid players for week {test_week}")
            return None
        
        # Enhance players with our analysis
        players = await self.optimizer.enhance_with_external_data(players)
        
        # Get optimal lineup recommendation
        lineup_result = self.optimizer.optimize_lineup(players, strategy="balanced")
        
        # Calculate regression metrics
        pred_values = list(predictions.values())
        actual_values = list(actuals.values())
        
        mae = mean_absolute_error(actual_values, pred_values)
        rmse = np.sqrt(mean_squared_error(actual_values, pred_values))
        r2 = r2_score(actual_values, pred_values) if len(actual_values) > 1 else 0.0
        
        # Calculate binary classification metrics for start/sit
        # Define "good performance" as scoring above position average
        position_avgs = test_data.groupby('position')['fantasy_points_ppr'].mean().to_dict()
        
        # Binary labels: 1 if player exceeded position average, 0 otherwise
        actual_binary = []
        pred_binary = []
        
        for player in players:
            if player.name in actuals:
                actual_score = actuals[player.name]
                pos_avg = position_avgs.get(player.position, 10)
                
                # Actual: did they exceed position average?
                actual_binary.append(1 if actual_score > pos_avg else 0)
                
                # Predicted: did we recommend starting them?
                is_starter = any(p.name == player.name for p in lineup_result['starters'].values())
                pred_binary.append(1 if is_starter else 0)
        
        if actual_binary and pred_binary:
            precision = precision_score(actual_binary, pred_binary, zero_division=0)
            recall = recall_score(actual_binary, pred_binary, zero_division=0)
            f1 = f1_score(actual_binary, pred_binary, zero_division=0)
        else:
            precision = recall = f1 = 0.0
        
        # Calculate decision value
        starter_scores = []
        bench_scores = []
        
        for pos, player in lineup_result['starters'].items():
            if player.name in actuals:
                starter_scores.append(actuals[player.name])
        
        for player in lineup_result['bench']:
            if player.name in actuals:
                bench_scores.append(actuals[player.name])
        
        avg_starter = np.mean(starter_scores) if starter_scores else 0
        avg_bench = np.mean(bench_scores) if bench_scores else 0
        decision_value = avg_starter - avg_bench
        
        # Calculate lineup efficiency
        recommended_score = sum(starter_scores)
        
        # Find optimal lineup (hindsight)
        all_scores = [(p, actuals.get(p.name, 0)) for p in players]
        all_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Build optimal lineup respecting position limits
        optimal_score = self._calculate_optimal_lineup_score(all_scores)
        
        lineup_efficiency = recommended_score / optimal_score if optimal_score > 0 else 0
        
        # Per-position metrics
        position_metrics = self._calculate_position_metrics(players, predictions, actuals)
        
        # Create result
        result = HoldoutValidationResult(
            season=season,
            train_weeks=train_weeks,
            test_week=test_week,
            mae=mae,
            rmse=rmse,
            r2=r2,
            precision=precision,
            recall=recall,
            f1=f1,
            avg_starter_score=avg_starter,
            avg_bench_score=avg_bench,
            decision_value=decision_value,
            position_metrics=position_metrics,
            recommended_lineup_score=recommended_score,
            optimal_lineup_score=optimal_score,
            lineup_efficiency=lineup_efficiency
        )
        
        self.validation_results.append(result)
        return result
    
    def _calculate_optimal_lineup_score(self, scored_players: List[Tuple[Player, float]]) -> float:
        """Calculate the optimal possible lineup score with position constraints."""
        positions_filled = {'QB': 0, 'RB': 0, 'WR': 0, 'TE': 0, 'FLEX': 0, 'K': 0, 'DEF': 0}
        max_positions = {'QB': 1, 'RB': 2, 'WR': 2, 'TE': 1, 'FLEX': 1, 'K': 1, 'DEF': 1}
        
        optimal_score = 0
        
        for player, score in scored_players:
            pos = player.position
            
            # Check if we can add this player
            if pos in positions_filled and positions_filled[pos] < max_positions[pos]:
                optimal_score += score
                positions_filled[pos] += 1
            elif pos in ['RB', 'WR', 'TE'] and positions_filled['FLEX'] < max_positions['FLEX']:
                # Use as FLEX
                optimal_score += score
                positions_filled['FLEX'] += 1
        
        return optimal_score
    
    def _calculate_position_metrics(self, players: List[Player], 
                                   predictions: Dict[str, float], 
                                   actuals: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        """Calculate metrics broken down by position."""
        position_metrics = {}
        
        for position in ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']:
            pos_players = [p for p in players if p.position == position]
            
            if not pos_players:
                continue
            
            pos_preds = [predictions.get(p.name, 0) for p in pos_players]
            pos_actuals = [actuals.get(p.name, 0) for p in pos_players]
            
            if pos_preds and pos_actuals:
                position_metrics[position] = {
                    'mae': mean_absolute_error(pos_actuals, pos_preds),
                    'rmse': np.sqrt(mean_squared_error(pos_actuals, pos_preds)),
                    'count': len(pos_players)
                }
        
        return position_metrics
    
    async def run_rolling_validation(self, season: int, roster: List[str], 
                                    min_train_weeks: int = 4) -> Dict:
        """
        Run rolling holdout validation for a season.
        
        Start with weeks 1-4 to predict week 5, then 1-5 to predict 6, etc.
        """
        print(f"\nRunning Rolling Holdout Validation for Season {season}")
        print("=" * 60)
        
        results = []
        
        # Start predictions after minimum training weeks
        for test_week in range(min_train_weeks + 1, 18):  # Weeks 5-17
            train_weeks = (1, test_week - 1)
            
            try:
                result = await self.validate_holdout_week(
                    season, train_weeks, test_week, roster
                )
                
                if result:
                    results.append(result)
                    print(f"  Week {test_week}: MAE={result.mae:.2f}, "
                          f"Precision={result.precision:.2%}, "
                          f"Decision Value={result.decision_value:.2f}, "
                          f"Efficiency={result.lineup_efficiency:.2%}")
                          
            except Exception as e:
                print(f"  Week {test_week}: Error - {e}")
                continue
        
        # Calculate aggregate statistics
        if results:
            summary = self._calculate_validation_summary(results)
            print("\n" + "=" * 60)
            print("ROLLING VALIDATION SUMMARY")
            print("=" * 60)
            print(f"Weeks Tested: {len(results)}")
            print(f"\nRegression Metrics:")
            print(f"  MAE: {summary['mae_mean']:.2f} ± {summary['mae_std']:.2f} points")
            print(f"  RMSE: {summary['rmse_mean']:.2f} points")
            print(f"  R²: {summary['r2_mean']:.3f}")
            print(f"\nClassification Metrics (Start/Sit):")
            print(f"  Precision: {summary['precision_mean']:.2%} (when we say 'start', they perform)")
            print(f"  Recall: {summary['recall_mean']:.2%} (catching breakout performances)")
            print(f"  F1 Score: {summary['f1_mean']:.2%}")
            print(f"\nDecision Value:")
            print(f"  Starters avg: {summary['avg_starter_mean']:.1f} pts")
            print(f"  Bench avg: {summary['avg_bench_mean']:.1f} pts")
            print(f"  Value added: +{summary['decision_value_mean']:.2f} pts/week")
            print(f"\nLineup Efficiency: {summary['efficiency_mean']:.2%} of optimal")
            
            return summary
        
        return {}
    
    def _calculate_validation_summary(self, results: List[HoldoutValidationResult]) -> Dict:
        """Calculate summary statistics from validation results."""
        summary = {
            # Regression metrics
            'mae_mean': np.mean([r.mae for r in results]),
            'mae_std': np.std([r.mae for r in results]),
            'rmse_mean': np.mean([r.rmse for r in results]),
            'r2_mean': np.mean([r.r2 for r in results]),
            
            # Classification metrics
            'precision_mean': np.mean([r.precision for r in results]),
            'recall_mean': np.mean([r.recall for r in results]),
            'f1_mean': np.mean([r.f1 for r in results]),
            
            # Decision value
            'avg_starter_mean': np.mean([r.avg_starter_score for r in results]),
            'avg_bench_mean': np.mean([r.avg_bench_score for r in results]),
            'decision_value_mean': np.mean([r.decision_value for r in results]),
            
            # Efficiency
            'efficiency_mean': np.mean([r.lineup_efficiency for r in results]),
            'efficiency_std': np.std([r.lineup_efficiency for r in results]),
            
            # Position breakdown
            'position_performance': self._aggregate_position_metrics(results)
        }
        
        return summary
    
    def _aggregate_position_metrics(self, results: List[HoldoutValidationResult]) -> Dict:
        """Aggregate position-specific metrics across all weeks."""
        position_data = {}
        
        for position in ['QB', 'RB', 'WR', 'TE']:
            mae_values = []
            for result in results:
                if position in result.position_metrics:
                    mae_values.append(result.position_metrics[position]['mae'])
            
            if mae_values:
                position_data[position] = {
                    'mae_mean': np.mean(mae_values),
                    'mae_std': np.std(mae_values)
                }
        
        return position_data
    
    def export_results(self, filepath: str = "rolling_validation_results.json"):
        """Export validation results to JSON."""
        output = {
            'timestamp': datetime.now().isoformat(),
            'results': [
                {
                    'season': int(r.season),
                    'test_week': int(r.test_week),
                    'train_weeks': f"{r.train_weeks[0]}-{r.train_weeks[1]}",
                    'mae': float(r.mae),
                    'rmse': float(r.rmse),
                    'r2': float(r.r2),
                    'precision': float(r.precision),
                    'recall': float(r.recall),
                    'f1': float(r.f1),
                    'decision_value': float(r.decision_value),
                    'lineup_efficiency': float(r.lineup_efficiency)
                }
                for r in self.validation_results
            ]
        }
        
        output_path = Path(__file__).parent.parent / "data" / filepath
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"\nResults exported to: {output_path}")


async def main():
    """Run advanced validation."""
    validator = AdvancedValidator()
    
    # Sample roster for testing
    sample_roster = [
        "Josh Allen", "Lamar Jackson", "Justin Herbert",
        "Christian McCaffrey", "Saquon Barkley", "Tony Pollard", "Austin Ekeler",
        "CeeDee Lamb", "Tyreek Hill", "AJ Brown", "Mike Evans", "Chris Olave",
        "Travis Kelce", "Mark Andrews",
        "Harrison Butker", "Justin Tucker",
        "Buffalo Bills", "Baltimore Ravens"
    ]
    
    # Load data
    await validator.load_historical_data([2023])
    
    # Run rolling validation
    summary = await validator.run_rolling_validation(2023, sample_roster)
    
    # Export results
    validator.export_results()
    
    return summary


if __name__ == "__main__":
    asyncio.run(main())