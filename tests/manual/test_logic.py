#!/usr/bin/env python3
"""
Test the consolidated logic directly.
"""

import asyncio
import json
import os
from pathlib import Path


def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value


load_env()


def test_logic():
    """Test the consolidated tool logic."""
    print("🔍 Testing Consolidated Tool Logic")
    print("=" * 40)

    # Test the logic from the consolidated tool
    data_level = "full"
    include_projections = True
    include_external_data = True
    include_analysis = True

    print(f"Input parameters:")
    print(f"   data_level: {data_level}")
    print(f"   include_projections: {include_projections}")
    print(f"   include_external_data: {include_external_data}")
    print(f"   include_analysis: {include_analysis}")

    # Determine effective settings based on data_level and explicit parameters
    if data_level == "basic":
        effective_projections = False
        effective_external = False
        effective_analysis = False
    elif data_level == "standard":
        effective_projections = True
        effective_external = False
        effective_analysis = False
    else:  # "full"
        effective_projections = True
        effective_external = True
        effective_analysis = True

    print(f"\nEffective settings based on data_level:")
    print(f"   effective_projections: {effective_projections}")
    print(f"   effective_external: {effective_external}")
    print(f"   effective_analysis: {effective_analysis}")

    # Explicit parameters override data_level defaults
    if not include_projections:
        effective_projections = False
    if not include_external_data:
        effective_external = False
    if not include_analysis:
        effective_analysis = False

    print(f"\nFinal effective settings after overrides:")
    print(f"   effective_projections: {effective_projections}")
    print(f"   effective_external: {effective_external}")
    print(f"   effective_analysis: {effective_analysis}")

    # Check the condition
    use_basic = not effective_projections and not effective_external and not effective_analysis
    print(f"\nShould use basic mode: {use_basic}")

    if use_basic:
        print("   → Will call legacy ff_get_roster")
    else:
        print("   → Will call enhanced ff_get_roster_with_projections")


if __name__ == "__main__":
    test_logic()
