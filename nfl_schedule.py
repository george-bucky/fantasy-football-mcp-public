#!/usr/bin/env python3
"""
NFL Schedule data for Week 3, 2025
Simple opponent lookup for matchup analysis
"""

# Week 3 NFL matchups (September 22-23, 2025)
# Format: {team: opponent}
WEEK_3_SCHEDULE = {
    # AFC East
    "Buf": "Jax",    # Buffalo vs Jacksonville  
    "Mia": "Sea",    # Miami vs Seattle
    "NE": "NYJ",     # New England vs NY Jets
    "NYJ": "NE",     # NY Jets vs New England
    
    # AFC North  
    "Bal": "Dal",    # Baltimore vs Dallas
    "Cin": "Was",    # Cincinnati vs Washington
    "Cle": "NYG",    # Cleveland vs NY Giants
    "Pit": "LAC",    # Pittsburgh vs LA Chargers
    
    # AFC South
    "Hou": "Min",    # Houston vs Minnesota
    "Ind": "Chi",    # Indianapolis vs Chicago
    "Jax": "Buf",    # Jacksonville vs Buffalo
    "Ten": "GB",     # Tennessee vs Green Bay
    
    # AFC West
    "Den": "TB",     # Denver vs Tampa Bay
    "KC": "Atl",     # Kansas City vs Atlanta
    "LV": "Car",     # Las Vegas vs Carolina
    "LAC": "Pit",    # LA Chargers vs Pittsburgh
    
    # NFC East
    "Dal": "Bal",    # Dallas vs Baltimore
    "NYG": "Cle",    # NY Giants vs Cleveland
    "Phi": "NO",     # Philadelphia vs New Orleans
    "Was": "Cin",    # Washington vs Cincinnati
    
    # NFC North
    "Chi": "Ind",    # Chicago vs Indianapolis
    "Det": "Ari",    # Detroit vs Arizona
    "GB": "Ten",     # Green Bay vs Tennessee
    "Min": "Hou",    # Minnesota vs Houston
    
    # NFC South
    "Atl": "KC",     # Atlanta vs Kansas City
    "Car": "LV",     # Carolina vs Las Vegas
    "NO": "Phi",     # New Orleans vs Philadelphia
    "TB": "Den",     # Tampa Bay vs Denver
    
    # NFC West
    "Ari": "Det",    # Arizona vs Detroit
    "LAR": "SF",     # LA Rams vs San Francisco
    "SF": "LAR",     # San Francisco vs LA Rams
    "Sea": "Mia",    # Seattle vs Miami
}


def get_opponent(team: str) -> str:
    """Get the opponent for a given team in Week 3."""
    return WEEK_3_SCHEDULE.get(team, "")


def get_week_3_schedule():
    """Get the complete Week 3 schedule."""
    return WEEK_3_SCHEDULE.copy()