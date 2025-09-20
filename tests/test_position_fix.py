#!/usr/bin/env python3
"""
Fix the position normalization issue in lineup optimizer.
"""

import asyncio
import json
import os
from pathlib import Path

def load_env():
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env()

async def test_position_fix():
    """Test the proposed position fix."""
    print("🔧 Testing Position Normalization Fix")
    print("=" * 45)
    
    # Position mapping for bench/flex positions
    position_map = {
        'BN': 'BENCH',     # Keep as bench but mark as BENCH
        'W/R': 'FLEX',     # Flex position 
        'D': 'DEF',        # Individual defensive player -> DEF
        'QB': 'QB',
        'RB': 'RB', 
        'WR': 'WR',
        'TE': 'TE',
        'K': 'K',
        'DEF': 'DEF'
    }
    
    # Test the position validation
    def normalize_position(pos):
        """Normalize position to valid fantasy position."""
        normalized = position_map.get(pos, pos)
        return normalized
    
    def is_valid_position(pos):
        """Check if position is valid for fantasy."""
        valid_positions = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF', 'BENCH', 'FLEX']
        return pos in valid_positions
    
    # Test positions from our debug
    test_positions = ['QB', 'WR', 'RB', 'TE', 'K', 'DEF', 'W/R', 'BN', 'D']
    
    print("🎯 Position Normalization Test:")
    for pos in test_positions:
        normalized = normalize_position(pos)
        valid = is_valid_position(normalized)
        print(f"   {pos:4s} → {normalized:5s} - Valid: {valid}")
    
    print("\n✅ This fix would make all positions valid!")
    print("   - Bench players (BN) → BENCH position")
    print("   - Flex players (W/R) → FLEX position") 
    print("   - Individual defensive (D) → DEF position")
    
    # Now let's also modify the is_valid check
    print("\n🔧 Updated is_valid() method should check:")
    print("   ['QB', 'RB', 'WR', 'TE', 'K', 'DEF', 'BENCH', 'FLEX']")

if __name__ == "__main__":
    asyncio.run(test_position_fix())