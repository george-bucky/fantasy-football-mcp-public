# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Fantasy Football MCP (Model Context Protocol) server integrating Yahoo Fantasy Sports API with advanced lineup optimization. Uses Sleeper API for expert rankings, defensive matchup analysis, and position-normalized FLEX decisions. Production server: `fantasy_football_multi_league.py`.

## Essential Commands

### Running & Testing
```bash
# Main MCP server
python fantasy_football_multi_league.py

# Run validation suite (tests model accuracy on historical data)
python tests_and_validation/run_validation.py

# Test borderline lineup decisions only
python tests_and_validation/run_real_decisions.py

# Test FLEX decision logic
python tests_and_validation/test_flex_decisions.py

# Analyze detailed FLEX performance
python tests_and_validation/analyze_flex_performance.py
```

### Token Management
```bash
python refresh_yahoo_token.py   # Refresh expired token (expires hourly)
python reauth_yahoo.py          # Full re-authentication
```

### Development
```bash
pip install -r requirements.txt
black . --line-length 100
pytest tests/ -v
```

## Architecture

### Core Optimization System

**Lineup Optimizer** (`lineup_optimizer.py`)
- Ultra-aggressive tier system: Elite (3x), Stud (2x), Solid (1.3x), Flex (1.0x), Bench (0.5x)
- Position normalization for FLEX decisions via `position_normalizer.py`
- Volatility/consistency scoring for floor vs ceiling strategies
- Week 17 rest adjustments for playoff teams

**Position Normalizer** (`position_normalizer.py`)
- Handles different scoring baselines: RB ~11pts, WR ~10pts, TE ~7pts
- Value Over Replacement (VOR) calculations
- FLEX value formula: `(VOR * scarcity * 0.3) + (projection * 0.7)`

**Matchup Analyzer** (`matchup_analyzer.py`)
- Sigmoid transformation with k=0.05 for matchup scores
- Non-linear scoring to differentiate elite/poor defenses

### Validation Framework (`tests_and_validation/`)
- Rolling holdout validation: train weeks 1-N, predict N+1
- Real decision validator: focuses on borderline calls only
- Current performance: 80.8% accuracy, +2.09 pts/decision, 91% efficiency

### Strategy Weights (Balanced)
```python
{
    "matchup": 0.10,   # Heavily reduced - player quality matters more
    "yahoo": 0.40,     # Trust expert projections
    "sleeper": 0.40,   # Trust expert projections
    "trending": 0.05,
    "momentum": 0.05
}
```

### FLEX Scoring
- 85% raw projection weight, 15% composite analysis
- Position normalization prevents TE trap
- Consistency bonuses for floor/ceiling strategies

### Draft Assistant System (`src/models/draft.py`, `src/agents/draft_evaluator.py`)
- **Multi-factor analysis**: VORP, scarcity, need, bye weeks, risk, upside
- **Strategy-based weighting**: Conservative (safety), Aggressive (upside), Balanced
- **Real-time recommendations**: Works during live drafts with current roster analysis
- **Statistical framework**: Value Over Replacement Player calculations and positional scarcity
- **Edge case handling**: Early/mid/late draft phases, positional runs, opportunity cost

## Critical Configuration

### Environment Variables (.env)
```env
YAHOO_CONSUMER_KEY=your_redacted_value
YAHOO_CONSUMER_SECRET=your_redacted_value
YAHOO_ACCESS_TOKEN=[current_token]
YAHOO_REFRESH_TOKEN=[current_refresh_token]
YAHOO_GUID=your_redacted_value  # Required for multi-league
```

### Yahoo API Response Patterns
```python
# Leagues
data["fantasy_content"]["users"]["0"]["user"][...]["leagues"]

# Teams - complex array structure
teams[key]["team"][0]  # List of dict elements
# Element 3: is_owned_by_current_login
# Element 23: managers list with GUIDs
```

### Cache TTLs (`yahoo_api_utils.py`)
- Leagues: 1 hour
- Standings: 5 minutes
- Matchups: 1 minute
- Players/stats: 15 minutes

## MCP Tools (13 Available)

**League**: `ff_get_leagues`, `ff_get_league_info`, `ff_get_standings`
**Team**: `ff_get_roster`, `ff_get_matchup`, `ff_get_optimal_lineup`
**Players**: `ff_get_players`, `ff_get_waiver_wire`, `ff_get_draft_rankings`
**Draft**: `ff_get_draft_recommendation`, `ff_analyze_draft_state`
**Admin**: `ff_get_draft_results`, `ff_refresh_token`

### Draft Tools Usage

**`ff_get_draft_recommendation`** - Live draft assistant
```python
# Get top 10 picks with balanced strategy
{
  "league_key": "461.l.900001",
  "strategy": "balanced",           # conservative, aggressive, balanced  
  "num_recommendations": 10,        # 1-20 recommendations
  "current_pick": 24               # optional overall pick number
}
```

**`ff_analyze_draft_state`** - Roster needs analysis  
```python
# Analyze current draft position and needs
{
  "league_key": "461.l.900001", 
  "strategy": "balanced"           # affects strategic advice
}
```

**Draft Strategies:**
- **Conservative**: Prioritize proven players, minimize risk
- **Aggressive**: Chase upside, target breakout candidates
- **Balanced**: Optimal mix of safety and upside potential

## Validation Results

Current model performance (2023 season validation):
- **80.8%** accuracy on borderline decisions
- **80%** FLEX decision accuracy (position-normalized)
- **+2.09** points per decision
- **91.2%** lineup efficiency
- **84%** precision on start/sit calls

Problem areas:
- Week 17 (players resting): 58% efficiency
- Some weeks show negative decision value (bench > starters)

## Common Issues

**Token Expiration (401 errors)**
- Tokens expire hourly
- Auto-refresh in `yahoo_api_call()`
- Manual: `python refresh_yahoo_token.py`

**Rate Limiting**
- Yahoo: 1000 req/hour limit
- Implemented: 900/hour sliding window
- Check via `ff_get_api_status` tool

**"Only showing one league"**
- Verify YAHOO_GUID in .env
- Test: `python test_all_leagues.py`

## Git Workflow

Current branch: `sleeper-api-integration`

Commit format:
```bash
git commit -m "type: Description

Details here

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"
```

## Active Leagues (2025)
1. Example League 1 (461.l.900001) - Team: BreesusChr1st
2. Example League 2 (461.l.900002)
3. Example League 3 (461.l.900003)
4. Example League 4 (461.l.900004)