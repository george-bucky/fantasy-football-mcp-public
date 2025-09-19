"""
Example usage of the Hybrid Fantasy Football Optimizer.

This example demonstrates how to use the hybrid optimization system
that combines mathematical optimization with LLM enhancement.
"""

import asyncio
import os
from decimal import Decimal
from typing import List, Dict, Any

# Import the hybrid optimization system
from src.agents.integration import FantasyFootballAssistant, create_fantasy_assistant
from src.agents.config import setup_development_config, get_config
from src.models.player import Player, Position, Team, PlayerProjections, PlayerStats
from src.models.lineup import LineupConstraints, OptimizationStrategy


def create_sample_players() -> List[Player]:
    """Create sample players for demonstration."""
    
    # Sample QB
    josh_allen = Player(
        id="1",
        name="Josh Allen",
        position=Position.QB,
        team=Team.BUF,
        season=2024,
        week=1,
        projections=PlayerProjections(
            projected_fantasy_points=Decimal('24.5'),
            projected_stats=PlayerStats(
                passing_yards=280,
                passing_touchdowns=2,
                rushing_yards=45,
                rushing_touchdowns=1
            ),
            confidence_score=Decimal('0.85'),
            projection_source="Yahoo",
            last_updated="2024-01-01T00:00:00Z"
        )
    )
    
    # Sample RBs
    cmc = Player(
        id="2",
        name="Christian McCaffrey",
        position=Position.RB,
        team=Team.SF,
        season=2024,
        week=1,
        projections=PlayerProjections(
            projected_fantasy_points=Decimal('22.3'),
            projected_stats=PlayerStats(
                rushing_yards=95,
                rushing_touchdowns=1,
                receptions=6,
                receiving_yards=45
            ),
            confidence_score=Decimal('0.90'),
            projection_source="Sleeper",
            last_updated="2024-01-01T00:00:00Z"
        )
    )
    
    austin_ekeler = Player(
        id="3",
        name="Austin Ekeler",
        position=Position.RB,
        team=Team.LAC,
        season=2024,
        week=1,
        projections=PlayerProjections(
            projected_fantasy_points=Decimal('18.7'),
            projected_stats=PlayerStats(
                rushing_yards=75,
                rushing_touchdowns=1,
                receptions=5,
                receiving_yards=35
            ),
            confidence_score=Decimal('0.80'),
            projection_source="Yahoo",
            last_updated="2024-01-01T00:00:00Z"
        )
    )
    
    # Sample WRs
    cooper_kupp = Player(
        id="4",
        name="Cooper Kupp",
        position=Position.WR,
        team=Team.LAR,
        season=2024,
        week=1,
        projections=PlayerProjections(
            projected_fantasy_points=Decimal('19.2'),
            projected_stats=PlayerStats(
                targets=10,
                receptions=7,
                receiving_yards=95,
                receiving_touchdowns=1
            ),
            confidence_score=Decimal('0.85'),
            projection_source="Sleeper",
            last_updated="2024-01-01T00:00:00Z"
        )
    )
    
    tyreek_hill = Player(
        id="5",
        name="Tyreek Hill",
        position=Position.WR,
        team=Team.MIA,
        season=2024,
        week=1,
        projections=PlayerProjections(
            projected_fantasy_points=Decimal('17.8'),
            projected_stats=PlayerStats(
                targets=9,
                receptions=6,
                receiving_yards=85,
                receiving_touchdowns=1
            ),
            confidence_score=Decimal('0.80'),
            projection_source="Yahoo",
            last_updated="2024-01-01T00:00:00Z"
        )
    )
    
    # Sample TE
    travis_kelce = Player(
        id="6",
        name="Travis Kelce",
        position=Position.TE,
        team=Team.KC,
        season=2024,
        week=1,
        projections=PlayerProjections(
            projected_fantasy_points=Decimal('16.4'),
            projected_stats=PlayerStats(
                targets=8,
                receptions=6,
                receiving_yards=75,
                receiving_touchdowns=1
            ),
            confidence_score=Decimal('0.85'),
            projection_source="Sleeper",
            last_updated="2024-01-01T00:00:00Z"
        )
    )
    
    # Sample K
    justin_tucker = Player(
        id="7",
        name="Justin Tucker",
        position=Position.K,
        team=Team.BAL,
        season=2024,
        week=1,
        projections=PlayerProjections(
            projected_fantasy_points=Decimal('9.2'),
            projected_stats=PlayerStats(
                field_goals_made=2,
                field_goals_attempted=3,
                extra_points_made=3,
                extra_points_attempted=3
            ),
            confidence_score=Decimal('0.75'),
            projection_source="Yahoo",
            last_updated="2024-01-01T00:00:00Z"
        )
    )
    
    # Sample DEF
    bills_def = Player(
        id="8",
        name="Buffalo Bills",
        position=Position.DEF,
        team=Team.BUF,
        season=2024,
        week=1,
        projections=PlayerProjections(
            projected_fantasy_points=Decimal('8.5'),
            projected_stats=PlayerStats(
                sacks=3,
                interceptions_def=1,
                fumble_recoveries=1,
                points_allowed=17
            ),
            confidence_score=Decimal('0.80'),
            projection_source="Sleeper",
            last_updated="2024-01-01T00:00:00Z"
        )
    )
    
    return [
        josh_allen, cmc, austin_ekeler, cooper_kupp, tyreek_hill,
        travis_kelce, justin_tucker, bills_def
    ]


def create_sample_constraints() -> LineupConstraints:
    """Create sample lineup constraints."""
    return LineupConstraints(
        salary_cap=50000,
        position_requirements={
            "QB": 1,
            "RB": 2,
            "WR": 2,
            "TE": 1,
            "FLEX": 1,
            "K": 1,
            "DEF": 1
        },
        max_players_per_team=3,
        min_salary_usage=Decimal('0.95')
    )


async def basic_optimization_example():
    """Example of basic lineup optimization."""
    print("=== Basic Optimization Example ===")
    
    # Setup configuration
    setup_development_config()
    
    # Create assistant (you would provide your actual API key)
    assistant = await create_fantasy_assistant(
        llm_api_key=os.getenv('OPENAI_API_KEY', 'your-api-key-here'),
        enable_llm=True
    )
    
    # Create sample data
    players = create_sample_players()
    constraints = create_sample_constraints()
    
    # Optimize lineup
    result = await assistant.optimize_lineup(
        players=players,
        constraints=constraints,
        strategy=OptimizationStrategy.BALANCED,
        context={
            "week": 1,
            "season": 2024,
            "contest_type": "GPP"
        }
    )
    
    # Display results
    print(f"Optimization completed!")
    print(f"Overall confidence: {result.overall_confidence:.2f}")
    print(f"Recommendation strength: {result.recommendation_strength}")
    print(f"Explanation: {result.get_explanation()}")
    print(f"Key insights: {result.get_key_insights()}")


async def interactive_questioning_example():
    """Example of interactive questioning."""
    print("\n=== Interactive Questioning Example ===")
    
    # Setup configuration
    setup_development_config()
    
    # Create assistant
    assistant = await create_fantasy_assistant(
        llm_api_key=os.getenv('OPENAI_API_KEY', 'your-api-key-here'),
        enable_llm=True
    )
    
    # Create sample data
    players = create_sample_players()
    constraints = create_sample_constraints()
    
    # Optimize lineup first
    result = await assistant.optimize_lineup(
        players=players,
        constraints=constraints,
        strategy=OptimizationStrategy.BALANCED
    )
    
    # Ask questions about the lineup
    questions = [
        "What if I use CMC instead of the current RB?",
        "Explain why you chose this lineup",
        "What are the main risks with this lineup?",
        "Suggest some improvements",
        "How does this lineup compare to alternatives?"
    ]
    
    for question in questions:
        print(f"\nQ: {question}")
        response = await assistant.ask_question(question)
        print(f"A: {response.answer}")
        print(f"Confidence: {response.confidence:.2f}")
        
        if response.follow_up_questions:
            print(f"Follow-up suggestions: {response.follow_up_questions}")


async def strategy_comparison_example():
    """Example of comparing different strategies."""
    print("\n=== Strategy Comparison Example ===")
    
    # Setup configuration
    setup_development_config()
    
    # Create assistant
    assistant = await create_fantasy_assistant(
        llm_api_key=os.getenv('OPENAI_API_KEY', 'your-api-key-here'),
        enable_llm=True
    )
    
    # Create sample data
    players = create_sample_players()
    constraints = create_sample_constraints()
    
    # Test different strategies
    strategies = [
        OptimizationStrategy.BALANCED,
        OptimizationStrategy.MAX_POINTS,
        OptimizationStrategy.SAFE,
        OptimizationStrategy.CONTRARIAN
    ]
    
    results = {}
    
    for strategy in strategies:
        print(f"\nTesting {strategy.value} strategy...")
        
        result = await assistant.optimize_lineup(
            players=players,
            constraints=constraints,
            strategy=strategy
        )
        
        results[strategy.value] = {
            "confidence": result.overall_confidence,
            "strength": result.recommendation_strength,
            "explanation": result.get_explanation()
        }
        
        print(f"Confidence: {result.overall_confidence:.2f}")
        print(f"Strength: {result.recommendation_strength}")
    
    # Compare results
    print("\n=== Strategy Comparison Summary ===")
    for strategy_name, data in results.items():
        print(f"{strategy_name}: {data['confidence']:.2f} confidence, {data['strength']} strength")


async def edge_case_analysis_example():
    """Example of edge case analysis."""
    print("\n=== Edge Case Analysis Example ===")
    
    # Setup configuration
    setup_development_config()
    
    # Create assistant
    assistant = await create_fantasy_assistant(
        llm_api_key=os.getenv('OPENAI_API_KEY', 'your-api-key-here'),
        enable_llm=True
    )
    
    # Create sample data
    players = create_sample_players()
    constraints = create_sample_constraints()
    
    # Optimize lineup
    result = await assistant.optimize_lineup(
        players=players,
        constraints=constraints,
        strategy=OptimizationStrategy.BALANCED
    )
    
    # Analyze edge cases
    edge_cases = await assistant.analyze_edge_cases()
    
    print(f"Found {len(edge_cases)} edge cases:")
    for i, edge_case in enumerate(edge_cases, 1):
        print(f"{i}. {edge_case.reasoning}")
        print(f"   Confidence: {edge_case.confidence:.2f}")
        print(f"   Impact: {edge_case.impact_score:.2f}")
        print(f"   Actionable: {edge_case.actionable}")


async def performance_monitoring_example():
    """Example of performance monitoring."""
    print("\n=== Performance Monitoring Example ===")
    
    # Setup configuration
    setup_development_config()
    
    # Create assistant
    assistant = await create_fantasy_assistant(
        llm_api_key=os.getenv('OPENAI_API_KEY', 'your-api-key-here'),
        enable_llm=True
    )
    
    # Create sample data
    players = create_sample_players()
    constraints = create_sample_constraints()
    
    # Perform multiple operations to generate performance data
    for i in range(3):
        result = await assistant.optimize_lineup(
            players=players,
            constraints=constraints,
            strategy=OptimizationStrategy.BALANCED
        )
        
        # Ask a few questions
        await assistant.ask_question("Explain this lineup")
        await assistant.ask_question("What are the risks?")
    
    # Get performance statistics
    stats = assistant.get_performance_stats()
    
    print("Performance Statistics:")
    print(f"Session duration: {stats['session_stats']['session_duration_minutes']:.2f} minutes")
    print(f"Optimizations performed: {stats['session_stats']['optimizations_performed']}")
    print(f"Interactions handled: {stats['session_stats']['interactions_handled']}")
    print(f"Average optimization time: {stats['session_stats']['average_optimization_time']:.2f} seconds")
    print(f"Average interaction time: {stats['session_stats']['average_interaction_time']:.2f} seconds")
    
    print(f"\nOptimizer Stats:")
    print(f"Success rate: {stats['optimizer_stats']['success_rate']:.2f}")
    print(f"LLM enhancement rate: {stats['optimizer_stats']['llm_enhancement_rate']:.2f}")
    print(f"Math-only fallback rate: {stats['optimizer_stats']['math_only_fallback_rate']:.2f}")
    
    print(f"\nInteraction Stats:")
    print(f"Success rate: {stats['interaction_stats']['success_rate']:.2f}")
    print(f"Average response time: {stats['interaction_stats']['average_response_time']:.2f} seconds")


async def configuration_example():
    """Example of configuration management."""
    print("\n=== Configuration Example ===")
    
    # Get current configuration
    config = get_config()
    
    print("Current Configuration:")
    config_dict = config.to_dict()
    
    # Print key configuration items
    print(f"Environment: {config_dict['environment']}")
    print(f"LLM Model: {config_dict['llm']['model']}")
    print(f"LLM Temperature: {config_dict['llm']['temperature']}")
    print(f"Max Workers: {config_dict['optimization']['max_workers']}")
    print(f"Genetic Algorithm: {config_dict['optimization']['use_genetic_algorithm']}")
    print(f"LLM Enhancement: {config_dict['feature_flags']['enable_llm_enhancement']}")
    
    # Validate configuration
    issues = config.validate()
    if issues:
        print(f"\nConfiguration Issues:")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("\nConfiguration is valid!")


async def main():
    """Run all examples."""
    print("Fantasy Football Hybrid Optimizer Examples")
    print("=" * 50)
    
    try:
        # Run examples
        await basic_optimization_example()
        await interactive_questioning_example()
        await strategy_comparison_example()
        await edge_case_analysis_example()
        await performance_monitoring_example()
        await configuration_example()
        
        print("\n" + "=" * 50)
        print("All examples completed successfully!")
        
    except Exception as e:
        print(f"Example failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Set up environment variables for testing
    if not os.getenv('OPENAI_API_KEY'):
        print("Warning: OPENAI_API_KEY not set. LLM features will be disabled.")
        print("Set OPENAI_API_KEY environment variable to enable LLM features.")
    
    # Run examples
    asyncio.run(main())