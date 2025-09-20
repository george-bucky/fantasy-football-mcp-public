from __future__ import annotations

"""Lightweight fallback lineup optimizer.

The original optimizer attempted deep projections and external data pulls but was
fragile against Yahoo payload changes.  This replacement keeps the same public
API so existing callers keep working, while delivering deterministic, best-effort
results based purely on the roster data already returned by the legacy layer.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

BENCH_SLOTS = {
    "BN",
    "BENCH",
    "IR",
    "IR+",
    "IRL",
    "IRR",
    "DNR",
    "NA",
    "N/A",
    "COVID-19",
    "COVID",
}


def _coerce_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        if isinstance(value, str) and not value.strip():
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_position(raw: Any) -> str:
    if not raw:
        return "BN"
    if isinstance(raw, dict):
        if "position" in raw:
            return str(raw.get("position", "BN")).upper()
        for val in raw.values():
            if isinstance(val, dict) and "position" in val:
                return str(val.get("position", "BN")).upper()
    return str(raw).upper()


@dataclass
class Player:
    """Simple player model that mirrors the attributes used by our callers."""

    name: str
    position: str
    team: str
    opponent: str = ""
    status: str = "OK"
    yahoo_projection: float = 0.0
    sleeper_projection: float = 0.0
    sleeper_projection_std: float = 0.0
    sleeper_projection_ppr: float = 0.0
    sleeper_projection_half_ppr: float = 0.0
    sleeper_id: str = ""
    sleeper_status: str = ""
    sleeper_injury_status: str = ""
    sleeper_match_method: str = ""
    player_tier: str = "starter"
    matchup_score: int = 50
    matchup_description: str = "No matchup context"
    trending_score: int = 0
    injury_status: str = "Healthy"
    injury_probability: float = 0.0
    ownership_pct: float = 0.0
    recent_performance: List[float] = field(default_factory=list)
    season_avg: float = 0.0
    target_share: float = 0.0
    snap_count_pct: float = 0.0
    weather_impact: str = "Unknown"
    vegas_total: float = 0.0
    team_implied_total: float = 0.0
    spread: float = 0.0
    defense_rank_allowed: str = "Unknown"
    value: float = 0.0
    value_score: float = 0.0
    floor_projection: float = 0.0
    ceiling_projection: float = 0.0
    consistency_score: float = 0.0
    risk_level: str = "medium"
    composite_score: float = 0.0
    # New expert advice fields
    expert_tier: str = ""
    expert_recommendation: str = ""
    expert_confidence: int = 0
    expert_advice: str = ""
    search_rank: int = 500
    raw: Dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        return bool(self.name and self.team)


class LineupOptimizer:
    """Best-effort lineup helper that works entirely offline."""

    def __init__(self) -> None:
        pass

    async def parse_yahoo_roster(self, roster_payload: Dict[str, Any]) -> List[Player]:
        """Convert a roster payload into Player objects.

        Supports both the simplified JSON returned by ``ff_get_roster`` and the
        raw Yahoo payload by delegating to ``parse_team_roster`` when needed.
        """

        entries: List[Dict[str, Any]] = []
        if isinstance(roster_payload, dict):
            roster_obj = roster_payload.get("roster")
            if isinstance(roster_obj, list):
                entries = roster_obj
            else:
                # Fallback: try using the legacy parser for raw Yahoo data
                try:
                    from fantasy_football_multi_league import parse_team_roster  # type: ignore

                    entries = parse_team_roster(roster_payload)
                except Exception:
                    entries = []
        players: List[Player] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or entry.get("full_name") or "").strip()
            if not name:
                continue
            team = str(
                entry.get("team")
                or entry.get("editorial_team_abbr")
                or entry.get("team_abbr")
                or entry.get("team_abbreviation")
                or ""
            ).strip()
            position = _normalize_position(
                entry.get("position")
                or entry.get("selected_position")
                or entry.get("display_position")
                or "BN"
            )
            player = Player(
                name=name,
                position=position,
                team=team,
                opponent=str(entry.get("opponent") or entry.get("opponent_abbr") or ""),
                status=str(entry.get("status") or "OK"),
                yahoo_projection=_coerce_float(entry.get("yahoo_projection") or entry.get("projection")),
                sleeper_projection=_coerce_float(entry.get("sleeper_projection")),
                sleeper_projection_std=_coerce_float(entry.get("sleeper_projection_std")),
                sleeper_projection_ppr=_coerce_float(entry.get("sleeper_projection_ppr")),
                sleeper_projection_half_ppr=_coerce_float(entry.get("sleeper_projection_half_ppr")),
                sleeper_id=str(entry.get("sleeper_id") or ""),
                sleeper_status=str(entry.get("sleeper_status") or ""),
                sleeper_injury_status=str(entry.get("sleeper_injury_status") or ""),
                sleeper_match_method=str(entry.get("sleeper_match_method") or ""),
                player_tier=str(entry.get("player_tier") or "starter"),
                matchup_score=_coerce_int(entry.get("matchup_score"), default=50),
                matchup_description=str(entry.get("matchup_description") or "No matchup context"),
                trending_score=_coerce_int(entry.get("trending_score"), default=0),
                injury_status=str(entry.get("injury_status") or "Healthy"),
                injury_probability=_coerce_float(entry.get("injury_probability")),
                ownership_pct=_coerce_float(entry.get("ownership_pct")),
                season_avg=_coerce_float(entry.get("season_avg")),
                target_share=_coerce_float(entry.get("target_share")),
                snap_count_pct=_coerce_float(entry.get("snap_count_pct")),
                weather_impact=str(entry.get("weather_impact") or "Unknown"),
                vegas_total=_coerce_float(entry.get("vegas_total")),
                team_implied_total=_coerce_float(entry.get("team_implied_total")),
                spread=_coerce_float(entry.get("spread")),
                defense_rank_allowed=str(entry.get("def_rank_vs_pos") or "Unknown"),
                value=_coerce_float(entry.get("value") or entry.get("value_score")),
                value_score=_coerce_float(entry.get("value_score")),
                floor_projection=_coerce_float(entry.get("floor_projection")),
                ceiling_projection=_coerce_float(entry.get("ceiling_projection")),
                consistency_score=_coerce_float(entry.get("consistency_score")),
                risk_level=str(entry.get("risk_level") or "medium"),
                composite_score=_coerce_float(entry.get("composite_score")),
                raw=entry,
            )
            players.append(player)
        return players

    async def enhance_with_external_data(
        self,
        players: Sequence[Player],
        *,
        week: Optional[int] = None,
    ) -> List[Player]:
        """Enhance players with Sleeper data including rankings, advice, and matchup analysis."""

        enhanced: List[Player] = []
        
        try:
            from sleeper_api import sleeper_client
            
            # Get current season and week once for all players
            from sleeper_api import get_current_season, get_current_week
            current_season = await get_current_season()
            current_week = await get_current_week()
            
            for player in players:
                # Create a copy to avoid modifying the original
                enhanced_player = Player(
                    name=player.name,
                    position=player.position,
                    team=player.team,
                    opponent=player.opponent,
                    status=player.status,
                    yahoo_projection=player.yahoo_projection,
                    sleeper_projection=player.sleeper_projection,
                    sleeper_projection_std=player.sleeper_projection_std,
                    sleeper_projection_ppr=player.sleeper_projection_ppr,
                    sleeper_projection_half_ppr=player.sleeper_projection_half_ppr,
                    sleeper_id=player.sleeper_id,
                    sleeper_status=player.sleeper_status,
                    sleeper_injury_status=player.sleeper_injury_status,
                    sleeper_match_method=player.sleeper_match_method,
                    player_tier=player.player_tier,
                    matchup_score=player.matchup_score,
                    matchup_description=player.matchup_description,
                    trending_score=player.trending_score,
                    injury_status=player.injury_status,
                    injury_probability=player.injury_probability,
                    ownership_pct=player.ownership_pct,
                    recent_performance=player.recent_performance.copy(),
                    season_avg=player.season_avg,
                    target_share=player.target_share,
                    snap_count_pct=player.snap_count_pct,
                    weather_impact=player.weather_impact,
                    vegas_total=player.vegas_total,
                    team_implied_total=player.team_implied_total,
                    spread=player.spread,
                    defense_rank_allowed=player.defense_rank_allowed,
                    value=player.value,
                    value_score=player.value_score,
                    floor_projection=player.floor_projection,
                    ceiling_projection=player.ceiling_projection,
                    consistency_score=player.consistency_score,
                    risk_level=player.risk_level,
                    composite_score=player.composite_score,
                    raw=player.raw.copy(),
                )
                
                use_week = week or current_week
                
                try:
                    # Get Sleeper player mapping and basic data
                    sleeper_id = await sleeper_client.map_yahoo_to_sleeper(
                        player.name, position=player.position, team=player.team
                    )
                    
                    if sleeper_id:
                        enhanced_player.sleeper_id = sleeper_id
                        enhanced_player.sleeper_match_method = "api"
                        
                        # Fetch projections for this player
                        try:
                            projections = await sleeper_client.get_projections(current_season, use_week)
                            if sleeper_id in projections:
                                proj_data = projections[sleeper_id]
                                # Sleeper projections typically have 'projected_stats' with 'pts' or position-specific
                                stats = proj_data.get('projected_stats', {})
                                if isinstance(stats, list):
                                    # Sum pts from list of stats if present
                                    enhanced_player.sleeper_projection = sum(_coerce_float(s.get('pts', 0)) for s in stats)
                                    enhanced_player.sleeper_projection_std = sum(_coerce_float(s.get('pts_std', 0)) for s in stats)
                                    enhanced_player.sleeper_projection_ppr = sum(_coerce_float(s.get('pts_ppr', 0)) for s in stats)
                                    enhanced_player.sleeper_projection_half_ppr = sum(_coerce_float(s.get('pts_half_ppr', 0)) for s in stats)
                                else:
                                    # Dict or direct pts
                                    enhanced_player.sleeper_projection = _coerce_float(stats.get('pts') or proj_data.get('pts', 0))
                                    enhanced_player.sleeper_projection_std = _coerce_float(stats.get('pts_std') or proj_data.get('pts_std', 0))
                                    enhanced_player.sleeper_projection_ppr = _coerce_float(stats.get('pts_ppr') or proj_data.get('pts_ppr', enhanced_player.sleeper_projection))
                                    enhanced_player.sleeper_projection_half_ppr = _coerce_float(stats.get('pts_half_ppr') or proj_data.get('pts_half_ppr', enhanced_player.sleeper_projection))
                        except Exception:
                            enhanced_player.sleeper_projection = 0.0  # Fallback if projections fail
                        
                        # Get expert advice for this player
                        advice = await sleeper_client.get_expert_advice(player.name, week=use_week)
                        if advice and advice.get('confidence', 0) > 0:
                            enhanced_player.expert_tier = advice.get('tier', 'starter')
                            enhanced_player.expert_recommendation = advice.get('recommendation', 'Start')
                            enhanced_player.expert_confidence = advice.get('confidence', 50)
                            enhanced_player.expert_advice = advice.get('advice', 'No advice available')
                            enhanced_player.search_rank = advice.get('search_rank', 500)
                            enhanced_player.matchup_description = advice.get('advice', 'No advice available')
                            
                            # Convert confidence to matchup score (0-100 -> 0-100)
                            enhanced_player.matchup_score = advice.get('confidence', 50)
                            
                            # Set risk level based on tier and confidence
                            confidence = advice.get('confidence', 50)
                            if confidence >= 70:
                                enhanced_player.risk_level = "low"
                            elif confidence >= 50:
                                enhanced_player.risk_level = "medium"
                            else:
                                enhanced_player.risk_level = "high"
                        
                        # Try to get trending data
                        try:
                            trending_adds = await sleeper_client.get_trending_players("nfl", "add", hours=24)
                            trending_drops = await sleeper_client.get_trending_players("nfl", "drop", hours=24)
                            
                            # Check if this player is trending
                            trending_add_ids = [p.get('player_id') for p in trending_adds]
                            trending_drop_ids = [p.get('player_id') for p in trending_drops]
                            
                            if sleeper_id in trending_add_ids:
                                enhanced_player.trending_score = 75  # Trending up
                            elif sleeper_id in trending_drop_ids:
                                enhanced_player.trending_score = 25  # Trending down
                            else:
                                enhanced_player.trending_score = 50  # Neutral
                        except Exception:
                            enhanced_player.trending_score = 50  # Default if trending fails
                            
                except Exception:
                    # If Sleeper lookup fails, keep original data
                    enhanced_player.sleeper_match_method = "failed"
                
                # Populate derived metrics
                # Use Sleeper projection if available, else Yahoo
                base_projection = enhanced_player.sleeper_projection or enhanced_player.yahoo_projection or 0.0
                if enhanced_player.composite_score == 0.0:
                    enhanced_player.composite_score = base_projection
                if enhanced_player.floor_projection == 0.0:
                    enhanced_player.floor_projection = max(base_projection * 0.75, 0.0)
                if enhanced_player.ceiling_projection == 0.0:
                    enhanced_player.ceiling_projection = max(base_projection * 1.25, enhanced_player.floor_projection)
                if enhanced_player.matchup_description == "No matchup context":
                    enhanced_player.matchup_description = f"Week {use_week} outlook"
                if not enhanced_player.matchup_score:
                    enhanced_player.matchup_score = 50
                    
                enhanced.append(enhanced_player)
                
        except ImportError:
            # If Sleeper API not available, fall back to basic enhancement
            for player in players:
                if player.composite_score == 0.0:
                    player.composite_score = (
                        player.yahoo_projection or player.sleeper_projection
                    )
                if player.floor_projection == 0.0:
                    player.floor_projection = max(player.composite_score * 0.75, 0.0)
                if player.ceiling_projection == 0.0:
                    player.ceiling_projection = max(player.composite_score * 1.25, player.floor_projection)
                if player.matchup_description == "No matchup context":
                    player.matchup_description = f"Week {week or 'current'} outlook"
                if not player.matchup_score:
                    player.matchup_score = 50
                enhanced.append(player)
        
        return enhanced

    async def optimize_lineup_smart(
        self,
        players: Sequence[Player],
        strategy: str = "balanced",
        week: Optional[int] = None,
        use_llm: bool = False,
    ) -> Dict[str, Any]:
        """Return a deterministic starter/bench split without heavy math."""

        starters: Dict[str, Player] = {}
        bench: List[Player] = []
        bench_ids: set[int] = set()
        selected_ids: set[int] = set()

        for player in players:
            slot = player.position.upper()
            if slot in BENCH_SLOTS:
                bench.append(player)
                bench_ids.add(id(player))
                continue

            existing = starters.get(slot)
            if existing is None:
                starters[slot] = player
                selected_ids.add(id(player))
                continue

            # Prefer the player with the higher projection
            if player.yahoo_projection > existing.yahoo_projection:
                bench.append(existing)
                bench_ids.add(id(existing))
                starters[slot] = player
                selected_ids.add(id(player))
            else:
                bench.append(player)
                bench_ids.add(id(player))

        for player in players:
            pid = id(player)
            if pid in selected_ids or pid in bench_ids:
                continue
            bench.append(player)
            bench_ids.add(pid)

        recommendations = [f"Start {p.name} at {pos}" for pos, p in starters.items()]
        data_quality = {
            "total_players": len(players),
            "valid_players": sum(1 for p in players if p.is_valid()),
            "players_with_projections": sum(
                1 for p in players if (p.yahoo_projection or p.sleeper_projection)
            ),
            "players_with_matchup_data": sum(
                1 for p in players if p.matchup_description and p.matchup_description != "No matchup context"
            ),
        }

        return {
            "status": "success",
            "strategy_used": strategy,
            "week": week or "current",
            "starters": starters,
            "bench": bench,
            "recommendations": recommendations,
            "errors": [],
            "data_quality": data_quality,
        }


lineup_optimizer = LineupOptimizer()

__all__ = ["Player", "LineupOptimizer", "lineup_optimizer"]
