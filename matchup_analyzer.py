#!/usr/bin/env python3
"""
Matchup Analyzer for Fantasy Football
Analyzes player matchups against opposing defenses
"""

from typing import Dict, List, Optional, Tuple
from sleeper_api import sleeper_client


class MatchupAnalyzer:
    """Analyzes fantasy football matchups based on defensive rankings."""

    def __init__(self):
        self.defensive_rankings = None

    async def load_defensive_rankings(self):
        """Load defensive rankings if not already loaded."""
        if not self.defensive_rankings:
            self.defensive_rankings = await sleeper_client.get_defensive_rankings()

    def get_matchup_score(self, opponent_team: str, position: str) -> Tuple[int, str]:
        """
        Get matchup score using non-linear transformation.

        Uses sigmoid transformation to better reflect the true difference
        between elite and poor defenses.

        Returns:
            (score, description)
            Score: 1-100 (100 = best matchup, 1 = worst matchup)
            Description: Text description of matchup quality
        """
        import numpy as np

        if not self.defensive_rankings or opponent_team not in self.defensive_rankings:
            return (50, "Unknown matchup")

        # Map position to ranking key
        position_map = {
            "QB": "vs_qb",
            "RB": "vs_rb",
            "WR": "vs_wr",
            "TE": "vs_te",
            "K": "vs_qb",  # Kickers correlate with offensive success
            "DEF": "vs_qb",  # Defense vs opposing QB
        }

        ranking_key = position_map.get(position, "vs_qb")
        ranking = self.defensive_rankings[opponent_team].get(ranking_key, 16)

        # Non-linear transformation using sigmoid curve
        # This better reflects the actual difference in fantasy points allowed
        # Convert ranking to percentile (32nd = 100th percentile = best matchup)
        percentile = ((32 - ranking + 1) / 32) * 100

        # Apply sigmoid transformation for better differentiation
        # Steeper curve at extremes, flatter in middle
        k = 0.05  # Steepness factor (further reduced for even less extreme differences)
        score = 100 / (1 + np.exp(-k * (percentile - 50)))

        # Ensure score is in valid range
        score = max(1, min(100, int(score)))

        # Generate description with more granular tiers
        if score >= 90:
            description = f"SMASH SPOT vs {opponent_team} (#{ranking}/32)"
        elif score >= 80:
            description = f"Elite matchup vs {opponent_team} (#{ranking}/32)"
        elif score >= 70:
            description = f"Great matchup vs {opponent_team} (#{ranking}/32)"
        elif score >= 60:
            description = f"Good matchup vs {opponent_team} (#{ranking}/32)"
        elif score >= 50:
            description = f"Neutral matchup vs {opponent_team} (#{ranking}/32)"
        elif score >= 40:
            description = f"Below average vs {opponent_team} (#{ranking}/32)"
        elif score >= 30:
            description = f"Tough matchup vs {opponent_team} (#{ranking}/32)"
        elif score >= 20:
            description = f"Bad matchup vs {opponent_team} (#{ranking}/32)"
        elif score >= 10:
            description = f"Terrible matchup vs {opponent_team} (#{ranking}/32)"
        else:
            description = f"AVOID - Elite defense vs {opponent_team} (#{ranking}/32)"

        return (score, description)

    def get_matchup_score_empirical(
        self, opponent_team: str, position: str, historical_data: Dict = None
    ) -> Tuple[int, str]:
        """
        Advanced matchup scoring using empirical cumulative distribution.
        Requires historical fantasy points allowed data.

        This method would be called when historical data is available.
        """
        import scipy.stats as stats

        if not historical_data:
            # Fall back to standard method
            return self.get_matchup_score(opponent_team, position)

        # Get historical points allowed by this defense to this position
        team_history = historical_data.get(opponent_team, {}).get(position, [])

        if not team_history or len(team_history) < 5:
            return self.get_matchup_score(opponent_team, position)

        # Calculate percentile based on actual points allowed
        all_defenses_avg = historical_data.get("league_average", {}).get(position, 15)
        team_avg = np.mean(team_history)

        # Higher points allowed = better matchup
        # Calculate z-score and convert to percentile
        league_std = historical_data.get("league_std", {}).get(position, 5)
        z_score = (team_avg - all_defenses_avg) / league_std
        percentile = stats.norm.cdf(z_score) * 100

        # Apply sigmoid for final score
        score = 100 / (1 + np.exp(-0.1 * (percentile - 50)))
        score = max(1, min(100, int(score)))

        # Enhanced description with statistical context
        if score >= 85:
            description = f"ELITE: {opponent_team} allows {team_avg:.1f} pts/game to {position} (+{team_avg-all_defenses_avg:.1f} vs avg)"
        elif score >= 70:
            description = f"Great: {opponent_team} allows {team_avg:.1f} pts/game to {position}"
        elif score >= 30:
            description = f"Neutral: {opponent_team} allows {team_avg:.1f} pts/game to {position}"
        else:
            description = f"TOUGH: {opponent_team} allows {team_avg:.1f} pts/game to {position} ({team_avg-all_defenses_avg:.1f} vs avg)"

        return (score, description)

    async def analyze_player_matchup(self, player_name: str, position: str, opponent: str) -> Dict:
        """
        Analyze a specific player's matchup.

        Args:
            player_name: Player's name
            position: Player's position
            opponent: Opponent team abbreviation (e.g., "BAL", "@DAL")

        Returns:
            Dict with matchup analysis
        """
        await self.load_defensive_rankings()

        # Clean opponent (remove @ for away games)
        opp_team = opponent.replace("@", "").strip()

        score, description = self.get_matchup_score(opp_team, position)

        # Get Sleeper projection if available
        from sleeper_api import get_player_projection

        sleeper_proj = await get_player_projection(player_name)
        sleeper_pts = None
        if sleeper_proj:
            sleeper_pts = sleeper_proj.get("pts_ppr", sleeper_proj.get("pts_std", 0))

        return {
            "player": player_name,
            "position": position,
            "opponent": opponent,
            "matchup_score": score,
            "matchup_description": description,
            "sleeper_projection": sleeper_pts,
            "recommendation": self._get_recommendation(score, position),
        }

    def _get_recommendation(self, score: int, position: str) -> str:
        """Get start/sit recommendation based on matchup score."""
        if position in ["QB", "TE", "K", "DEF"]:
            # Single starter positions - be more conservative
            if score >= 70:
                return "START - Great matchup"
            elif score >= 40:
                return "START - Decent matchup"
            elif score >= 25:
                return "RISKY - Monitor for better options"
            else:
                return "SIT - Find alternative if possible"
        else:
            # RB/WR - multiple starters, can be more aggressive
            if score >= 80:
                return "MUST START - Elite matchup"
            elif score >= 65:
                return "START - Favorable matchup"
            elif score >= 50:
                return "FLEX - Solid play"
            elif score >= 35:
                return "BENCH - Only if desperate"
            else:
                return "SIT - Avoid this matchup"

    async def analyze_roster_matchups(self, roster: List[Dict]) -> List[Dict]:
        """
        Analyze matchups for an entire roster.

        Args:
            roster: List of player dicts with 'name', 'position', 'opponent'

        Returns:
            List of matchup analyses sorted by score
        """
        await self.load_defensive_rankings()

        analyses = []
        for player in roster:
            if not player.get("opponent"):
                continue

            analysis = await self.analyze_player_matchup(
                player["name"], player["position"], player["opponent"]
            )
            analyses.append(analysis)

        # Sort by matchup score (best first)
        analyses.sort(key=lambda x: x["matchup_score"], reverse=True)

        return analyses

    def get_position_matchups(self, position: str, week_matchups: Dict[str, str]) -> List[Dict]:
        """
        Get all matchups for a position in a given week.

        Args:
            position: Position to analyze
            week_matchups: Dict of {team: opponent} for the week

        Returns:
            List of team matchups sorted by score
        """
        if not self.defensive_rankings:
            return []

        matchups = []
        for team, opponent in week_matchups.items():
            opp_team = opponent.replace("@", "").strip()
            if opp_team in self.defensive_rankings:
                score, description = self.get_matchup_score(opp_team, position)
                matchups.append(
                    {"team": team, "opponent": opponent, "score": score, "description": description}
                )

        # Sort by score (best matchups first)
        matchups.sort(key=lambda x: x["score"], reverse=True)

        return matchups


# Global instance
matchup_analyzer = MatchupAnalyzer()


# Convenience functions
async def get_matchup_score(opponent: str, position: str) -> Tuple[int, str]:
    """Quick function to get a matchup score."""
    await matchup_analyzer.load_defensive_rankings()
    return matchup_analyzer.get_matchup_score(opponent, position)


async def analyze_player(name: str, position: str, opponent: str) -> Dict:
    """Quick function to analyze a player's matchup."""
    return await matchup_analyzer.analyze_player_matchup(name, position, opponent)
