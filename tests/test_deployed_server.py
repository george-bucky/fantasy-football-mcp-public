#!/usr/bin/env python3
"""
Simple MCP Client to test the deployed FastMCP fantasy football server
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any, Optional


class FastMCPClient:
    """Client to test FastMCP deployed servers."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Call a tool on the FastMCP server."""
        url = f"{self.base_url}/tools/{tool_name}"

        # Prepare the request payload
        payload = {"arguments": kwargs}

        print(f"🔗 Calling {url}")
        print(f"📤 Payload: {json.dumps(payload, indent=2)}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                ) as response:
                    print(f"📊 Status: {response.status}")

                    if response.status == 200:
                        result = await response.json()
                        print("✅ Success!")
                        return result
                    else:
                        error_text = await response.text()
                        print(f"❌ Error: {error_text}")
                        return {"error": f"HTTP {response.status}", "details": error_text}

        except Exception as e:
            print(f"❌ Exception: {e}")
            return {"error": "Connection failed", "details": str(e)}

    async def list_tools(self) -> Dict[str, Any]:
        """List available tools."""
        url = f"{self.base_url}/tools"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        return {"error": f"HTTP {response.status}", "details": error_text}
        except Exception as e:
            return {"error": "Connection failed", "details": str(e)}


async def test_fantasy_football_server():
    """Test the deployed fantasy football server."""
    print("🏈 Testing Fantasy Football MCP Server")
    print("=" * 50)

    # Your deployed FastMCP URL
    server_url = "https://your-app-name.fastmcp.app/mcp"
    client = FastMCPClient(server_url)

    # Test 1: List available tools
    print("\n🔍 Step 1: Listing available tools...")
    tools = await client.list_tools()
    print("📋 Available tools:")
    print(json.dumps(tools, indent=2))

    # Test 2: Get leagues (this should work if auth is set up)
    print("\n🔍 Step 2: Testing ff_get_leagues...")
    leagues_result = await client.call_tool("ff_get_leagues")
    print("📋 Leagues result:")
    print(json.dumps(leagues_result, indent=2))

    # Extract a league key if leagues were found
    league_key = None
    if "leagues" in leagues_result and len(leagues_result["leagues"]) > 0:
        league_key = leagues_result["leagues"][0]["key"]
        print(f"🎯 Using league key: {league_key}")
    else:
        print("❌ No leagues found - using a test league key")
        league_key = "nfl.l.XXXXXX"  # Replace with your test league key

    # Test 3: Test the optimal lineup tool
    print(f"\n🔍 Step 3: Testing ff_get_optimal_lineup with league {league_key}...")
    lineup_result = await client.call_tool(
        "ff_get_optimal_lineup", league_key=league_key, strategy="balanced"
    )
    print("🏆 Optimal lineup result:")
    print(json.dumps(lineup_result, indent=2))

    # Analysis
    print("\n" + "=" * 50)
    print("📊 TEST ANALYSIS")
    print("=" * 50)

    if "error" in lineup_result:
        print("❌ ff_get_optimal_lineup FAILED")
        print(f"   Error: {lineup_result.get('error', 'Unknown')}")
        print(f"   Details: {lineup_result.get('details', 'No details')}")

        # Common issues and solutions
        print("\n🔧 Potential Issues:")
        if "401" in str(lineup_result):
            print("   • Yahoo API authentication expired")
            print("   • Solution: Run ff_refresh_token tool")
        elif "500" in str(lineup_result):
            print("   • Server error - likely missing dependencies")
            print("   • Solution: Check deployment logs")
        elif "Connection failed" in str(lineup_result):
            print("   • Network/URL issue")
            print("   • Solution: Verify FastMCP URL")
        else:
            print("   • Unknown issue - check server logs")

    elif "optimal_lineup" in lineup_result:
        print("✅ ff_get_optimal_lineup WORKING!")
        if lineup_result.get("status") == "partial":
            print("   ⚠️  Status: Partial (some data missing)")
        else:
            print(f"   Status: {lineup_result.get('status', 'Unknown')}")

        lineup = lineup_result.get("optimal_lineup", {})
        print(f"   Players found: {len(lineup)} positions")

        # Check for specific issues
        analysis = lineup_result.get("analysis", {})
        if analysis.get("players_with_projections", 0) == 0:
            print("   ⚠️  No projection data - Sleeper API might be down")
        if analysis.get("players_with_matchup_data", 0) == 0:
            print("   ⚠️  No matchup data - opponent info missing")

    else:
        print("❓ Unexpected response format")


if __name__ == "__main__":
    asyncio.run(test_fantasy_football_server())
