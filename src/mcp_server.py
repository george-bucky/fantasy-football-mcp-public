#!/usr/bin/env python3
"""
Fantasy Football MCP Server
Production-grade MCP server for Yahoo Fantasy Sports integration with
sophisticated lineup optimization and parallel processing capabilities.
"""

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from pathlib import Path

from mcp import Context, Tool, Resource, resource, tool, stdio_server
from pydantic import BaseModel, Field
from loguru import logger
from dotenv import load_dotenv

from agents.data_fetcher import DataFetcherAgent
from agents.statistical import StatisticalAnalysisAgent
from agents.optimization import OptimizationAgent
from agents.decision import DecisionAgent
from agents.cache_manager import CacheManager
from agents.reddit_analyzer import RedditSentimentAgent
from models.player import Player
from models.lineup import Lineup, LineupRecommendation
from models.matchup import Matchup, MatchupAnalysis
from utils.constants import POSITIONS, ROSTER_POSITIONS
from config.settings import Settings

load_dotenv()

class FantasyFootballServer:
    """Main MCP server for Fantasy Football operations."""
    
    def __init__(self):
        """Initialize the Fantasy Football MCP server."""
        self.settings = Settings()
        self._setup_logging()
        
        # Initialize agents
        self.cache_manager = CacheManager(self.settings)
        self.data_fetcher = DataFetcherAgent(self.settings, self.cache_manager)
        self.statistical = StatisticalAnalysisAgent(self.settings)
        self.optimization = OptimizationAgent(self.settings)
        self.decision = DecisionAgent(self.settings)
        self.reddit_sentiment = RedditSentimentAgent(self.settings)
        
        # Track available leagues (discovered dynamically)
        self.available_leagues: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"Fantasy Football MCP Server v{self.settings.mcp_server_version} initialized")
    
    def _setup_logging(self):
        """Configure logging for the server."""
        log_path = Path(self.settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            self.settings.log_file,
            rotation="10 MB",
            retention="7 days",
            level=self.settings.log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}"
        )
    
    async def discover_leagues(self) -> Dict[str, Dict[str, Any]]:
        """
        Discover all available leagues for the authenticated user.
        Returns a dictionary of league_id -> league_info.
        """
        try:
            leagues = await self.data_fetcher.get_user_leagues()
            self.available_leagues = {
                league['league_id']: {
                    'name': league['name'],
                    'season': league['season'],
                    'num_teams': league['num_teams'],
                    'scoring_type': league['scoring_type'],
                    'current_week': league.get('current_week', 1),
                    'is_active': league.get('is_finished', False) == False
                }
                for league in leagues
            }
            logger.info(f"Discovered {len(self.available_leagues)} leagues")
            return self.available_leagues
        except Exception as e:
            logger.error(f"Failed to discover leagues: {e}")
            return {}
    
    @tool
    async def get_leagues(self, context: Context) -> Dict[str, Any]:
        """
        Get all available fantasy leagues for the authenticated user.
        
        Returns:
            Dictionary containing all discovered leagues with their details.
        """
        leagues = await self.discover_leagues()
        
        return {
            "status": "success",
            "leagues": leagues,
            "total_count": len(leagues),
            "active_leagues": [
                lid for lid, info in leagues.items() 
                if info.get('is_active', False)
            ]
        }
    
    @tool
    async def get_optimal_lineup(
        self,
        context: Context,
        league_id: Optional[str] = None,
        week: Optional[int] = None,
        strategy: str = "balanced"
    ) -> Dict[str, Any]:
        """
        Get the mathematically optimal lineup for a given week.
        
        Args:
            league_id: The league ID. If not provided, uses all available leagues.
            week: The week number. If not provided, uses current week.
            strategy: Lineup strategy - 'conservative', 'aggressive', or 'balanced'.
        
        Returns:
            Optimal lineup recommendations with detailed analysis.
        """
        try:
            # Handle multiple leagues if no specific league_id provided
            if not league_id:
                if not self.available_leagues:
                    await self.discover_leagues()
                
                results = {}
                # Process all active leagues in parallel
                tasks = [
                    self._get_optimal_lineup_for_league(lid, week, strategy)
                    for lid, info in self.available_leagues.items()
                    if info.get('is_active', False)
                ]
                
                lineups = await asyncio.gather(*tasks, return_exceptions=True)
                
                for (lid, info), lineup in zip(
                    [(lid, info) for lid, info in self.available_leagues.items() if info.get('is_active', False)],
                    lineups
                ):
                    if isinstance(lineup, Exception):
                        logger.error(f"Failed to get lineup for league {lid}: {lineup}")
                        results[lid] = {"error": str(lineup)}
                    else:
                        results[lid] = {
                            "league_name": info['name'],
                            "lineup": lineup
                        }
                
                return {
                    "status": "success",
                    "lineups": results,
                    "strategy": strategy,
                    "week": week
                }
            else:
                # Single league processing
                lineup = await self._get_optimal_lineup_for_league(league_id, week, strategy)
                return {
                    "status": "success",
                    "league_id": league_id,
                    "lineup": lineup,
                    "strategy": strategy,
                    "week": week
                }
                
        except Exception as e:
            logger.error(f"Failed to get optimal lineup: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def _get_optimal_lineup_for_league(
        self,
        league_id: str,
        week: Optional[int],
        strategy: str
    ) -> Dict[str, Any]:
        """Get optimal lineup for a specific league."""
        # Fetch roster and matchup data
        roster_data = await self.data_fetcher.get_roster(league_id)
        matchup_data = await self.data_fetcher.get_matchup(league_id, week)
        
        # Get player stats and projections in parallel
        player_tasks = [
            self.statistical.analyze_player(player, week)
            for player in roster_data['players']
        ]
        player_analyses = await asyncio.gather(*player_tasks)
        
        # Run optimization with selected strategy
        optimal_lineup = await self.optimization.optimize_lineup(
            players=player_analyses,
            roster_positions=roster_data['roster_positions'],
            strategy=strategy,
            matchup_context=matchup_data
        )
        
        # Get decision synthesis
        recommendation = await self.decision.synthesize_lineup_decision(
            optimal_lineup=optimal_lineup,
            player_analyses=player_analyses,
            strategy=strategy,
            matchup_data=matchup_data
        )
        
        return recommendation.dict()
    
    @tool
    async def analyze_matchup(
        self,
        context: Context,
        league_id: Optional[str] = None,
        week: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Perform deep analysis of weekly matchup with win probability.
        
        Args:
            league_id: The league ID. If not provided, analyzes all leagues.
            week: The week number. If not provided, uses current week.
        
        Returns:
            Comprehensive matchup analysis with win probability.
        """
        try:
            if not league_id:
                # Analyze all active leagues
                if not self.available_leagues:
                    await self.discover_leagues()
                
                results = {}
                tasks = [
                    self._analyze_matchup_for_league(lid, week)
                    for lid, info in self.available_leagues.items()
                    if info.get('is_active', False)
                ]
                
                analyses = await asyncio.gather(*tasks, return_exceptions=True)
                
                for (lid, info), analysis in zip(
                    [(lid, info) for lid, info in self.available_leagues.items() if info.get('is_active', False)],
                    analyses
                ):
                    if isinstance(analysis, Exception):
                        logger.error(f"Failed to analyze matchup for league {lid}: {analysis}")
                        results[lid] = {"error": str(analysis)}
                    else:
                        results[lid] = {
                            "league_name": info['name'],
                            "analysis": analysis
                        }
                
                return {
                    "status": "success",
                    "matchups": results,
                    "week": week
                }
            else:
                analysis = await self._analyze_matchup_for_league(league_id, week)
                return {
                    "status": "success",
                    "league_id": league_id,
                    "analysis": analysis,
                    "week": week
                }
                
        except Exception as e:
            logger.error(f"Failed to analyze matchup: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def _analyze_matchup_for_league(
        self,
        league_id: str,
        week: Optional[int]
    ) -> Dict[str, Any]:
        """Analyze matchup for a specific league."""
        # Get matchup data
        matchup_data = await self.data_fetcher.get_matchup(league_id, week)
        
        # Parallel analysis of both teams
        my_analysis_task = self.statistical.analyze_team(
            matchup_data['my_team'],
            week
        )
        opp_analysis_task = self.statistical.analyze_team(
            matchup_data['opponent_team'],
            week
        )
        
        my_analysis, opp_analysis = await asyncio.gather(
            my_analysis_task,
            opp_analysis_task
        )
        
        # Calculate win probability and recommendations
        matchup_analysis = await self.decision.analyze_matchup(
            my_team=my_analysis,
            opponent=opp_analysis,
            week=week
        )
        
        return matchup_analysis.dict()
    
    @tool
    async def get_waiver_targets(
        self,
        context: Context,
        league_id: Optional[str] = None,
        position: Optional[str] = None,
        max_results: int = 10
    ) -> Dict[str, Any]:
        """
        Identify high-value waiver wire targets using trending data.
        
        Args:
            league_id: The league ID. If not provided, analyzes all leagues.
            position: Filter by position (QB, RB, WR, TE, etc.)
            max_results: Maximum number of recommendations per league.
        
        Returns:
            Top waiver wire pickup recommendations.
        """
        try:
            if not league_id:
                # Get waiver targets for all leagues
                if not self.available_leagues:
                    await self.discover_leagues()
                
                results = {}
                tasks = [
                    self._get_waiver_targets_for_league(lid, position, max_results)
                    for lid, info in self.available_leagues.items()
                    if info.get('is_active', False)
                ]
                
                targets = await asyncio.gather(*tasks, return_exceptions=True)
                
                for (lid, info), target_list in zip(
                    [(lid, info) for lid, info in self.available_leagues.items() if info.get('is_active', False)],
                    targets
                ):
                    if isinstance(target_list, Exception):
                        logger.error(f"Failed to get waiver targets for league {lid}: {target_list}")
                        results[lid] = {"error": str(target_list)}
                    else:
                        results[lid] = {
                            "league_name": info['name'],
                            "targets": target_list
                        }
                
                return {
                    "status": "success",
                    "waiver_targets": results,
                    "position_filter": position,
                    "max_results": max_results
                }
            else:
                targets = await self._get_waiver_targets_for_league(league_id, position, max_results)
                return {
                    "status": "success",
                    "league_id": league_id,
                    "targets": targets,
                    "position_filter": position
                }
                
        except Exception as e:
            logger.error(f"Failed to get waiver targets: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def _get_waiver_targets_for_league(
        self,
        league_id: str,
        position: Optional[str],
        max_results: int
    ) -> List[Dict[str, Any]]:
        """Get waiver targets for a specific league."""
        # Get available players
        available_players = await self.data_fetcher.get_available_players(
            league_id,
            position=position
        )
        
        # Analyze players in parallel
        analysis_tasks = [
            self.statistical.analyze_waiver_value(player)
            for player in available_players[:max_results * 3]  # Analyze more to filter
        ]
        
        analyses = await asyncio.gather(*analysis_tasks)
        
        # Score and rank by waiver value
        recommendations = await self.optimization.rank_waiver_targets(
            analyses,
            max_results=max_results
        )
        
        return recommendations
    
    @tool
    async def analyze_trade(
        self,
        context: Context,
        league_id: str,
        give_players: List[str],
        receive_players: List[str]
    ) -> Dict[str, Any]:
        """
        Evaluate trade proposals using rest-of-season projections.
        
        Args:
            league_id: The league ID for the trade.
            give_players: List of player IDs to trade away.
            receive_players: List of player IDs to receive.
        
        Returns:
            Trade analysis with recommendation and value assessment.
        """
        try:
            # Fetch player data for both sides
            give_data = await asyncio.gather(*[
                self.data_fetcher.get_player(league_id, pid)
                for pid in give_players
            ])
            
            receive_data = await asyncio.gather(*[
                self.data_fetcher.get_player(league_id, pid)
                for pid in receive_players
            ])
            
            # Get ROS projections for all players
            give_projections = await asyncio.gather(*[
                self.statistical.get_ros_projection(player)
                for player in give_data
            ])
            
            receive_projections = await asyncio.gather(*[
                self.statistical.get_ros_projection(player)
                for player in receive_data
            ])
            
            # Analyze trade impact
            trade_analysis = await self.decision.analyze_trade(
                give_players=give_projections,
                receive_players=receive_projections,
                roster_context=await self.data_fetcher.get_roster(league_id)
            )
            
            return {
                "status": "success",
                "league_id": league_id,
                "analysis": trade_analysis.dict(),
                "recommendation": trade_analysis.recommendation,
                "value_differential": trade_analysis.value_differential
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze trade: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    @tool
    async def get_injury_impact(
        self,
        context: Context,
        league_id: str,
        player_id: str
    ) -> Dict[str, Any]:
        """
        Assess how a player's injury affects lineup decisions.
        
        Args:
            league_id: The league ID.
            player_id: The injured player's ID.
        
        Returns:
            Analysis of injury impact with recommended replacements.
        """
        try:
            # Get player and injury data
            player_data = await self.data_fetcher.get_player(league_id, player_id)
            injury_data = await self.data_fetcher.get_injury_report(player_id)
            
            # Get roster to understand replacement options
            roster = await self.data_fetcher.get_roster(league_id)
            
            # Find potential replacements
            replacements = await self.optimization.find_injury_replacements(
                injured_player=player_data,
                injury_info=injury_data,
                roster=roster
            )
            
            # Analyze impact
            impact_analysis = await self.decision.analyze_injury_impact(
                player=player_data,
                injury=injury_data,
                replacements=replacements,
                roster=roster
            )
            
            return {
                "status": "success",
                "league_id": league_id,
                "player": player_data['name'],
                "injury_status": injury_data.get('status', 'Unknown'),
                "impact_analysis": impact_analysis.dict(),
                "recommended_replacements": replacements[:3]
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze injury impact: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    @tool
    async def analyze_reddit_sentiment(
        self,
        context: Context,
        players: List[str],
        time_window_hours: int = 48
    ) -> Dict[str, Any]:
        """
        Analyze Reddit sentiment for player Start/Sit decisions.
        
        Args:
            players: List of player names to compare (e.g., ["Josh Allen", "Jared Goff"])
            time_window_hours: How far back to look for Reddit posts (default 48 hours)
        
        Returns:
            Reddit sentiment analysis with Start/Sit recommendations based on community consensus.
        """
        try:
            if not players:
                return {
                    "status": "error",
                    "error": "No players provided for analysis"
                }
            
            # Single player analysis
            if len(players) == 1:
                sentiment = await self.reddit_sentiment.analyze_player_sentiment(
                    players[0],
                    time_window_hours
                )
                return {
                    "status": "success",
                    "analysis_type": "single_player",
                    "player": players[0],
                    "sentiment_data": sentiment,
                    "recommendation": sentiment.get('consensus', 'UNKNOWN'),
                    "confidence": sentiment.get('hype_score', 0) * 100
                }
            
            # Multi-player comparison (Start/Sit decision)
            comparison = await self.reddit_sentiment.compare_players_sentiment(
                players,
                time_window_hours
            )
            
            return {
                "status": "success",
                "analysis_type": "comparison",
                "players": players,
                "comparison_data": comparison,
                "recommendation": comparison.get('recommendation'),
                "confidence": comparison.get('confidence', 0)
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze Reddit sentiment: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    @resource
    async def get_cache_status(self, uri: str) -> str:
        """Get the current cache status and statistics."""
        stats = await self.cache_manager.get_stats()
        return json.dumps(stats, indent=2)

async def main():
    """Main entry point for the MCP server."""
    server = FantasyFootballServer()
    
    # Create MCP server instance
    mcp_server = stdio_server.Server(
        name=server.settings.mcp_server_name,
        version=server.settings.mcp_server_version
    )
    
    # Register tools
    mcp_server.add_tool(server.get_leagues)
    mcp_server.add_tool(server.get_optimal_lineup)
    mcp_server.add_tool(server.analyze_matchup)
    mcp_server.add_tool(server.get_waiver_targets)
    mcp_server.add_tool(server.analyze_trade)
    mcp_server.add_tool(server.get_injury_impact)
    mcp_server.add_tool(server.analyze_reddit_sentiment)
    
    # Register resources
    mcp_server.add_resource(server.get_cache_status)
    
    # Start server
    logger.info("Starting Fantasy Football MCP Server...")
    await mcp_server.run()

if __name__ == "__main__":
    asyncio.run(main())