"""
High-performance lineup optimization agent with parallel processing.

This module implements advanced lineup optimization strategies using:
- Massive parallel processing with asyncio and concurrent.futures
- Genetic algorithms for large solution spaces
- Smart pruning to reduce search space
- Correlation-based stacking strategies
- Multiple optimization objectives (points, value, ownership)
"""

import asyncio
import itertools
import logging
import random
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from functools import partial

import numpy as np
from pydantic import BaseModel, Field

from ..models.player import Player, Position, PlayerProjections
from ..models.lineup import (
    Lineup,
    LineupSlot,
    LineupConstraints,
    LineupRecommendation,
    LineupAlternative,
    OptimizationStrategy,
    LineupType,
)

logger = logging.getLogger(__name__)


class OptimizationObjective(str, Enum):
    """Optimization objectives for lineup construction."""

    MAXIMIZE_POINTS = "maximize_points"
    MAXIMIZE_VALUE = "maximize_value"
    MINIMIZE_OWNERSHIP = "minimize_ownership"
    MAXIMIZE_CEILING = "maximize_ceiling"
    MAXIMIZE_FLOOR = "maximize_floor"
    BALANCED = "balanced"


@dataclass
class OptimizationWeights:
    """Weights for multi-objective optimization."""

    points: float = 0.7
    value: float = 0.2
    ownership: float = 0.1
    ceiling: float = 0.0
    floor: float = 0.0
    correlation: float = 0.0
    variance_penalty: float = 0.0


@dataclass
class GeneticAlgorithmConfig:
    """Configuration for genetic algorithm optimization."""

    population_size: int = 1000
    generations: int = 200
    mutation_rate: float = 0.1
    crossover_rate: float = 0.8
    elitism_rate: float = 0.1
    tournament_size: int = 5
    diversity_threshold: float = 0.8


class LineupChromosome:
    """Genetic algorithm chromosome representing a lineup."""

    def __init__(self, players: List[Player], constraints: LineupConstraints):
        self.players = players
        self.constraints = constraints
        self.fitness: Optional[float] = None
        self.violations: List[str] = []
        self._lineup: Optional[Lineup] = None

    def to_lineup(self) -> Lineup:
        """Convert chromosome to Lineup model."""
        if self._lineup is None:
            slots = []
            total_salary = 0
            total_points = Decimal("0")

            for i, player in enumerate(self.players):
                position = self._get_position_for_slot(i)
                salary = self._get_player_salary(player)

                slot = LineupSlot(position=position, player=player, salary_used=salary)
                slots.append(slot)
                total_salary += salary

                if player.projections:
                    total_points += player.projections.projected_fantasy_points

            self._lineup = Lineup(
                lineup_type=LineupType.DRAFTKINGS,
                slots=slots,
                total_salary=total_salary,
                salary_remaining=self.constraints.salary_cap - total_salary,
                salary_cap=self.constraints.salary_cap,
                total_projected_points=total_points,
                confidence_score=Decimal("0.8"),
            )

        return self._lineup

    def _get_position_for_slot(self, slot_index: int) -> Position:
        """Map slot index to position requirement."""
        # Standard DraftKings lineup: QB, RB, RB, WR, WR, WR, TE, FLEX, DST
        position_map = {
            0: Position.QB,
            1: Position.RB,
            2: Position.RB,
            3: Position.WR,
            4: Position.WR,
            5: Position.WR,
            6: Position.TE,
            7: Position.RB,  # FLEX - simplified to RB
            8: Position.DEF,
        }
        return position_map.get(slot_index, Position.RB)

    def _get_player_salary(self, player: Player) -> int:
        """Get player salary for optimization."""
        if player.value_metrics:
            return (
                player.value_metrics.draftkings_salary
                or player.value_metrics.fanduel_salary
                or player.value_metrics.yahoo_salary
                or 5000
            )
        return 5000


class OptimizationAgent:
    """High-performance lineup optimization agent with parallel processing."""

    def __init__(self, max_workers: int = None):
        """Initialize the optimization agent.

        Args:
            max_workers: Maximum number of worker threads/processes
        """
        self.max_workers = max_workers or min(32, (asyncio.get_event_loop().get_debug() and 1) or 4)
        self.logger = logging.getLogger(__name__)
        self._correlation_cache: Dict[str, Dict[str, float]] = {}

        # Performance tracking
        self.optimization_stats = {"total_evaluations": 0, "cache_hits": 0, "parallel_tasks": 0}

    async def optimize_lineup(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        strategy: OptimizationStrategy = OptimizationStrategy.BALANCED,
        objective: OptimizationObjective = OptimizationObjective.MAXIMIZE_POINTS,
        weights: Optional[OptimizationWeights] = None,
        use_genetic_algorithm: bool = True,
        max_alternatives: int = 5,
    ) -> LineupRecommendation:
        """Optimize lineup with parallel processing and multiple strategies.

        Args:
            players: Available players for selection
            constraints: Lineup construction constraints
            strategy: Optimization strategy
            objective: Primary optimization objective
            weights: Custom optimization weights
            use_genetic_algorithm: Whether to use genetic algorithm for large spaces
            max_alternatives: Maximum alternative lineups to generate

        Returns:
            LineupRecommendation with optimal lineup and alternatives
        """
        start_time = time.time()
        self.logger.info(f"Starting lineup optimization with {len(players)} players")

        # Set default weights based on strategy
        if weights is None:
            weights = self._get_strategy_weights(strategy)

        # Filter and validate players
        valid_players = await self._filter_valid_players(players, constraints)
        self.logger.info(f"Filtered to {len(valid_players)} valid players")

        if len(valid_players) < 9:  # Minimum for a lineup
            raise ValueError("Insufficient players to form a valid lineup")

        # Determine optimization approach
        search_space_size = self._estimate_search_space(valid_players)
        self.logger.info(f"Estimated search space size: {search_space_size:,}")

        if use_genetic_algorithm and search_space_size > 10**6:
            optimal_lineup = await self._genetic_algorithm_optimization(
                valid_players, constraints, weights, objective
            )
        else:
            optimal_lineup = await self._parallel_bruteforce_optimization(
                valid_players, constraints, weights, objective
            )

        # Generate alternative lineups
        alternatives = await self._generate_alternatives(
            valid_players, constraints, weights, optimal_lineup, max_alternatives
        )

        # Create recommendation
        recommendation = self._create_recommendation(
            optimal_lineup, alternatives, strategy, weights
        )

        optimization_time = time.time() - start_time
        self.logger.info(f"Optimization completed in {optimization_time:.2f} seconds")

        return recommendation

    async def rank_waiver_targets(
        self,
        available_players: List[Player],
        current_roster: List[Player],
        constraints: LineupConstraints,
        weeks_ahead: int = 4,
    ) -> List[Tuple[Player, float, str]]:
        """Rank waiver wire targets based on lineup impact.

        Args:
            available_players: Players available on waivers
            current_roster: Current roster players
            constraints: Lineup constraints
            weeks_ahead: Number of weeks to project

        Returns:
            List of (player, impact_score, reasoning) tuples
        """
        self.logger.info(f"Ranking {len(available_players)} waiver targets")

        # Create tasks for parallel evaluation
        tasks = []
        for player in available_players:
            task = self._evaluate_waiver_impact(player, current_roster, constraints, weeks_ahead)
            tasks.append(task)

        # Execute in parallel with task groups
        async with asyncio.TaskGroup() as tg:
            results = [tg.create_task(task) for task in tasks]

        # Collect and sort results
        player_rankings = []
        for i, result in enumerate(results):
            impact_score, reasoning = await result
            player_rankings.append((available_players[i], impact_score, reasoning))

        # Sort by impact score descending
        player_rankings.sort(key=lambda x: x[1], reverse=True)

        return player_rankings[:20]  # Top 20 targets

    async def find_injury_replacements(
        self,
        injured_players: List[Player],
        available_players: List[Player],
        constraints: LineupConstraints,
        max_replacements: int = 3,
    ) -> Dict[str, List[Tuple[Player, float, str]]]:
        """Find optimal injury replacements with parallel processing.

        Args:
            injured_players: Players who are injured
            available_players: Available replacement players
            constraints: Lineup constraints
            max_replacements: Maximum replacements per injured player

        Returns:
            Dict mapping injured player ID to list of (replacement, score, reason)
        """
        self.logger.info(f"Finding replacements for {len(injured_players)} injured players")

        replacement_map = {}

        # Create parallel tasks for each injured player
        tasks = []
        for injured_player in injured_players:
            task = self._find_position_replacements(
                injured_player, available_players, constraints, max_replacements
            )
            tasks.append((injured_player.id, task))

        # Execute in parallel
        results = await asyncio.gather(*[task for _, task in tasks])

        # Map results back to injured players
        for i, (player_id, _) in enumerate(tasks):
            replacement_map[player_id] = results[i]

        return replacement_map

    async def _filter_valid_players(
        self, players: List[Player], constraints: LineupConstraints
    ) -> List[Player]:
        """Filter players based on constraints with parallel validation."""

        async def is_player_valid(player: Player) -> bool:
            """Check if player meets basic constraints."""
            # Check exclusions
            if constraints.excluded_players and player.id in constraints.excluded_players:
                return False

            # Check salary constraints
            if player.value_metrics:
                salary = (
                    player.value_metrics.draftkings_salary
                    or player.value_metrics.fanduel_salary
                    or player.value_metrics.yahoo_salary
                )
                if salary and salary > constraints.salary_cap:
                    return False

            # Check injury status
            if player.is_injured():
                # Allow questionable players but not out/doubtful
                injury_status = player.injury_report.status if player.injury_report else None
                if injury_status in ["Out", "Doubtful", "IR"]:
                    return False

            # Check projections
            if not player.projections or not player.projections.projected_fantasy_points:
                return False

            return True

        # Parallel validation
        tasks = [is_player_valid(player) for player in players]
        validity_results = await asyncio.gather(*tasks)

        return [player for player, is_valid in zip(players, validity_results) if is_valid]

    async def _parallel_bruteforce_optimization(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        weights: OptimizationWeights,
        objective: OptimizationObjective,
    ) -> Lineup:
        """Parallel brute force optimization with smart pruning."""

        # Group players by position for efficient combination generation
        players_by_position = self._group_players_by_position(players)

        # Generate position combinations with pruning
        position_combinations = await self._generate_position_combinations(
            players_by_position, constraints
        )

        self.logger.info(f"Generated {len(position_combinations)} position combinations")

        # Parallel evaluation of combinations
        best_lineup = None
        best_score = float("-inf")

        # Process in batches to manage memory
        batch_size = min(1000, len(position_combinations) // self.max_workers + 1)

        for i in range(0, len(position_combinations), batch_size):
            batch = position_combinations[i : i + batch_size]

            # Create evaluation tasks
            tasks = []
            for combination in batch:
                task = self._evaluate_lineup_combination(
                    combination, constraints, weights, objective
                )
                tasks.append(task)

            # Execute batch in parallel
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for result in batch_results:
                if isinstance(result, Exception):
                    continue

                lineup, score = result
                if score > best_score:
                    best_score = score
                    best_lineup = lineup

        if best_lineup is None:
            raise ValueError("No valid lineup found with given constraints")

        return best_lineup

    async def _genetic_algorithm_optimization(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        weights: OptimizationWeights,
        objective: OptimizationObjective,
        config: Optional[GeneticAlgorithmConfig] = None,
    ) -> Lineup:
        """Genetic algorithm optimization with parallel fitness evaluation."""

        if config is None:
            config = GeneticAlgorithmConfig()

        self.logger.info(f"Starting genetic algorithm with population {config.population_size}")

        # Initialize population
        population = await self._initialize_population(players, constraints, config)

        best_fitness = float("-inf")
        best_chromosome = None
        generations_without_improvement = 0

        for generation in range(config.generations):
            # Parallel fitness evaluation
            await self._evaluate_population_fitness(population, weights, objective)

            # Track best solution
            current_best = max(population, key=lambda x: x.fitness or float("-inf"))
            if current_best.fitness and current_best.fitness > best_fitness:
                best_fitness = current_best.fitness
                best_chromosome = current_best
                generations_without_improvement = 0
                self.logger.info(f"Generation {generation}: New best fitness {best_fitness:.3f}")
            else:
                generations_without_improvement += 1

            # Early stopping
            if generations_without_improvement > 50:
                self.logger.info(f"Early stopping at generation {generation}")
                break

            # Create next generation
            population = await self._create_next_generation(
                population, players, constraints, config
            )

        if best_chromosome is None:
            raise ValueError("Genetic algorithm failed to find valid solution")

        return best_chromosome.to_lineup()

    async def _generate_alternatives(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        weights: OptimizationWeights,
        optimal_lineup: Lineup,
        max_alternatives: int,
    ) -> List[LineupAlternative]:
        """Generate alternative lineups with different strategies."""

        alternatives = []

        # Alternative strategies to try
        alternative_objectives = [
            (OptimizationObjective.MAXIMIZE_VALUE, "Value-focused alternative"),
            (OptimizationObjective.MINIMIZE_OWNERSHIP, "Low-ownership contrarian play"),
            (OptimizationObjective.MAXIMIZE_CEILING, "High-ceiling tournament play"),
            (OptimizationObjective.MAXIMIZE_FLOOR, "Safe cash game play"),
        ]

        # Generate alternatives in parallel
        tasks = []
        for objective, reason in alternative_objectives[:max_alternatives]:
            task = self._create_alternative_lineup(
                players, constraints, weights, objective, optimal_lineup, reason
            )
            tasks.append(task)

        alternative_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in alternative_results:
            if isinstance(result, Exception):
                continue
            if result is not None:
                alternatives.append(result)

        return alternatives

    async def _evaluate_waiver_impact(
        self,
        player: Player,
        current_roster: List[Player],
        constraints: LineupConstraints,
        weeks_ahead: int,
    ) -> Tuple[float, str]:
        """Evaluate waiver player's impact on lineup optimization."""

        # Create extended roster with waiver player
        extended_roster = current_roster + [player]

        # Optimize lineup with and without the player
        try:
            with_player_lineup = await self._quick_optimization(extended_roster, constraints)
            without_player_lineup = await self._quick_optimization(current_roster, constraints)

            # Calculate impact
            point_improvement = (
                with_player_lineup.total_projected_points
                - without_player_lineup.total_projected_points
            )

            # Factor in upcoming matchups and consistency
            upside_factor = self._calculate_upside_factor(player, weeks_ahead)
            consistency_factor = self._calculate_consistency_factor(player)

            impact_score = float(point_improvement) * upside_factor * consistency_factor

            reasoning = f"Projected {point_improvement:.1f} point improvement, {upside_factor:.1f}x upside, {consistency_factor:.1f}x consistency"

            return impact_score, reasoning

        except Exception as e:
            self.logger.warning(f"Error evaluating waiver impact for {player.name}: {e}")
            return 0.0, "Evaluation error"

    async def _find_position_replacements(
        self,
        injured_player: Player,
        available_players: List[Player],
        constraints: LineupConstraints,
        max_replacements: int,
    ) -> List[Tuple[Player, float, str]]:
        """Find best replacements for an injured player."""

        # Filter to same position
        position_matches = [p for p in available_players if p.position == injured_player.position]

        if not position_matches:
            return []

        # Evaluate replacements in parallel
        tasks = []
        for replacement in position_matches:
            task = self._evaluate_replacement_player(injured_player, replacement, constraints)
            tasks.append(task)

        replacement_scores = await asyncio.gather(*tasks)

        # Create ranked list
        replacements = []
        for i, (score, reason) in enumerate(replacement_scores):
            replacements.append((position_matches[i], score, reason))

        # Sort and return top replacements
        replacements.sort(key=lambda x: x[1], reverse=True)
        return replacements[:max_replacements]

    def _group_players_by_position(self, players: List[Player]) -> Dict[Position, List[Player]]:
        """Group players by position for efficient combination generation."""

        groups = {}
        for player in players:
            if player.position not in groups:
                groups[player.position] = []
            groups[player.position].append(player)

        # Sort each position group by projected points descending
        for position in groups:
            groups[position].sort(
                key=lambda p: (
                    p.projections.projected_fantasy_points if p.projections else Decimal("0")
                ),
                reverse=True,
            )

        return groups

    async def _generate_position_combinations(
        self, players_by_position: Dict[Position, List[Player]], constraints: LineupConstraints
    ) -> List[List[Player]]:
        """Generate valid position combinations with smart pruning."""

        # Standard DraftKings positions: QB(1), RB(2), WR(3), TE(1), DEF(1), FLEX(1)
        position_requirements = {
            Position.QB: 1,
            Position.RB: 2,
            Position.WR: 3,
            Position.TE: 1,
            Position.DEF: 1,
        }

        # Limit players per position for feasibility
        max_players_per_position = {
            Position.QB: min(5, len(players_by_position.get(Position.QB, []))),
            Position.RB: min(10, len(players_by_position.get(Position.RB, []))),
            Position.WR: min(15, len(players_by_position.get(Position.WR, []))),
            Position.TE: min(8, len(players_by_position.get(Position.TE, []))),
            Position.DEF: min(5, len(players_by_position.get(Position.DEF, []))),
        }

        combinations = []

        # Generate combinations with FLEX consideration
        qb_players = players_by_position.get(Position.QB, [])[
            : max_players_per_position[Position.QB]
        ]
        rb_players = players_by_position.get(Position.RB, [])[
            : max_players_per_position[Position.RB]
        ]
        wr_players = players_by_position.get(Position.WR, [])[
            : max_players_per_position[Position.WR]
        ]
        te_players = players_by_position.get(Position.TE, [])[
            : max_players_per_position[Position.TE]
        ]
        def_players = players_by_position.get(Position.DEF, [])[
            : max_players_per_position[Position.DEF]
        ]

        # Use concurrent processing for combination generation
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Generate core position combinations
            core_combinations = list(
                itertools.product(
                    itertools.combinations(qb_players, 1),
                    itertools.combinations(rb_players, 2),
                    itertools.combinations(wr_players, 3),
                    itertools.combinations(te_players, 1),
                    itertools.combinations(def_players, 1),
                )
            )

            # Add FLEX players (can be RB, WR, or TE)
            flex_players = rb_players + wr_players + te_players

            for core_combo in core_combinations[:10000]:  # Limit for performance
                qbs, rbs, wrs, tes, defs = core_combo
                used_players = set(list(qbs) + list(rbs) + list(wrs) + list(tes) + list(defs))

                # Add available FLEX players
                available_flex = [p for p in flex_players if p not in used_players]
                for flex_player in available_flex[:3]:  # Top 3 FLEX options
                    lineup_players = (
                        list(qbs) + list(rbs) + list(wrs) + list(tes) + list(defs) + [flex_player]
                    )

                    # Quick salary check for pruning
                    if self._quick_salary_check(lineup_players, constraints):
                        combinations.append(lineup_players)

        return combinations

    def _quick_salary_check(self, players: List[Player], constraints: LineupConstraints) -> bool:
        """Quick salary feasibility check for pruning."""

        total_salary = 0
        for player in players:
            if player.value_metrics:
                salary = (
                    player.value_metrics.draftkings_salary
                    or player.value_metrics.fanduel_salary
                    or player.value_metrics.yahoo_salary
                    or 5000
                )
                total_salary += salary
            else:
                total_salary += 5000

        return total_salary <= constraints.salary_cap

    async def _evaluate_lineup_combination(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        weights: OptimizationWeights,
        objective: OptimizationObjective,
    ) -> Tuple[Optional[Lineup], float]:
        """Evaluate a specific player combination as a lineup."""

        try:
            # Create lineup from players
            lineup = self._create_lineup_from_players(players, constraints)

            # Validate constraints
            violations = lineup.validate_against_constraints(constraints)
            if violations:
                return None, float("-inf")

            # Calculate multi-objective score
            score = await self._calculate_lineup_score(lineup, weights, objective)

            self.optimization_stats["total_evaluations"] += 1

            return lineup, score

        except Exception as e:
            self.logger.debug(f"Error evaluating combination: {e}")
            return None, float("-inf")

    def _create_lineup_from_players(
        self, players: List[Player], constraints: LineupConstraints
    ) -> Lineup:
        """Create a Lineup object from a list of players."""

        # Map players to positions (simplified DraftKings structure)
        position_map = [
            Position.QB,
            Position.RB,
            Position.RB,
            Position.WR,
            Position.WR,
            Position.WR,
            Position.TE,
            Position.RB,
            Position.DEF,
        ]

        slots = []
        total_salary = 0
        total_points = Decimal("0")

        for i, player in enumerate(players):
            position = position_map[i] if i < len(position_map) else player.position
            salary = self._get_player_salary_for_optimization(player)

            slot = LineupSlot(position=position, player=player, salary_used=salary)
            slots.append(slot)
            total_salary += salary

            if player.projections:
                total_points += player.projections.projected_fantasy_points

        return Lineup(
            lineup_type=LineupType.DRAFTKINGS,
            slots=slots,
            total_salary=total_salary,
            salary_remaining=constraints.salary_cap - total_salary,
            salary_cap=constraints.salary_cap,
            total_projected_points=total_points,
            confidence_score=Decimal("0.8"),
        )

    def _get_player_salary_for_optimization(self, player: Player) -> int:
        """Get player salary for optimization calculations."""

        if player.value_metrics:
            return (
                player.value_metrics.draftkings_salary
                or player.value_metrics.fanduel_salary
                or player.value_metrics.yahoo_salary
                or 5000
            )
        return 5000

    async def _calculate_lineup_score(
        self, lineup: Lineup, weights: OptimizationWeights, objective: OptimizationObjective
    ) -> float:
        """Calculate multi-objective score for a lineup."""

        # Base projected points
        points_score = float(lineup.total_projected_points)

        # Value score (points per $1000)
        value_score = float(lineup.get_salary_efficiency()) if lineup.total_salary > 0 else 0

        # Ownership score (lower is better for contrarian plays)
        ownership_score = 100 - float(lineup.projected_ownership or 50)

        # Ceiling and floor scores
        ceiling_score = float(lineup.ceiling_points or lineup.total_projected_points)
        floor_score = float(lineup.floor_points or lineup.total_projected_points * Decimal("0.7"))

        # Correlation bonus
        correlation_score = await self._calculate_correlation_score(lineup)

        # Variance penalty
        variance_penalty = self._calculate_variance_penalty(lineup)

        # Combine scores based on objective and weights
        if objective == OptimizationObjective.MAXIMIZE_POINTS:
            score = points_score
        elif objective == OptimizationObjective.MAXIMIZE_VALUE:
            score = value_score * 10  # Scale to similar range
        elif objective == OptimizationObjective.MINIMIZE_OWNERSHIP:
            score = ownership_score
        elif objective == OptimizationObjective.MAXIMIZE_CEILING:
            score = ceiling_score
        elif objective == OptimizationObjective.MAXIMIZE_FLOOR:
            score = floor_score
        else:  # BALANCED
            score = (
                points_score * weights.points
                + value_score * weights.value * 10
                + ownership_score * weights.ownership
                + ceiling_score * weights.ceiling
                + floor_score * weights.floor
                + correlation_score * weights.correlation
                - variance_penalty * weights.variance_penalty
            )

        return score

    async def _calculate_correlation_score(self, lineup: Lineup) -> float:
        """Calculate correlation bonus for stacked players."""

        correlation_score = 0.0
        players = lineup.get_players()

        # QB-WR correlation bonus
        qbs = lineup.get_players_by_position(Position.QB)
        wrs = lineup.get_players_by_position(Position.WR)

        for qb in qbs:
            for wr in wrs:
                if qb.team == wr.team:
                    correlation_score += 2.0  # Same team bonus

        # RB-DEF negative correlation penalty
        rbs = lineup.get_players_by_position(Position.RB)
        defs = lineup.get_players_by_position(Position.DEF)

        for rb in rbs:
            for defense in defs:
                if rb.team == defense.team:
                    correlation_score -= 1.0  # Same team penalty

        return correlation_score

    def _calculate_variance_penalty(self, lineup: Lineup) -> float:
        """Calculate variance penalty for high-risk lineups."""

        variance_penalty = 0.0

        # Penalty for multiple players from same team (except stacks)
        team_exposure = lineup.get_team_exposure()
        for team, count in team_exposure.items():
            if count > 3:  # More than 3 from same team
                variance_penalty += (count - 3) * 0.5

        return variance_penalty

    async def _initialize_population(
        self, players: List[Player], constraints: LineupConstraints, config: GeneticAlgorithmConfig
    ) -> List[LineupChromosome]:
        """Initialize genetic algorithm population."""

        population = []
        players_by_position = self._group_players_by_position(players)

        # Create diverse initial population
        for _ in range(config.population_size):
            try:
                chromosome_players = await self._create_random_valid_lineup(
                    players_by_position, constraints
                )
                chromosome = LineupChromosome(chromosome_players, constraints)
                population.append(chromosome)
            except Exception as e:
                self.logger.debug(f"Failed to create random lineup: {e}")
                continue

        # Ensure minimum population size
        while len(population) < config.population_size // 2:
            try:
                chromosome_players = await self._create_random_valid_lineup(
                    players_by_position, constraints
                )
                chromosome = LineupChromosome(chromosome_players, constraints)
                population.append(chromosome)
            except:
                break

        return population

    async def _create_random_valid_lineup(
        self, players_by_position: Dict[Position, List[Player]], constraints: LineupConstraints
    ) -> List[Player]:
        """Create a random valid lineup for genetic algorithm initialization."""

        lineup_players = []
        remaining_salary = constraints.salary_cap

        # Standard DraftKings positions
        positions_needed = [
            Position.QB,
            Position.RB,
            Position.RB,
            Position.WR,
            Position.WR,
            Position.WR,
            Position.TE,
            Position.RB,
            Position.DEF,
        ]

        for position in positions_needed:
            available_players = players_by_position.get(position, [])

            # Filter by remaining salary
            affordable_players = [
                p
                for p in available_players
                if p not in lineup_players
                and self._get_player_salary_for_optimization(p) <= remaining_salary
            ]

            if not affordable_players:
                # Fallback to cheapest available
                affordable_players = [p for p in available_players if p not in lineup_players]
                if affordable_players:
                    affordable_players = [
                        min(
                            affordable_players,
                            key=lambda x: self._get_player_salary_for_optimization(x),
                        )
                    ]

            if affordable_players:
                # Weighted random selection (higher projection = higher probability)
                weights = [
                    float(p.projections.projected_fantasy_points) if p.projections else 1.0
                    for p in affordable_players
                ]

                if sum(weights) > 0:
                    player = random.choices(affordable_players, weights=weights)[0]
                else:
                    player = random.choice(affordable_players)

                lineup_players.append(player)
                remaining_salary -= self._get_player_salary_for_optimization(player)

        return lineup_players

    async def _evaluate_population_fitness(
        self,
        population: List[LineupChromosome],
        weights: OptimizationWeights,
        objective: OptimizationObjective,
    ) -> None:
        """Evaluate fitness for entire population in parallel."""

        # Create evaluation tasks
        tasks = []
        for chromosome in population:
            task = self._evaluate_chromosome_fitness(chromosome, weights, objective)
            tasks.append(task)

        # Execute in parallel batches
        batch_size = min(100, len(tasks))
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i : i + batch_size]
            await asyncio.gather(*batch)

    async def _evaluate_chromosome_fitness(
        self,
        chromosome: LineupChromosome,
        weights: OptimizationWeights,
        objective: OptimizationObjective,
    ) -> None:
        """Evaluate fitness for a single chromosome."""

        try:
            lineup = chromosome.to_lineup()

            # Check constraint violations
            violations = lineup.validate_against_constraints(chromosome.constraints)
            if violations:
                chromosome.fitness = float("-inf")
                chromosome.violations = violations
                return

            # Calculate fitness score
            fitness = await self._calculate_lineup_score(lineup, weights, objective)
            chromosome.fitness = fitness
            chromosome.violations = []

        except Exception as e:
            chromosome.fitness = float("-inf")
            chromosome.violations = [f"Evaluation error: {str(e)}"]

    async def _create_next_generation(
        self,
        population: List[LineupChromosome],
        players: List[Player],
        constraints: LineupConstraints,
        config: GeneticAlgorithmConfig,
    ) -> List[LineupChromosome]:
        """Create next generation through selection, crossover, and mutation."""

        # Sort population by fitness
        population.sort(key=lambda x: x.fitness or float("-inf"), reverse=True)

        next_generation = []

        # Elitism: Keep top performers
        elite_count = int(config.population_size * config.elitism_rate)
        next_generation.extend(population[:elite_count])

        # Generate offspring through crossover and mutation
        while len(next_generation) < config.population_size:
            # Tournament selection
            parent1 = self._tournament_selection(population, config.tournament_size)
            parent2 = self._tournament_selection(population, config.tournament_size)

            # Crossover
            if random.random() < config.crossover_rate:
                offspring = await self._crossover(parent1, parent2, constraints)
            else:
                offspring = parent1 if parent1.fitness > parent2.fitness else parent2

            # Mutation
            if random.random() < config.mutation_rate:
                offspring = await self._mutate(offspring, players, constraints)

            next_generation.append(offspring)

        return next_generation[: config.population_size]

    def _tournament_selection(
        self, population: List[LineupChromosome], tournament_size: int
    ) -> LineupChromosome:
        """Select parent using tournament selection."""

        tournament = random.sample(population, min(tournament_size, len(population)))
        return max(tournament, key=lambda x: x.fitness or float("-inf"))

    async def _crossover(
        self, parent1: LineupChromosome, parent2: LineupChromosome, constraints: LineupConstraints
    ) -> LineupChromosome:
        """Create offspring through crossover."""

        try:
            # Position-aware crossover
            offspring_players = []

            for i in range(len(parent1.players)):
                if random.random() < 0.5:
                    offspring_players.append(parent1.players[i])
                else:
                    offspring_players.append(parent2.players[i])

            # Ensure no duplicate players
            seen_players = set()
            unique_players = []

            for player in offspring_players:
                if player.id not in seen_players:
                    unique_players.append(player)
                    seen_players.add(player.id)

            # If we have duplicates, fill from parents
            if len(unique_players) < len(offspring_players):
                all_parent_players = parent1.players + parent2.players
                for player in all_parent_players:
                    if len(unique_players) >= len(offspring_players):
                        break
                    if player.id not in seen_players:
                        unique_players.append(player)
                        seen_players.add(player.id)

            return LineupChromosome(unique_players[: len(parent1.players)], constraints)

        except Exception:
            # Return better parent if crossover fails
            return parent1 if parent1.fitness > parent2.fitness else parent2

    async def _mutate(
        self, chromosome: LineupChromosome, players: List[Player], constraints: LineupConstraints
    ) -> LineupChromosome:
        """Mutate chromosome by replacing random players."""

        try:
            mutated_players = chromosome.players.copy()

            # Replace 1-2 random players
            num_mutations = random.randint(1, 2)
            positions_to_mutate = random.sample(range(len(mutated_players)), num_mutations)

            for pos_idx in positions_to_mutate:
                current_player = mutated_players[pos_idx]
                position = current_player.position

                # Find replacement candidates
                position_players = [
                    p for p in players if p.position == position and p.id != current_player.id
                ]

                if position_players:
                    # Filter by salary constraint
                    current_salary = sum(
                        self._get_player_salary_for_optimization(p) for p in mutated_players
                    )
                    current_player_salary = self._get_player_salary_for_optimization(current_player)
                    available_salary = (
                        constraints.salary_cap - current_salary + current_player_salary
                    )

                    affordable_players = [
                        p
                        for p in position_players
                        if self._get_player_salary_for_optimization(p) <= available_salary
                    ]

                    if affordable_players:
                        new_player = random.choice(affordable_players)
                        mutated_players[pos_idx] = new_player

            return LineupChromosome(mutated_players, constraints)

        except Exception:
            return chromosome

    async def _create_alternative_lineup(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        weights: OptimizationWeights,
        objective: OptimizationObjective,
        optimal_lineup: Lineup,
        reason: str,
    ) -> Optional[LineupAlternative]:
        """Create an alternative lineup with different optimization focus."""

        try:
            # Modify constraints to force different players
            modified_constraints = LineupConstraints(
                salary_cap=constraints.salary_cap,
                position_requirements=constraints.position_requirements,
                max_players_per_team=constraints.max_players_per_team,
                excluded_players=(constraints.excluded_players or [])
                + [p.id for p in optimal_lineup.get_players()[:3]],
            )

            alternative_lineup = await self._quick_optimization(
                players, modified_constraints, objective
            )

            if alternative_lineup:
                # Calculate differences
                point_diff = (
                    alternative_lineup.total_projected_points
                    - optimal_lineup.total_projected_points
                )
                salary_diff = alternative_lineup.total_salary - optimal_lineup.total_salary
                ownership_diff = (alternative_lineup.projected_ownership or Decimal("50")) - (
                    optimal_lineup.projected_ownership or Decimal("50")
                )

                return LineupAlternative(
                    lineup=alternative_lineup,
                    reason=reason,
                    point_difference=point_diff,
                    salary_difference=salary_diff,
                    ownership_difference=ownership_diff,
                    confidence=Decimal("0.7"),
                )

        except Exception as e:
            self.logger.debug(f"Failed to create alternative: {e}")
            return None

    async def _quick_optimization(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        objective: OptimizationObjective = OptimizationObjective.MAXIMIZE_POINTS,
    ) -> Optional[Lineup]:
        """Quick optimization for alternatives and evaluations."""

        try:
            # Use simplified greedy optimization for speed
            return await self._greedy_optimization(players, constraints, objective)
        except Exception:
            return None

    async def _greedy_optimization(
        self,
        players: List[Player],
        constraints: LineupConstraints,
        objective: OptimizationObjective,
    ) -> Optional[Lineup]:
        """Fast greedy optimization approach."""

        # Sort players by optimization criteria
        if objective == OptimizationObjective.MAXIMIZE_POINTS:
            players.sort(
                key=lambda p: (
                    p.projections.projected_fantasy_points if p.projections else Decimal("0")
                ),
                reverse=True,
            )
        elif objective == OptimizationObjective.MAXIMIZE_VALUE:
            players.sort(key=lambda p: p.get_projected_value() or Decimal("0"), reverse=True)
        elif objective == OptimizationObjective.MINIMIZE_OWNERSHIP:
            players.sort(
                key=lambda p: (
                    p.value_metrics.ownership_percentage if p.value_metrics else Decimal("50")
                )
            )

        # Greedy selection by position
        selected_players = []
        remaining_salary = constraints.salary_cap

        positions_needed = [
            Position.QB,
            Position.RB,
            Position.RB,
            Position.WR,
            Position.WR,
            Position.WR,
            Position.TE,
            Position.RB,
            Position.DEF,
        ]

        for position in positions_needed:
            best_player = None

            for player in players:
                if (
                    player.position == position
                    and player not in selected_players
                    and self._get_player_salary_for_optimization(player) <= remaining_salary
                ):

                    if constraints.excluded_players and player.id in constraints.excluded_players:
                        continue

                    best_player = player
                    break

            if best_player:
                selected_players.append(best_player)
                remaining_salary -= self._get_player_salary_for_optimization(best_player)
            else:
                return None  # Cannot complete lineup

        if len(selected_players) == 9:
            return self._create_lineup_from_players(selected_players, constraints)

        return None

    async def _evaluate_replacement_player(
        self, injured_player: Player, replacement: Player, constraints: LineupConstraints
    ) -> Tuple[float, str]:
        """Evaluate how well a replacement player fills the injured player's role."""

        # Basic point comparison
        injured_points = (
            injured_player.projections.projected_fantasy_points
            if injured_player.projections
            else Decimal("0")
        )
        replacement_points = (
            replacement.projections.projected_fantasy_points
            if replacement.projections
            else Decimal("0")
        )

        point_difference = float(replacement_points - injured_points)

        # Factor in matchup quality
        matchup_factor = 1.0
        if replacement.projections and replacement.projections.matchup_rating:
            if "favorable" in replacement.projections.matchup_rating.lower():
                matchup_factor = 1.2
            elif "difficult" in replacement.projections.matchup_rating.lower():
                matchup_factor = 0.8

        # Factor in consistency
        consistency_factor = self._calculate_consistency_factor(replacement)

        score = point_difference * matchup_factor * consistency_factor

        reason = f"{point_difference:+.1f} pts vs injured player, {matchup_factor:.1f}x matchup, {consistency_factor:.1f}x consistency"

        return score, reason

    def _calculate_upside_factor(self, player: Player, weeks_ahead: int) -> float:
        """Calculate upside factor based on player's ceiling potential."""

        if not player.projections:
            return 1.0

        base_projection = float(player.projections.projected_fantasy_points)
        ceiling_projection = float(
            player.projections.ceiling_points or player.projections.projected_fantasy_points
        )

        if base_projection > 0:
            upside_ratio = ceiling_projection / base_projection
            return min(upside_ratio, 2.0)  # Cap at 2x

        return 1.0

    def _calculate_consistency_factor(self, player: Player) -> float:
        """Calculate consistency factor based on floor vs projection."""

        if not player.projections:
            return 1.0

        base_projection = float(player.projections.projected_fantasy_points)
        floor_projection = float(
            player.projections.floor_points
            or player.projections.projected_fantasy_points * Decimal("0.7")
        )

        if base_projection > 0:
            floor_ratio = floor_projection / base_projection
            return max(floor_ratio, 0.5)  # Minimum 0.5x

        return 1.0

    def _get_strategy_weights(self, strategy: OptimizationStrategy) -> OptimizationWeights:
        """Get optimization weights based on strategy."""

        if strategy == OptimizationStrategy.MAX_POINTS:
            return OptimizationWeights(points=1.0, value=0.0, ownership=0.0)
        elif strategy == OptimizationStrategy.MAX_VALUE:
            return OptimizationWeights(points=0.3, value=0.7, ownership=0.0)
        elif strategy == OptimizationStrategy.LOW_OWNERSHIP:
            return OptimizationWeights(points=0.4, value=0.2, ownership=0.4)
        elif strategy == OptimizationStrategy.CONTRARIAN:
            return OptimizationWeights(points=0.3, value=0.2, ownership=0.5)
        elif strategy == OptimizationStrategy.SAFE:
            return OptimizationWeights(points=0.5, value=0.2, ownership=0.0, floor=0.3)
        elif strategy == OptimizationStrategy.GPP:
            return OptimizationWeights(points=0.4, value=0.2, ownership=0.2, ceiling=0.2)
        else:  # BALANCED
            return OptimizationWeights(points=0.5, value=0.3, ownership=0.2)

    def _estimate_search_space(self, players: List[Player]) -> int:
        """Estimate the size of the optimization search space."""

        players_by_position = self._group_players_by_position(players)

        # Estimate combinations for standard DraftKings lineup
        qb_count = len(players_by_position.get(Position.QB, []))
        rb_count = len(players_by_position.get(Position.RB, []))
        wr_count = len(players_by_position.get(Position.WR, []))
        te_count = len(players_by_position.get(Position.TE, []))
        def_count = len(players_by_position.get(Position.DEF, []))

        # Rough estimate: QB(1) * RB(2) * WR(3) * TE(1) * DEF(1) * FLEX options
        if all([qb_count, rb_count >= 2, wr_count >= 3, te_count, def_count]):
            from math import comb

            estimate = (
                qb_count
                * comb(rb_count, 2)
                * comb(wr_count, 3)
                * te_count
                * def_count
                * max(1, rb_count + wr_count + te_count - 6)  # FLEX options
            )

            return estimate

        return 0

    def _create_recommendation(
        self,
        optimal_lineup: Lineup,
        alternatives: List[LineupAlternative],
        strategy: OptimizationStrategy,
        weights: OptimizationWeights,
    ) -> LineupRecommendation:
        """Create comprehensive lineup recommendation."""

        # Generate reasoning
        reasoning = self._generate_reasoning(optimal_lineup, strategy, weights)

        # Key factors
        key_factors = [
            f"Projected {optimal_lineup.total_projected_points} points",
            f"${optimal_lineup.salary_remaining} salary remaining",
            f"{optimal_lineup.projected_ownership or 50:.1f}% projected ownership",
        ]

        # Risk assessment
        risk_level = self._assess_risk_level(optimal_lineup)
        upside_potential = self._assess_upside_potential(optimal_lineup)
        floor_assessment = self._assess_floor_potential(optimal_lineup)

        # Contest recommendations
        recommended_contests = self._get_contest_recommendations(optimal_lineup, strategy)

        return LineupRecommendation(
            optimal_lineup=optimal_lineup,
            alternatives=alternatives,
            reasoning=reasoning,
            key_factors=key_factors,
            strategy=strategy,
            contest_type=recommended_contests[0] if recommended_contests else "GPP",
            risk_level=risk_level,
            upside_potential=upside_potential,
            floor_assessment=floor_assessment,
            recommended_contest_types=recommended_contests,
            week=1,  # Would be dynamic
            season=2024,  # Would be dynamic
            overall_confidence=Decimal("0.8"),
        )

    def _generate_reasoning(
        self, lineup: Lineup, strategy: OptimizationStrategy, weights: OptimizationWeights
    ) -> str:
        """Generate reasoning text for the lineup recommendation."""

        reasoning_parts = []

        # Strategy-specific reasoning
        if strategy == OptimizationStrategy.MAX_POINTS:
            reasoning_parts.append("Optimized for maximum projected points")
        elif strategy == OptimizationStrategy.MAX_VALUE:
            reasoning_parts.append("Optimized for salary value efficiency")
        elif strategy == OptimizationStrategy.LOW_OWNERSHIP:
            reasoning_parts.append("Designed for contrarian, low-ownership plays")

        # Team stacking
        team_exposure = lineup.get_team_exposure()
        high_exposure_teams = [team for team, count in team_exposure.items() if count >= 2]
        if high_exposure_teams:
            reasoning_parts.append(f"Features team stacks from: {', '.join(high_exposure_teams)}")

        # Salary efficiency
        efficiency = lineup.get_salary_efficiency()
        reasoning_parts.append(f"Salary efficiency: {efficiency:.2f} points per $1K")

        return ". ".join(reasoning_parts) + "."

    def _assess_risk_level(self, lineup: Lineup) -> str:
        """Assess overall risk level of the lineup."""

        # Factors: ownership, variance, team concentration
        ownership = float(lineup.projected_ownership or 50)

        if ownership > 70:
            return "High"  # High-owned = higher risk of not differentiating
        elif ownership < 30:
            return "High"  # Very low-owned = higher bust risk
        else:
            return "Medium"

    def _assess_upside_potential(self, lineup: Lineup) -> str:
        """Assess upside potential of the lineup."""

        ceiling = lineup.ceiling_points or lineup.total_projected_points * Decimal("1.3")
        projection = lineup.total_projected_points

        upside_ratio = float(ceiling / projection) if projection > 0 else 1.0

        if upside_ratio > 1.4:
            return "Very High"
        elif upside_ratio > 1.2:
            return "High"
        else:
            return "Medium"

    def _assess_floor_potential(self, lineup: Lineup) -> str:
        """Assess floor/safety of the lineup."""

        floor = lineup.floor_points or lineup.total_projected_points * Decimal("0.7")
        projection = lineup.total_projected_points

        floor_ratio = float(floor / projection) if projection > 0 else 0.7

        if floor_ratio > 0.8:
            return "Very Safe"
        elif floor_ratio > 0.7:
            return "Safe"
        else:
            return "Volatile"

    def _get_contest_recommendations(
        self, lineup: Lineup, strategy: OptimizationStrategy
    ) -> List[str]:
        """Get recommended contest types for the lineup."""

        contests = []

        if strategy in [OptimizationStrategy.SAFE, OptimizationStrategy.CASH_GAME]:
            contests.extend(["Cash Games", "Double-ups", "50/50s"])

        if strategy in [OptimizationStrategy.GPP, OptimizationStrategy.CONTRARIAN]:
            contests.extend(["GPPs", "Tournaments", "Large-field contests"])

        if strategy == OptimizationStrategy.BALANCED:
            contests.extend(["Cash Games", "Small-field GPPs"])

        return contests or ["GPPs"]

    # CPU-bound optimization helper functions for ProcessPoolExecutor
    @staticmethod
    def _evaluate_combination_batch(
        combinations_batch: List[List[Player]],
        constraints_dict: Dict[str, Any],
        weights_dict: Dict[str, float],
        objective: str,
    ) -> List[Tuple[Optional[Dict], float]]:
        """Evaluate a batch of combinations in a separate process."""

        results = []
        for combination in combinations_batch:
            try:
                # Simplified evaluation for CPU-bound processing
                total_salary = sum(
                    player.value_metrics.draftkings_salary or 5000
                    for player in combination
                    if player.value_metrics
                )

                total_points = sum(
                    float(player.projections.projected_fantasy_points)
                    for player in combination
                    if player.projections
                )

                if total_salary <= constraints_dict["salary_cap"]:
                    score = total_points  # Simplified scoring
                    lineup_dict = {
                        "players": [{"id": p.id, "name": p.name} for p in combination],
                        "total_salary": total_salary,
                        "total_points": total_points,
                    }
                    results.append((lineup_dict, score))
                else:
                    results.append((None, float("-inf")))

            except Exception:
                results.append((None, float("-inf")))

        return results
