#!/usr/bin/env python3
"""
FastMCP Deployment Checker
Verifies the deployment is ready with all fixes
"""

import os
import sys
import json
from pathlib import Path


def check_environment_variables():
    """Check that all required environment variables are set."""
    required_vars = ["YAHOO_ACCESS_TOKEN", "YAHOO_CONSUMER_KEY", "YAHOO_GUID"]

    print("🔍 Checking environment variables...")
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
        else:
            print(f"✅ {var}: SET")

    if missing:
        print(f"❌ Missing variables: {missing}")
        return False
    return True


def check_code_files():
    """Check that all necessary files exist."""
    required_files = [
        "fastmcp_server.py",
        "fantasy_football_multi_league.py",
        "lineup_optimizer.py",
        "nfl_schedule.py",
        "matchup_analyzer.py",
        "sleeper_api.py",
        "yahoo_api_utils.py",
        "position_normalizer.py",
    ]

    print("\n📁 Checking required files...")
    missing = []
    for file in required_files:
        if Path(file).exists():
            print(f"✅ {file}")
        else:
            missing.append(file)
            print(f"❌ {file}")

    if missing:
        print(f"❌ Missing files: {missing}")
        return False
    return True


def check_yahoo_parsing_fix():
    """Check if the Yahoo parsing fix is present."""
    print("\n🔧 Checking Yahoo parsing fix...")

    try:
        with open("lineup_optimizer.py", "r") as f:
            content = f.read()

        if "fantasy_content.team[1].roster" in content:
            print("✅ Yahoo parsing fix detected")
            return True
        else:
            print("❌ Yahoo parsing fix NOT found")
            return False
    except Exception as e:
        print(f"❌ Error checking parsing fix: {e}")
        return False


def check_nfl_schedule():
    """Check if NFL schedule data is present."""
    print("\n📅 Checking NFL schedule data...")

    try:
        with open("nfl_schedule.py", "r") as f:
            content = f.read()

        if "WEEK_3_SCHEDULE" in content and 'Buf": "Jax"' in content:
            print("✅ Week 3 NFL schedule detected")
            return True
        else:
            print("❌ NFL schedule data incomplete")
            return False
    except Exception as e:
        print(f"❌ Error checking schedule: {e}")
        return False


def main():
    print("🚀 FastMCP Deployment Readiness Check")
    print("=" * 50)

    checks = [
        ("Environment Variables", check_environment_variables),
        ("Code Files", check_code_files),
        ("Yahoo Parsing Fix", check_yahoo_parsing_fix),
        ("NFL Schedule Data", check_nfl_schedule),
    ]

    results = []
    for name, check_func in checks:
        result = check_func()
        results.append((name, result))

    print("\n" + "=" * 50)
    print("📊 DEPLOYMENT READINESS SUMMARY")
    print("=" * 50)

    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 READY FOR DEPLOYMENT!")
        print("\nNext steps:")
        print("1. Commit all changes to git")
        print("2. Push to your repository")
        print("3. Redeploy on FastMCP cloud")
        print("4. Set environment variables in cloud deployment")
    else:
        print("❌ NOT READY - Fix issues above before deploying")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
