#!/usr/bin/env python3
"""
Run Real Decision Validation

Tests the model on the lineup decisions that actually matter:
- FLEX spot choices
- Borderline start/sit calls  
- NOT obvious studs

This shows if the model helps with the tough weekly decisions.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from validation.real_decision_validator import main


if __name__ == "__main__":
    print("=" * 60)
    print("🏈 REAL LINEUP DECISION VALIDATOR")
    print("=" * 60)
    print()
    print("This tests the model on borderline decisions only:")
    print("- FLEX spot (RB3 vs WR3)")
    print("- Close calls between similar players")
    print("- Excludes obvious starts (studs/elites)")
    print()
    print("Starting validation...")
    print()
    
    asyncio.run(main())