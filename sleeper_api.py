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
import os
import re

# Import caching from our yahoo utils
from src.api.yahoo_utils import ResponseCache


class SleeperAPI:
    """Client for Sleeper's free fantasy football API."""

    BASE_URL = "https://api.sleeper.app/v1"

    def __init__(self):
        self.cache = ResponseCache()
        # Override cache TTLs for Sleeper data
        self.cache.default_ttls.update(
            {
                "players": 86400,  # 24 hours - player pool rarely changes
                "trending": 1800,  # 30 minutes - trending is more dynamic
                "projections": 3600,  # 1 hour - projections update periodically
                "stats": 300,  # 5 minutes - during games
                "matchups": 86400,  # 24 hours - NFL matchups are weekly
            }
        )

        # Cache for player name mapping
        self._players_cache = None
        self._players_cache_time = None

    async def _make_request(self, endpoint: str, use_cache: bool = True) -> Optional[Dict]:
        """Make a request to Sleeper API."""
        # Ensure endpoint is str
        if not isinstance(endpoint, str):
            endpoint = str(endpoint)

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
        - Handle initials: Concatenate consecutive single letters (e.g., "J.K." -> "jk")
        - Remove suffix tokens (jr, sr, ii, iii, iv, v, jr., sr., etc.)
        - Collapse whitespace
        - Optional: Apply common nickname mappings
        """
        if not name:
            return ""
        n = name.lower()
        # Remove punctuation but preserve for initial detection
        n = re.sub(r"[,`'-]", " ", n)

        # Handle initials: Find patterns like "j . k" or "j.k" and concatenate to "jk"
        words = n.split()
        i = 0
        while i < len(words):
            word = words[i]
            if len(word) == 1 and i + 1 < len(words) and len(words[i + 1]) == 1:
                # Concatenate two single letters: "j k" -> "jk"
                words[i] = word + words[i + 1]
                del words[i + 1]
                i += 1  # Skip next now-deleted
            elif "." in word and all(len(part) == 1 for part in word.split(".")):
                # "j.k." -> "jk"
                words[i] = "".join(part for part in word.split(".") if part)
            i += 1

        n = " ".join(words)

        # Remove punctuation fully now
        n = re.sub(r"[\.'`,-]", " ", n)

        # Remove suffix tokens (expanded)
        suffixes = {"jr", "sr", "ii", "iii", "iv", "v", "jr.", "sr.", "ii.", "iii.", "iv.", "v."}
        parts = [p.strip() for p in n.split() if p.strip() not in suffixes and len(p.strip()) > 0]

        # Remove single-letter middle initials (now after concatenation)
        parts = [p for p in parts if len(p) > 1 or parts.count(p) == 1]

        normalized = " ".join(parts).strip()

        # Apply common nickname mappings (expand as needed)
        nickname_map = {
            "deebosamuel": "demonte samuel",
            "dkmetcalf": "dk metcalf",
            # Add more: "cmac" -> "christian mccaffrey", etc.
        }
        normalized_lower = normalized.lower().replace(" ", "")
        for nick, full in nickname_map.items():
            if nick in normalized_lower:
                return full

        return normalized

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
                # Store variant forms
                if first and last:
                    # Initial + last (original)
                    initial_form = f"{first[0]} {last}".lower()
                    variants.setdefault(norm, []).append(self._normalize_name(initial_form))

                    # Concatenated initials + last (new: e.g., "jk dobbins")
                    initials = "".join([f[0] for f in first.split() if f and len(f) > 0])
                    if len(initials) > 1:
                        concat_form = f"{initials} {last}".lower()
                        variants.setdefault(norm, []).append(self._normalize_name(concat_form))

                    # Full first without middle + last
                    first_no_middle = " ".join([part for part in first.split() if len(part) > 1])
                    if first_no_middle:
                        full_no_middle = f"{first_no_middle} {last}".lower()
                        variants.setdefault(norm, []).append(self._normalize_name(full_no_middle))
        self._normalized_index = idx
        self._normalized_variants = variants

    def _fuzzy_lookup(self, norm_query: str, cutoff: float = 0.82) -> Optional[str]:
        """Fuzzy match normalized query among normalized index keys."""
        if not self._normalized_index:
            return None
        candidates = list(self._normalized_index.keys())
        # Limit candidate set by first letter of last token to speed up
        if " " in norm_query:
            last_token = norm_query.split()[-1][:1]
            candidates = [c for c in candidates if c.split()[-1].startswith(last_token)] or list(
                self._normalized_index.keys()
            )
        matches = difflib.get_close_matches(norm_query, candidates, n=1, cutoff=cutoff)
        if matches:
            return self._normalized_index.get(matches[0])
        return None

    async def get_trending_players(
        self, sport: str = "nfl", add_drop: str = "add", hours: int = 24, limit: int = 25
    ) -> List[Dict]:
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
                    enriched.append(
                        {
                            "player_id": player_id,
                            "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                            "position": player.get("position"),
                            "team": player.get("team"),
                            "count": item.get("count", 0),  # Number of adds/drops
                            "injury_status": player.get("injury_status"),
                            "age": player.get("age"),
                            "years_exp": player.get("years_exp"),
                        }
                    )

            return enriched
        return []

    async def get_nfl_state(self) -> Dict:
        """Get current NFL season state (week, season, etc)."""
        return await self._make_request("state/nfl") or {}

    async def get_projections(
        self, season: int, week: int, positions: Optional[List[str]] = None
    ) -> Dict[str, Dict]:
        """
        Get player projections for a specific week.

        Since Sleeper's projection API often returns empty data, this function
        creates fallback projections based on rankings and stats.

        Returns dict keyed by player_id with projection data.
        """
        endpoint = f"projections/nfl/{season}/{week}"
        raw = await self._make_request(endpoint) or {}

        # Check if we have real projection data
        real_projections = {}
        if isinstance(raw, dict):
            real_projections = {
                pid: pdata
                for pid, pdata in raw.items()
                if isinstance(pdata, dict) and pdata.get("pts") is not None
            }

        # If no real projections, create fallback projections based on rankings
        if not real_projections:
            print("No real projections available, creating fallback projections from rankings...")
            return await self._create_fallback_projections(season, week, positions)

        # Enrich real projections with player info
        all_players = await self.get_all_players()
        if positions:
            positions_set = set(positions)
            filtered: Dict[str, Dict] = {}
            for player_id, proj_data in real_projections.items():
                player = all_players.get(player_id)
                if not player:
                    continue
                if player.get("position") in positions_set:
                    proj_data = dict(proj_data)
                    proj_data["player_name"] = (
                        f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
                    )
                    proj_data["position"] = player.get("position")
                    proj_data["team"] = player.get("team")
                    filtered[player_id] = proj_data
            return filtered

        # Enrich without filtering
        for player_id, proj_data in list(real_projections.items()):
            player = all_players.get(player_id)
            if player:
                proj_data["player_name"] = (
                    f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
                )
                proj_data["position"] = player.get("position")
                proj_data["team"] = player.get("team")

        return real_projections

    async def _create_fallback_projections(
        self, season: int, week: int, positions: Optional[List[str]] = None
    ) -> Dict[str, Dict]:
        """
        Create fallback projections based on player rankings and position averages.
        """
        fallback_projections = {}
        all_players = await self.get_all_players()

        # Position-based average fantasy points (rough estimates for 2025)
        position_averages = {
            "QB": {"elite": 25.0, "strong": 20.0, "solid": 16.0, "depth": 12.0, "deep": 8.0},
            "RB": {"elite": 18.0, "strong": 14.0, "solid": 11.0, "depth": 8.0, "deep": 5.0},
            "WR": {"elite": 16.0, "strong": 12.0, "solid": 10.0, "depth": 7.0, "deep": 4.0},
            "TE": {"elite": 12.0, "strong": 9.0, "solid": 7.0, "depth": 5.0, "deep": 3.0},
            "K": {"elite": 9.0, "strong": 7.0, "solid": 6.0, "depth": 5.0, "deep": 3.0},
            "DEF": {"elite": 10.0, "strong": 7.0, "solid": 5.0, "depth": 3.0, "deep": 1.0},
        }

        # Filter positions if specified
        target_positions = set(positions) if positions else {"QB", "RB", "WR", "TE", "K", "DEF"}

        for position in target_positions:
            position_players = [
                player
                for player in all_players.values()
                if (
                    player.get("position") == position.upper()
                    and player.get("active", False)
                    and player.get("team") is not None
                )  # Active players on teams
            ]

            # Sort by search_rank (lower = better)
            position_players.sort(key=lambda x: x.get("search_rank") or 9999)

            # Create projections based on ranking tiers
            for i, player in enumerate(position_players):
                player_id = player.get("player_id")
                if not player_id:
                    continue

                # Determine tier based on position ranking
                if i < 5:
                    tier = "elite"
                elif i < 12:
                    tier = "strong"
                elif i < 24:
                    tier = "solid"
                elif i < 50:
                    tier = "depth"
                else:
                    tier = "deep"

                # Get base projection for position/tier
                base_proj = position_averages.get(position, {}).get(tier, 5.0)

                # Add some variance based on exact ranking within tier
                tier_adjustment = max(0.0, 1.0 - (i * 0.02))  # Slight decrease per rank
                final_projection = base_proj * (0.8 + tier_adjustment * 0.4)  # 80-120% of base

                # Create projection data
                fallback_projections[str(player_id)] = {
                    "player_name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                    "position": player.get("position"),
                    "team": player.get("team"),
                    "pts": round(final_projection, 1),
                    "pts_ppr": round(final_projection * 1.1, 1),  # PPR boost
                    "pts_half_ppr": round(final_projection * 1.05, 1),  # Half PPR boost
                    "pts_std": round(final_projection, 1),
                    "projection_source": "fallback_ranking",
                    "tier": tier,
                    "position_rank": i + 1,
                }

        return fallback_projections

    async def get_player_by_name(self, name: str) -> Optional[Dict]:
        """Improved player lookup with normalization and fuzzy fallback."""
        all_players = await self.get_all_players()
        if not all_players:
            return None

        raw = name.strip()
        lower_raw = raw.lower()
        norm = self._normalize_name(raw)

        # Debug logging (enable with SLEEPER_DEBUG=1 env var)
        debug = os.getenv("SLEEPER_DEBUG")
        if debug:
            print(f"DEBUG Sleeper lookup: raw='{raw}' -> norm='{norm}'")

        # Direct exact full-name match (raw)
        for pid, pdata in all_players.items():
            full = f"{pdata.get('first_name', '')} {pdata.get('last_name', '')}".strip().lower()
            if full == lower_raw:
                pdata = pdata.copy()
                pdata["sleeper_id"] = pid
                pdata["match_method"] = "exact"
                if debug:
                    print(f"  -> Matched EXACT: {full}")
                return pdata

        # Normalized index lookup
        if norm in self._normalized_index:
            pid = self._normalized_index[norm]
            pdata = all_players.get(pid)
            if pdata:
                pdata = pdata.copy()
                pdata["sleeper_id"] = pid
                pdata["match_method"] = "normalized"
                if debug:
                    print(f"  -> Matched NORMALIZED: {norm}")
                return pdata

        # Variant forms (initial + last)
        for base_norm, var_list in self._normalized_variants.items():
            if norm in var_list:
                pid = self._normalized_index.get(base_norm)
                if pid:
                    pdata = all_players.get(pid)
                    if pdata:
                        pdata = pdata.copy()
                        pdata["sleeper_id"] = pid
                        pdata["match_method"] = "variant"
                        if debug:
                            print(f"  -> Matched VARIANT: {norm} -> {base_norm}")
                        return pdata

        # Partial token match (subset containment)
        tokens = set(norm.split())
        if tokens:
            for pid, pdata in all_players.items():
                full_norm = self._normalize_name(
                    f"{pdata.get('first_name', '')} {pdata.get('last_name', '')}"
                )
                if tokens.issubset(set(full_norm.split())):
                    pdata = pdata.copy()
                    pdata["sleeper_id"] = pid
                    pdata["match_method"] = "token_subset"
                    if debug:
                        print(f"  -> Matched TOKEN_SUBSET: {tokens} subset of {full_norm}")
                    return pdata

        # Fuzzy fallback
        fuzzy_pid = self._fuzzy_lookup(norm)
        if fuzzy_pid:
            pdata = all_players.get(fuzzy_pid)
            if pdata:
                pdata = pdata.copy()
                pdata["sleeper_id"] = fuzzy_pid
                pdata["match_method"] = "fuzzy"
                if debug:
                    print(f"  -> Matched FUZZY: {norm} -> {fuzzy_pid}")
                return pdata

        if debug:
            print(f"  -> NO MATCH for '{norm}'")
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
        mock_rankings: Dict[str, Dict[str, int]] = {
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
            "WAS": {"vs_qb": 32, "vs_rb": 21, "vs_wr": 1, "vs_te": 1},
        }

        return mock_rankings

    async def map_yahoo_to_sleeper(
        self, yahoo_name: str, position: Optional[str] = None, team: Optional[str] = None
    ) -> Optional[str]:
        """
        Map a Yahoo player name to Sleeper player ID.

        Args:
            yahoo_name: Player name from Yahoo
            position: Optional position to help disambiguation
            team: Optional team to help disambiguation

        Returns:
            Sleeper player_id if found (with relaxed filters)
        """
        # Clean the Yahoo name (remove Jr., Sr., III, etc)
        clean_name = (
            yahoo_name.replace(" Jr.", "")
            .replace(" Sr.", "")
            .replace(" III", "")
            .replace(" II", "")
            .replace(" IV", "")
            .replace(" Jr", "")
            .replace(" Sr", "")
        )

        player = await self.get_player_by_name(clean_name)

        if player:
            match_method = player.get("match_method", "unknown")

            # Relaxed verification: Flag mismatches but don't reject
            pos_mismatch = position and player.get("position") != position
            team_mismatch = team and player.get("team") != team

            if pos_mismatch:
                match_method += "_pos_mismatch"
            if team_mismatch:
                match_method += "_team_mismatch"

            # Update match_method in player data
            player["sleeper_match_method"] = match_method

            # Only reject if both mismatch AND no strong match (e.g., fuzzy or weaker)
            if (pos_mismatch and team_mismatch) and match_method in ["fuzzy", "token_subset"]:
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
            player
            for player in all_players.values()
            if player.get("position") == position.upper() and player.get("active", False)
        ]

        # Sort by search_rank (Sleeper's internal ranking), handling None values
        position_players.sort(key=lambda x: x.get("search_rank") or 9999)

        # Create tier-based rankings
        rankings = []
        for i, player in enumerate(position_players[:50]):  # Top 50 per position
            tier = 1 if i < 5 else 2 if i < 12 else 3 if i < 24 else 4
            confidence = max(100 - (i * 2), 50)  # Confidence decreases with rank

            rankings.append(
                {
                    "player_id": player.get("sleeper_id"),
                    "name": player.get("full_name"),
                    "team": player.get("team"),
                    "position": player.get("position"),
                    "rank": i + 1,
                    "tier": tier,
                    "confidence": confidence,
                    "tier_description": {
                        1: "Elite - Must Start",
                        2: "Strong Start",
                        3: "Solid Option",
                        4: "Depth/Bye Week",
                    }.get(tier, "Deep Bench"),
                }
            )

        return rankings

    async def get_expert_advice(
        self, player_name: str, week: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive expert advice for a specific player using multiple data sources.

        Factors considered:
        - Player projections and tier
        - Injury status and health
        - Matchup analysis
        - Trending data and momentum
        - Position-specific context
        """
        player = await self.get_player_by_name(player_name)
        if not player:
            return {"advice": "Player not found", "confidence": 0}

        current_week = week or await get_current_week()
        position = player.get("position")
        team = player.get("team")
        player_id = player.get("player_id")
        search_rank = player.get("search_rank", 999)

        # Get projection data
        season = 2025
        projections = await self.get_projections(season, current_week, [position])
        player_projection = projections.get(str(player_id), {})

        # Base scoring factors
        projection_score = player_projection.get("pts", 0)
        tier = player_projection.get("tier", "unknown")

        # Injury/health assessment
        injury_status = player.get("injury_status")
        health_factor = self._calculate_health_factor(injury_status)

        # Matchup analysis (import here to avoid circular imports)
        try:
            from matchup_analyzer import MatchupAnalyzer

            analyzer = MatchupAnalyzer()
            await analyzer.load_defensive_rankings()
            matchup_score, matchup_desc = analyzer.get_matchup_score(team, position)
        except:
            matchup_score, matchup_desc = 50, "Unknown matchup"

        # Trending analysis
        trending_factor = await self._get_trending_factor(player_name, player_id)

        # Calculate composite confidence score
        confidence = self._calculate_composite_confidence(
            projection_score, search_rank, health_factor, matchup_score, trending_factor
        )

        # Determine tier and recommendation
        final_tier, recommendation = self._determine_tier_and_recommendation(
            confidence, projection_score, position
        )

        # Generate contextual advice
        advice_text = self._generate_contextual_advice(
            player_name,
            final_tier,
            recommendation,
            matchup_desc,
            injury_status,
            projection_score,
            position,
        )

        return {
            "player_name": player_name,
            "position": position,
            "team": team,
            "tier": final_tier,
            "search_rank": search_rank,
            "recommendation": recommendation,
            "confidence": confidence,
            "advice": advice_text,
            "week": current_week,
            "projection": projection_score,
            "matchup_score": matchup_score,
            "health_factor": health_factor,
            "trending_factor": trending_factor,
        }

    def _calculate_health_factor(self, injury_status: Optional[str]) -> float:
        """Calculate health factor based on injury status (0.0-1.0)"""
        if not injury_status or injury_status in ["Healthy", "Active"]:
            return 1.0
        elif injury_status in ["Questionable", "Q"]:
            return 0.7
        elif injury_status in ["Doubtful", "D"]:
            return 0.3
        elif injury_status in ["Out", "O", "IR", "Inactive"]:
            return 0.0
        else:
            return 0.8  # Unknown but assume mostly healthy

    async def _get_trending_factor(self, player_name: str, player_id: Optional[str]) -> float:
        """Get trending factor based on recent adds/drops (0.0-1.0)"""
        try:
            trending_adds = await self.get_trending_players(add_drop="add", limit=100)
            trending_drops = await self.get_trending_players(add_drop="drop", limit=100)

            # Check if player is trending up or down
            is_trending_add = any(
                p.get("player_id") == player_id or p.get("name") == player_name
                for p in trending_adds
            )
            is_trending_drop = any(
                p.get("player_id") == player_id or p.get("name") == player_name
                for p in trending_drops
            )

            if is_trending_add:
                return 1.2  # Boost for trending up
            elif is_trending_drop:
                return 0.8  # Slight penalty for trending down
            else:
                return 1.0  # Neutral
        except:
            return 1.0  # Default neutral

    def _calculate_composite_confidence(
        self,
        projection: float,
        search_rank: int,
        health_factor: float,
        matchup_score: int,
        trending_factor: float,
    ) -> int:
        """Calculate composite confidence score from multiple factors"""

        # Projection-based score (40% weight)
        if projection >= 20:
            proj_score = 90
        elif projection >= 15:
            proj_score = 75
        elif projection >= 12:
            proj_score = 60
        elif projection >= 8:
            proj_score = 45
        else:
            proj_score = 25

        # Ranking-based score (25% weight)
        if search_rank <= 20:
            rank_score = 85
        elif search_rank <= 50:
            rank_score = 70
        elif search_rank <= 100:
            rank_score = 55
        elif search_rank <= 200:
            rank_score = 40
        else:
            rank_score = 25

        # Combine all factors
        composite = (
            proj_score * 0.40  # Projection weight
            + rank_score * 0.25  # Ranking weight
            + matchup_score * 0.20  # Matchup weight
            + health_factor * 100 * 0.10  # Health weight
            + trending_factor * 50 * 0.05  # Trending weight
        )

        return max(0, min(100, int(composite)))

    def _determine_tier_and_recommendation(
        self, confidence: int, projection: float, position: str
    ) -> tuple:
        """Determine tier and recommendation based on confidence and projection"""

        if confidence >= 80:
            tier = "Elite"
            recommendation = "Strong Start"
        elif confidence >= 65:
            tier = "Strong"
            recommendation = "Strong Start"
        elif confidence >= 50:
            tier = "Solid"
            recommendation = "Start"
        elif confidence >= 35:
            tier = "Depth"
            recommendation = "Flex/Consider"
        else:
            tier = "Deep"
            recommendation = "Bench/Avoid"

        return tier, recommendation

    def _generate_contextual_advice(
        self,
        player_name: str,
        tier: str,
        recommendation: str,
        matchup_desc: str,
        injury_status: Optional[str],
        projection: float,
        position: str,
    ) -> str:
        """Generate contextual advice text with specific factors"""

        # Base advice
        base_advice = f"{player_name} ({tier} tier) projects for {projection:.1f} points"

        # Add recommendation context
        if recommendation == "Strong Start":
            action_text = "is a confident start option this week"
        elif recommendation == "Start":
            action_text = "is a solid start for your lineup"
        elif recommendation == "Flex/Consider":
            action_text = "could work as a flex play or deeper option"
        else:
            action_text = "is better kept on bench unless desperate"

        # Add injury context
        injury_context = ""
        if injury_status and injury_status not in ["Healthy", "Active"]:
            if injury_status in ["Questionable", "Q"]:
                injury_context = " Monitor injury reports closely."
            elif injury_status in ["Doubtful", "D"]:
                injury_context = " Unlikely to play - have backup ready."
            elif injury_status in ["Out", "O", "IR"]:
                injury_context = " Currently inactive."

        # Add matchup context if meaningful
        matchup_context = ""
        if "great" in matchup_desc.lower() or "excellent" in matchup_desc.lower():
            matchup_context = " Excellent matchup boosts appeal."
        elif "tough" in matchup_desc.lower() or "difficult" in matchup_desc.lower():
            matchup_context = " Tough matchup creates risk."

        return f"{base_advice} and {action_text}.{injury_context}{matchup_context}"


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
