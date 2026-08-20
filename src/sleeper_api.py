#!/usr/bin/env python3
"""
Sleeper API client for fantasy football data
No authentication required - completely free and open API
"""

import asyncio
import aiohttp
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import hashlib

# Import caching from our yahoo utils
from yahoo_api_utils import ResponseCache


class SleeperAPI:
    """Client for Sleeper's free fantasy football API."""
    
    BASE_URL = "https://api.sleeper.app/v1"
    
    def __init__(self):
        self.cache = ResponseCache()
        # Override cache TTLs for Sleeper data
        self.cache.default_ttls.update({
            "players": 86400,      # 24 hours - player pool rarely changes
            "trending": 1800,      # 30 minutes - trending is more dynamic
            "projections": 3600,   # 1 hour - projections update periodically
            "stats": 300,          # 5 minutes - during games
            "matchups": 86400,     # 24 hours - NFL matchups are weekly
        })
        
        # Cache for player name mapping
        self._players_cache = None
        self._players_cache_time = None
        
    async def _make_request(self, endpoint: str, use_cache: bool = True) -> Optional[Dict]:
        """Make a request to Sleeper API."""
        # Check cache first
        if use_cache:
            cached = await self.cache.get(endpoint)
            if cached is not None:
                return cached
        
        url = f"{self.BASE_URL}/{endpoint}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Cache successful response
                        if use_cache:
                            await self.cache.set(endpoint, data)
                        return data
                    else:
                        print(f"Sleeper API error {response.status} for {endpoint}")
                        return None
        except Exception as e:
            print(f"Error fetching from Sleeper: {e}")
            return None
    
    async def get_all_players(self) -> Dict[str, Dict]:
        """
        Get all NFL players with their IDs and info.
        Returns dict keyed by player_id.
        """
        # Use cached version if available (24 hour cache)
        if self._players_cache and self._players_cache_time:
            age = (datetime.now() - self._players_cache_time).seconds
            if age < 86400:  # 24 hours
                return self._players_cache
        
        players = await self._make_request("players/nfl")
        if players:
            self._players_cache = players
            self._players_cache_time = datetime.now()
        return players or {}
    
    async def get_trending_players(self, sport: str = "nfl", add_drop: str = "add", hours: int = 24, limit: int = 25) -> List[Dict]:
        """
        Get trending players being added or dropped.
        
        Args:
            sport: Sport (default "nfl")
            add_drop: "add" for most added, "drop" for most dropped
            hours: Lookback period (24 or 48 hours)
            limit: Number of results
        """
        endpoint = f"players/{sport}/trending/{add_drop}?lookback_hours={hours}&limit={limit}"
        data = await self._make_request(endpoint, use_cache=True)
        
        if data:
            # Enrich with player names
            all_players = await self.get_all_players()
            enriched = []
            
            for item in data:
                player_id = item.get("player_id")
                if player_id and player_id in all_players:
                    player = all_players[player_id]
                    enriched.append({
                        "player_id": player_id,
                        "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                        "position": player.get("position"),
                        "team": player.get("team"),
                        "count": item.get("count", 0),  # Number of adds/drops
                        "injury_status": player.get("injury_status"),
                        "age": player.get("age"),
                        "years_exp": player.get("years_exp")
                    })
            
            return enriched
        return []
    
    async def get_nfl_state(self) -> Dict:
        """Get current NFL season state (week, season, etc)."""
        return await self._make_request("state/nfl") or {}
    
    async def get_projections(self, season: int, week: int, positions: Optional[List[str]] = None) -> Dict[str, Dict]:
        """
        Get player projections for a specific week.
        
        Returns dict keyed by player_id with projection data.
        """
        # Get base projections
        endpoint = f"projections/nfl/{season}/{week}"
        projections = await self._make_request(endpoint) or {}
        
        # Filter by positions if specified
        if positions and projections:
            filtered = {}
            all_players = await self.get_all_players()
            
            for player_id, proj_data in projections.items():
                if player_id in all_players:
                    player = all_players[player_id]
                    if player.get("position") in positions:
                        # Add player info to projection
                        proj_data["player_name"] = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
                        proj_data["position"] = player.get("position")
                        proj_data["team"] = player.get("team")
                        filtered[player_id] = proj_data
            
            return filtered
        
        return projections
    
    async def get_player_by_name(self, name: str) -> Optional[Dict]:
        """
        Find a player by name (case insensitive).
        Returns player info with sleeper_id.
        """
        all_players = await self.get_all_players()
        
        name_lower = name.lower().strip()
        
        # Try exact match first
        for player_id, player in all_players.items():
            full_name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip().lower()
            if full_name == name_lower:
                player["sleeper_id"] = player_id
                return player
        
        # Try partial match
        for player_id, player in all_players.items():
            full_name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip().lower()
            if name_lower in full_name or full_name in name_lower:
                player["sleeper_id"] = player_id
                return player
        
        # Try last name only
        for player_id, player in all_players.items():
            last_name = player.get('last_name', '').lower()
            if last_name and (last_name == name_lower or name_lower == last_name):
                player["sleeper_id"] = player_id
                return player
        
        return None
    
    async def get_defensive_rankings(self, season: int = 2024) -> Dict[str, Dict]:
        """Return no ranking when source-backed defensive evidence is absent."""
        return {}
    
    async def map_yahoo_to_sleeper(self, yahoo_name: str, position: str = None, team: str = None) -> Optional[str]:
        """
        Map a Yahoo player name to Sleeper player ID.
        
        Args:
            yahoo_name: Player name from Yahoo
            position: Optional position to help disambiguation
            team: Optional team to help disambiguation
            
        Returns:
            Sleeper player_id if found
        """
        # Clean the Yahoo name (remove Jr., Sr., III, etc)
        clean_name = yahoo_name.replace(" Jr.", "").replace(" Sr.", "").replace(" III", "").replace(" II", "")
        
        player = await self.get_player_by_name(clean_name)
        
        if player:
            # Verify position/team if provided
            if position and player.get("position") != position:
                return None
            if team and player.get("team") != team:
                return None
            
            return player.get("sleeper_id")
        
        return None


# Global instance
sleeper_client = SleeperAPI()


# Convenience functions for direct use
async def get_trending_adds(limit: int = 10) -> List[Dict]:
    """Get top trending player adds."""
    return await sleeper_client.get_trending_players(add_drop="add", limit=limit)


async def get_trending_drops(limit: int = 10) -> List[Dict]:
    """Get top trending player drops."""
    return await sleeper_client.get_trending_players(add_drop="drop", limit=limit)


async def get_current_week() -> int:
    """Get current NFL week."""
    state = await sleeper_client.get_nfl_state()
    return state.get("week", 1)


async def get_player_projection(player_name: str, week: Optional[int] = None) -> Optional[Dict]:
    """Get projection for a specific player by name."""
    # Get current week if not specified
    if not week:
        week = await get_current_week()
    
    # Find player
    player = await sleeper_client.get_player_by_name(player_name)
    if not player:
        return None
    
    # Get projections
    projections = await sleeper_client.get_projections(2024, week)
    
    player_id = player.get("sleeper_id")
    if player_id and player_id in projections:
        proj = projections[player_id]
        proj["player_name"] = player_name
        proj["position"] = player.get("position")
        proj["team"] = player.get("team")
        return proj
    
    return None
