"""
Roster detection and configuration for Yahoo Fantasy leagues.
Automatically detects and adapts to any roster configuration.
"""

import asyncio
from typing import Dict, List, Optional, Any
from loguru import logger

from .yahoo_auth import YahooAuth
from ..utils.roster_configs import RosterConfiguration, RosterPosition, LeagueType


class RosterDetector:
    """
    Detects and manages roster configurations for different Yahoo leagues.
    """
    
    def __init__(self, auth: YahooAuth):
        """Initialize with Yahoo authentication."""
        self.auth = auth
        self.league_rosters: Dict[str, List[RosterPosition]] = {}
        self.league_settings: Dict[str, Dict[str, Any]] = {}
    
    async def detect_league_roster(self, league_key: str) -> List[RosterPosition]:
        """
        Detect the roster configuration for a specific league.
        
        Args:
            league_key: Yahoo league key (e.g., "423.l.123456")
            
        Returns:
            List of RosterPosition objects defining the league's roster
        """
        # Check cache
        if league_key in self.league_rosters:
            return self.league_rosters[league_key]
        
        try:
            # Fetch league settings from Yahoo
            endpoint = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}/settings"
            
            async with self.auth.authenticated_session() as session:
                headers = {"Accept": "application/json"}
                async with session.get(endpoint, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to get league settings: {response.status}")
                        return self._get_default_roster()
                    
                    data = await response.json()
            
            # Parse the settings
            roster_positions = self._parse_yahoo_settings(data)
            
            # Cache the result
            self.league_rosters[league_key] = roster_positions
            
            # Store full settings for reference
            self.league_settings[league_key] = self._extract_league_settings(data)
            
            logger.info(f"Detected roster for {league_key}: {self._summarize_roster(roster_positions)}")
            
            return roster_positions
            
        except Exception as e:
            logger.error(f"Error detecting roster for {league_key}: {e}")
            return self._get_default_roster()
    
    def _parse_yahoo_settings(self, data: Dict[str, Any]) -> List[RosterPosition]:
        """
        Parse Yahoo's league settings response to extract roster positions.
        
        Yahoo returns settings in a complex nested structure.
        """
        positions = []
        
        try:
            # Navigate Yahoo's nested JSON structure
            content = data.get("fantasy_content", {})
            league = content.get("league", {})
            
            if isinstance(league, list):
                for item in league:
                    if isinstance(item, dict) and "settings" in item:
                        settings = item["settings"]
                        
                        if isinstance(settings, list):
                            for setting in settings:
                                if isinstance(setting, dict) and "roster_positions" in setting:
                                    roster_data = setting["roster_positions"]
                                    
                                    if isinstance(roster_data, list):
                                        for pos_item in roster_data:
                                            if isinstance(pos_item, dict) and "roster_position" in pos_item:
                                                pos_info = pos_item["roster_position"]
                                                positions.append(self._parse_position(pos_info))
                                    elif isinstance(roster_data, dict):
                                        # Sometimes it's a dict with numbered keys
                                        for key, value in roster_data.items():
                                            if key != "count" and isinstance(value, dict):
                                                if "roster_position" in value:
                                                    positions.append(self._parse_position(value["roster_position"]))
            
            # If we couldn't parse, check for alternative structure
            if not positions:
                positions = self._parse_alternative_structure(data)
            
        except Exception as e:
            logger.error(f"Error parsing Yahoo settings: {e}")
            positions = self._get_default_roster()
        
        return positions if positions else self._get_default_roster()
    
    def _parse_position(self, pos_data: Dict[str, Any]) -> RosterPosition:
        """
        Parse a single position from Yahoo's format.
        
        Example Yahoo position data:
        {
            "position": "WR",
            "position_type": "O",  # O=Offense, F=Flex, K=Kicker, etc.
            "count": 3,
            "is_starting_position": true
        }
        """
        position_name = pos_data.get("position", "UNKNOWN")
        count = int(pos_data.get("count", 1))
        position_type = pos_data.get("position_type", "")
        
        # Map Yahoo position names to our standard names
        position_map = {
            "BN": "BN",
            "IR": "IR",
            "IR+": "IR",
            "IL": "IR",
            "IL+": "IR",
            "DEF": "DST",
            "D/ST": "DST",
            "W/R": "W/R",
            "W/T": "W/T",
            "W/R/T": "FLEX",
            "Q/W/R/T": "SUPERFLEX",
            "UTIL": "FLEX",
            "OP": "SUPERFLEX"
        }
        
        mapped_position = position_map.get(position_name, position_name)
        
        # Determine position properties
        is_bench = position_type == "BN" or mapped_position == "BN"
        is_ir = position_type in ["IR", "IL"] or mapped_position == "IR"
        
        # Get eligible positions for flex spots
        eligible = RosterConfiguration.POSITION_ELIGIBILITY.get(mapped_position)
        
        return RosterPosition(
            position_type=mapped_position,
            count=count,
            eligible_positions=eligible,
            is_bench=is_bench,
            is_ir=is_ir
        )
    
    def _parse_alternative_structure(self, data: Dict[str, Any]) -> List[RosterPosition]:
        """
        Try alternative parsing if primary method fails.
        Some leagues have different JSON structures.
        """
        positions = []
        
        try:
            # Look for settings in different location
            league = data.get("fantasy_content", {}).get("league", {})
            
            # If league is a single dict (not a list)
            if isinstance(league, dict) and "settings" in league:
                settings = league["settings"]
                if "roster_positions" in settings:
                    for pos in settings["roster_positions"]:
                        positions.append(self._parse_position(pos))
        except Exception as e:
            logger.debug(f"Alternative parsing also failed: {e}")
        
        return positions
    
    def _extract_league_settings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract other useful league settings.
        """
        settings = {}
        
        try:
            content = data.get("fantasy_content", {}).get("league", {})
            
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        # Extract scoring type
                        if "scoring_type" in item:
                            settings["scoring_type"] = item["scoring_type"]
                        
                        # Extract other settings
                        if "settings" in item:
                            league_settings = item["settings"]
                            if isinstance(league_settings, list):
                                for setting in league_settings:
                                    if isinstance(setting, dict):
                                        # Common settings to extract
                                        for key in ["max_teams", "playoff_start_week", 
                                                   "uses_playoff", "has_multiweek_championship",
                                                   "waiver_type", "waiver_rule", "uses_faab",
                                                   "trade_reject_time", "league_update_timestamp"]:
                                            if key in setting:
                                                settings[key] = setting[key]
            
            # Detect if it's PPR, Half-PPR, or Standard
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "stat_modifiers" in item:
                        modifiers = item["stat_modifiers"]
                        if isinstance(modifiers, dict) and "stats" in modifiers:
                            stats = modifiers["stats"]
                            if isinstance(stats, list):
                                for stat in stats:
                                    if stat.get("stat_id") == 9:  # Receptions
                                        value = float(stat.get("value", 0))
                                        if value == 1.0:
                                            settings["scoring_format"] = "PPR"
                                        elif value == 0.5:
                                            settings["scoring_format"] = "Half-PPR"
                                        else:
                                            settings["scoring_format"] = "Standard"
                                        break
        
        except Exception as e:
            logger.debug(f"Error extracting league settings: {e}")
        
        return settings
    
    def _get_default_roster(self) -> List[RosterPosition]:
        """
        Return a default roster configuration if detection fails.
        """
        logger.warning("Using default roster configuration")
        return RosterConfiguration.ROSTER_TEMPLATES["yahoo_standard"]
    
    def _summarize_roster(self, positions: List[RosterPosition]) -> str:
        """
        Create a human-readable summary of roster positions.
        """
        starting = []
        bench = 0
        ir = 0
        
        for pos in positions:
            if pos.is_bench:
                bench += pos.count
            elif pos.is_ir:
                ir += pos.count
            else:
                if pos.count > 1:
                    starting.append(f"{pos.count}{pos.position_type}")
                else:
                    starting.append(pos.position_type)
        
        summary = ", ".join(starting)
        if bench > 0:
            summary += f", {bench}BN"
        if ir > 0:
            summary += f", {ir}IR"
        
        return summary
    
    async def detect_all_league_rosters(self, league_keys: List[str]) -> Dict[str, List[RosterPosition]]:
        """
        Detect rosters for multiple leagues in parallel.
        
        Args:
            league_keys: List of Yahoo league keys
            
        Returns:
            Dictionary mapping league_key to roster configuration
        """
        tasks = [self.detect_league_roster(key) for key in league_keys]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        rosters = {}
        for league_key, result in zip(league_keys, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to detect roster for {league_key}: {result}")
                rosters[league_key] = self._get_default_roster()
            else:
                rosters[league_key] = result
        
        return rosters
    
    def get_league_type(self, league_key: str) -> LeagueType:
        """
        Determine the type of league based on its roster configuration.
        """
        if league_key not in self.league_rosters:
            return LeagueType.STANDARD
        
        roster = self.league_rosters[league_key]
        return RosterConfiguration.detect_league_type(roster)
    
    def get_starting_positions(self, league_key: str) -> List[str]:
        """
        Get the starting positions for a league as a flat list.
        
        Returns: ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST", "K"]
        """
        if league_key not in self.league_rosters:
            roster = self._get_default_roster()
        else:
            roster = self.league_rosters[league_key]
        
        return RosterConfiguration.get_starting_positions(roster)
    
    def can_start_player(self, league_key: str, player_position: str, 
                        roster_slot: str) -> bool:
        """
        Check if a player can be started in a specific roster slot.
        
        Args:
            league_key: Yahoo league key
            player_position: Player's actual position (e.g., "RB")
            roster_slot: The roster slot to fill (e.g., "FLEX")
            
        Returns:
            True if the player can fill that slot
        """
        if league_key not in self.league_rosters:
            roster = self._get_default_roster()
        else:
            roster = self.league_rosters[league_key]
        
        return RosterConfiguration.can_slot_player(player_position, roster_slot, roster)
    
    def get_league_summary(self, league_key: str) -> Dict[str, Any]:
        """
        Get a summary of the league's configuration.
        """
        roster = self.league_rosters.get(league_key, self._get_default_roster())
        settings = self.league_settings.get(league_key, {})
        league_type = self.get_league_type(league_key)
        
        return {
            "league_key": league_key,
            "league_type": league_type.value,
            "roster_summary": self._summarize_roster(roster),
            "starting_positions": self.get_starting_positions(league_key),
            "scoring_format": settings.get("scoring_format", "Unknown"),
            "waiver_type": settings.get("waiver_type", "Unknown"),
            "uses_faab": settings.get("uses_faab", False),
            "settings": settings
        }