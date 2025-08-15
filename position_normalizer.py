#!/usr/bin/env python3
"""
Position Normalizer for Fantasy Football

Normalizes player scores across positions for fair FLEX comparisons.
Uses historical averages and standard deviations to create z-scores.
"""

from typing import Dict, Tuple
import numpy as np


class PositionNormalizer:
    """Normalizes fantasy scores across positions for fair comparison."""
    
    def __init__(self):
        # 2023 PPR scoring averages by position (based on starters)
        # These are typical weekly averages for fantasy-relevant players
        self.position_stats = {
            "QB": {
                "mean": 18.0,
                "std": 6.0,
                "starter_threshold": 15.0,  # QB12 level
                "elite_threshold": 22.0     # QB3 level
            },
            "RB": {
                "mean": 11.0,
                "std": 5.0,
                "starter_threshold": 8.0,   # RB24 level
                "elite_threshold": 15.0     # RB5 level
            },
            "WR": {
                "mean": 10.0,
                "std": 4.5,
                "starter_threshold": 7.0,   # WR36 level  
                "elite_threshold": 14.0     # WR5 level
            },
            "TE": {
                "mean": 7.0,
                "std": 3.5,
                "starter_threshold": 5.0,   # TE12 level
                "elite_threshold": 10.0     # TE3 level
            },
            "K": {
                "mean": 8.0,
                "std": 3.0,
                "starter_threshold": 6.0,
                "elite_threshold": 10.0
            },
            "DEF": {
                "mean": 8.0,
                "std": 4.0,
                "starter_threshold": 6.0,
                "elite_threshold": 12.0
            }
        }
        
    def normalize_projection(self, projection: float, position: str) -> float:
        """
        Convert raw projection to normalized score (z-score).
        
        A normalized score of:
        - 0 = average for that position
        - 1 = 1 standard deviation above average (good)
        - 2 = 2 standard deviations above average (elite)
        - -1 = 1 standard deviation below average (poor)
        
        Args:
            projection: Raw fantasy point projection
            position: Player position
            
        Returns:
            Normalized score (z-score)
        """
        if position not in self.position_stats:
            return 0.0
        
        stats = self.position_stats[position]
        z_score = (projection - stats["mean"]) / stats["std"]
        
        return z_score
    
    def get_flex_value(self, projection: float, position: str) -> float:
        """
        Calculate FLEX value score that accounts for position scarcity.
        
        This creates a fair comparison across positions by considering:
        1. How much above replacement level the player is
        2. Position scarcity factor
        
        Args:
            projection: Raw fantasy point projection
            position: Player position
            
        Returns:
            FLEX value score (higher = better FLEX play)
        """
        if position not in self.position_stats:
            return projection  # Fallback to raw projection
        
        stats = self.position_stats[position]
        
        # Value Over Replacement (VOR)
        # Replacement level is roughly the starter threshold
        replacement_level = stats["starter_threshold"]
        vor = projection - replacement_level
        
        # Position scarcity multiplier
        # TEs have fewer elite options, so good TEs get a small boost
        scarcity_factors = {
            "RB": 1.0,   # Baseline
            "WR": 0.95,  # Slightly more WRs available
            "TE": 1.05   # Slight boost for scarcity, but not too much
        }
        
        scarcity = scarcity_factors.get(position, 1.0)
        
        # FLEX value = VOR * scarcity + baseline projection weight
        # We still weight the raw projection heavily to avoid TE trap
        flex_value = (vor * scarcity * 0.3) + (projection * 0.7)
        
        return flex_value
    
    def get_percentile_rank(self, projection: float, position: str) -> float:
        """
        Get percentile rank for a projection within position.
        
        Args:
            projection: Raw fantasy point projection
            position: Player position
            
        Returns:
            Percentile (0-100, where 100 = best)
        """
        if position not in self.position_stats:
            return 50.0
        
        stats = self.position_stats[position]
        z_score = self.normalize_projection(projection, position)
        
        # Convert z-score to percentile using normal CDF approximation
        # This is a simplified version - could use scipy.stats.norm.cdf
        percentile = 50 + (z_score * 33.3)  # Rough approximation
        percentile = max(0, min(100, percentile))
        
        return percentile
    
    def is_starter_worthy(self, projection: float, position: str) -> bool:
        """
        Determine if a player is starter-worthy at their position.
        
        Args:
            projection: Raw fantasy point projection
            position: Player position
            
        Returns:
            True if starter-worthy, False otherwise
        """
        if position not in self.position_stats:
            return projection >= 7.0  # Generic threshold
        
        return projection >= self.position_stats[position]["starter_threshold"]
    
    def is_elite(self, projection: float, position: str) -> bool:
        """
        Determine if a player is elite at their position.
        
        Args:
            projection: Raw fantasy point projection
            position: Player position
            
        Returns:
            True if elite, False otherwise
        """
        if position not in self.position_stats:
            return projection >= 15.0  # Generic threshold
        
        return projection >= self.position_stats[position]["elite_threshold"]
    
    def compare_for_flex(self, player_a: Tuple[float, str], 
                        player_b: Tuple[float, str]) -> str:
        """
        Compare two players for FLEX spot using normalized scoring.
        
        Args:
            player_a: (projection, position) for player A
            player_b: (projection, position) for player B
            
        Returns:
            "A" if player A is better, "B" if player B is better
        """
        proj_a, pos_a = player_a
        proj_b, pos_b = player_b
        
        # Get FLEX values
        flex_a = self.get_flex_value(proj_a, pos_a)
        flex_b = self.get_flex_value(proj_b, pos_b)
        
        # If FLEX values are very close (within 0.3 points), 
        # use raw projection as tiebreaker
        if abs(flex_a - flex_b) < 0.3:
            return "A" if proj_a >= proj_b else "B"
        
        return "A" if flex_a > flex_b else "B"
    
    def explain_comparison(self, player_a: Tuple[float, str, str],
                          player_b: Tuple[float, str, str]) -> str:
        """
        Explain why one player is better for FLEX than another.
        
        Args:
            player_a: (projection, position, name) for player A
            player_b: (projection, position, name) for player B
            
        Returns:
            Explanation string
        """
        proj_a, pos_a, name_a = player_a
        proj_b, pos_b, name_b = player_b
        
        # Calculate various metrics
        z_a = self.normalize_projection(proj_a, pos_a)
        z_b = self.normalize_projection(proj_b, pos_b)
        
        flex_a = self.get_flex_value(proj_a, pos_a)
        flex_b = self.get_flex_value(proj_b, pos_b)
        
        pct_a = self.get_percentile_rank(proj_a, pos_a)
        pct_b = self.get_percentile_rank(proj_b, pos_b)
        
        winner = name_a if flex_a > flex_b else name_b
        
        explanation = f"""
FLEX Comparison: {name_a} ({pos_a}) vs {name_b} ({pos_b})

{name_a} ({pos_a}):
  - Projection: {proj_a:.1f} points
  - Position Percentile: {pct_a:.0f}th
  - Normalized Score: {z_a:+.2f} ({"above" if z_a > 0 else "below"} average)
  - FLEX Value: {flex_a:.1f}

{name_b} ({pos_b}):
  - Projection: {proj_b:.1f} points  
  - Position Percentile: {pct_b:.0f}th
  - Normalized Score: {z_b:+.2f} ({"above" if z_b > 0 else "below"} average)
  - FLEX Value: {flex_b:.1f}

Winner: {winner}
Reason: {"Higher FLEX value accounting for position and scarcity" if abs(flex_a - flex_b) >= 0.3 else "Higher raw projection (tiebreaker)"}
        """
        
        return explanation


# Global instance
position_normalizer = PositionNormalizer()


# Example usage
if __name__ == "__main__":
    normalizer = PositionNormalizer()
    
    # Example: 9-point TE vs 10-point RB
    print("Example 1: 9-point TE vs 10-point RB")
    print("-" * 40)
    
    te_proj = 9.0
    rb_proj = 10.0
    
    winner = normalizer.compare_for_flex((te_proj, "TE"), (rb_proj, "RB"))
    print(f"Winner: {'TE' if winner == 'A' else 'RB'}")
    
    explanation = normalizer.explain_comparison(
        (te_proj, "TE", "George Kittle"),
        (rb_proj, "RB", "Tony Pollard")
    )
    print(explanation)
    
    # Example 2: 8-point WR vs 8-point RB (true tie)
    print("\nExample 2: 8-point WR vs 8-point RB")
    print("-" * 40)
    
    wr_proj = 8.0
    rb_proj = 8.0
    
    winner = normalizer.compare_for_flex((wr_proj, "WR"), (rb_proj, "RB"))
    print(f"Winner: {'WR' if winner == 'A' else 'RB'}")
    
    explanation = normalizer.explain_comparison(
        (wr_proj, "WR", "Chris Olave"),
        (rb_proj, "RB", "Dameon Pierce")
    )
    print(explanation)