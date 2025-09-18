#!/usr/bin/env python3
"""
Lineup Optimizer for Fantasy Football
Combines Yahoo data, Sleeper rankings, and matchup analysis
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import external modules with error handling
try:
    from matchup_analyzer import matchup_analyzer
except ImportError as e:
    logger.error(f"Failed to import matchup_analyzer: {e}")
    matchup_analyzer = None

try:
    from sleeper_api import sleeper_client, get_trending_adds
except ImportError as e:
    logger.error(f"Failed to import sleeper_api: {e}")
    sleeper_client = None
    get_trending_adds = None

try:
    from position_normalizer import position_normalizer
except ImportError as e:
    logger.error(f"Failed to import position_normalizer: {e}")
    position_normalizer = None

try:
    from nfl_schedule import get_opponent
except ImportError as e:
    logger.error(f"Failed to import nfl_schedule: {e}")
    get_opponent = None


@dataclass
class Player:
    """Represents a player with all relevant data."""
    name: str
    position: str
    team: str
    opponent: str = ""
    yahoo_projection: float = 0.0
    sleeper_projection: float = 0.0
    matchup_score: int = 50
    matchup_description: str = "Unknown matchup"
    trending_score: int = 0  # Based on adds/drops
    composite_score: float = 0.0
    recommendation: str = ""
    is_starter: bool = False
    roster_position: str = ""  # QB, RB1, RB2, WR1, etc.
    player_tier: str = "unknown"  # "elite", "stud", "solid", "flex", "bench"
    base_rank: int = 999  # Overall positional rank (1 = best)
    momentum_score: float = 50.0  # Recent performance trend (0-100)
    recent_scores: List[float] = field(default_factory=list)  # Last 3-5 games
    floor_projection: float = 0.0  # Low-end projection
    ceiling_projection: float = 0.0  # High-end projection
    consistency_score: float = 50.0  # 0-100, higher = more consistent
    flex_score: float = 0.0  # Position-normalized FLEX value
    
    def is_valid(self) -> bool:
        """Validate player has minimum required data."""
        return all([
            self.name and self.name.strip(),
            self.position in ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'],
            self.team and self.team.strip()
        ])
    
    def get_best_projection(self) -> float:
        """Get the higher of Yahoo or Sleeper projection."""
        projections = [p for p in [self.yahoo_projection, self.sleeper_projection] if p > 0]
        return max(projections) if projections else 0.0


class LineupOptimizer:
    """Optimizes fantasy lineup using multiple data sources."""
    
    # Standard lineup positions
    STANDARD_POSITIONS = {
        "QB": 1,
        "RB": 2,
        "WR": 2,
        "TE": 1,
        "FLEX": 1,  # RB/WR/TE
        "K": 1,
        "DEF": 1
    }
    
    def __init__(self):
        self.trending_players = None
        
        # Elite/Stud thresholds by position (based on typical fantasy points)
        self.tier_thresholds = {
            "QB": {"elite": 22, "stud": 18, "solid": 15, "flex": 12},
            "RB": {"elite": 18, "stud": 14, "solid": 10, "flex": 7},
            "WR": {"elite": 16, "stud": 12, "solid": 9, "flex": 6},
            "TE": {"elite": 12, "stud": 9, "solid": 6, "flex": 4},
            "K": {"elite": 10, "stud": 8, "solid": 6, "flex": 5},
            "DEF": {"elite": 10, "stud": 8, "solid": 6, "flex": 4}
        }
        
    async def load_trending_data(self):
        """Load trending player data with error handling."""
        if not self.trending_players:
            try:
                if get_trending_adds is not None:
                    adds = await get_trending_adds(limit=100)
                    self.trending_players = {p['name']: p['count'] for p in adds if 'name' in p and 'count' in p}
                    logger.info(f"Loaded trending data for {len(self.trending_players)} players")
                else:
                    logger.warning("get_trending_adds not available, using empty trending data")
                    self.trending_players = {}
            except Exception as e:
                logger.error(f"Failed to load trending data: {e}")
                self.trending_players = {}  # Use empty dict as fallback
    
    def determine_player_tier(self, player: Player) -> str:
        """
        Determine player tier using dynamic percentile-based thresholds.
        Adapts to weekly scoring environment changes.
        """
        # Use the higher of Yahoo or Sleeper projection
        proj = player.get_best_projection()
        
        if not proj or player.position not in self.tier_thresholds:
            return "unknown"
        
        # Get dynamic thresholds if available, else use static
        if hasattr(self, 'dynamic_thresholds') and player.position in self.dynamic_thresholds:
            thresholds = self.dynamic_thresholds[player.position]
        else:
            thresholds = self.tier_thresholds[player.position]
        
        if proj >= thresholds["elite"]:
            return "elite"
        elif proj >= thresholds["stud"]:
            return "stud"
        elif proj >= thresholds["solid"]:
            return "solid"
        elif proj >= thresholds["flex"]:
            return "flex"
        else:
            return "bench"
    
    async def calculate_dynamic_thresholds(self, all_projections: Dict[str, List[float]]):
        """
        Calculate dynamic tier thresholds based on current week's projections.
        Uses percentiles to adapt to scoring environment.
        """
        
        self.dynamic_thresholds = {}
        
        for position, projections in all_projections.items():
            if len(projections) < 10:  # Need enough data
                continue
                
            # Calculate percentiles for this week
            percentiles = np.percentile(projections, [90, 75, 50, 25])
            
            self.dynamic_thresholds[position] = {
                "elite": percentiles[0],    # Top 10%
                "stud": percentiles[1],     # Top 25%
                "solid": percentiles[2],    # Top 50%
                "flex": percentiles[3]      # Top 75%
            }
    
    def calculate_composite_score(
        self,
        player: Player,
        strategy: str = "balanced"
    ) -> float:
        """
        Calculate composite score using multiplicative tier system.
        
        Uses multiplicative adjustments with diminishing returns to prevent
        illogical rankings where lesser players outscore elite players.
        
        Strategies:
        - matchup_heavy: Prioritize matchups (but studs still start)
        - balanced: Equal weight to all factors  
        - expert_consensus: Trust projections more
        - trending: Weight trending players higher
        - floor_focused: Minimize variance for cash games
        - ceiling_focused: Maximize upside for tournaments
        """
        
        # Define strategy weights
        weights = {
            "matchup_heavy": {
                "matchup": 0.45,
                "yahoo": 0.20,
                "sleeper": 0.20,
                "trending": 0.15,
                "momentum": 0.00
            },
            "balanced": {
                "matchup": 0.10,  # Heavily reduced - matchups matter less than player quality
                "yahoo": 0.40,    # Heavily increased - trust expert projections
                "sleeper": 0.40,  # Heavily increased - trust expert projections
                "trending": 0.05,
                "momentum": 0.05
            },
            "expert_consensus": {
                "matchup": 0.15,
                "yahoo": 0.35,
                "sleeper": 0.35,
                "trending": 0.05,
                "momentum": 0.10
            },
            "trending": {
                "matchup": 0.20,
                "yahoo": 0.20,
                "sleeper": 0.20,
                "trending": 0.25,
                "momentum": 0.15
            },
            "floor_focused": {
                "matchup": 0.20,
                "yahoo": 0.35,
                "sleeper": 0.35,
                "trending": 0.05,
                "momentum": 0.05
            },
            "ceiling_focused": {
                "matchup": 0.35,
                "yahoo": 0.20,
                "sleeper": 0.20,
                "trending": 0.15,
                "momentum": 0.10
            }
        }
        
        strategy_weights = weights.get(strategy, weights["balanced"])
        
        # Normalize scores to 0-100 scale with better scaling
        # Use position-specific normalization values
        position_max_proj = {
            "QB": 30, "RB": 25, "WR": 22, "TE": 18, "K": 12, "DEF": 12
        }
        max_proj = position_max_proj.get(player.position, 20)
        
        yahoo_norm = min(100, (player.yahoo_projection / max_proj) * 100) if player.yahoo_projection else 50
        sleeper_norm = min(100, (player.sleeper_projection / max_proj) * 100) if player.sleeper_projection else 50
        trending_norm = min(100, (player.trending_score / 10000) * 100) if player.trending_score else 0
        
        # Calculate momentum score (placeholder - will be enhanced)
        momentum_score = getattr(player, 'momentum_score', 50)
        
        # Calculate base weighted score
        base_score = (
            strategy_weights["matchup"] * player.matchup_score +
            strategy_weights["yahoo"] * yahoo_norm +
            strategy_weights["sleeper"] * sleeper_norm +
            strategy_weights["trending"] * trending_norm +
            strategy_weights.get("momentum", 0) * momentum_score
        )
        
        # Apply MULTIPLICATIVE tier adjustments with diminishing returns
        # ULTRA-AGGRESSIVE multipliers to ensure elite players ALWAYS start
        tier_multipliers = {
            "elite": 3.0,    # 200% boost - TRIPLE score for elite (never bench!)
            "stud": 2.0,     # 100% boost - DOUBLE score for studs
            "solid": 1.3,    # 30% boost
            "flex": 1.0,     # Neutral
            "bench": 0.50,   # 50% penalty - strong disincentive
            "unknown": 1.0
        }
        
        tier_mult = tier_multipliers.get(player.player_tier, 1.0)
        
        # Apply multiplier with diminishing returns formula
        # This prevents runaway scores while maintaining tier separation
        final_score = base_score * tier_mult * (1 - 0.3 * np.exp(-base_score/50))
        
        # Cap at 150 to allow for elite players with great matchups
        return min(150, final_score)
    
    async def _fill_opponent_data(self, players: List[Player]):
        """Fill in opponent data for players using NFL schedule data."""
        try:
            # Use the external schedule module for current week
            if get_opponent:
                for player in players:
                    if not player.opponent and player.team:
                        opponent_team = get_opponent(player.team)
                        if opponent_team:
                            player.opponent = opponent_team
                            logger.debug(f"Set opponent for {player.name}: {player.team} vs {opponent_team}")
            else:
                logger.warning("NFL schedule module not available - opponents will remain empty")
                        
        except Exception as e:
            logger.warning(f"Failed to load opponent data: {e}")
    
    async def parse_yahoo_roster(self, roster_data: dict) -> List[Player]:
        """Parse Yahoo roster data into Player objects with robust error handling."""
        players = []
        
        try:
            logger.info("Starting Yahoo roster parsing...")
            
            # Strategy 1: Handle the actual Yahoo API format: fantasy_content.team[1].roster['0'].players['0'].player
            try:
                logger.info("Trying new parsing strategy for actual Yahoo format...")
                fantasy_content = roster_data.get('fantasy_content', {})
                team_data = fantasy_content.get('team', [])
                
                # Find the roster in the team array
                roster = None
                for item in team_data:
                    if isinstance(item, dict) and 'roster' in item:
                        roster = item['roster']
                        break
                
                if roster and '0' in roster:
                    players_container = roster['0']
                    if 'players' in players_container:
                        players_dict = players_container['players']
                        
                        # Players are in numbered keys like '0', '1', '2', etc.
                        for player_key in players_dict:
                            if player_key.isdigit():  # Only process numbered player entries
                                player_data = players_dict[player_key]
                                if 'player' in player_data:
                                    player_info_list = player_data['player']
                                    
                                    # Player info is an array of dictionaries
                                    if isinstance(player_info_list, list) and len(player_info_list) > 0:
                                        player_info_array = player_info_list[0]  # First element contains the info
                                        
                                        # Extract name, position, team, and opponent from the array of dicts
                                        name = "Unknown"
                                        position = ""
                                        team = ""
                                        opponent = ""
                                        player_id = ""
                                        
                                        for info_dict in player_info_array:
                                            if 'name' in info_dict:
                                                name = info_dict['name'].get('full', 'Unknown')
                                            elif 'display_position' in info_dict:
                                                position = info_dict['display_position']
                                            elif 'editorial_team_abbr' in info_dict:
                                                team = info_dict['editorial_team_abbr']
                                            elif 'opponent_team' in info_dict:
                                                opponent = info_dict['opponent_team']
                                            elif 'opponent' in info_dict:
                                                opponent = info_dict['opponent']
                                            elif 'player_id' in info_dict:
                                                player_id = str(info_dict['player_id'])
                                        
                                        if name != "Unknown" and position and team:
                                            player = Player(
                                                name=name,
                                                position=position,
                                                team=team,
                                                opponent=opponent,
                                                yahoo_projection=0.0,
                                                sleeper_projection=0.0
                                            )
                                            players.append(player)
                                            logger.debug(f"Parsed player: {name} ({position}) - {team} vs {opponent if opponent else 'TBD'}")
                                        else:
                                            logger.warning(f"Incomplete player data: name='{name}', position='{position}', team='{team}'")
                
                if players:
                    logger.info(f"Successfully parsed {len(players)} players using new Yahoo format strategy")
                    
                    # Fill in opponent data if missing
                    await self._fill_opponent_data(players)
                    
                    return players  # Return immediately on success
                else:
                    logger.error("New Yahoo format strategy found no valid players")
                    
            except Exception as e:
                logger.error(f"New Yahoo format strategy failed: {e}")
            
            # Fallback to original strategies if new one fails
            if not players:
                logger.info("Falling back to original parsing strategies...")
                
                # Multiple parsing strategies to handle different Yahoo API response formats
            parsing_strategies = [
                self._parse_yahoo_strategy_1,
                self._parse_yahoo_strategy_2,
                self._parse_yahoo_strategy_fallback
            ]
            
            for i, strategy in enumerate(parsing_strategies):
                try:
                    logger.info(f"Trying parsing strategy {i+1}...")
                    players = strategy(roster_data)
                    if players:
                        logger.info(f"Successfully parsed {len(players)} players using strategy {i+1}")
                        break
                except Exception as e:
                    logger.warning(f"Parsing strategy {i+1} failed: {e}")
                    continue
            
            if not players:
                logger.error("All parsing strategies failed")
                return []
            
            # Validate and filter players
            valid_players = []
            for player in players:
                if player.is_valid():
                    valid_players.append(player)
                else:
                    logger.warning(f"Invalid player data: {player.name} - {player.position} - {player.team}")
            
            logger.info(f"Parsed {len(valid_players)} valid players from Yahoo roster")
            return valid_players
            
        except Exception as e:
            logger.error(f"Critical error in parse_yahoo_roster: {e}")
            return []
    
    def _parse_yahoo_strategy_1(self, roster_data: dict) -> List[Player]:
        """Primary parsing strategy for Yahoo roster data."""
        players = []
        
        team = roster_data.get("fantasy_content", {}).get("team", [])
        
        for item in team:
            if isinstance(item, dict) and "roster" in item:
                roster = item["roster"]
                if "0" in roster and "players" in roster["0"]:
                    player_list = roster["0"]["players"]
                    
                    for key in player_list:
                        if key != "count" and isinstance(player_list[key], dict):
                            if "player" in player_list[key]:
                                player_array = player_list[key]["player"]
                                if isinstance(player_array, list) and len(player_array) > 1:
                                    player_obj = self._parse_single_player(player_array)
                                    if player_obj:
                                        players.append(player_obj)
        
        return players
    
    def _parse_yahoo_strategy_2(self, roster_data: dict) -> List[Player]:
        """Alternative parsing strategy for different Yahoo API format."""
        players = []
        
        try:
            # Try direct access to team roster
            if "team" in roster_data:
                team_data = roster_data["team"]
                if isinstance(team_data, list):
                    for team_item in team_data:
                        if "roster" in team_item:
                            players.extend(self._extract_players_from_roster(team_item["roster"]))
                elif isinstance(team_data, dict) and "roster" in team_data:
                    players.extend(self._extract_players_from_roster(team_data["roster"]))
        except Exception as e:
            logger.warning(f"Strategy 2 parsing failed: {e}")
        
        return players
    
    def _parse_yahoo_strategy_fallback(self, roster_data: dict) -> List[Player]:
        """Fallback parsing strategy that recursively searches for player data."""
        players = []
        
        def find_players_recursive(data, path=""):
            if isinstance(data, dict):
                # Look for player arrays
                if "player" in data and isinstance(data["player"], list):
                    player_obj = self._parse_single_player(data["player"])
                    if player_obj:
                        players.append(player_obj)
                
                # Recurse through dictionary
                for key, value in data.items():
                    find_players_recursive(value, f"{path}.{key}")
            
            elif isinstance(data, list):
                for i, item in enumerate(data):
                    find_players_recursive(item, f"{path}[{i}]")
        
        find_players_recursive(roster_data)
        return players
    
    def _extract_players_from_roster(self, roster_data: dict) -> List[Player]:
        """Extract players from roster data structure."""
        players = []
        
        if "players" in roster_data:
            players_data = roster_data["players"]
            if isinstance(players_data, dict):
                for key, player_data in players_data.items():
                    if key != "count" and "player" in player_data:
                        player_obj = self._parse_single_player(player_data["player"])
                        if player_obj:
                            players.append(player_obj)
        
        return players
    
    def _parse_single_player(self, player_array: list) -> Optional[Player]:
        """Parse a single player from Yahoo API array format."""
        try:
            player_obj = Player(
                name="Unknown",
                position="",
                team="",
                opponent=""
            )
            
            # Parse player data with multiple fallback methods
            for p in player_array:
                if isinstance(p, dict):
                    # Player name
                    if "name" in p:
                        if isinstance(p["name"], dict) and "full" in p["name"]:
                            player_obj.name = p["name"]["full"]
                        elif isinstance(p["name"], str):
                            player_obj.name = p["name"]
                    
                    # Position and starter status
                    if "selected_position" in p:
                        pos_data = p["selected_position"]
                        if isinstance(pos_data, list) and len(pos_data) > 0:
                            pos_info = pos_data[0]
                            player_obj.roster_position = pos_info.get("position", "")
                            player_obj.is_starter = pos_info.get("position") != "BN"
                        elif isinstance(pos_data, dict):
                            player_obj.roster_position = pos_data.get("position", "")
                            player_obj.is_starter = pos_data.get("position") != "BN"
                    
                    # Display position
                    if "display_position" in p:
                        player_obj.position = p["display_position"]
                    elif "eligible_positions" in p and isinstance(p["eligible_positions"], list):
                        if p["eligible_positions"]:
                            player_obj.position = p["eligible_positions"][0].get("position", "")
                    
                    # Team
                    if "editorial_team_abbr" in p:
                        player_obj.team = p["editorial_team_abbr"]
                    elif "editorial_team_key" in p:
                        # Extract team from key if needed
                        team_key = p["editorial_team_key"]
                        if "." in team_key:
                            player_obj.team = team_key.split(".")[-1].upper()
                    
                    # Opponent (if available)
                    if "matchup" in p:
                        player_obj.opponent = str(p["matchup"])
                    
                    # Yahoo projection (if available)
                    if "player_points" in p:
                        points_data = p["player_points"]
                        if "total" in points_data:
                            player_obj.yahoo_projection = float(points_data["total"])
            
            # Clean up data
            player_obj.name = player_obj.name.strip()
            player_obj.team = player_obj.team.strip().upper()
            player_obj.position = player_obj.position.strip().upper()
            
            # Validate minimum requirements
            if not player_obj.name or not player_obj.position:
                logger.warning(f"Incomplete player data: name='{player_obj.name}', position='{player_obj.position}'")
                return None
            
            return player_obj
            
        except Exception as e:
            logger.warning(f"Failed to parse single player: {e}")
            return None
    
    def calculate_momentum(self, recent_scores: List[float], alpha: float = 0.3) -> float:
        """
        Calculate momentum score using exponentially weighted moving average.
        
        Args:
            recent_scores: List of recent fantasy scores (newest first)
            alpha: Smoothing factor (0-1, higher = more weight on recent)
            
        Returns:
            Momentum score (0-100, 50 = neutral)
        """
        
        if not recent_scores or len(recent_scores) < 2:
            return 50.0  # Neutral if insufficient data
        
        # Calculate EWMA
        ewma = recent_scores[0]
        for score in recent_scores[1:]:
            ewma = alpha * score + (1 - alpha) * ewma
        
        # Calculate average for normalization
        avg = np.mean(recent_scores)
        
        if avg == 0:
            return 50.0
        
        # Normalize to 0-100 scale
        # 1.0 = neutral (50), >1.0 = hot (50-100), <1.0 = cold (0-50)
        ratio = ewma / avg
        
        if ratio >= 1.0:
            # Hot streak: map 1.0-2.0 to 50-100
            momentum = min(100, 50 + (ratio - 1.0) * 50)
        else:
            # Cold streak: map 0.0-1.0 to 0-50
            momentum = max(0, ratio * 50)
        
        return momentum
    
    def calculate_floor_ceiling(self, yahoo_proj: float, sleeper_proj: float, 
                               matchup_score: int, recent_scores: List[float] = None) -> Tuple[float, float]:
        """
        Calculate floor and ceiling projections with volatility analysis.
        
        Args:
            yahoo_proj: Yahoo projection
            sleeper_proj: Sleeper projection
            matchup_score: Matchup quality (0-100)
            recent_scores: Recent game scores for volatility calculation
            
        Returns:
            (floor, ceiling) projections
        """
        
        # Base projection is average of available projections
        projections = [p for p in [yahoo_proj, sleeper_proj] if p > 0]
        if not projections:
            return (0.0, 0.0)
        
        base_proj = np.mean(projections)
        
        # Calculate volatility from recent scores if available
        if recent_scores and len(recent_scores) >= 3:
            std_dev = np.std(recent_scores)
            mean_score = np.mean(recent_scores)
            
            # Coefficient of variation (normalized volatility)
            cv = std_dev / mean_score if mean_score > 0 else 0.5
            
            # Actual floor/ceiling based on historical performance
            floor = mean_score - (std_dev * 0.8)  # 80% confidence floor
            ceiling = mean_score + (std_dev * 1.2)  # Upside potential
            
            # Adjust for matchup
            if matchup_score >= 70:
                floor *= 1.1  # Better floor in good matchups
                ceiling *= 1.2  # Higher ceiling too
            elif matchup_score <= 30:
                floor *= 0.85  # Lower floor in bad matchups
                ceiling *= 0.95  # Capped ceiling
        else:
            # Fallback to matchup-based estimates
            if matchup_score >= 70:
                floor = base_proj * 0.75
                ceiling = base_proj * 1.35
            elif matchup_score >= 50:
                floor = base_proj * 0.80
                ceiling = base_proj * 1.25
            elif matchup_score >= 30:
                floor = base_proj * 0.70
                ceiling = base_proj * 1.15
            else:
                floor = base_proj * 0.60
                ceiling = base_proj * 1.10
        
        return (max(0, floor), ceiling)
    
    def calculate_consistency_score(self, recent_scores: List[float]) -> float:
        """
        Calculate player consistency score (0-100).
        
        100 = extremely consistent (low variance)
        50 = average consistency
        0 = extremely volatile (boom/bust)
        """
        
        if not recent_scores or len(recent_scores) < 3:
            return 50.0  # Default to average
        
        std_dev = np.std(recent_scores)
        mean_score = np.mean(recent_scores)
        
        if mean_score == 0:
            return 50.0
        
        # Coefficient of variation (lower = more consistent)
        cv = std_dev / mean_score
        
        # Convert to 0-100 scale (CV of 0 = 100, CV of 1+ = 0)
        consistency = max(0, min(100, (1 - cv) * 100))
        
        return consistency
    
    async def enhance_with_external_data(self, players: List[Player]) -> List[Player]:
        """Add Sleeper projections, matchup scores, trending data, momentum, and tier with robust error handling."""
        logger.info(f"Enhancing {len(players)} players with external data...")
        
        # Import sleeper function for projections
        try:
            from sleeper_api import get_player_projection
        except ImportError:
            get_player_projection = None
        
        # Track data enhancement success rates
        enhancement_stats = {
            "trending_loaded": False,
            "matchup_loaded": False,
            "sleeper_projections": 0,
            "matchup_scores": 0,
            "trending_data": 0,
            "errors": []
        }
        
        # Load trending data with error handling
        try:
            if get_trending_adds is not None:
                await self.load_trending_data()
                enhancement_stats["trending_loaded"] = True
                logger.info("Successfully loaded trending data")
            else:
                logger.warning("Trending data unavailable - get_trending_adds not imported")
        except Exception as e:
            error_msg = f"Failed to load trending data: {e}"
            logger.error(error_msg)
            enhancement_stats["errors"].append(error_msg)
        
        # Load matchup data with error handling
        try:
            if matchup_analyzer is not None:
                await matchup_analyzer.load_defensive_rankings()
                enhancement_stats["matchup_loaded"] = True
                logger.info("Successfully loaded defensive rankings")
            else:
                logger.warning("Matchup analyzer unavailable - matchup_analyzer not imported")
        except Exception as e:
            error_msg = f"Failed to load defensive rankings: {e}"
            logger.error(error_msg)
            enhancement_stats["errors"].append(error_msg)
        
        # Enhance each player with available data
        for i, player in enumerate(players):
            try:
                logger.debug(f"Enhancing player {i+1}/{len(players)}: {player.name}")
                
                # Get matchup score with fallback
                if matchup_analyzer is not None and player.opponent and player.position:
                    try:
                        opponent_clean = player.opponent.replace("@", "").replace("vs", "").strip()
                        score, desc = matchup_analyzer.get_matchup_score(opponent_clean, player.position)
                        player.matchup_score = score
                        player.matchup_description = desc
                        enhancement_stats["matchup_scores"] += 1
                    except Exception as e:
                        logger.warning(f"Failed to get matchup score for {player.name}: {e}")
                        player.matchup_score = 50  # Neutral default
                        player.matchup_description = "Matchup data unavailable"
                
                # Get Sleeper projection with fallback
                if sleeper_client is not None and get_player_projection is not None:
                    try:
                        proj = await get_player_projection(player.name)
                        if proj and isinstance(proj, dict):
                            player.sleeper_projection = proj.get('pts_ppr', proj.get('pts_std', 0))
                            enhancement_stats["sleeper_projections"] += 1
                    except Exception as e:
                        logger.warning(f"Failed to get Sleeper projection for {player.name}: {e}")
                        player.sleeper_projection = 0.0
                
                # Get trending score with fallback
                if self.trending_players and player.name in self.trending_players:
                    try:
                        trending_value = self.trending_players[player.name]
                        if isinstance(trending_value, (int, float)) and trending_value >= 0:
                            player.trending_score = int(trending_value)
                            enhancement_stats["trending_data"] += 1
                    except Exception as e:
                        logger.warning(f"Failed to get trending score for {player.name}: {e}")
                        player.trending_score = 0
                
                # Calculate momentum if recent scores available
                if player.recent_scores:
                    try:
                        player.momentum_score = self.calculate_momentum(player.recent_scores)
                    except Exception as e:
                        logger.warning(f"Failed to calculate momentum for {player.name}: {e}")
                        player.momentum_score = 50.0
                
                # Calculate floor/ceiling projections with volatility
                try:
                    floor, ceiling = self.calculate_floor_ceiling(
                        player.yahoo_projection,
                        player.sleeper_projection,
                        player.matchup_score,
                        player.recent_scores
                    )
                    player.floor_projection = floor
                    player.ceiling_projection = ceiling
                except Exception as e:
                    logger.warning(f"Failed to calculate floor/ceiling for {player.name}: {e}")
                    player.floor_projection = 0.0
                    player.ceiling_projection = 0.0
                
                # Determine player tier
                try:
                    player.player_tier = self.determine_player_tier(player)
                except Exception as e:
                    logger.warning(f"Failed to determine tier for {player.name}: {e}")
                    player.player_tier = "unknown"
                    
            except Exception as e:
                error_msg = f"Critical error enhancing {player.name}: {e}"
                logger.error(error_msg)
                enhancement_stats["errors"].append(error_msg)
        
        # Log enhancement statistics
        logger.info(f"Enhancement complete - Sleeper projections: {enhancement_stats['sleeper_projections']}/{len(players)}, "
                   f"Matchup scores: {enhancement_stats['matchup_scores']}/{len(players)}, "
                   f"Trending data: {enhancement_stats['trending_data']}/{len(players)}")
        
        if enhancement_stats["errors"]:
            logger.warning(f"Enhancement errors: {len(enhancement_stats['errors'])}")
        
        return players
    
    def optimize_lineup(
        self,
        players: List[Player],
        strategy: str = "balanced",
        week: Optional[int] = None
    ) -> Dict[str, any]:
        """
        Optimize the lineup based on composite scores with comprehensive error handling.
        
        Returns dict with:
        - status: success/partial/error
        - starters: Optimal starting lineup
        - bench: Bench players
        - recommendations: Specific advice
        - errors: Any issues encountered
        - data_quality: Data completeness metrics
        """
        logger.info(f"Starting lineup optimization with {len(players)} players, strategy: {strategy}")
        
        # Initialize result structure
        result = {
            "status": "success",
            "starters": {},
            "bench": [],
            "recommendations": [],
            "strategy_used": strategy,
            "errors": [],
            "data_quality": {
                "total_players": len(players),
                "valid_players": 0,
                "players_with_projections": 0,
                "players_with_matchup_data": 0
            }
        }
        
        try:
            # Validate input
            if not players:
                result["status"] = "error"
                result["errors"].append("No players provided for optimization")
                return result
            
            # Filter and validate players
            valid_players = [p for p in players if p.is_valid()]
            result["data_quality"]["valid_players"] = len(valid_players)
            
            if len(valid_players) < 9:  # Minimum for a lineup
                result["status"] = "error"
                result["errors"].append(f"Insufficient valid players: {len(valid_players)}/9 minimum required")
                return result
            
            # Calculate data quality metrics
            players_with_proj = sum(1 for p in valid_players if p.get_best_projection() > 0)
            players_with_matchup = sum(1 for p in valid_players if p.matchup_score != 50)
            
            result["data_quality"]["players_with_projections"] = players_with_proj
            result["data_quality"]["players_with_matchup_data"] = players_with_matchup
            
            # Warn if data quality is poor
            if players_with_proj < len(valid_players) * 0.5:
                result["status"] = "partial"
                result["errors"].append("Less than 50% of players have projection data")
            
            # Calculate composite scores with error handling
            successful_scores = 0
            for player in valid_players:
                try:
                    player.composite_score = self.calculate_composite_score(player, strategy)
                    successful_scores += 1
                    
                    # Week 17 adjustment - reduce projections for potential rest
                    if week == 17:
                        if player.player_tier == "elite":
                            player.composite_score *= 0.85
                            player.yahoo_projection *= 0.85
                            player.sleeper_projection *= 0.85
                    
                    # OVERRIDE: Elite and Stud players get massive boost to ensure they start
                    if player.player_tier == "elite":
                        player.composite_score = max(player.composite_score, 120)
                    elif player.player_tier == "stud":
                        player.composite_score = max(player.composite_score, 100)
                    
                    # Calculate FLEX scores with error handling
                    try:
                        base_projection = player.get_best_projection()
                        consistency = self.calculate_consistency_score(
                            getattr(player, 'recent_scores', [])
                        )
                        player.consistency_score = consistency
                        
                        # Get position-normalized FLEX value
                        if position_normalizer is not None:
                            flex_value = position_normalizer.get_flex_value(base_projection, player.position)
                            flex_base = (flex_value * 10) + (player.composite_score * 0.01)
                            
                            # Adjust for strategy
                            if strategy == "floor_focused":
                                consistency_bonus = (consistency - 50) * 0.02
                                player.flex_score = flex_base + consistency_bonus
                            elif strategy == "ceiling_focused":
                                volatility_bonus = (50 - consistency) * 0.02
                                player.flex_score = flex_base + volatility_bonus
                            else:
                                consistency_bonus = (consistency - 50) * 0.01
                                player.flex_score = flex_base + consistency_bonus
                        else:
                            # Fallback if position_normalizer unavailable
                            player.flex_score = player.composite_score
                            
                    except Exception as e:
                        logger.warning(f"Failed to calculate FLEX score for {player.name}: {e}")
                        player.flex_score = player.composite_score
                        
                except Exception as e:
                    error_msg = f"Failed to calculate composite score for {player.name}: {e}"
                    logger.warning(error_msg)
                    result["errors"].append(error_msg)
                    player.composite_score = 0.0  # Set to 0 so they won't be started
            
            logger.info(f"Successfully calculated scores for {successful_scores}/{len(valid_players)} players")
            
            # Sort players by position and score
            qbs = sorted([p for p in valid_players if p.position == "QB"], 
                        key=lambda x: x.composite_score, reverse=True)
            rbs = sorted([p for p in valid_players if p.position == "RB"],
                        key=lambda x: x.composite_score, reverse=True)
            wrs = sorted([p for p in valid_players if p.position == "WR"],
                        key=lambda x: x.composite_score, reverse=True)
            tes = sorted([p for p in valid_players if p.position == "TE"],
                        key=lambda x: x.composite_score, reverse=True)
            ks = sorted([p for p in valid_players if p.position == "K"],
                       key=lambda x: x.composite_score, reverse=True)
            defs = sorted([p for p in valid_players if p.position == "DEF"],
                         key=lambda x: x.composite_score, reverse=True)
            
            # Build optimal lineup with error handling
            starters = {}
            bench = []
            
            try:
                # QB
                if qbs:
                    starters["QB"] = qbs[0]
                    bench.extend(qbs[1:])
                else:
                    result["errors"].append("No QB available")
                
                # RB (2 starters)
                if len(rbs) >= 2:
                    starters["RB1"] = rbs[0]
                    starters["RB2"] = rbs[1]
                    bench.extend(rbs[2:])
                elif len(rbs) == 1:
                    starters["RB1"] = rbs[0]
                    result["errors"].append("Only 1 RB available, need 2")
                else:
                    result["errors"].append("No RBs available")
                
                # WR (2 starters)
                if len(wrs) >= 2:
                    starters["WR1"] = wrs[0]
                    starters["WR2"] = wrs[1]
                    bench.extend(wrs[2:])
                elif len(wrs) == 1:
                    starters["WR1"] = wrs[0]
                    result["errors"].append("Only 1 WR available, need 2")
                else:
                    result["errors"].append("No WRs available")
                
                # TE
                if tes:
                    starters["TE"] = tes[0]
                    bench.extend(tes[1:])
                else:
                    result["errors"].append("No TE available")
                
                # FLEX (best remaining RB/WR/TE)
                flex_eligible = []
                if len(rbs) > 2:
                    flex_eligible.extend(rbs[2:])
                if len(wrs) > 2:
                    flex_eligible.extend(wrs[2:])
                if len(tes) > 1:
                    flex_eligible.extend(tes[1:])
                
                if flex_eligible:
                    # Use flex_score for FLEX comparison
                    flex_eligible.sort(key=lambda x: getattr(x, 'flex_score', x.composite_score), reverse=True)
                    starters["FLEX"] = flex_eligible[0]
                    # Remove FLEX from bench
                    if starters["FLEX"] in bench:
                        bench.remove(starters["FLEX"])
                else:
                    result["errors"].append("No FLEX eligible players available")
                
                # K
                if ks:
                    starters["K"] = ks[0]
                    bench.extend(ks[1:])
                else:
                    result["errors"].append("No K available")
                
                # DEF
                if defs:
                    starters["DEF"] = defs[0]
                    bench.extend(defs[1:])
                else:
                    result["errors"].append("No DEF available")
                
            except Exception as e:
                error_msg = f"Error building lineup: {e}"
                logger.error(error_msg)
                result["errors"].append(error_msg)
                result["status"] = "error"
            
            # Generate recommendations
            try:
                recommendations = self._generate_recommendations(starters, bench, valid_players)
                result["recommendations"] = recommendations
            except Exception as e:
                error_msg = f"Error generating recommendations: {e}"
                logger.warning(error_msg)
                result["errors"].append(error_msg)
                result["recommendations"] = ["Unable to generate recommendations due to error"]
            
            # Set final status
            if result["errors"]:
                if result["status"] == "success":
                    result["status"] = "partial"
            
            result["starters"] = starters
            result["bench"] = bench
            
            logger.info(f"Lineup optimization complete - Status: {result['status']}, "
                       f"Starters: {len(starters)}/9, Errors: {len(result['errors'])}")
            
            return result
            
        except Exception as e:
            error_msg = f"Critical error in optimize_lineup: {e}"
            logger.error(error_msg)
            result["status"] = "error"
            result["errors"].append(error_msg)
            return result
    
    def _generate_recommendations(
        self,
        starters: Dict[str, Player],
        bench: List[Player],
        all_players: List[Player]
    ) -> List[str]:
        """Generate specific recommendations based on analysis."""
        recommendations = []
        
        # Check for elite/stud players on bench (should never happen)
        for player in bench:
            if player.player_tier in ["elite", "stud"]:
                recommendations.append(
                    f"[AUTO-START] {player.name} ({player.player_tier.upper()}) on bench! Must start regardless of matchup"
                )
            elif player.matchup_score >= 85 and player.composite_score > 70:
                recommendations.append(
                    f"[WARNING] {player.name} on bench has ELITE matchup vs {player.opponent} - consider starting"
                )
        
        # Check for studs with tough matchups (start anyway)
        for pos, player in starters.items():
            if player.player_tier in ["elite", "stud"] and player.matchup_score <= 30:
                recommendations.append(
                    f"[KEEP STARTING] {player.name} is {player.player_tier.upper()} - starting despite tough matchup vs {player.opponent}"
                )
            elif player.player_tier not in ["elite", "stud"] and player.matchup_score <= 20:
                recommendations.append(
                    f"[WARNING] {player.name} faces tough matchup vs {player.opponent} (score: {player.matchup_score}/100) - consider alternatives"
                )
        
        # Check for trending players
        for player in all_players:
            if player.trending_score > 10000 and player not in starters.values():
                recommendations.append(
                    f"[TRENDING] {player.name} is trending ({player.trending_score:,} adds) - monitor for breakout"
                )
        
        # Highlight best matchups
        best_matchup = max(starters.values(), key=lambda x: x.matchup_score)
        if best_matchup.matchup_score >= 80:
            if best_matchup.player_tier in ["elite", "stud"]:
                recommendations.append(
                    f"[MATCHUP] SMASH PLAY: {best_matchup.name} ({best_matchup.player_tier}) vs {best_matchup.opponent} - elite player + elite matchup!"
                )
            else:
                recommendations.append(
                    f"[MATCHUP] Great matchup: {best_matchup.name} vs {best_matchup.opponent} (matchup score: {best_matchup.matchup_score}/100)"
                )
        
        return recommendations


# Global instance
lineup_optimizer = LineupOptimizer()