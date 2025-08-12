"""
Roster configuration handling for different league types and platforms.
Supports custom roster positions, superflex, 2QB, dynasty, best ball, etc.
"""

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
from enum import Enum


class LeagueType(Enum):
    """Common league type presets."""
    STANDARD = "standard"
    PPR = "ppr"
    HALF_PPR = "half_ppr"
    SUPERFLEX = "superflex"
    TWO_QB = "2qb"
    DYNASTY = "dynasty"
    BEST_BALL = "best_ball"
    IDP = "idp"  # Individual Defensive Players
    CUSTOM = "custom"


@dataclass
class RosterPosition:
    """Represents a single roster position slot."""
    position_type: str  # "QB", "RB", "WR", "TE", "FLEX", "SUPERFLEX", etc.
    count: int = 1  # Number of this position
    eligible_positions: Optional[List[str]] = None  # For FLEX positions
    is_bench: bool = False
    is_ir: bool = False  # Injured Reserve
    max_players: Optional[int] = None  # For position limits


class RosterConfiguration:
    """
    Handles all roster configuration variations across different leagues.
    """
    
    # Standard position mappings
    POSITION_ELIGIBILITY = {
        "FLEX": ["RB", "WR", "TE"],
        "SUPERFLEX": ["QB", "RB", "WR", "TE"],
        "W/R": ["WR", "RB"],
        "W/T": ["WR", "TE"],
        "R/T": ["RB", "TE"],
        "W/R/T": ["WR", "RB", "TE"],
        "Q/W/R/T": ["QB", "WR", "RB", "TE"],
        "RB/WR": ["RB", "WR"],
        "WR/TE": ["WR", "TE"],
        "UTIL": ["RB", "WR", "TE"],  # Some leagues use UTIL instead of FLEX
        "OP": ["QB", "RB", "WR", "TE"],  # Offensive Player (Superflex alternative)
        
        # IDP Positions
        "IDP": ["LB", "DB", "DL", "S", "CB", "DE", "DT"],
        "IDP_FLEX": ["LB", "DB", "DL", "S", "CB", "DE", "DT"],
        "D": ["LB", "DB", "DL"],  # Generic defensive player
        "DB": ["S", "CB"],  # Defensive backs
        "DL": ["DE", "DT"],  # Defensive line
        "LB": ["LB", "OLB", "ILB", "MLB"],  # Linebackers
    }
    
    # Common roster templates
    ROSTER_TEMPLATES = {
        "yahoo_standard": [
            RosterPosition("QB", 1),
            RosterPosition("RB", 2),
            RosterPosition("WR", 2),
            RosterPosition("TE", 1),
            RosterPosition("FLEX", 1, ["RB", "WR", "TE"]),
            RosterPosition("K", 1),
            RosterPosition("DST", 1),
            RosterPosition("BN", 6, is_bench=True),
        ],
        
        "espn_standard": [
            RosterPosition("QB", 1),
            RosterPosition("RB", 2),
            RosterPosition("WR", 2),
            RosterPosition("TE", 1),
            RosterPosition("FLEX", 1, ["RB", "WR", "TE"]),
            RosterPosition("D/ST", 1),
            RosterPosition("K", 1),
            RosterPosition("BE", 7, is_bench=True),
        ],
        
        "superflex": [
            RosterPosition("QB", 1),
            RosterPosition("RB", 2),
            RosterPosition("WR", 3),
            RosterPosition("TE", 1),
            RosterPosition("FLEX", 1, ["RB", "WR", "TE"]),
            RosterPosition("SUPERFLEX", 1, ["QB", "RB", "WR", "TE"]),
            RosterPosition("DST", 1),
            RosterPosition("K", 1),
            RosterPosition("BN", 6, is_bench=True),
        ],
        
        "2qb": [
            RosterPosition("QB", 2),
            RosterPosition("RB", 2),
            RosterPosition("WR", 3),
            RosterPosition("TE", 1),
            RosterPosition("FLEX", 1, ["RB", "WR", "TE"]),
            RosterPosition("DST", 1),
            RosterPosition("K", 1),
            RosterPosition("BN", 5, is_bench=True),
        ],
        
        "dynasty_superflex": [
            RosterPosition("QB", 1),
            RosterPosition("RB", 2),
            RosterPosition("WR", 3),
            RosterPosition("TE", 1),
            RosterPosition("FLEX", 2, ["RB", "WR", "TE"]),
            RosterPosition("SUPERFLEX", 1, ["QB", "RB", "WR", "TE"]),
            RosterPosition("BN", 15, is_bench=True),  # Deep benches
            RosterPosition("IR", 3, is_ir=True),  # IR spots
            RosterPosition("TAXI", 5, is_bench=True),  # Taxi squad for rookies
        ],
        
        "bestball": [
            RosterPosition("QB", 3),  # Best Ball drafts more players
            RosterPosition("RB", 6),
            RosterPosition("WR", 8),
            RosterPosition("TE", 3),
            RosterPosition("DST", 2),
            RosterPosition("K", 2),
        ],
        
        "idp_standard": [
            RosterPosition("QB", 1),
            RosterPosition("RB", 2),
            RosterPosition("WR", 2),
            RosterPosition("TE", 1),
            RosterPosition("FLEX", 1, ["RB", "WR", "TE"]),
            RosterPosition("LB", 2),
            RosterPosition("DB", 2),
            RosterPosition("DL", 1),
            RosterPosition("IDP_FLEX", 1, ["LB", "DB", "DL"]),
            RosterPosition("K", 1),
            RosterPosition("BN", 8, is_bench=True),
        ],
        
        "deep_league": [
            RosterPosition("QB", 1),
            RosterPosition("RB", 2),
            RosterPosition("WR", 3),
            RosterPosition("TE", 1),
            RosterPosition("FLEX", 2, ["RB", "WR", "TE"]),
            RosterPosition("DST", 1),
            RosterPosition("K", 1),
            RosterPosition("BN", 8, is_bench=True),
        ],
        
        "guillotine": [  # Guillotine leagues (lowest team eliminated weekly)
            RosterPosition("QB", 2),
            RosterPosition("RB", 4),
            RosterPosition("WR", 4),
            RosterPosition("TE", 2),
            RosterPosition("FLEX", 2, ["RB", "WR", "TE"]),
            RosterPosition("DST", 2),
            RosterPosition("K", 2),
        ],
    }
    
    def __init__(self):
        """Initialize roster configuration handler."""
        self.custom_configs: Dict[str, List[RosterPosition]] = {}
    
    @classmethod
    def parse_yahoo_roster_positions(cls, yahoo_roster_data: Dict) -> List[RosterPosition]:
        """
        Parse Yahoo's roster position format into our structure.
        
        Yahoo format example:
        {
            "roster_positions": [
                {"position": "QB", "position_type": "O", "count": 1},
                {"position": "WR", "position_type": "O", "count": 3},
                {"position": "RB", "position_type": "O", "count": 2},
                {"position": "TE", "position_type": "O", "count": 1},
                {"position": "W/R/T", "position_type": "F", "count": 2},
                {"position": "K", "position_type": "K", "count": 1},
                {"position": "DEF", "position_type": "DT", "count": 1},
                {"position": "BN", "position_type": "BN", "count": 6},
                {"position": "IR", "position_type": "IR", "count": 2}
            ]
        }
        """
        positions = []
        
        for pos_data in yahoo_roster_data.get("roster_positions", []):
            position_name = pos_data.get("position", "")
            count = pos_data.get("count", 1)
            pos_type = pos_data.get("position_type", "")
            
            # Determine if it's a bench or IR position
            is_bench = pos_type == "BN" or position_name == "BN"
            is_ir = pos_type == "IR" or position_name == "IR"
            
            # Get eligible positions for flex spots
            eligible = cls.POSITION_ELIGIBILITY.get(position_name)
            
            positions.append(RosterPosition(
                position_type=position_name,
                count=count,
                eligible_positions=eligible,
                is_bench=is_bench,
                is_ir=is_ir
            ))
        
        return positions
    
    @classmethod
    def parse_espn_roster(cls, espn_roster_data: Dict) -> List[RosterPosition]:
        """
        Parse ESPN's roster format.
        
        ESPN uses different position codes:
        0: QB, 2: RB, 4: WR, 6: TE, 16: D/ST, 17: K, 
        20: Bench, 21: IR, 23: FLEX, 24: Superflex
        """
        position_map = {
            0: "QB", 2: "RB", 4: "WR", 6: "TE",
            16: "DST", 17: "K", 20: "BN", 21: "IR",
            23: "FLEX", 24: "SUPERFLEX"
        }
        
        positions = []
        for slot_id, count in espn_roster_data.get("roster_slots", {}).items():
            position_name = position_map.get(int(slot_id), "UNKNOWN")
            
            is_bench = position_name == "BN"
            is_ir = position_name == "IR"
            eligible = cls.POSITION_ELIGIBILITY.get(position_name)
            
            positions.append(RosterPosition(
                position_type=position_name,
                count=count,
                eligible_positions=eligible,
                is_bench=is_bench,
                is_ir=is_ir
            ))
        
        return positions
    
    @classmethod
    def parse_sleeper_roster(cls, sleeper_settings: Dict) -> List[RosterPosition]:
        """
        Parse Sleeper's roster format.
        
        Sleeper format:
        {
            "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "BN", "BN", ...]
        }
        """
        position_counts = {}
        
        for position in sleeper_settings.get("roster_positions", []):
            position_counts[position] = position_counts.get(position, 0) + 1
        
        positions = []
        for position_name, count in position_counts.items():
            is_bench = position_name == "BN"
            is_ir = position_name in ["IR", "TAXI"]
            eligible = cls.POSITION_ELIGIBILITY.get(position_name)
            
            positions.append(RosterPosition(
                position_type=position_name,
                count=count,
                eligible_positions=eligible,
                is_bench=is_bench,
                is_ir=is_ir
            ))
        
        return positions
    
    @classmethod
    def detect_league_type(cls, roster_positions: List[RosterPosition]) -> LeagueType:
        """
        Detect the league type based on roster configuration.
        """
        # Count key positions
        qb_count = sum(p.count for p in roster_positions if p.position_type == "QB")
        superflex_count = sum(p.count for p in roster_positions if p.position_type in ["SUPERFLEX", "OP"])
        idp_count = sum(p.count for p in roster_positions if p.position_type in ["LB", "DB", "DL", "IDP"])
        bench_count = sum(p.count for p in roster_positions if p.is_bench)
        
        # Detect type
        if idp_count > 0:
            return LeagueType.IDP
        elif superflex_count > 0:
            return LeagueType.SUPERFLEX
        elif qb_count >= 2:
            return LeagueType.TWO_QB
        elif bench_count >= 15:
            return LeagueType.DYNASTY
        else:
            return LeagueType.STANDARD
    
    @classmethod
    def get_starting_positions(cls, roster_positions: List[RosterPosition]) -> List[str]:
        """
        Get list of starting positions (non-bench, non-IR).
        Returns flattened list like ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"]
        """
        starting = []
        for position in roster_positions:
            if not position.is_bench and not position.is_ir:
                for _ in range(position.count):
                    starting.append(position.position_type)
        return starting
    
    @classmethod
    def get_position_limits(cls, roster_positions: List[RosterPosition]) -> Dict[str, int]:
        """
        Get maximum number of players allowed per position.
        """
        limits = {}
        for position in roster_positions:
            if position.max_players:
                limits[position.position_type] = position.max_players
        return limits
    
    @classmethod
    def validate_lineup(cls, lineup: List[Dict[str, str]], 
                       roster_positions: List[RosterPosition]) -> Tuple[bool, List[str]]:
        """
        Validate if a lineup meets roster requirements.
        
        Args:
            lineup: List of {"position": "RB", "player": "player_name"}
            roster_positions: Roster configuration
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        required_positions = cls.get_starting_positions(roster_positions)
        
        # Count filled positions
        filled_positions = {}
        for slot in lineup:
            pos = slot.get("position")
            filled_positions[pos] = filled_positions.get(pos, 0) + 1
        
        # Check each required position
        position_counts = {}
        for pos in required_positions:
            position_counts[pos] = position_counts.get(pos, 0) + 1
        
        for position, required_count in position_counts.items():
            filled_count = filled_positions.get(position, 0)
            
            if filled_count < required_count:
                errors.append(f"Missing {required_count - filled_count} {position}")
            elif filled_count > required_count:
                errors.append(f"Too many {position} ({filled_count}/{required_count})")
        
        return (len(errors) == 0, errors)
    
    @classmethod
    def can_slot_player(cls, player_position: str, roster_slot: str,
                       roster_positions: List[RosterPosition]) -> bool:
        """
        Check if a player can fill a specific roster slot.
        
        Args:
            player_position: The player's actual position (e.g., "RB")
            roster_slot: The roster slot to fill (e.g., "FLEX")
            roster_positions: Roster configuration
            
        Returns:
            True if player can fill the slot
        """
        # Direct position match
        if player_position == roster_slot:
            return True
        
        # Check flex eligibility
        for position in roster_positions:
            if position.position_type == roster_slot:
                if position.eligible_positions and player_position in position.eligible_positions:
                    return True
        
        return False
    
    @classmethod
    def optimize_position_assignment(cls, players: List[Dict], 
                                    roster_positions: List[RosterPosition]) -> List[Dict]:
        """
        Optimally assign players to roster slots considering flex positions.
        
        This is important for maximizing lineup flexibility.
        Returns list of {"player": player_obj, "slot": "position"}
        """
        assignments = []
        used_players = set()
        
        # First, fill non-flex positions
        for position in roster_positions:
            if position.is_bench or position.is_ir:
                continue
                
            if not position.eligible_positions:  # Non-flex position
                # Find best players for this position
                eligible_players = [
                    p for p in players 
                    if p["position"] == position.position_type and p["id"] not in used_players
                ]
                
                # Sort by projected points (or your metric)
                eligible_players.sort(key=lambda x: x.get("projected_points", 0), reverse=True)
                
                for i in range(min(position.count, len(eligible_players))):
                    assignments.append({
                        "player": eligible_players[i],
                        "slot": position.position_type
                    })
                    used_players.add(eligible_players[i]["id"])
        
        # Then fill flex positions with best remaining players
        for position in roster_positions:
            if position.is_bench or position.is_ir:
                continue
                
            if position.eligible_positions:  # Flex position
                eligible_players = [
                    p for p in players 
                    if p["position"] in position.eligible_positions and p["id"] not in used_players
                ]
                
                eligible_players.sort(key=lambda x: x.get("projected_points", 0), reverse=True)
                
                for i in range(min(position.count, len(eligible_players))):
                    assignments.append({
                        "player": eligible_players[i],
                        "slot": position.position_type
                    })
                    used_players.add(eligible_players[i]["id"])
        
        return assignments


def create_custom_roster(config_string: str) -> List[RosterPosition]:
    """
    Create custom roster from string format.
    
    Example: "1QB,2RB,3WR,1TE,2FLEX,1K,1DST,6BN"
    """
    positions = []
    
    for part in config_string.split(","):
        part = part.strip()
        
        # Extract count and position
        count = 1
        position = part
        
        # Check if there's a number prefix
        for i, char in enumerate(part):
            if not char.isdigit():
                if i > 0:
                    count = int(part[:i])
                    position = part[i:]
                break
        
        # Determine position properties
        is_bench = position in ["BN", "BE", "BENCH"]
        is_ir = position in ["IR", "IL"]
        eligible = RosterConfiguration.POSITION_ELIGIBILITY.get(position)
        
        positions.append(RosterPosition(
            position_type=position,
            count=count,
            eligible_positions=eligible,
            is_bench=is_bench,
            is_ir=is_ir
        ))
    
    return positions