#!/usr/bin/env python3
"""
Parse available league data and display top 10 teams per league
"""

import json
import os
from collections import defaultdict

def parse_standings_data():
    """Parse the test_standings.json file to extract standings"""
    standings_file = 'test_standings.json'
    
    if not os.path.exists(standings_file):
        print(f"Error: {standings_file} not found")
        return None
    
    with open(standings_file, 'r') as f:
        data = json.load(f)
    
    # Parse the nested structure
    fantasy_content = data.get('fantasy_content', {})
    league_info = fantasy_content.get('league', [])
    
    if len(league_info) < 2:
        print("No standings data found in file")
        return None
    
    # Extract league details
    league_details = league_info[0]
    league_name = league_details.get('name', 'Unknown League')
    league_key = league_details.get('league_key', 'Unknown')
    season = league_details.get('season', 'Unknown')
    
    # Extract standings
    standings_data = league_info[1].get('standings', [])
    
    teams = []
    if standings_data and isinstance(standings_data[0], dict):
        teams_dict = standings_data[0].get('teams', {})
        
        for team_key, team_data in teams_dict.items():
            if isinstance(team_data, dict) and 'team' in team_data:
                team_info = team_data['team']
                
                # Extract team details from nested array structure
                team_details = {}
                for item in team_info:
                    if isinstance(item, dict):
                        if 'name' in item:
                            team_details['name'] = item['name']
                        elif 'team_standings' in item:
                            standings = item['team_standings']
                            rank_val = standings.get('rank', '999')
                            team_details['rank'] = int(rank_val) if rank_val and rank_val != '' else 999
                            
                            outcome_totals = standings.get('outcome_totals', {})
                            wins_val = outcome_totals.get('wins', '0')
                            losses_val = outcome_totals.get('losses', '0')
                            ties_val = outcome_totals.get('ties', '0')
                            pct_val = outcome_totals.get('percentage', '0')
                            
                            team_details['wins'] = int(wins_val) if wins_val and wins_val != '' else 0
                            team_details['losses'] = int(losses_val) if losses_val and losses_val != '' else 0
                            team_details['ties'] = int(ties_val) if ties_val and ties_val != '' else 0
                            team_details['percentage'] = float(pct_val) if pct_val and pct_val != '' else 0
                            
                            points = standings.get('points_for', 0)
                            team_details['points_for'] = float(points) if points else 0
                            
                            points_against = standings.get('points_against', 0)
                            team_details['points_against'] = float(points_against) if points_against else 0
                        elif 'managers' in item:
                            managers = item.get('managers', [])
                            if managers and isinstance(managers[0], dict):
                                manager_info = managers[0].get('manager', {})
                                team_details['manager'] = manager_info.get('nickname', 'Unknown')
                
                if 'name' in team_details:
                    teams.append(team_details)
    
    # Sort teams by rank
    teams.sort(key=lambda x: x.get('rank', 999))
    
    return {
        'league_name': league_name,
        'league_key': league_key,
        'season': season,
        'teams': teams
    }

def parse_all_leagues():
    """Parse all_leagues_raw.json to get list of current leagues"""
    leagues_file = 'all_leagues_raw.json'
    
    if not os.path.exists(leagues_file):
        return []
    
    with open(leagues_file, 'r') as f:
        data = json.load(f)
    
    current_leagues = []
    
    # Navigate through the nested structure
    fantasy_content = data.get('fantasy_content', {})
    users = fantasy_content.get('users', {})
    
    if '0' in users:
        user_data = users['0'].get('user', [])
        for item in user_data:
            if isinstance(item, dict) and 'games' in item:
                games = item['games']
                
                # Look for 2024/2025 seasons
                for game_key, game_data in games.items():
                    if isinstance(game_data, dict) and 'game' in game_data:
                        game_info = game_data['game']
                        
                        # Check if this is a recent season
                        for g_item in game_info:
                            if isinstance(g_item, dict):
                                season = g_item.get('season', '')
                                if season in ['2024', '2025']:
                                    # Get leagues for this season
                                    for g_item2 in game_info:
                                        if isinstance(g_item2, dict) and 'leagues' in g_item2:
                                            leagues = g_item2['leagues']
                                            
                                            for league_key, league_data in leagues.items():
                                                if league_key != 'count' and isinstance(league_data, dict):
                                                    league_info = league_data.get('league', [])
                                                    if league_info:
                                                        league_details = league_info[0] if isinstance(league_info, list) else league_info
                                                        
                                                        current_leagues.append({
                                                            'name': league_details.get('name', 'Unknown'),
                                                            'league_key': league_details.get('league_key', ''),
                                                            'season': league_details.get('season', ''),
                                                            'num_teams': league_details.get('num_teams', 0)
                                                        })
    
    return current_leagues

def main():
    print("=" * 80)
    print("FANTASY FOOTBALL - TOP 10 PLAYERS PER LEAGUE")
    print("=" * 80)
    print()
    
    # First, try to get the list of current leagues
    current_leagues = parse_all_leagues()
    
    if current_leagues:
        print(f"Found {len(current_leagues)} league(s) in your account:")
        print()
        
        for league in current_leagues:
            print(f"• {league['name']} ({league['season']} season, {league['num_teams']} teams)")
        print()
        print("-" * 80)
        print()
    
    # Now parse the standings data we have
    standings = parse_standings_data()
    
    if standings:
        print(f"League: {standings['league_name']} ({standings['season']} Season)")
        print(f"League Key: {standings['league_key']}")
        print("-" * 80)
        print(f"{'Rank':<5} {'Team Name':<35} {'Manager':<15} {'W-L-T':<10} {'Win %':<8} {'Points For':<12}")
        print("-" * 80)
        
        # Show top 10 teams
        for team in standings['teams'][:10]:
            rank = team.get('rank', '-')
            name = team.get('name', 'Unknown')[:34]
            manager = team.get('manager', 'Unknown')[:14]
            wins = team.get('wins', 0)
            losses = team.get('losses', 0)
            ties = team.get('ties', 0)
            pct = team.get('percentage', 0)
            points = team.get('points_for', 0)
            
            record = f"{wins}-{losses}-{ties}"
            
            print(f"{rank:<5} {name:<35} {manager:<15} {record:<10} {pct:.3f}   {points:>10.2f}")
        
        print()
        print("Note: This shows data from the 'Example League 1' league only.")
        print("To get data from other leagues, the MCP server needs to be connected with active authentication.")
    else:
        print("Could not parse standings data from available files.")
        print()
        print("The Fantasy Football MCP server requires active Yahoo API authentication")
        print("to fetch real-time data from all your leagues.")
    
    print()
    print("=" * 80)

if __name__ == "__main__":
    main()