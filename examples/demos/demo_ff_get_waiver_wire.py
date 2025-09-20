import asyncio
import json

from fantasy_football_multi_league import call_tool

async def main():
    """Demonstrate ff_get_waiver_wire tool output with full enhancements."""
    # Discover leagues
    leagues_response = await call_tool("ff_get_leagues", {})
    leagues_payload = json.loads(leagues_response[0].text)  # type: ignore
    leagues = leagues_payload.get("leagues", [])
    if not leagues:
        print("No leagues found. Ensure Yahoo credentials are set.")
        return
    
    league_key = leagues[0].get("key")
    print(f"Using league_key: {league_key}")
    print(f"League name: {leagues[0].get('name')}")
    
    # Call ff_get_waiver_wire with full enhancements
    waiver_args = {
        "league_key": league_key,
        "position": "all",
        "sort": "rank",
        "count": 10,
        "include_expert_analysis": True,
        "include_projections": True,
        "include_external_data": True
    }
    waiver_response = await call_tool("ff_get_waiver_wire", waiver_args)
    waiver_result = json.loads(waiver_response[0].text)  # type: ignore
    
    if waiver_result.get("status") == "success":
        print("\n=== ff_get_waiver_wire Output (Full Enhancements) ===")
        print(json.dumps(waiver_result, indent=2))
    else:
        print(f"Error: {waiver_result}")

if __name__ == "__main__":
    asyncio.run(main())