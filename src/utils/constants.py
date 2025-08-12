"""
Fantasy Football constants including NFL teams, positions, scoring systems, and platform configurations.
"""

from typing import Dict, List, Any
from enum import Enum
from datetime import datetime, date


class Platform(Enum):
    """Supported fantasy platforms"""
    DRAFTKINGS = "draftkings"
    FANDUEL = "fanduel"
    YAHOO = "yahoo"
    ESPN = "espn"
    SLEEPER = "sleeper"
    SUPERDRAFT = "superdraft"


# Core Positions
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]

# Position Groups
SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]
FLEX_POSITIONS = ["RB", "WR", "TE"]
OFFENSIVE_POSITIONS = ["QB", "RB", "WR", "TE"]
DEFENSIVE_POSITIONS = ["DST"]

# Position Hierarchies for different contexts
POSITION_PRIORITY = {
    "cash_games": ["QB", "RB", "WR", "TE", "K", "DST"],
    "tournaments": ["QB", "WR", "RB", "TE", "K", "DST"]
}

# Roster Configurations by Platform
ROSTER_POSITIONS: Dict[Platform, Dict[str, Any]] = {
    Platform.DRAFTKINGS: {
        "positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"],
        "salary_cap": 50000,
        "flex_eligible": ["RB", "WR", "TE"],
        "max_players_per_team": 8,
        "roster_size": 9
    },
    Platform.FANDUEL: {
        "positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "K", "DST"],
        "salary_cap": 60000,
        "flex_eligible": [],
        "max_players_per_team": 4,
        "roster_size": 9
    },
    Platform.YAHOO: {
        "positions": ["QB", "WR", "WR", "RB", "TE", "FLEX", "K", "DST", "BN", "BN", "BN", "BN", "BN", "BN"],
        "salary_cap": None,  # Season-long, no salary cap
        "flex_eligible": ["RB", "WR", "TE"],
        "max_players_per_team": None,
        "roster_size": 16
    },
    Platform.ESPN: {
        "positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DST", "K", "BN", "BN", "BN", "BN", "BN", "BN", "BN"],
        "salary_cap": None,  # Season-long, no salary cap
        "flex_eligible": ["RB", "WR", "TE"],
        "max_players_per_team": None,
        "roster_size": 16
    },
    Platform.SLEEPER: {
        "positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DST", "BN", "BN", "BN", "BN", "BN", "BN"],
        "salary_cap": None,  # Season-long, no salary cap
        "flex_eligible": ["RB", "WR", "TE"],
        "max_players_per_team": None,
        "roster_size": 15
    },
    Platform.SUPERDRAFT: {
        "positions": ["QB", "RB", "WR", "WR", "TE", "FLEX"],
        "salary_cap": None,  # Multiplier-based
        "flex_eligible": ["RB", "WR", "TE"],
        "max_players_per_team": 6,
        "roster_size": 6,
        "multiplier_cap": 5.0
    }
}

# NFL Teams with abbreviations and full names
NFL_TEAMS = {
    "ARI": {"name": "Arizona Cardinals", "conference": "NFC", "division": "West"},
    "ATL": {"name": "Atlanta Falcons", "conference": "NFC", "division": "South"},
    "BAL": {"name": "Baltimore Ravens", "conference": "AFC", "division": "North"},
    "BUF": {"name": "Buffalo Bills", "conference": "AFC", "division": "East"},
    "CAR": {"name": "Carolina Panthers", "conference": "NFC", "division": "South"},
    "CHI": {"name": "Chicago Bears", "conference": "NFC", "division": "North"},
    "CIN": {"name": "Cincinnati Bengals", "conference": "AFC", "division": "North"},
    "CLE": {"name": "Cleveland Browns", "conference": "AFC", "division": "North"},
    "DAL": {"name": "Dallas Cowboys", "conference": "NFC", "division": "East"},
    "DEN": {"name": "Denver Broncos", "conference": "AFC", "division": "West"},
    "DET": {"name": "Detroit Lions", "conference": "NFC", "division": "North"},
    "GB": {"name": "Green Bay Packers", "conference": "NFC", "division": "North"},
    "HOU": {"name": "Houston Texans", "conference": "AFC", "division": "South"},
    "IND": {"name": "Indianapolis Colts", "conference": "AFC", "division": "South"},
    "JAX": {"name": "Jacksonville Jaguars", "conference": "AFC", "division": "South"},
    "KC": {"name": "Kansas City Chiefs", "conference": "AFC", "division": "West"},
    "LV": {"name": "Las Vegas Raiders", "conference": "AFC", "division": "West"},
    "LAC": {"name": "Los Angeles Chargers", "conference": "AFC", "division": "West"},
    "LAR": {"name": "Los Angeles Rams", "conference": "NFC", "division": "West"},
    "MIA": {"name": "Miami Dolphins", "conference": "AFC", "division": "East"},
    "MIN": {"name": "Minnesota Vikings", "conference": "NFC", "division": "North"},
    "NE": {"name": "New England Patriots", "conference": "AFC", "division": "East"},
    "NO": {"name": "New Orleans Saints", "conference": "NFC", "division": "South"},
    "NYG": {"name": "New York Giants", "conference": "NFC", "division": "East"},
    "NYJ": {"name": "New York Jets", "conference": "AFC", "division": "East"},
    "PHI": {"name": "Philadelphia Eagles", "conference": "NFC", "division": "East"},
    "PIT": {"name": "Pittsburgh Steelers", "conference": "AFC", "division": "North"},
    "SF": {"name": "San Francisco 49ers", "conference": "NFC", "division": "West"},
    "SEA": {"name": "Seattle Seahawks", "conference": "NFC", "division": "West"},
    "TB": {"name": "Tampa Bay Buccaneers", "conference": "NFC", "division": "South"},
    "TEN": {"name": "Tennessee Titans", "conference": "AFC", "division": "South"},
    "WAS": {"name": "Washington Commanders", "conference": "NFC", "division": "East"}
}

# Team Lists
AFC_TEAMS = [team for team, info in NFL_TEAMS.items() if info["conference"] == "AFC"]
NFC_TEAMS = [team for team, info in NFL_TEAMS.items() if info["conference"] == "NFC"]

# Scoring Settings by Platform
SCORING_SYSTEMS: Dict[Platform, Dict[str, Any]] = {
    Platform.DRAFTKINGS: {
        "passing": {
            "yards_per_point": 25,  # 1 point per 25 yards
            "td": 4,
            "interception": -1,
            "fumble_lost": -1,
            "two_point": 2,
            "completions": 0,
            "300_yard_bonus": 3,
            "400_yard_bonus": 0
        },
        "rushing": {
            "yards_per_point": 10,  # 1 point per 10 yards
            "td": 6,
            "fumble_lost": -1,
            "two_point": 2,
            "100_yard_bonus": 3,
            "200_yard_bonus": 0
        },
        "receiving": {
            "yards_per_point": 10,
            "td": 6,
            "reception": 1,  # PPR
            "fumble_lost": -1,
            "two_point": 2,
            "100_yard_bonus": 3,
            "200_yard_bonus": 0
        },
        "kicking": {
            "pat": 1,
            "fg_0_39": 3,
            "fg_40_49": 4,
            "fg_50_plus": 5,
            "fg_miss": -1
        },
        "defense": {
            "points_allowed_0": 10,
            "points_allowed_1_6": 7,
            "points_allowed_7_13": 4,
            "points_allowed_14_20": 1,
            "points_allowed_21_27": 0,
            "points_allowed_28_34": -1,
            "points_allowed_35_plus": -4,
            "sack": 1,
            "interception": 2,
            "fumble_recovery": 2,
            "safety": 2,
            "td": 6,
            "blocked_kick": 2,
            "yards_allowed_bonus": 0
        }
    },
    Platform.FANDUEL: {
        "passing": {
            "yards_per_point": 25,
            "td": 4,
            "interception": -1,
            "fumble_lost": -1,
            "two_point": 2,
            "completions": 0.5,  # Half point per completion
            "300_yard_bonus": 0,
            "400_yard_bonus": 0
        },
        "rushing": {
            "yards_per_point": 10,
            "td": 6,
            "fumble_lost": -1,
            "two_point": 2,
            "100_yard_bonus": 0,
            "200_yard_bonus": 0
        },
        "receiving": {
            "yards_per_point": 10,
            "td": 6,
            "reception": 0.5,  # Half PPR
            "fumble_lost": -1,
            "two_point": 2,
            "100_yard_bonus": 0,
            "200_yard_bonus": 0
        },
        "kicking": {
            "pat": 1,
            "fg_0_39": 3,
            "fg_40_49": 4,
            "fg_50_plus": 5,
            "fg_miss": 0
        },
        "defense": {
            "points_allowed_0": 10,
            "points_allowed_1_6": 7,
            "points_allowed_7_13": 4,
            "points_allowed_14_20": 1,
            "points_allowed_21_27": 0,
            "points_allowed_28_34": -1,
            "points_allowed_35_plus": -4,
            "sack": 1,
            "interception": 2,
            "fumble_recovery": 2,
            "safety": 2,
            "td": 6,
            "blocked_kick": 2
        }
    },
    Platform.YAHOO: {
        "passing": {
            "yards_per_point": 25,
            "td": 4,
            "interception": -1,
            "fumble_lost": -1,
            "two_point": 2,
            "completions": 0,
            "300_yard_bonus": 0,
            "400_yard_bonus": 0
        },
        "rushing": {
            "yards_per_point": 10,
            "td": 6,
            "fumble_lost": -1,
            "two_point": 2,
            "100_yard_bonus": 0,
            "200_yard_bonus": 0
        },
        "receiving": {
            "yards_per_point": 10,
            "td": 6,
            "reception": 1,  # Full PPR (default)
            "fumble_lost": -1,
            "two_point": 2,
            "100_yard_bonus": 0,
            "200_yard_bonus": 0
        },
        "kicking": {
            "pat": 1,
            "fg_0_39": 3,
            "fg_40_49": 4,
            "fg_50_plus": 5,
            "fg_miss": -1
        },
        "defense": {
            "points_allowed_0": 10,
            "points_allowed_1_6": 7,
            "points_allowed_7_13": 4,
            "points_allowed_14_20": 1,
            "points_allowed_21_27": 0,
            "points_allowed_28_34": -1,
            "points_allowed_35_plus": -4,
            "sack": 1,
            "interception": 2,
            "fumble_recovery": 2,
            "safety": 2,
            "td": 6,
            "blocked_kick": 2
        }
    }
}

# Season Structure
SEASON_WEEKS = 18
PLAYOFF_WEEKS = [15, 16, 17, 18]  # Fantasy playoff weeks
REGULAR_SEASON_WEEKS = list(range(1, 15))  # Weeks 1-14

# Season Dates (2024 season - update annually)
SEASON_START_DATE = date(2024, 9, 5)  # Thursday Night Football Week 1
SEASON_END_DATE = date(2025, 1, 8)    # End of Week 18
PLAYOFF_START_DATE = date(2024, 12, 21)  # Start of Week 16 (common playoff start)

# Week Date Ranges (approximate - update annually)
WEEK_DATES = {
    1: {"start": date(2024, 9, 5), "end": date(2024, 9, 9)},
    2: {"start": date(2024, 9, 12), "end": date(2024, 9, 16)},
    3: {"start": date(2024, 9, 19), "end": date(2024, 9, 23)},
    4: {"start": date(2024, 9, 26), "end": date(2024, 9, 30)},
    5: {"start": date(2024, 10, 3), "end": date(2024, 10, 7)},
    6: {"start": date(2024, 10, 10), "end": date(2024, 10, 14)},
    7: {"start": date(2024, 10, 17), "end": date(2024, 10, 21)},
    8: {"start": date(2024, 10, 24), "end": date(2024, 10, 28)},
    9: {"start": date(2024, 10, 31), "end": date(2024, 11, 4)},
    10: {"start": date(2024, 11, 7), "end": date(2024, 11, 11)},
    11: {"start": date(2024, 11, 14), "end": date(2024, 11, 18)},
    12: {"start": date(2024, 11, 21), "end": date(2024, 11, 25)},
    13: {"start": date(2024, 11, 28), "end": date(2024, 12, 2)},
    14: {"start": date(2024, 12, 5), "end": date(2024, 12, 9)},
    15: {"start": date(2024, 12, 12), "end": date(2024, 12, 16)},
    16: {"start": date(2024, 12, 19), "end": date(2024, 12, 23)},
    17: {"start": date(2024, 12, 26), "end": date(2024, 12, 30)},
    18: {"start": date(2025, 1, 2), "end": date(2025, 1, 8)}
}

# Game Slate Information
SLATE_TYPES = {
    "main": {"start_day": "Sunday", "games": "all_sunday"},
    "early": {"start_day": "Sunday", "games": "early_only"},
    "late": {"start_day": "Sunday", "games": "late_only"},
    "primetime": {"start_day": "Sunday", "games": "sunday_night"},
    "monday": {"start_day": "Monday", "games": "monday_night"},
    "thursday": {"start_day": "Thursday", "games": "thursday_night"},
    "showdown": {"start_day": "varies", "games": "single_game"}
}

# Positional Scarcity Factors (for value calculations)
POSITION_SCARCITY = {
    "QB": 1.0,    # Baseline
    "RB": 1.3,    # More scarce
    "WR": 1.1,    # Slightly scarce
    "TE": 1.5,    # Most scarce
    "K": 0.8,     # Less important
    "DST": 0.9    # Less important
}

# Tournament vs Cash Game Constants
GAME_TYPES = {
    "cash": {
        "description": "Head-to-head, 50/50s, Double-ups",
        "ownership_threshold": 30,  # High ownership is okay
        "ceiling_weight": 0.3,      # Focus on floor
        "floor_weight": 0.7,
        "correlation_preference": "positive"
    },
    "tournament": {
        "description": "GPPs, Tournaments",
        "ownership_threshold": 15,  # Avoid high ownership
        "ceiling_weight": 0.7,      # Focus on ceiling
        "floor_weight": 0.3,
        "correlation_preference": "contrarian"
    }
}

# Stack Configurations
STACK_TYPES = {
    "qb_wr": {"positions": ["QB", "WR"], "min_correlation": 0.6},
    "qb_te": {"positions": ["QB", "TE"], "min_correlation": 0.5},
    "qb_wr_wr": {"positions": ["QB", "WR", "WR"], "min_correlation": 0.4},
    "rb_dst": {"positions": ["RB", "DST"], "min_correlation": -0.3, "type": "contrarian"},
    "bring_back": {"description": "Opposing player to primary stack"}
}

# Weather Impact Thresholds
WEATHER_THRESHOLDS = {
    "wind_speed": {
        "moderate": 15,  # mph
        "severe": 25
    },
    "precipitation": {
        "light": 0.1,    # inches
        "moderate": 0.25,
        "heavy": 0.5
    },
    "temperature": {
        "cold": 32,      # fahrenheit
        "very_cold": 20
    }
}

# DFS Optimization Constants
OPTIMIZATION_SETTINGS = {
    "max_exposure": 0.30,        # Maximum exposure to any single player
    "min_salary_used": 0.98,     # Minimum salary utilization
    "correlation_boost": 1.15,   # Boost for correlated players
    "contrarian_boost": 1.10,    # Boost for low-owned players
    "injury_discount": 0.85,     # Discount for questionable players
    "backup_discount": 0.70,     # Discount for backup players
}