#!/usr/bin/env python3
"""
Fetch top 10 players from all Yahoo Fantasy Football leagues
"""

import os
import json
import asyncio
from dotenv import load_dotenv
import sys
# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment
load_dotenv()

# Import the MCP server
from fantasy_football_multi_league import FantasyFootballMultiLeagueServer

async def fetch_top_players():
    """Fetch and display top 10 players from all leagues"""
    
    # Initialize the server
    server = FantasyFootballMultiLeagueServer()
    
    print("=" * 80)
    print("FANTASY FOOTBALL - TOP 10 PLAYERS PER LEAGUE")
    print("=" * 80)
    print()
    
    try:
        # Get all leagues
        print("Fetching your leagues...")
        leagues_result = await server.ff_get_leagues()
        
        if 'error' in leagues_result:
            print(f"Error fetching leagues: {leagues_result['error']}")
            return
        
        leagues = leagues_result.get('leagues', [])
        total_leagues = leagues_result.get('total_leagues', 0)
        
        print(f"Found {total_leagues} active league(s)")
        print()
        
        # For each league, get standings (top 10)
        for league in leagues:
            league_key = league['league_key']
            league_name = league['name']
            season = league.get('season', 'Unknown')
            num_teams = league.get('num_teams', 0)
            
            print(f"League: {league_name} ({season} Season)")
            print(f"League Key: {league_key} | Teams: {num_teams}")
            print("-" * 80)
            
            # Get standings for this league
            standings_result = await server.ff_get_standings(league_key=league_key)
            
            if 'error' in standings_result:
                print(f"Error fetching standings: {standings_result['error']}")
                print()
                continue
            
            standings = standings_result.get('standings', [])
            
            if not standings:
                print("No standings available (season may not have started)")
                print()
                continue
            
            # Display top 10 teams
            print(f"{'Rank':<5} {'Team Name':<35} {'Manager':<15} {'W-L-T':<10} {'Win %':<8} {'Points':<10}")
            print("-" * 80)
            
            for i, team in enumerate(standings[:10], 1):
                rank = team.get('rank', i)
                name = team.get('name', 'Unknown')[:34]
                manager = team.get('manager', 'Unknown')[:14]
                wins = team.get('wins', 0)
                losses = team.get('losses', 0)
                ties = team.get('ties', 0)
                pct = team.get('percentage', 0.0)
                points = team.get('points_for', 0.0)
                
                record = f"{wins}-{losses}-{ties}"
                
                print(f"{rank:<5} {name:<35} {manager:<15} {record:<10} {pct:.3f}   {points:>10.2f}")
            
            print()
            print("=" * 80)
            print()
        
        print("✅ Successfully fetched standings from all leagues!")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(fetch_top_players())