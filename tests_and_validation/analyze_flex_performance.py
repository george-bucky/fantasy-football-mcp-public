#!/usr/bin/env python3
"""
Analyze FLEX Performance - Detailed analysis of FLEX decisions

Provides detailed data on:
- Position vs position win rates
- Projection accuracy by position
- When the model gets it right/wrong
- Position normalization impact
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
import pandas as pd
import numpy as np

# Add parent directory
sys.path.append(str(Path(__file__).parent.parent))
from position_normalizer import position_normalizer


def load_decision_data():
    """Load the real decision results."""
    path = Path(__file__).parent / "data" / "real_decision_results.json"
    with open(path, 'r') as f:
        return json.load(f)


def analyze_flex_decisions(data):
    """Analyze FLEX-specific decisions."""
    flex_decisions = [
        d for d in data['decisions'] 
        if d['type'] == 'flex'
    ]
    
    if not flex_decisions:
        print("No FLEX decisions found in data")
        return
    
    print("\n" + "="*60)
    print("FLEX DECISION ANALYSIS")
    print("="*60)
    
    # Overall FLEX performance
    correct = sum(1 for d in flex_decisions if d['was_correct'])
    total = len(flex_decisions)
    accuracy = correct / total if total > 0 else 0
    
    print(f"\n📊 Overall FLEX Performance:")
    print(f"  Total FLEX decisions: {total}")
    print(f"  Correct: {correct}")
    print(f"  Accuracy: {accuracy:.1%}")
    
    # Points impact
    total_impact = sum(d['points_impact'] for d in flex_decisions)
    avg_impact = total_impact / total if total > 0 else 0
    
    print(f"\n💰 Points Impact:")
    print(f"  Total points gained/lost: {total_impact:+.1f}")
    print(f"  Average per decision: {avg_impact:+.2f}")
    
    # Analyze by position matchup
    print(f"\n🎯 Position Matchups in FLEX:")
    position_matchups = defaultdict(lambda: {'wins': 0, 'losses': 0})
    
    for decision in flex_decisions:
        choice = decision['choice']
        alternative = decision['alternative']
        
        # Determine positions (simplified - would need actual data)
        # For now, infer from names
        choice_pos = infer_position(choice)
        alt_pos = infer_position(alternative)
        
        matchup_key = f"{choice_pos} vs {alt_pos}"
        
        if decision['was_correct']:
            position_matchups[matchup_key]['wins'] += 1
        else:
            position_matchups[matchup_key]['losses'] += 1
    
    for matchup, results in position_matchups.items():
        wins = results['wins']
        losses = results['losses']
        total_matchup = wins + losses
        win_rate = wins / total_matchup if total_matchup > 0 else 0
        print(f"  {matchup}: {wins}-{losses} ({win_rate:.0%} win rate)")
    
    # Projection differential analysis
    print(f"\n📈 Projection Analysis:")
    projection_diffs = []
    
    for decision in flex_decisions:
        # Get projection differences
        choice_proj = decision['model_scores'].get(decision['choice'], 0)
        alt_proj = decision['model_scores'].get(decision['alternative'], 0)
        proj_diff = choice_proj - alt_proj
        
        actual_diff = decision['points_impact'] if decision['was_correct'] else -abs(decision['points_impact'])
        
        projection_diffs.append({
            'week': decision['week'],
            'proj_diff': proj_diff,
            'actual_diff': actual_diff,
            'correct': decision['was_correct']
        })
    
    # Group by projection difference ranges
    print("  Model confidence vs accuracy:")
    
    # High confidence (>5 point difference)
    high_conf = [d for d in projection_diffs if abs(d['proj_diff']) > 5]
    if high_conf:
        high_acc = sum(1 for d in high_conf if d['correct']) / len(high_conf)
        print(f"    High confidence (>5 pt diff): {high_acc:.0%} accurate ({len(high_conf)} decisions)")
    
    # Medium confidence (2-5 point difference)
    med_conf = [d for d in projection_diffs if 2 <= abs(d['proj_diff']) <= 5]
    if med_conf:
        med_acc = sum(1 for d in med_conf if d['correct']) / len(med_conf)
        print(f"    Medium confidence (2-5 pt diff): {med_acc:.0%} accurate ({len(med_conf)} decisions)")
    
    # Low confidence (<2 point difference)
    low_conf = [d for d in projection_diffs if abs(d['proj_diff']) < 2]
    if low_conf:
        low_acc = sum(1 for d in low_conf if d['correct']) / len(low_conf)
        print(f"    Low confidence (<2 pt diff): {low_acc:.0%} accurate ({len(low_conf)} decisions)")
    
    # Week-by-week breakdown
    print(f"\n📅 Week-by-Week FLEX Performance:")
    for decision in flex_decisions:
        status = "✅" if decision['was_correct'] else "❌"
        impact = decision['points_impact']
        print(f"  Week {decision['week']}: {status} {decision['choice']} over {decision['alternative']} ({impact:+.1f} pts)")


def infer_position(player_name):
    """Infer position from player name (simplified)."""
    # Common patterns
    if any(te in player_name.lower() for te in ['kelce', 'kittle', 'andrews', 'goedert']):
        return 'TE'
    elif any(wr in player_name.lower() for wr in ['hill', 'lamb', 'evans', 'olave', 'hopkins', 'kirk', 'cooper']):
        return 'WR'
    elif any(rb in player_name.lower() for rb in ['mccaffrey', 'pollard', 'williams', 'pierce', 'white']):
        return 'RB'
    return 'UNK'


def analyze_position_decisions(data):
    """Analyze RB and WR specific decisions."""
    rb_decisions = [d for d in data['decisions'] if d['type'] == 'rb_decision']
    wr_decisions = [d for d in data['decisions'] if d['type'] == 'wr_decision']
    
    print("\n" + "="*60)
    print("POSITION-SPECIFIC DECISION ANALYSIS")
    print("="*60)
    
    # RB decisions
    if rb_decisions:
        rb_correct = sum(1 for d in rb_decisions if d['was_correct'])
        rb_accuracy = rb_correct / len(rb_decisions)
        rb_points = sum(d['points_impact'] for d in rb_decisions)
        
        print(f"\n🏃 RB vs RB Decisions:")
        print(f"  Total: {len(rb_decisions)}")
        print(f"  Accuracy: {rb_accuracy:.1%}")
        print(f"  Points impact: {rb_points:+.1f} total")
        
        # Show specific matchups
        print("  Notable decisions:")
        for d in rb_decisions[:3]:  # Show first 3
            status = "✅" if d['was_correct'] else "❌"
            print(f"    Week {d['week']}: {status} {d['choice']} > {d['alternative']} ({d['points_impact']:+.1f})")
    
    # WR decisions
    if wr_decisions:
        wr_correct = sum(1 for d in wr_decisions if d['was_correct'])
        wr_accuracy = wr_correct / len(wr_decisions)
        wr_points = sum(d['points_impact'] for d in wr_decisions)
        
        print(f"\n🎯 WR vs WR Decisions:")
        print(f"  Total: {len(wr_decisions)}")
        print(f"  Accuracy: {wr_accuracy:.1%}")
        print(f"  Points impact: {wr_points:+.1f} total")
        
        # Show specific matchups
        print("  Notable decisions:")
        for d in wr_decisions[:3]:  # Show first 3
            status = "✅" if d['was_correct'] else "❌"
            print(f"    Week {d['week']}: {status} {d['choice']} > {d['alternative']} ({d['points_impact']:+.1f})")


def test_position_normalizer():
    """Test the position normalizer with various scenarios."""
    print("\n" + "="*60)
    print("POSITION NORMALIZER TESTING")
    print("="*60)
    
    test_cases = [
        # (projection, position, name)
        (12.0, "RB", "Christian McCaffrey"),
        (12.0, "WR", "Tyreek Hill"),
        (12.0, "TE", "Travis Kelce"),
        (8.0, "RB", "Tony Pollard"),
        (8.0, "WR", "Chris Olave"),
        (8.0, "TE", "Dallas Goedert"),
        (15.0, "RB", "Austin Ekeler"),
        (15.0, "WR", "CeeDee Lamb"),
        (10.0, "TE", "Mark Andrews"),
    ]
    
    print("\n📊 Position-Relative Values:")
    print(f"{'Player':<25} {'Pos':<4} {'Proj':<6} {'Z-Score':<8} {'%ile':<6} {'FLEX':<6}")
    print("-" * 60)
    
    for proj, pos, name in test_cases:
        z_score = position_normalizer.normalize_projection(proj, pos)
        percentile = position_normalizer.get_percentile_rank(proj, pos)
        flex_value = position_normalizer.get_flex_value(proj, pos)
        
        print(f"{name:<25} {pos:<4} {proj:<6.1f} {z_score:<+8.2f} {percentile:<6.0f} {flex_value:<6.1f}")
    
    print("\n🔄 Direct FLEX Comparisons:")
    comparisons = [
        ((10.0, "RB", "RB Player"), (10.0, "WR", "WR Player")),
        ((9.0, "TE", "TE Player"), (10.0, "RB", "RB Player")),
        ((8.0, "RB", "RB Player"), (8.0, "TE", "TE Player")),
        ((12.0, "WR", "WR Player"), (11.0, "RB", "RB Player")),
    ]
    
    for (proj_a, pos_a, name_a), (proj_b, pos_b, name_b) in comparisons:
        winner = position_normalizer.compare_for_flex(
            (proj_a, pos_a), 
            (proj_b, pos_b)
        )
        winner_name = name_a if winner == "A" else name_b
        
        flex_a = position_normalizer.get_flex_value(proj_a, pos_a)
        flex_b = position_normalizer.get_flex_value(proj_b, pos_b)
        
        print(f"\n  {name_a} ({proj_a} {pos_a}) vs {name_b} ({proj_b} {pos_b})")
        print(f"    FLEX values: {flex_a:.1f} vs {flex_b:.1f}")
        print(f"    Winner: {winner_name}")


def calculate_summary_stats(data):
    """Calculate summary statistics."""
    print("\n" + "="*60)
    print("SUMMARY STATISTICS")
    print("="*60)
    
    all_decisions = data['decisions']
    
    # Overall metrics
    total = len(all_decisions)
    correct = sum(1 for d in all_decisions if d['was_correct'])
    accuracy = correct / total if total > 0 else 0
    
    # Points metrics
    total_points = sum(d['points_impact'] for d in all_decisions)
    avg_points = total_points / total if total > 0 else 0
    
    # Best and worst decisions
    best = max(all_decisions, key=lambda x: x['points_impact'])
    worst = min(all_decisions, key=lambda x: x['points_impact'])
    
    print(f"\n📊 Overall Performance:")
    print(f"  Total decisions: {total}")
    print(f"  Accuracy: {accuracy:.1%}")
    print(f"  Total points gained: {total_points:+.1f}")
    print(f"  Average per decision: {avg_points:+.2f}")
    
    print(f"\n🏆 Best Decision:")
    print(f"  Week {best['week']}: {best['choice']} over {best['alternative']}")
    print(f"  Points gained: +{best['points_impact']:.1f}")
    
    print(f"\n😰 Worst Decision:")
    print(f"  Week {worst['week']}: {worst['choice']} over {worst['alternative']}")
    print(f"  Points lost: {worst['points_impact']:.1f}")
    
    # Decision confidence correlation
    print(f"\n🎯 Model Confidence Analysis:")
    
    confident_right = 0
    confident_wrong = 0
    close_right = 0
    close_wrong = 0
    
    for d in all_decisions:
        choice_score = list(d['model_scores'].values())[0]
        alt_score = list(d['model_scores'].values())[1]
        score_diff = abs(choice_score - alt_score)
        
        if score_diff > 5:  # High confidence
            if d['was_correct']:
                confident_right += 1
            else:
                confident_wrong += 1
        else:  # Low confidence
            if d['was_correct']:
                close_right += 1
            else:
                close_wrong += 1
    
    if confident_right + confident_wrong > 0:
        conf_accuracy = confident_right / (confident_right + confident_wrong)
        print(f"  High confidence decisions: {conf_accuracy:.1%} accurate")
    
    if close_right + close_wrong > 0:
        close_accuracy = close_right / (close_right + close_wrong)
        print(f"  Close call decisions: {close_accuracy:.1%} accurate")


def main():
    """Run all analyses."""
    print("="*60)
    print("COMPREHENSIVE FLEX & DECISION ANALYSIS")
    print("="*60)
    
    # Load data
    data = load_decision_data()
    
    # Run analyses
    analyze_flex_decisions(data)
    analyze_position_decisions(data)
    test_position_normalizer()
    calculate_summary_stats(data)
    
    print("\n" + "="*60)
    print("ANALYSIS COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()