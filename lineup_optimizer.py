#!/usr/bin/env python3
"""
Lineup Optimizer for Fantasy Football
Combines Yahoo data, Sleeper rankings, and matchup analysis
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import numpy as np
from matchup_analyzer import matchup_analyzer
from sleeper_api import sleeper_client, get_trending_adds
from position_normalizer import position_normalizer


@dataclass
class Player:
    """Represents a player with all relevant data."""
    name: str
    position: str
    team: str
    opponent: str
    yahoo_projection: float = 0.0
    sleeper_projection: float = 0.0
    matchup_score: int = 50
    matchup_description: str = ""
    trending_score: int = 0  # Based on adds/drops
    composite_score: float = 0.0
    recommendation: str = ""
    is_starter: bool = False
    roster_position: str = ""  # QB, RB1, RB2, WR1, etc.
    player_tier: str = ""  # "elite", "stud", "solid", "flex", "bench"
    base_rank: int = 999  # Overall positional rank (1 = best)
    momentum_score: float = 50.0  # Recent performance trend (0-100)
    recent_scores: List[float] = field(default_factory=list)  # Last 3-5 games
    floor_projection: float = 0.0  # Low-end projection
    ceiling_projection: float = 0.0  # High-end projection
    consistency_score: float = 50.0  # 0-100, higher = more consistent
    flex_score: float = 0.0  # Position-normalized FLEX value


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
        """Load trending player data."""
        if not self.trending_players:
            adds = await get_trending_adds(limit=100)
            self.trending_players = {p['name']: p['count'] for p in adds}
    
    def determine_player_tier(self, player: Player) -> str:
        """
        Determine player tier using dynamic percentile-based thresholds.
        Adapts to weekly scoring environment changes.
        """
        # Use the higher of Yahoo or Sleeper projection
        proj = max(player.yahoo_projection, player.sleeper_projection)
        
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
        import numpy as np
        
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
        import numpy as np
        
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
    
    async def parse_yahoo_roster(self, roster_data: dict) -> List[Player]:
        """Parse Yahoo roster data into Player objects."""
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
                                    player_obj = Player(
                                        name="Unknown",
                                        position="",
                                        team="",
                                        opponent=""
                                    )
                                    
                                    # Parse player data
                                    for p in player_array:
                                        if isinstance(p, dict):
                                            if "name" in p:
                                                player_obj.name = p["name"]["full"]
                                            if "selected_position" in p:
                                                pos_data = p["selected_position"][0]
                                                player_obj.roster_position = pos_data.get("position", "")
                                                player_obj.is_starter = pos_data.get("position") != "BN"
                                            if "display_position" in p:
                                                player_obj.position = p["display_position"]
                                            if "editorial_team_abbr" in p:
                                                player_obj.team = p["editorial_team_abbr"]
                                            # Get opponent from matchup data if available
                                            if "matchup" in p:
                                                player_obj.opponent = p.get("matchup", "")
                                    
                                    players.append(player_obj)
        
        return players
    
    def calculate_momentum(self, recent_scores: List[float], alpha: float = 0.3) -> float:
        """
        Calculate momentum score using exponentially weighted moving average.
        
        Args:
            recent_scores: List of recent fantasy scores (newest first)
            alpha: Smoothing factor (0-1, higher = more weight on recent)
            
        Returns:
            Momentum score (0-100, 50 = neutral)
        """
        import numpy as np
        
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
        import numpy as np
        
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
        import numpy as np
        
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
        """Add Sleeper projections, matchup scores, trending data, momentum, and tier."""
        await self.load_trending_data()
        await matchup_analyzer.load_defensive_rankings()
        
        for player in players:
            # Get matchup score
            if player.opponent and player.position:
                score, desc = matchup_analyzer.get_matchup_score(
                    player.opponent.replace("@", "").strip(),
                    player.position
                )
                player.matchup_score = score
                player.matchup_description = desc
            
            # Get Sleeper projection
            from sleeper_api import get_player_projection
            proj = await get_player_projection(player.name)
            if proj:
                player.sleeper_projection = proj.get('pts_ppr', proj.get('pts_std', 0))
            
            # Get trending score
            if self.trending_players and player.name in self.trending_players:
                player.trending_score = self.trending_players[player.name]
            
            # Calculate momentum if recent scores available
            if player.recent_scores:
                player.momentum_score = self.calculate_momentum(player.recent_scores)
            
            # Calculate floor/ceiling projections with volatility
            floor, ceiling = self.calculate_floor_ceiling(
                player.yahoo_projection,
                player.sleeper_projection,
                player.matchup_score,
                player.recent_scores
            )
            player.floor_projection = floor
            player.ceiling_projection = ceiling
            
            # Determine player tier (elite, stud, solid, flex, bench)
            player.player_tier = self.determine_player_tier(player)
        
        return players
    
    def optimize_lineup(
        self,
        players: List[Player],
        strategy: str = "balanced",
        week: int = None
    ) -> Dict[str, any]:
        """
        Optimize the lineup based on composite scores.
        
        Returns dict with:
        - starters: Optimal starting lineup
        - bench: Bench players
        - recommendations: Specific advice
        """
        # Calculate composite scores
        for player in players:
            player.composite_score = self.calculate_composite_score(player, strategy)
            
            # Week 17 adjustment - reduce projections for potential rest
            if week == 17:
                # Players on playoff teams might rest
                # This is a simplified approach - ideally check team playoff status
                if player.player_tier == "elite":
                    player.composite_score *= 0.85  # 15% reduction for rest risk
                    player.yahoo_projection *= 0.85
                    player.sleeper_projection *= 0.85
            
            # OVERRIDE: Elite and Stud players get massive boost to ensure they start
            if player.player_tier == "elite":
                player.composite_score = max(player.composite_score, 120)  # Minimum score of 120
            elif player.player_tier == "stud":
                player.composite_score = max(player.composite_score, 100)  # Minimum score of 100
            
            # FLEX POSITION ADJUSTMENT: Use position-normalized scoring
            base_projection = max(player.yahoo_projection, player.sleeper_projection)
            
            # Calculate consistency if we have recent scores
            consistency = self.calculate_consistency_score(
                getattr(player, 'recent_scores', [])
            )
            player.consistency_score = consistency
            
            # Get position-normalized FLEX value
            flex_value = position_normalizer.get_flex_value(base_projection, player.position)
            
            # Scale up for differentiation and add small composite influence
            flex_base = (flex_value * 10) + (player.composite_score * 0.01)
            
            # Adjust for game script and volatility preferences
            # In balanced/default strategy, slight preference for consistency
            if strategy == "floor_focused":
                # Prefer consistent players for cash games
                consistency_bonus = (consistency - 50) * 0.02  # +/-1 point max
                player.flex_score = flex_base + consistency_bonus
            elif strategy == "ceiling_focused":
                # Prefer volatile players for tournaments
                volatility_bonus = (50 - consistency) * 0.02  # Inverse of consistency
                player.flex_score = flex_base + volatility_bonus
            else:
                # Balanced - slight consistency preference
                consistency_bonus = (consistency - 50) * 0.01  # +/-0.5 point max
                player.flex_score = flex_base + consistency_bonus
        
        # Sort by position and score
        qbs = sorted([p for p in players if p.position == "QB"], 
                    key=lambda x: x.composite_score, reverse=True)
        rbs = sorted([p for p in players if p.position == "RB"],
                    key=lambda x: x.composite_score, reverse=True)
        wrs = sorted([p for p in players if p.position == "WR"],
                    key=lambda x: x.composite_score, reverse=True)
        tes = sorted([p for p in players if p.position == "TE"],
                    key=lambda x: x.composite_score, reverse=True)
        ks = sorted([p for p in players if p.position == "K"],
                   key=lambda x: x.composite_score, reverse=True)
        defs = sorted([p for p in players if p.position == "DEF"],
                     key=lambda x: x.composite_score, reverse=True)
        
        # Build optimal lineup
        starters = {}
        bench = []
        warnings = []
        
        # QB - Check for empty list before accessing
        if qbs and len(qbs) > 0:
            starters["QB"] = qbs[0]
            bench.extend(qbs[1:])
        else:
            warnings.append("No QB available to start")
        
        # RB (2 starters) - Defensive checks for each position
        if len(rbs) >= 2:
            starters["RB1"] = rbs[0]
            starters["RB2"] = rbs[1]
            bench.extend(rbs[2:])
        elif len(rbs) == 1:
            starters["RB1"] = rbs[0]
            warnings.append("Only 1 RB available (need 2)")
        else:
            warnings.append("No RBs available to start")
        
        # WR (2 starters) - Defensive checks for each position
        if len(wrs) >= 2:
            starters["WR1"] = wrs[0]
            starters["WR2"] = wrs[1]
            bench.extend(wrs[2:])
        elif len(wrs) == 1:
            starters["WR1"] = wrs[0]
            warnings.append("Only 1 WR available (need 2)")
        else:
            warnings.append("No WRs available to start")
        
        # TE - Check for empty list
        if tes and len(tes) > 0:
            starters["TE"] = tes[0]
            bench.extend(tes[1:])
        else:
            warnings.append("No TE available to start")
        
        # FLEX (best remaining RB/WR/TE)
        flex_eligible = []
        if len(rbs) > 2:
            flex_eligible.extend(rbs[2:])
        if len(wrs) > 2:
            flex_eligible.extend(wrs[2:])
        if len(tes) > 1:
            flex_eligible.extend(tes[1:])
        
        if flex_eligible and len(flex_eligible) > 0:
            # Use flex_score for FLEX comparison (position-adjusted)
            flex_eligible.sort(key=lambda x: getattr(x, 'flex_score', x.composite_score), reverse=True)
            starters["FLEX"] = flex_eligible[0]
            # Remove FLEX from bench
            if starters["FLEX"] in bench:
                bench.remove(starters["FLEX"])
        else:
            warnings.append("No eligible players for FLEX position")
        
        # K - Check for empty list
        if ks and len(ks) > 0:
            starters["K"] = ks[0]
            bench.extend(ks[1:])
        else:
            warnings.append("No Kicker available to start")
        
        # DEF - Check for empty list
        if defs and len(defs) > 0:
            starters["DEF"] = defs[0]
            bench.extend(defs[1:])
        else:
            warnings.append("No Defense available to start")
        
        # Generate recommendations
        recommendations = self._generate_recommendations(starters, bench, players)
        
        # Add warnings to recommendations if any exist
        if warnings:
            recommendations.extend([f"⚠️ {warning}" for warning in warnings])
        
        return {
            "starters": starters,
            "bench": bench,
            "recommendations": recommendations,
            "strategy_used": strategy,
            "warnings": warnings
        }
    
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
                    f"🚨 {player.name} ({player.player_tier.upper()}) on bench! Must start regardless of matchup"
                )
            elif player.matchup_score >= 85 and player.composite_score > 70:
                recommendations.append(
                    f"⚠️ {player.name} on bench has ELITE matchup vs {player.opponent} - consider starting"
                )
        
        # Check for studs with tough matchups (start anyway)
        for pos, player in starters.items():
            if player.player_tier in ["elite", "stud"] and player.matchup_score <= 30:
                recommendations.append(
                    f"💪 {player.name} is {player.player_tier.upper()} - starting despite tough matchup vs {player.opponent}"
                )
            elif player.player_tier not in ["elite", "stud"] and player.matchup_score <= 20:
                recommendations.append(
                    f"⚠️ {player.name} faces tough matchup vs {player.opponent} (score: {player.matchup_score}/100) - consider alternatives"
                )
        
        # Check for trending players
        for player in all_players:
            if player.trending_score > 10000 and player not in starters.values():
                recommendations.append(
                    f"📈 {player.name} is trending ({player.trending_score:,} adds) - monitor for breakout"
                )
        
        # Highlight best matchups
        best_matchup = max(starters.values(), key=lambda x: x.matchup_score)
        if best_matchup.matchup_score >= 80:
            if best_matchup.player_tier in ["elite", "stud"]:
                recommendations.append(
                    f"🎯 SMASH PLAY: {best_matchup.name} ({best_matchup.player_tier}) vs {best_matchup.opponent} - elite player + elite matchup!"
                )
            else:
                recommendations.append(
                    f"🎯 Great matchup: {best_matchup.name} vs {best_matchup.opponent} (matchup score: {best_matchup.matchup_score}/100)"
                )
        
        return recommendations


# Global instance
lineup_optimizer = LineupOptimizer()