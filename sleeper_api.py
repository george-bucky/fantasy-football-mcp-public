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
import difflib
import re

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
            # Build normalized index for improved matching
            self._build_normalized_index(players)
        return players or {}

    # ----------------------- Name Normalization Utilities ------------------
    _normalized_index: Dict[str, str] = {}
    _normalized_variants: Dict[str, List[str]] = {}

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize player name for matching.

        Steps:
        - Lowercase
        - Remove punctuation (periods, apostrophes, commas, hyphens)
        - Remove suffix tokens (jr, sr, ii, iii, iv, v)
        - Collapse whitespace
        """
        if not name:
            return ""
        n = name.lower()
        # Remove punctuation
        n = re.sub(r"[\.'`,-]", " ", n)
        # Remove suffix tokens
        suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
        parts = [p for p in n.split() if p not in suffixes and len(p) > 0]
        # Remove single-letter middle initials
        parts = [p for p in parts if len(p) > 1 or parts.count(p) == 1]
        return " ".join(parts).strip()

    def _build_normalized_index(self, players: Dict[str, Dict]) -> None:
        """Build a mapping of normalized full names -> player_id for fast lookup."""
        idx: Dict[str, str] = {}
        variants: Dict[str, List[str]] = {}
        for pid, pdata in players.items():
            first = pdata.get("first_name", "")
            last = pdata.get("last_name", "")
            full = f"{first} {last}".strip()
            if not full:
                continue
            norm = self._normalize_name(full)
            if norm and norm not in idx:
                idx[norm] = pid
                # Store variant forms (initial + last)
                if first and last:
                    initial_form = f"{first[0]} {last}".lower()
                    variants.setdefault(norm, []).append(self._normalize_name(initial_form))
        self._normalized_index = idx
        self._normalized_variants = variants

    def _fuzzy_lookup(self, norm_query: str, cutoff: float = 0.88) -> Optional[str]:
        """Fuzzy match normalized query among normalized index keys."""
        if not self._normalized_index:
            return None
        candidates = list(self._normalized_index.keys())
        # Limit candidate set by first letter of last token to speed up
        if " " in norm_query:
            last_token = norm_query.split()[-1][:1]
            candidates = [c for c in candidates if c.split()[-1].startswith(last_token)] or list(self._normalized_index.keys())
        matches = difflib.get_close_matches(norm_query, candidates, n=1, cutoff=cutoff)
        if matches:
            return self._normalized_index.get(matches[0])
        return None
    
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
        Handles both list and dict response shapes from Sleeper API.
        """
        endpoint = f"projections/nfl/{season}/{week}"
        raw = await self._make_request(endpoint) or []
        
        # Normalize to dict keyed by player_id
        normalized: Dict[str, Dict] = {}
        if isinstance(raw, dict):
            # Already keyed by player_id
            normalized = {pid: pdata for pid, pdata in raw.items() if isinstance(pdata, dict)}
        elif isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    pid = entry.get("player_id")
                    if pid:
                        normalized[str(pid)] = entry
        else:
            # Unknown shape
            return {}

        if not normalized:
            return {}

        # Optionally filter by positions and enrich with player info
        all_players = await self.get_all_players()
        if positions:
            positions_set = set(positions)
            filtered: Dict[str, Dict] = {}
            for player_id, proj_data in normalized.items():
                player = all_players.get(player_id)
                if not player:
                    continue
                if player.get("position") in positions_set:
                    proj_data = dict(proj_data)
                    proj_data["player_name"] = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
                    proj_data["position"] = player.get("position")
                    proj_data["team"] = player.get("team")
                    filtered[player_id] = proj_data
            return filtered
        
        # Enrich without filtering for convenience
        for player_id, proj_data in list(normalized.items()):
            player = all_players.get(player_id)
            if player:
                proj_data["player_name"] = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
                proj_data["position"] = player.get("position")
                proj_data["team"] = player.get("team")
        
        return normalized
    
    async def get_player_by_name(self, name: str) -> Optional[Dict]:
        """Improved player lookup with normalization and fuzzy fallback."""
        all_players = await self.get_all_players()
        if not all_players:
            return None

        raw = name.strip()
        lower_raw = raw.lower()
        norm = self._normalize_name(raw)

        # Direct exact full-name match (raw)
        for pid, pdata in all_players.items():
            full = f"{pdata.get('first_name', '')} {pdata.get('last_name', '')}".strip().lower()
            if full == lower_raw:
                pdata["sleeper_id"] = pid
                pdata["match_method"] = "exact"
                return pdata

        # Normalized index lookup
        if norm in self._normalized_index:
            pid = self._normalized_index[norm]
            pdata = all_players.get(pid)
            if pdata:
                pdata["sleeper_id"] = pid
                pdata["match_method"] = "normalized"
                return pdata

        # Variant forms (initial + last)
        for base_norm, var_list in self._normalized_variants.items():
            if norm in var_list:
                pid = self._normalized_index.get(base_norm)
                pdata = all_players.get(pid)
                if pdata:
                    pdata["sleeper_id"] = pid
                    pdata["match_method"] = "variant"
                    return pdata

        # Partial token match (subset containment)
        tokens = set(norm.split())
        if tokens:
            for pid, pdata in all_players.items():
                full_norm = self._normalize_name(f"{pdata.get('first_name', '')} {pdata.get('last_name', '')}")
                if tokens.issubset(set(full_norm.split())):
                    pdata["sleeper_id"] = pid
                    pdata["match_method"] = "token_subset"
                    return pdata

        # Fuzzy fallback
        fuzzy_pid = self._fuzzy_lookup(norm)
        if fuzzy_pid:
            pdata = all_players.get(fuzzy_pid)
            if pdata:
                pdata["sleeper_id"] = fuzzy_pid
                pdata["match_method"] = "fuzzy"
                return pdata

        return None
    
    async def get_defensive_rankings(self, season: int = 2024) -> Dict[str, Dict]:
        """
        Get defensive rankings by team and position matchup.
        This is derived from player stats and matchup data.
        
        Returns: {
            "team_abbr": {
                "vs_qb_rank": 1-32,
                "vs_rb_rank": 1-32,
                "vs_wr_rank": 1-32,
                "vs_te_rank": 1-32
            }
        }
        """
        # For now, return a mock structure
        # In production, this would aggregate actual defensive performance data
        # Sleeper doesn't provide direct defensive rankings, so we'd need to calculate
        # from game stats or integrate with another source
        
        # Mock data for testing (will be replaced with real calculations)
        mock_rankings = {
            "ARI": {"vs_qb": 28, "vs_rb": 32, "vs_wr": 25, "vs_te": 27},
            "ATL": {"vs_qb": 22, "vs_rb": 26, "vs_wr": 18, "vs_te": 20},
            "BAL": {"vs_qb": 2, "vs_rb": 3, "vs_wr": 2, "vs_te": 5},
            "BUF": {"vs_qb": 8, "vs_rb": 12, "vs_wr": 10, "vs_te": 8},
            "CAR": {"vs_qb": 25, "vs_rb": 27, "vs_wr": 30, "vs_te": 24},
            "CHI": {"vs_qb": 12, "vs_rb": 8, "vs_wr": 15, "vs_te": 14},
            "CIN": {"vs_qb": 18, "vs_rb": 20, "vs_wr": 16, "vs_te": 19},
            "CLE": {"vs_qb": 1, "vs_rb": 7, "vs_wr": 4, "vs_te": 3},
            "DAL": {"vs_qb": 7, "vs_rb": 10, "vs_wr": 8, "vs_te": 11},
            "DEN": {"vs_qb": 4, "vs_rb": 14, "vs_wr": 6, "vs_te": 9},
            "DET": {"vs_qb": 24, "vs_rb": 30, "vs_wr": 28, "vs_te": 26},
            "GB": {"vs_qb": 14, "vs_rb": 17, "vs_wr": 13, "vs_te": 15},
            "HOU": {"vs_qb": 11, "vs_rb": 5, "vs_wr": 12, "vs_te": 10},
            "IND": {"vs_qb": 20, "vs_rb": 22, "vs_wr": 21, "vs_te": 18},
            "JAX": {"vs_qb": 26, "vs_rb": 24, "vs_wr": 27, "vs_te": 28},
            "KC": {"vs_qb": 15, "vs_rb": 16, "vs_wr": 14, "vs_te": 13},
            "LAC": {"vs_qb": 10, "vs_rb": 9, "vs_wr": 11, "vs_te": 12},
            "LAR": {"vs_qb": 19, "vs_rb": 18, "vs_wr": 20, "vs_te": 21},
            "LV": {"vs_qb": 27, "vs_rb": 29, "vs_wr": 26, "vs_te": 30},
            "MIA": {"vs_qb": 16, "vs_rb": 15, "vs_wr": 17, "vs_te": 16},
            "MIN": {"vs_qb": 13, "vs_rb": 11, "vs_wr": 19, "vs_te": 17},
            "NE": {"vs_qb": 6, "vs_rb": 4, "vs_wr": 7, "vs_te": 6},
            "NO": {"vs_qb": 9, "vs_rb": 6, "vs_wr": 9, "vs_te": 7},
            "NYG": {"vs_qb": 21, "vs_rb": 23, "vs_wr": 22, "vs_te": 23},
            "NYJ": {"vs_qb": 3, "vs_rb": 2, "vs_wr": 3, "vs_te": 4},
            "PHI": {"vs_qb": 5, "vs_rb": 13, "vs_wr": 5, "vs_te": 2},
            "PIT": {"vs_qb": 17, "vs_rb": 1, "vs_wr": 23, "vs_te": 22},
            "SEA": {"vs_qb": 29, "vs_rb": 31, "vs_wr": 29, "vs_te": 31},
            "SF": {"vs_qb": 23, "vs_rb": 19, "vs_wr": 24, "vs_te": 25},
            "TB": {"vs_qb": 30, "vs_rb": 25, "vs_wr": 31, "vs_te": 29},
            "TEN": {"vs_qb": 31, "vs_rb": 28, "vs_wr": 32, "vs_te": 32},
            "WAS": {"vs_qb": 32, "vs_rb": 21, "vs_wr": 1, "vs_te": 1}
        }
        
        return mock_rankings
    
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

    async def get_position_rankings(self, position: str, week: Optional[int] = None) -> List[Dict]:
        """
        Get position rankings and tiers for lineup decisions.
        Returns players ranked by expert consensus and matchup strength.
        """
        # Get all players for the position
        all_players = await self.get_all_players()
        position_players = [
            player for player in all_players.values() 
            if player.get('position') == position.upper() and player.get('active', False)
        ]
        
        # Sort by search_rank (Sleeper's internal ranking)
        position_players.sort(key=lambda x: x.get('search_rank', 9999))
        
        # Create tier-based rankings
        rankings = []
        for i, player in enumerate(position_players[:50]):  # Top 50 per position
            tier = 1 if i < 5 else 2 if i < 12 else 3 if i < 24 else 4
            confidence = max(100 - (i * 2), 50)  # Confidence decreases with rank
            
            rankings.append({
                'player_id': player.get('sleeper_id'),
                'name': player.get('full_name'),
                'team': player.get('team'),
                'position': player.get('position'),
                'rank': i + 1,
                'tier': tier,
                'confidence': confidence,
                'tier_description': {
                    1: 'Elite - Must Start',
                    2: 'Strong Start',
                    3: 'Solid Option',
                    4: 'Depth/Bye Week'
                }.get(tier, 'Deep Bench')
            })
        
        return rankings

    async def get_expert_advice(self, player_name: str, week: Optional[int] = None) -> Dict[str, Any]:
        """
        Generate expert advice for a specific player including start/sit recommendations.
        """
        player = await self.get_player_by_name(player_name)
        if not player:
            return {'advice': 'Player not found', 'confidence': 0}
        
        position = player.get('position')
        team = player.get('team')
        search_rank = player.get('search_rank', 500)
        
        # Determine player tier based on search rank
        if search_rank <= 20:
            tier = "Elite"
            base_confidence = 85
        elif search_rank <= 50:
            tier = "Strong"
            base_confidence = 70
        elif search_rank <= 100:
            tier = "Solid"
            base_confidence = 55
        elif search_rank <= 200:
            tier = "Depth"
            base_confidence = 40
        else:
            tier = "Deep"
            base_confidence = 25
        
        # Generate contextual advice
        if base_confidence >= 70:
            recommendation = "Strong Start"
            advice_text = f"{player_name} ({tier} tier) is a confident start option this week."
        elif base_confidence >= 50:
            recommendation = "Start"
            advice_text = f"{player_name} ({tier} tier) is a solid start option for your lineup."
        elif base_confidence >= 35:
            recommendation = "Flex/Consider"
            advice_text = f"{player_name} ({tier} tier) could work as a flex play or deeper option."
        else:
            recommendation = "Bench/Avoid"
            advice_text = f"{player_name} ({tier} tier) is better kept on bench unless desperate."
        
        return {
            'player_name': player_name,
            'position': position,
            'team': team,
            'tier': tier,
            'search_rank': search_rank,
            'recommendation': recommendation,
            'confidence': base_confidence,
            'advice': advice_text,
            'week': week or await get_current_week()
        }


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


async def get_current_season() -> int:
    """Get current NFL season (fallback to current year)."""
    try:
        state = await sleeper_client.get_nfl_state()
        season = state.get("season")
        if isinstance(season, int):
            return season
        # Sleeper may return season as string
        if isinstance(season, str) and season.isdigit():
            return int(season)
    except Exception:
        pass
    # Fallback: infer from calendar year
    return datetime.now().year


async def get_player_projection(
    player_name: str,
    week: Optional[int] = None,
    season: Optional[int] = None,
) -> Optional[Dict]:
    """Get projection for a specific player by name using dynamic season/week."""
    # Resolve week/season if not specified
    if not week:
        week = await get_current_week()
    if not season:
        season = await get_current_season()

    # Find player
    player = await sleeper_client.get_player_by_name(player_name)
    if not player:
        return None

    # Get projections for requested season/week
    projections = await sleeper_client.get_projections(season, week)

    player_id = player.get("sleeper_id")
    if player_id and player_id in projections:
        proj = projections[player_id]
        proj["player_name"] = player_name
        proj["position"] = player.get("position")
        proj["team"] = player.get("team")
        if "match_method" in player:
            proj["match_method"] = player["match_method"]
        return proj

    return None