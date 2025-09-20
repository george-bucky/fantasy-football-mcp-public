#!/usr/bin/env python3
"""
MCP Client test for the fantasy football server
This connects as a proper MCP client instead of making raw HTTP requests
"""

import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_mcp_server():
    """Test the fantasy football MCP server locally."""
    print("🏈 Testing Fantasy Football MCP Server Locally")
    print("=" * 50)
    
    # Server parameters - run the local server
    server_params = StdioServerParameters(
        command="python",
        args=["simple_mcp_server.py"]
    )
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the client
                await session.initialize()
                
                print("✅ MCP client connected")
                
                # List available tools
                tools = await session.list_tools()
                print(f"📋 Available tools: {[tool.name for tool in tools.tools]}")
                
                # Test ff_get_leagues first
                print("\n🔍 Testing ff_get_leagues...")
                try:
                    leagues_result = await session.call_tool("ff_get_leagues", {})
                    print("✅ ff_get_leagues succeeded")
                    print(f"📋 Result: {leagues_result.content[0].text[:200]}...")
                    
                    # Parse the result to get a league key
                    leagues_data = json.loads(leagues_result.content[0].text)
                    if leagues_data.get("leagues"):
                        league_key = leagues_data["leagues"][0]["key"]
                        print(f"🎯 Using league key: {league_key}")
                        
                        # Test ff_get_optimal_lineup
                        print(f"\n🔍 Testing ff_get_optimal_lineup with {league_key}...")
                        try:
                            lineup_result = await session.call_tool(
                                "ff_get_optimal_lineup", 
                                {
                                    "league_key": league_key,
                                    "strategy": "balanced"
                                }
                            )
                            print("✅ ff_get_optimal_lineup succeeded")
                            print(f"📋 Result: {lineup_result.content[0].text[:300]}...")
                            
                        except Exception as e:
                            print(f"❌ ff_get_optimal_lineup failed: {e}")
                    else:
                        print("❌ No leagues found in response")
                        
                except Exception as e:
                    print(f"❌ ff_get_leagues failed: {e}")
                    
    except Exception as e:
        print(f"❌ MCP client connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_mcp_server())