#!/usr/bin/env python3
"""
Simple HTTP test for the deployed FastMCP server using requests
"""

import requests
import json


def test_fastmcp_server():
    """Test the deployed FastMCP server with simple HTTP requests."""
    base_url = "https://ideal-blush-lemming.fastmcp.app"

    print("🏈 Testing FastMCP Fantasy Football Server")
    print("=" * 50)
    print(f"🔗 Base URL: {base_url}")

    # Test 1: Basic health check
    print("\n🔍 Step 1: Testing server health...")
    try:
        response = requests.get(f"{base_url}/", timeout=10)
        print(f"📊 Status: {response.status_code}")
        print(f"📝 Response: {response.text[:200]}...")
    except Exception as e:
        print(f"❌ Health check failed: {e}")

    # Test 2: Try to list tools
    print("\n🔍 Step 2: Testing tools endpoint...")
    try:
        response = requests.get(f"{base_url}/mcp/tools", timeout=10)
        print(f"📊 Status: {response.status_code}")
        if response.status_code == 200:
            tools = response.json()
            print("✅ Tools endpoint accessible")
            print(f"📋 Found {len(tools)} tools")
        else:
            print(f"❌ Tools endpoint error: {response.text}")
    except Exception as e:
        print(f"❌ Tools endpoint failed: {e}")

    # Test 3: Try to call ff_get_leagues
    print("\n🔍 Step 3: Testing ff_get_leagues...")
    try:
        payload = {"arguments": {}}
        headers = {"Content-Type": "application/json"}

        response = requests.post(
            f"{base_url}/mcp/tools/ff_get_leagues", json=payload, headers=headers, timeout=30
        )

        print(f"📊 Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print("✅ ff_get_leagues succeeded")
            print(f"📋 Response: {json.dumps(result, indent=2)[:300]}...")
        else:
            print(f"❌ ff_get_leagues failed: {response.text}")

    except Exception as e:
        print(f"❌ ff_get_leagues exception: {e}")

    # Test 4: Try to call ff_get_optimal_lineup
    print("\n🔍 Step 4: Testing ff_get_optimal_lineup...")
    try:
        payload = {"arguments": {"league_key": "nfl.l.XXXXXX", "strategy": "balanced"}}
        headers = {"Content-Type": "application/json"}

        response = requests.post(
            f"{base_url}/mcp/tools/ff_get_optimal_lineup",
            json=payload,
            headers=headers,
            timeout=60,  # Longer timeout for this complex operation
        )

        print(f"📊 Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print("✅ ff_get_optimal_lineup succeeded")
            print(f"📋 Response: {json.dumps(result, indent=2)[:500]}...")
        else:
            print(f"❌ ff_get_optimal_lineup failed")
            print(f"📝 Response: {response.text}")

    except Exception as e:
        print(f"❌ ff_get_optimal_lineup exception: {e}")


if __name__ == "__main__":
    test_fastmcp_server()
