import asyncio
import json

from fantasy_football_multi_league import call_tool

async def main():
    """Demonstrate ff_get_roster tool output with full data level."""
    # Discover leagues
    leagues_response = await call_tool("ff_get_leagues", {})
    leagues_payload = json.loads(leagues_response[0].text)
    leagues = leagues_payload.get("leagues", [])
    if not leagues:
        print("No leagues found. Ensure Yahoo credentials are set.")
        return
    
    league_key = leagues[0].get("key")
    print(f"Using league_key: {league_key}")
    print(f"League name: {leagues[0].get('name')}")
    
    # Call ff_get_roster with full data level
    roster_args = {
        "league_key": league_key,
        "data_level": "full",
        "include_projections": True,
        "include_external_data": True,
        "include_analysis": True
    }
    roster_response = await call_tool("ff_get_roster", roster_args)
    roster_result = json.loads(roster_response[0].text)
    
    if roster_result.get("status") == "success":
        print("\n=== ff_get_roster Output (Full Data Level) ===")
        print(json.dumps(roster_result, indent=2))
    else:
        print(f"Error: {roster_result}")

if __name__ == "__main__":
    asyncio.run(main())