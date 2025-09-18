#!/usr/bin/env python3
"""
NFL Schedule data for Week 3, 2025
Simple opponent lookup for matchup analysis
"""

# Week 3 NFL matchups (September 22-23, 2025)
# Format: {team: opponent}
WEEK_3_SCHEDULE = {
    # AFC East
    "BUF": "JAX",    # Buffalo vs Jacksonville  
    "MIA": "SEA",    # Miami vs Seattle
    "NE": "NYJ",     # New England vs NY Jets
    "NYJ": "NE",     # NY Jets vs New England
    
    # AFC North  
    "BAL": "DAL",    # Baltimore vs Dallas
    "CIN": "WAS",    # Cincinnati vs Washington
    "CLE": "NYG",    # Cleveland vs NY Giants
    "PIT": "LAC",    # Pittsburgh vs LA Chargers
    
    # AFC South
    "HOU": "MIN",    # Houston vs Minnesota
    "IND": "CHI",    # Indianapolis vs Chicago
    "JAX": "BUF",    # Jacksonville vs Buffalo
    "TEN": "GB",     # Tennessee vs Green Bay
    
    # AFC West
    "DEN": "TB",     # Denver vs Tampa Bay
    "KC": "ATL",     # Kansas City vs Atlanta
    "LAC": "PIT",    # LA Chargers vs Pittsburgh
    "LV": "CAR",     # Las Vegas vs Carolina
    
    # NFC East
    "DAL": "BAL",    # Dallas vs Baltimore
    "NYG": "CLE",    # NY Giants vs Cleveland
    "PHI": "NO",     # Philadelphia vs New Orleans
    "WAS": "CIN",    # Washington vs Cincinnati
    
    # NFC North
    "CHI": "IND",    # Chicago vs Indianapolis
    "DET": "ARI",    # Detroit vs Arizona
    "GB": "TEN",     # Green Bay vs Tennessee
    "MIN": "HOU",    # Minnesota vs Houston
    
    # NFC South
    "ATL": "KC",     # Atlanta vs Kansas City
    "CAR": "LV",     # Carolina vs Las Vegas
    "NO": "PHI",     # New Orleans vs Philadelphia
    "TB": "DEN",     # Tampa Bay vs Denver
    
    # NFC West
    "ARI": "DET",    # Arizona vs Detroit
    "LAR": "SF",     # LA Rams vs San Francisco
    "SF": "LAR",     # San Francisco vs LA Rams
    "SEA": "MIA",    # Seattle vs Miami
}


def get_opponent(team: str) -> str:
    """Get the opponent for a given team in Week 3."""
    return WEEK_3_SCHEDULE.get(team, "")


def get_week_3_schedule():
    """Get the complete Week 3 schedule."""
    return WEEK_3_SCHEDULE.copy()