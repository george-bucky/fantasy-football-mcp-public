#!/usr/bin/env python3
"""
Backtest Runner - Main script to run comprehensive model validation

Usage:
    python backtest_runner.py --season 2023
    python backtest_runner.py --season 2023 --weeks 1-5
    python backtest_runner.py --full  # Run all available seasons
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime
import json
from typing import Dict, List

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from historical_validator import ModelValidator


class BacktestRunner:
    """Orchestrates comprehensive backtesting of the model."""
    
    def __init__(self):
        self.validator = ModelValidator()
        self.results = []
        
    async def run_backtest(self, seasons: List[int], 
                          start_week: int = 1, 
                          end_week: int = 17) -> Dict:
        """
        Run full backtest across multiple seasons.
        
        Args:
            seasons: List of seasons to test
            start_week: First week to test
            end_week: Last week to test
            
        Returns:
            Combined results dictionary
        """
        print("=" * 60)
        print("FANTASY FOOTBALL MODEL BACKTEST")
        print("=" * 60)
        print(f"Testing Seasons: {seasons}")
        print(f"Week Range: {start_week}-{end_week}")
        print("=" * 60)
        
        # Load all historical data
        print("\nLoading historical data...")
        await self.validator.load_historical_data(seasons)
        
        # Run validation for each season
        season_summaries = []
        for season in seasons:
            summary = await self.validator.run_season_validation(
                season, start_week, end_week
            )
            if summary:
                season_summaries.append(summary)
        
        # Calculate overall statistics
        if season_summaries:
            overall_stats = self.calculate_overall_statistics(season_summaries)
            self.generate_visualizations(season_summaries)
            
            return overall_stats
        
        return {}
    
    def calculate_overall_statistics(self, summaries: List[Dict]) -> Dict:
        """Calculate overall model performance statistics."""
        
        print("\n" + "=" * 60)
        print("OVERALL MODEL PERFORMANCE")
        print("=" * 60)
        
        # Extract key metrics
        lineup_accuracies = [s['avg_lineup_accuracy'] for s in summaries]
        tier_accuracies = [s['avg_tier_accuracy'] for s in summaries]
        matchup_correlations = [s['avg_matchup_correlation'] for s in summaries]
        
        stats = {
            'total_seasons_tested': len(summaries),
            'total_weeks_tested': sum(s['weeks_tested'] for s in summaries),
            
            # Lineup Accuracy
            'lineup_accuracy_mean': np.mean(lineup_accuracies),
            'lineup_accuracy_std': np.std(lineup_accuracies),
            'lineup_accuracy_min': np.min(lineup_accuracies),
            'lineup_accuracy_max': np.max(lineup_accuracies),
            
            # Tier System
            'tier_accuracy_mean': np.mean(tier_accuracies),
            'tier_accuracy_std': np.std(tier_accuracies),
            
            # Matchup Predictions
            'matchup_correlation_mean': np.mean(matchup_correlations),
            'matchup_correlation_std': np.std(matchup_correlations),
            
            # Best strategy across all seasons
            'best_overall_strategy': self._find_best_overall_strategy(summaries),
            
            # Statistical significance
            'model_improvement_vs_baseline': self._calculate_improvement(),
            
            'timestamp': datetime.now().isoformat()
        }
        
        # Print summary
        print(f"\nLineup Prediction Accuracy:")
        print(f"  Mean: {stats['lineup_accuracy_mean']:.2%} ± {stats['lineup_accuracy_std']:.2%}")
        print(f"  Range: {stats['lineup_accuracy_min']:.2%} - {stats['lineup_accuracy_max']:.2%}")
        
        print(f"\nTier System Accuracy:")
        print(f"  Mean: {stats['tier_accuracy_mean']:.2%} ± {stats['tier_accuracy_std']:.2%}")
        
        print(f"\nMatchup Correlation:")
        print(f"  Mean: {stats['matchup_correlation_mean']:.3f} ± {stats['matchup_correlation_std']:.3f}")
        
        print(f"\nBest Strategy: {stats['best_overall_strategy']}")
        
        # Check if model meets expected improvements
        self._validate_expected_improvements(stats)
        
        # Save detailed results
        self._save_results(stats)
        
        return stats
    
    def _find_best_overall_strategy(self, summaries: List[Dict]) -> str:
        """Find the best performing strategy across all seasons."""
        strategy_counts = {}
        for summary in summaries:
            strategy = summary.get('best_strategy', 'balanced')
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        
        return max(strategy_counts, key=strategy_counts.get)
    
    def _calculate_improvement(self) -> float:
        """
        Calculate improvement vs baseline (random selection).
        Baseline accuracy is typically around 45-50% for random lineups.
        """
        baseline_accuracy = 0.50
        
        if self.validator.validation_results:
            actual_accuracy = np.mean([r.lineup_accuracy for r in self.validator.validation_results])
            improvement = (actual_accuracy - baseline_accuracy) / baseline_accuracy
            return improvement
        
        return 0.0
    
    def _validate_expected_improvements(self, stats: Dict):
        """Check if model meets the expected +40% accuracy improvement."""
        print("\n" + "=" * 60)
        print("MODEL VALIDATION AGAINST EXPECTATIONS")
        print("=" * 60)
        
        # Expected: +40% accuracy improvement
        baseline = 0.50
        expected_accuracy = baseline * 1.40  # 70%
        actual_accuracy = stats['lineup_accuracy_mean']
        
        if actual_accuracy >= expected_accuracy:
            print(f"✅ PASS: Model accuracy ({actual_accuracy:.2%}) meets expected target ({expected_accuracy:.2%})")
        else:
            print(f"⚠️  NEEDS TUNING: Model accuracy ({actual_accuracy:.2%}) below target ({expected_accuracy:.2%})")
            print(f"   Shortfall: {(expected_accuracy - actual_accuracy):.2%}")
        
        # Check tier system
        if stats['tier_accuracy_mean'] >= 0.75:
            print(f"✅ PASS: Tier system ({stats['tier_accuracy_mean']:.2%}) correctly ranks players")
        else:
            print(f"⚠️  NEEDS TUNING: Tier system accuracy ({stats['tier_accuracy_mean']:.2%}) needs improvement")
        
        # Check matchup correlation
        if stats['matchup_correlation_mean'] >= 0.30:
            print(f"✅ PASS: Matchup predictions show positive correlation ({stats['matchup_correlation_mean']:.3f})")
        else:
            print(f"⚠️  WEAK: Matchup correlation ({stats['matchup_correlation_mean']:.3f}) is weak")
    
    def generate_visualizations(self, summaries: List[Dict]):
        """Generate visualization plots for the validation results."""
        try:
            import matplotlib.pyplot as plt
            import seaborn as sns
            
            sns.set_style("whitegrid")
            fig, axes = plt.subplots(2, 2, figsize=(12, 10))
            
            # Plot 1: Accuracy over time
            weeks = []
            accuracies = []
            for result in self.validator.validation_results:
                weeks.append(f"W{result.week}")
                accuracies.append(result.lineup_accuracy)
            
            if weeks and accuracies:
                axes[0, 0].plot(weeks[:20], accuracies[:20], marker='o')
                axes[0, 0].set_title('Lineup Accuracy by Week')
                axes[0, 0].set_xlabel('Week')
                axes[0, 0].set_ylabel('Accuracy')
                axes[0, 0].axhline(y=0.70, color='r', linestyle='--', label='Target (70%)')
                axes[0, 0].legend()
            
            # Plot 2: Strategy comparison
            if self.validator.validation_results:
                strategies = list(self.validator.validation_results[0].strategy_performance.keys())
                strategy_scores = {s: [] for s in strategies}
                
                for result in self.validator.validation_results:
                    for strategy, score in result.strategy_performance.items():
                        strategy_scores[strategy].append(score)
                
                strategy_means = [np.mean(strategy_scores[s]) for s in strategies]
                axes[0, 1].bar(strategies, strategy_means)
                axes[0, 1].set_title('Strategy Performance Comparison')
                axes[0, 1].set_ylabel('Average Accuracy')
            
            # Plot 3: Tier accuracy distribution
            tier_accuracies = [r.tier_accuracy for r in self.validator.validation_results]
            if tier_accuracies:
                axes[1, 0].hist(tier_accuracies, bins=20, edgecolor='black')
                axes[1, 0].set_title('Tier System Accuracy Distribution')
                axes[1, 0].set_xlabel('Accuracy')
                axes[1, 0].set_ylabel('Frequency')
                axes[1, 0].axvline(x=np.mean(tier_accuracies), color='r', linestyle='--', 
                                  label=f'Mean: {np.mean(tier_accuracies):.2%}')
                axes[1, 0].legend()
            
            # Plot 4: Matchup correlation
            matchup_corrs = [r.matchup_correlation for r in self.validator.validation_results]
            if matchup_corrs:
                axes[1, 1].scatter(range(len(matchup_corrs)), matchup_corrs, alpha=0.6)
                axes[1, 1].set_title('Matchup Score Correlation')
                axes[1, 1].set_xlabel('Week Index')
                axes[1, 1].set_ylabel('Correlation')
                axes[1, 1].axhline(y=0, color='black', linestyle='-', alpha=0.3)
                axes[1, 1].axhline(y=np.mean(matchup_corrs), color='r', linestyle='--',
                                  label=f'Mean: {np.mean(matchup_corrs):.3f}')
                axes[1, 1].legend()
            
            plt.suptitle('Fantasy Football Model Validation Results', fontsize=16)
            plt.tight_layout()
            
            # Save figure
            output_path = Path(__file__).parent.parent / "data" / "validation_plots.png"
            plt.savefig(output_path, dpi=100)
            print(f"\nVisualization saved to: {output_path}")
            
        except ImportError:
            print("\nSkipping visualizations (matplotlib/seaborn not available)")
        except Exception as e:
            print(f"\nError generating visualizations: {e}")
    
    def _save_results(self, stats: Dict):
        """Save detailed results to JSON file."""
        output_path = Path(__file__).parent.parent / "data" / "backtest_results.json"
        
        with open(output_path, 'w') as f:
            json.dump(stats, f, indent=2)
        
        print(f"\nDetailed results saved to: {output_path}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Run Fantasy Football Model Backtest')
    parser.add_argument('--season', type=int, help='Season to test (e.g., 2023)')
    parser.add_argument('--seasons', type=str, help='Multiple seasons (e.g., "2023,2024")')
    parser.add_argument('--weeks', type=str, default='1-17', 
                       help='Week range (e.g., "1-5" or "1-17")')
    parser.add_argument('--full', action='store_true', 
                       help='Run full validation on all available seasons')
    
    args = parser.parse_args()
    
    # Determine seasons to test
    if args.full:
        seasons = [2023, 2024]
    elif args.seasons:
        seasons = [int(s) for s in args.seasons.split(',')]
    elif args.season:
        seasons = [args.season]
    else:
        seasons = [2023]  # Default
    
    # Parse week range
    if '-' in args.weeks:
        start_week, end_week = map(int, args.weeks.split('-'))
    else:
        start_week = end_week = int(args.weeks)
    
    # Run backtest
    runner = BacktestRunner()
    results = await runner.run_backtest(seasons, start_week, end_week)
    
    print("\n" + "=" * 60)
    print("BACKTEST COMPLETE")
    print("=" * 60)
    
    return results


if __name__ == "__main__":
    asyncio.run(main())