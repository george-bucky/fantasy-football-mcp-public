"""
Enhanced prompts and resources for client LLM decision-making.

This module provides comprehensive prompts and resources that help the client LLM
make intelligent fantasy football decisions using the enhanced data from the MCP server.
"""

import json
from typing import Dict, Any, List
from fastmcp import FastMCP

# Import the enhanced server
from enhanced_mcp_tools import enhanced_server


@enhanced_server.prompt
def lineup_optimization_analysis(
    league_key: str, 
    team_key: str, 
    week: int,
    strategy_preference: str = "balanced"
) -> str:
    """Generate a comprehensive prompt for lineup optimization analysis."""
    return f"""You are a championship-level fantasy football analyst. Analyze the lineup optimization for team {team_key} in league {league_key} for Week {week}.

**YOUR MISSION:**
Provide intelligent lineup recommendations using the enhanced data from the MCP server tools.

**ANALYSIS FRAMEWORK:**

1. **DATA GATHERING** (Use these tools in order):
   - ff_get_decision_context - Get league settings, opponent, standings context
   - ff_get_enhanced_roster - Get comprehensive player data with projections, matchups, trends
   - ff_analyze_lineup_options - Get multiple strategy analyses (balanced, aggressive, conservative)

2. **COMPREHENSIVE ANALYSIS:**
   - **Player Evaluation**: Analyze each player's projections, matchup score, trending data, injury status
   - **Strategy Assessment**: Compare different lineup strategies and their risk/reward profiles
   - **Context Integration**: Consider opponent strength, playoff implications, weather, injuries
   - **Market Intelligence**: Factor in ownership percentages, trending adds, contrarian opportunities

3. **DECISION FACTORS:**
   - **Elite/Stud Players**: Must-start regardless of matchup (tier 1-2)
   - **Matchup Analysis**: Favorable matchups for mid-tier players (matchup score 70+)
   - **Risk Management**: Balance upside potential with floor projections
   - **Leverage Opportunities**: Identify contrarian plays for tournament leverage
   - **Injury Considerations**: Assess injury risk and have backup plans

4. **RECOMMENDATION STRUCTURE:**
   - **Primary Recommendation**: Best lineup with clear reasoning
   - **Alternative Options**: 2-3 alternative approaches with trade-offs
   - **Key Insights**: 3-5 critical factors driving the decision
   - **Risk Assessment**: Overall risk level and mitigation strategies
   - **Contingency Plans**: What to do if key players are ruled out

**STRATEGY PREFERENCE:** {strategy_preference}

**CRITICAL REQUIREMENTS:**
- Use ALL available data from the enhanced tools
- Provide specific reasoning for each player selection
- Consider both weekly and season-long implications
- Address potential edge cases and concerns
- Give actionable advice with clear next steps

**OUTPUT FORMAT:**
Provide a structured analysis with clear sections for each component above. Be specific, data-driven, and actionable."""


@enhanced_server.prompt
def player_comparison_analysis(
    league_key: str,
    player_names: List[str],
    comparison_context: str = "lineup_decision"
) -> str:
    """Generate a prompt for detailed player comparison analysis."""
    return f"""You are analyzing {len(player_names)} players for a {comparison_context} in league {league_key}.

**PLAYERS TO COMPARE:** {', '.join(player_names)}

**ANALYSIS FRAMEWORK:**

1. **DATA GATHERING:**
   - Use ff_compare_players to get comprehensive comparison data
   - Use ff_get_decision_context for league and matchup context

2. **COMPARISON FACTORS:**
   - **Projections**: Consensus projections and confidence levels
   - **Matchups**: Opponent difficulty and opportunity assessment
   - **Trending**: Market sentiment and recent activity
   - **Injury Risk**: Current status and probability of playing
   - **Ownership**: Public ownership and leverage potential
   - **Value**: Cost vs expected production
   - **Consistency**: Floor vs ceiling projections
   - **Upside**: Breakout potential and ceiling

3. **CONTEXTUAL ANALYSIS:**
   - **League Settings**: Scoring system impact on player values
   - **Opponent Strength**: How matchup affects each player
   - **Team Needs**: Positional requirements and depth
   - **Strategy Fit**: How each player fits the overall approach

4. **DECISION FRAMEWORK:**
   - **Primary Factors**: Projections and matchups (70% weight)
   - **Secondary Factors**: Trending, injury risk, ownership (20% weight)
   - **Tiebreakers**: Value, consistency, upside (10% weight)

**RECOMMENDATION REQUIREMENTS:**
- Rank players with clear reasoning
- Identify the best choice and why
- Highlight key differentiators
- Address potential concerns
- Provide contingency options

**OUTPUT FORMAT:**
Provide a ranked comparison with detailed analysis for each player and a clear recommendation."""


@enhanced_server.prompt
def what_if_scenario_analysis(
    league_key: str,
    scenario_description: str,
    scenario_type: str = "player_substitution"
) -> str:
    """Generate a prompt for what-if scenario analysis."""
    return f"""You are analyzing a "what if" scenario for league {league_key}.

**SCENARIO:** {scenario_description}
**SCENARIO TYPE:** {scenario_type}

**ANALYSIS FRAMEWORK:**

1. **CURRENT STATE ANALYSIS:**
   - Use ff_analyze_lineup_options to understand current lineup
   - Use ff_get_decision_context for current context

2. **SCENARIO IMPACT ANALYSIS:**
   - Use ff_what_if_analysis to model the scenario
   - Compare current vs proposed state
   - Quantify the impact (points, risk, upside)

3. **EVALUATION CRITERIA:**
   - **Point Impact**: Expected change in projected points
   - **Risk Impact**: How scenario affects risk profile
   - **Upside Impact**: Change in ceiling potential
   - **Context Fit**: How scenario fits current situation
   - **Opportunity Cost**: What you give up vs gain

4. **DECISION FRAMEWORK:**
   - **Quantitative Analysis**: Point projections and statistical impact
   - **Qualitative Analysis**: Strategic fit and risk assessment
   - **Contextual Analysis**: League situation and opponent factors
   - **Alternative Analysis**: Other options to consider

**SCENARIO TYPES:**
- **Player Substitution**: Replacing one player with another
- **Strategy Change**: Switching from balanced to aggressive/conservative
- **Constraint Change**: Modifying salary cap or roster requirements

**RECOMMENDATION REQUIREMENTS:**
- Clear recommendation (proceed/avoid/modify)
- Quantified impact assessment
- Risk/reward analysis
- Alternative considerations
- Implementation guidance

**OUTPUT FORMAT:**
Provide a structured analysis with impact assessment, recommendation, and clear reasoning."""


@enhanced_server.prompt
def weekly_strategy_planning(
    league_key: str,
    week: int,
    team_key: str
) -> str:
    """Generate a prompt for comprehensive weekly strategy planning."""
    return f"""You are developing a comprehensive weekly strategy for team {team_key} in league {league_key} for Week {week}.

**STRATEGIC PLANNING FRAMEWORK:**

1. **SITUATIONAL ASSESSMENT:**
   - Use ff_get_decision_context for league standings, opponent, playoff implications
   - Assess week importance and strategic priorities
   - Evaluate team's current position and needs

2. **ROSTER ANALYSIS:**
   - Use ff_get_enhanced_roster for comprehensive player evaluation
   - Identify strengths, weaknesses, and opportunities
   - Assess injury risks and backup options

3. **OPPONENT ANALYSIS:**
   - Analyze opponent's roster and recent performance
   - Identify matchup advantages and disadvantages
   - Consider opponent's likely strategy

4. **MARKET OPPORTUNITIES:**
   - Use ff_get_waiver_wire for available upgrades
   - Identify trending players and contrarian opportunities
   - Assess trade possibilities

5. **STRATEGY SELECTION:**
   - Use ff_analyze_lineup_options to compare strategies
   - Choose approach based on situation and risk tolerance
   - Develop contingency plans

**STRATEGIC CONSIDERATIONS:**
- **Early Season (Weeks 1-4)**: Focus on season-long value and player evaluation
- **Mid Season (Weeks 5-10)**: Balance weekly wins with long-term strategy
- **Playoff Push (Weeks 11-14)**: Prioritize weekly wins and playoff positioning
- **Playoffs (Weeks 15-17)**: All-in approach with maximum upside

**DECISION PRIORITIES:**
1. **Must-Start Players**: Elite/stud players regardless of matchup
2. **Favorable Matchups**: Mid-tier players with good matchups
3. **Contrarian Plays**: Low-owned players with upside for leverage
4. **Risk Management**: Injury concerns and backup plans
5. **Context Factors**: Weather, game script, playoff implications

**OUTPUT REQUIREMENTS:**
- **Primary Strategy**: Recommended approach with reasoning
- **Lineup Construction**: Specific player recommendations
- **Key Decisions**: Critical choices and trade-offs
- **Risk Assessment**: Potential concerns and mitigation
- **Contingency Plans**: Backup options for various scenarios
- **Action Items**: Specific steps to implement the strategy

**OUTPUT FORMAT:**
Provide a comprehensive weekly strategy with clear sections for each component above."""


@enhanced_server.prompt
def trade_evaluation_analysis(
    league_key: str,
    trade_proposal: str,
    team_key: str
) -> str:
    """Generate a prompt for trade evaluation analysis."""
    return f"""You are evaluating a trade proposal for team {team_key} in league {league_key}.

**TRADE PROPOSAL:** {trade_proposal}

**EVALUATION FRAMEWORK:**

1. **CURRENT ROSTER ASSESSMENT:**
   - Use ff_get_enhanced_roster to understand current team strengths/weaknesses
   - Identify positional needs and depth issues
   - Assess current lineup construction

2. **TRADE IMPACT ANALYSIS:**
   - Use ff_compare_players to evaluate players involved
   - Analyze how trade affects lineup construction
   - Assess impact on team's overall strategy

3. **VALUE ASSESSMENT:**
   - Compare player values using projections, matchups, trends
   - Consider positional scarcity and replacement value
   - Evaluate long-term vs short-term impact

4. **STRATEGIC FIT:**
   - How trade aligns with team's current strategy
   - Impact on playoff positioning and championship odds
   - Consideration of league context and opponent strength

5. **ALTERNATIVE ANALYSIS:**
   - Other trade possibilities to consider
   - Waiver wire alternatives
   - Opportunity cost of the trade

**EVALUATION CRITERIA:**
- **Fairness**: Is the trade balanced in value?
- **Need**: Does it address team weaknesses?
- **Fit**: Does it improve the overall roster?
- **Timing**: Is this the right time for this trade?
- **Risk**: What are the potential downsides?

**RECOMMENDATION FRAMEWORK:**
- **Accept**: Trade is clearly beneficial
- **Reject**: Trade is not in team's best interest
- **Counter**: Suggest modifications to improve the trade
- **Negotiate**: Use as starting point for further discussion

**OUTPUT REQUIREMENTS:**
- Clear recommendation with reasoning
- Detailed analysis of each player involved
- Impact assessment on team construction
- Alternative options to consider
- Negotiation strategy if applicable

**OUTPUT FORMAT:**
Provide a structured trade evaluation with clear recommendation and detailed reasoning."""


# Enhanced Resources for Client LLM Context

@enhanced_server.resource("strategy://decision-framework")
def get_decision_framework() -> str:
    """Provide comprehensive decision-making framework for fantasy football."""
    return """Fantasy Football Decision-Making Framework for LLMs:

**CORE PRINCIPLES:**
1. **Data-Driven Decisions**: Always use comprehensive data from MCP tools
2. **Context-Aware Analysis**: Consider league settings, opponent, situation
3. **Risk-Adjusted Thinking**: Balance upside potential with floor projections
4. **Strategic Flexibility**: Adapt approach based on circumstances
5. **Long-term Perspective**: Consider both weekly and season-long implications

**DECISION HIERARCHY:**
1. **Elite/Stud Players (Tier 1-2)**: Must-start regardless of matchup
2. **Favorable Matchups**: Mid-tier players with matchup score 70+
3. **Contrarian Opportunities**: Low-owned players with upside for leverage
4. **Risk Management**: Injury concerns and backup plans
5. **Context Factors**: Weather, game script, playoff implications

**ANALYSIS FRAMEWORK:**
- **Quantitative**: Projections, matchups, trends, ownership data
- **Qualitative**: Player tiers, injury status, team situation
- **Contextual**: League settings, opponent strength, playoff race
- **Strategic**: Risk tolerance, upside potential, leverage opportunities

**TOOL USAGE PATTERNS:**
1. **ff_get_decision_context**: Always start here for situational awareness
2. **ff_get_enhanced_roster**: Get comprehensive player data
3. **ff_analyze_lineup_options**: Compare different strategies
4. **ff_compare_players**: Evaluate specific player decisions
5. **ff_what_if_analysis**: Model scenario impacts

**COMMON DECISION SCENARIOS:**
- **Lineup Optimization**: Use enhanced roster + lineup analysis tools
- **Player Comparisons**: Use compare players tool with context
- **Trade Evaluations**: Use roster analysis + player comparison
- **Waiver Decisions**: Use waiver wire + trending data
- **Strategy Changes**: Use what-if analysis for impact assessment

**RED FLAGS TO WATCH:**
- Players with injury status "Doubtful" or "Out"
- Matchup scores below 30 (very difficult matchups)
- High ownership (50%+) in tournament formats
- Weather concerns affecting passing games
- Game script concerns (blowout potential)

**SUCCESS METRICS:**
- Consistent weekly point production
- Effective risk management
- Strategic flexibility and adaptation
- Long-term roster building
- Playoff positioning and championship odds"""


@enhanced_server.resource("data://player-evaluation-criteria")
def get_player_evaluation_criteria() -> str:
    """Provide detailed criteria for player evaluation."""
    return """Player Evaluation Criteria for Fantasy Football:

**PROJECTION ANALYSIS:**
- **Consensus Projection**: Average of Yahoo and Sleeper projections
- **Confidence Level**: Based on data quality and consistency
- **Floor vs Ceiling**: Range of possible outcomes
- **Recent Performance**: Last 3-4 games trend analysis

**MATCHUP EVALUATION:**
- **Matchup Score**: 0-100 scale (70+ = favorable, 30- = difficult)
- **Defense Ranking**: Opponent's defense vs player's position
- **Game Script**: Expected game flow and pace
- **Weather Impact**: Wind, rain, temperature effects

**TRENDING ANALYSIS:**
- **Adds/Drops**: Recent waiver wire activity
- **Market Sentiment**: Public opinion and buzz
- **Injury Reports**: Status updates and probability
- **Role Changes**: Increased/decreased opportunity

**VALUE ASSESSMENT:**
- **Cost vs Production**: Salary/price relative to projections
- **Positional Scarcity**: Availability of similar players
- **Replacement Value**: Next best available option
- **Opportunity Cost**: What you give up to acquire/start

**RISK EVALUATION:**
- **Injury Risk**: Historical injury patterns and current status
- **Consistency**: Variance in weekly performance
- **Upside Potential**: Breakout and ceiling scenarios
- **Floor Protection**: Minimum expected production

**CONTEXTUAL FACTORS:**
- **Team Situation**: Offensive system and game plan
- **Opponent Strength**: Quality of opposing defense
- **Game Environment**: Home/away, weather, crowd
- **Playoff Implications**: Week importance and strategy

**TIER CLASSIFICATION:**
- **Elite (Tier 1)**: Must-start regardless of matchup
- **Stud (Tier 2)**: Start in most situations
- **Solid (Tier 3)**: Start with good matchups
- **Flex (Tier 4)**: Situational starts
- **Bench (Tier 5)**: Deep bench or streaming options

**DECISION MATRIX:**
- **High Projection + Good Matchup**: Strong start
- **High Projection + Bad Matchup**: Consider alternatives
- **Low Projection + Good Matchup**: Situational start
- **Low Projection + Bad Matchup**: Avoid or bench"""


@enhanced_server.resource("strategy://weekly-planning-guide")
def get_weekly_planning_guide() -> str:
    """Provide comprehensive weekly planning guide."""
    return """Weekly Fantasy Football Planning Guide:

**EARLY WEEK (Tuesday-Wednesday):**
1. **Injury Assessment**: Check injury reports and practice participation
2. **Matchup Analysis**: Review opponent strength and game script
3. **Trending Review**: Monitor waiver wire activity and market sentiment
4. **Strategy Selection**: Choose approach based on situation

**MID WEEK (Thursday-Friday):**
1. **Lineup Construction**: Build optimal lineup using enhanced data
2. **Contingency Planning**: Prepare backup options for injury concerns
3. **Weather Monitoring**: Check game-day weather forecasts
4. **Final Adjustments**: Make last-minute optimizations

**GAME DAY (Sunday):**
1. **Inactive Reports**: Check final injury status and inactive lists
2. **Weather Updates**: Monitor any last-minute weather changes
3. **Lineup Finalization**: Make final lineup decisions
4. **Live Monitoring**: Track games and adjust if needed

**WEEKLY STRATEGY SELECTION:**
- **Conservative**: Focus on high-floor, consistent players
- **Balanced**: Mix of safe picks and upside plays
- **Aggressive**: Target high-upside, contrarian players
- **Contrarian**: Low-owned players for tournament leverage

**SITUATIONAL FACTORS:**
- **Early Season**: Focus on player evaluation and season-long value
- **Mid Season**: Balance weekly wins with long-term strategy
- **Playoff Push**: Prioritize weekly wins and playoff positioning
- **Playoffs**: All-in approach with maximum upside

**KEY DECISION POINTS:**
1. **Elite Player Management**: Start studs regardless of matchup
2. **Matchup Exploitation**: Target favorable matchups for mid-tier players
3. **Contrarian Opportunities**: Identify low-owned players with upside
4. **Risk Management**: Balance upside potential with injury concerns
5. **Context Integration**: Consider opponent, weather, and situation

**SUCCESS FACTORS:**
- **Data Utilization**: Use all available enhanced data
- **Strategic Flexibility**: Adapt approach based on circumstances
- **Risk Awareness**: Understand and manage downside risk
- **Opportunity Recognition**: Identify and exploit market inefficiencies
- **Long-term Thinking**: Balance weekly and season-long goals"""


@enhanced_server.resource("meta://enhanced-tool-usage")
def get_enhanced_tool_usage_guide() -> str:
    """Provide comprehensive guide for using enhanced MCP tools."""
    return json.dumps({
        "title": "Enhanced Fantasy Football Tool Usage Guide",
        "description": "Comprehensive guide for LLMs on optimal usage of enhanced fantasy football tools",
        "tool_hierarchy": {
            "foundation_tools": [
                "ff_get_decision_context - Always start here for situational awareness",
                "ff_get_enhanced_roster - Get comprehensive player data with context"
            ],
            "analysis_tools": [
                "ff_analyze_lineup_options - Compare different lineup strategies",
                "ff_compare_players - Evaluate specific player decisions",
                "ff_what_if_analysis - Model scenario impacts and alternatives"
            ],
            "specialized_tools": [
                "ff_get_waiver_wire - Identify available upgrades",
                "ff_analyze_reddit_sentiment - Gauge market sentiment",
                "ff_get_matchup - Analyze opponent and weekly context"
            ]
        },
        "workflow_patterns": {
            "lineup_optimization": [
                "1. ff_get_decision_context (situational awareness)",
                "2. ff_get_enhanced_roster (comprehensive player data)",
                "3. ff_analyze_lineup_options (strategy comparison)",
                "4. ff_compare_players (specific decisions)",
                "5. ff_what_if_analysis (scenario modeling)"
            ],
            "player_evaluation": [
                "1. ff_get_enhanced_roster (player data)",
                "2. ff_compare_players (direct comparison)",
                "3. ff_get_decision_context (league context)",
                "4. ff_what_if_analysis (impact assessment)"
            ],
            "trade_analysis": [
                "1. ff_get_enhanced_roster (current roster)",
                "2. ff_compare_players (trade evaluation)",
                "3. ff_get_decision_context (team needs)",
                "4. ff_what_if_analysis (trade impact)"
            ]
        },
        "data_utilization": {
            "enhanced_player_data": {
                "projections": "Use consensus projections for primary decisions",
                "matchups": "Matchup scores 70+ = favorable, 30- = difficult",
                "trending": "High trending scores indicate market interest",
                "injury_status": "Monitor injury probability and status",
                "ownership": "Consider ownership for leverage opportunities",
                "tiers": "Elite/stud players must-start regardless of matchup"
            },
            "contextual_factors": {
                "league_settings": "Scoring system affects player values",
                "opponent_analysis": "Consider opponent strength and strategy",
                "playoff_implications": "Week importance affects strategy",
                "weather_conditions": "Monitor weather impact on games",
                "injury_reports": "Check practice participation and status"
            }
        },
        "decision_framework": {
            "primary_factors": {
                "projections": "Consensus projections with confidence levels",
                "matchups": "Opponent difficulty and opportunity assessment",
                "player_tiers": "Elite/stud players must-start"
            },
            "secondary_factors": {
                "trending": "Market sentiment and recent activity",
                "injury_risk": "Current status and probability of playing",
                "ownership": "Public ownership and leverage potential"
            },
            "tiebreakers": {
                "value": "Cost vs expected production",
                "consistency": "Floor vs ceiling projections",
                "upside": "Breakout potential and ceiling"
            }
        },
        "best_practices": [
            "ALWAYS start with ff_get_decision_context for situational awareness",
            "USE ff_get_enhanced_roster for comprehensive player data",
            "COMPARE multiple strategies with ff_analyze_lineup_options",
            "EVALUATE specific decisions with ff_compare_players",
            "MODEL scenarios with ff_what_if_analysis",
            "CONSIDER all data points, not just projections",
            "BALANCE risk and reward in decision-making",
            "ADAPT strategy based on league context and situation"
        ],
        "common_mistakes": [
            "Ignoring matchup scores in favor of projections only",
            "Not considering injury risk and backup plans",
            "Overlooking ownership percentages for leverage",
            "Failing to adapt strategy based on league context",
            "Not using all available enhanced data",
            "Making decisions without considering alternatives",
            "Ignoring weather and game environment factors",
            "Not planning for contingency scenarios"
        ]
    })


# Export all prompts and resources
__all__ = [
    "lineup_optimization_analysis",
    "player_comparison_analysis", 
    "what_if_scenario_analysis",
    "weekly_strategy_planning",
    "trade_evaluation_analysis",
    "get_decision_framework",
    "get_player_evaluation_criteria",
    "get_weekly_planning_guide",
    "get_enhanced_tool_usage_guide"
]