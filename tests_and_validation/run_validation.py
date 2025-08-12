#!/usr/bin/env python3
"""
Simple Validation Runner - Easy one-command testing

Just run: python tests_and_validation/run_validation.py

This will:
1. Download historical data (cached after first run)
2. Run rolling holdout validation
3. Show key metrics in a clean format
4. Save detailed results for later analysis
"""

import asyncio
import sys
from pathlib import Path

# Add validation directory to path
sys.path.append(str(Path(__file__).parent / "validation"))

from advanced_validator import AdvancedValidator


async def quick_validation():
    """Run a quick validation with sensible defaults."""
    
    print("\n" + "="*60)
    print("🏈 FANTASY FOOTBALL MODEL VALIDATION")
    print("="*60)
    print("\nThis will validate the model using 2023 NFL data")
    print("Using rolling holdout: train on weeks 1-N, predict N+1")
    print("-"*60)
    
    validator = AdvancedValidator()
    
    # Use a realistic roster (top fantasy players from 2023)
    roster = [
        # QBs
        "Josh Allen", "Jalen Hurts", "Lamar Jackson",
        # RBs  
        "Christian McCaffrey", "Austin Ekeler", "Nick Chubb", "Tony Pollard",
        # WRs
        "Tyreek Hill", "CeeDee Lamb", "Justin Jefferson", "AJ Brown", "Stefon Diggs",
        # TEs
        "Travis Kelce", "Mark Andrews",
        # K
        "Justin Tucker",
        # DEF
        "Dallas Cowboys"
    ]
    
    print("\n📊 Loading 2023 NFL data...")
    try:
        await validator.load_historical_data([2023])
        print("✅ Data loaded successfully!")
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        print("\nTrying to install nfl_data_py...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "nfl-data-py"])
        print("Retry after installing dependency")
        return
    
    print("\n🔄 Running validation (this takes ~30 seconds)...")
    summary = await validator.run_rolling_validation(2023, roster, min_train_weeks=4)
    
    if summary:
        print("\n" + "="*60)
        print("✅ VALIDATION COMPLETE - KEY FINDINGS")
        print("="*60)
        
        # Interpret results
        mae = summary.get('mae_mean', 0)
        precision = summary.get('precision_mean', 0)
        decision_value = summary.get('decision_value_mean', 0)
        efficiency = summary.get('efficiency_mean', 0)
        
        print("\n📈 Model Performance:")
        
        # MAE interpretation
        if mae < 5:
            print(f"  ✅ Excellent: Off by only {mae:.1f} points on average")
        elif mae < 8:
            print(f"  ✅ Good: Off by {mae:.1f} points on average")
        else:
            print(f"  ⚠️  Needs work: Off by {mae:.1f} points on average")
        
        # Precision interpretation
        if precision > 0.70:
            print(f"  ✅ Excellent: {precision:.0%} of 'start' recommendations performed well")
        elif precision > 0.60:
            print(f"  ✅ Good: {precision:.0%} of 'start' recommendations performed well")
        else:
            print(f"  ⚠️  Needs tuning: Only {precision:.0%} of 'start' recommendations performed well")
        
        # Decision value
        if decision_value > 5:
            print(f"  ✅ Great value: Starters scored {decision_value:.1f} pts more than bench")
        elif decision_value > 0:
            print(f"  ✅ Positive value: Starters scored {decision_value:.1f} pts more than bench")
        else:
            print(f"  ❌ Problem: Bench outscored starters!")
        
        # Efficiency
        if efficiency > 0.85:
            print(f"  ✅ Excellent: Achieved {efficiency:.0%} of optimal lineup score")
        elif efficiency > 0.75:
            print(f"  ✅ Good: Achieved {efficiency:.0%} of optimal lineup score")
        else:
            print(f"  ⚠️  Room for improvement: Only {efficiency:.0%} of optimal")
        
        # Overall assessment
        print("\n🎯 Overall Assessment:")
        
        score = 0
        if mae < 8: score += 1
        if precision > 0.65: score += 1
        if decision_value > 3: score += 1
        if efficiency > 0.80: score += 1
        
        if score >= 3:
            print("  ✅ MODEL IS WORKING WELL!")
            print("  The statistical refinements are showing positive results.")
        elif score >= 2:
            print("  ✅ MODEL IS DECENT")
            print("  Some metrics are good, but there's room for improvement.")
        else:
            print("  ⚠️  MODEL NEEDS TUNING")
            print("  Consider adjusting tier multipliers and weights.")
        
        # Save results
        validator.export_results("quick_validation_results.json")
        print("\n💾 Detailed results saved to: tests_and_validation/data/quick_validation_results.json")
        
    else:
        print("\n❌ Validation failed - check error messages above")
    
    print("\n" + "="*60)
    print("Done! Check the metrics above to see how well the model performs.")
    print("="*60 + "\n")


async def full_validation():
    """Run comprehensive validation on multiple seasons."""
    
    print("\n" + "="*60)
    print("🏈 COMPREHENSIVE MODEL VALIDATION")
    print("="*60)
    
    validator = AdvancedValidator()
    
    # Expanded roster
    roster = [
        # QBs
        "Josh Allen", "Jalen Hurts", "Lamar Jackson", "Patrick Mahomes", "Dak Prescott",
        # RBs
        "Christian McCaffrey", "Austin Ekeler", "Nick Chubb", "Tony Pollard",
        "Saquon Barkley", "Derrick Henry", "Josh Jacobs", "Rhamondre Stevenson",
        # WRs
        "Tyreek Hill", "CeeDee Lamb", "Justin Jefferson", "AJ Brown", 
        "Stefon Diggs", "Cooper Kupp", "Davante Adams", "Chris Olave",
        # TEs
        "Travis Kelce", "Mark Andrews", "TJ Hockenson", "George Kittle",
        # K
        "Justin Tucker", "Daniel Carlson",
        # DEF
        "Dallas Cowboys", "San Francisco 49ers"
    ]
    
    print("\n📊 Loading 2023-2024 NFL data...")
    await validator.load_historical_data([2023, 2024])
    
    print("\n🔄 Running comprehensive validation...")
    
    # Test both seasons
    all_summaries = []
    for season in [2023, 2024]:
        print(f"\n--- Season {season} ---")
        summary = await validator.run_rolling_validation(season, roster)
        if summary:
            all_summaries.append(summary)
    
    # Overall summary
    if all_summaries:
        print("\n" + "="*60)
        print("📊 MULTI-SEASON SUMMARY")
        print("="*60)
        
        avg_mae = sum(s['mae_mean'] for s in all_summaries) / len(all_summaries)
        avg_precision = sum(s['precision_mean'] for s in all_summaries) / len(all_summaries)
        avg_value = sum(s['decision_value_mean'] for s in all_summaries) / len(all_summaries)
        
        print(f"Average MAE: {avg_mae:.2f} points")
        print(f"Average Precision: {avg_precision:.2%}")
        print(f"Average Decision Value: {avg_value:.2f} points/week")
        
        validator.export_results("comprehensive_validation_results.json")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run Fantasy Football Model Validation')
    parser.add_argument('--full', action='store_true', help='Run full multi-season validation')
    parser.add_argument('--quick', action='store_true', help='Run quick validation (default)')
    
    args = parser.parse_args()
    
    if args.full:
        asyncio.run(full_validation())
    else:
        # Default to quick validation
        asyncio.run(quick_validation())