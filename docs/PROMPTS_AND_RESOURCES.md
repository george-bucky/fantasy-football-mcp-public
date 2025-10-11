# MCP Prompts & Resources - Feature Summary

## Overview

Added comprehensive MCP prompts and resources to enable LLMs to provide better fantasy football advice through structured templates and contextual knowledge.

## What Was Added

### ✅ 8 New Prompt Templates

1. **`start_sit_decision`** - Start/sit decision making with confidence levels
   - Parameters: `league_key`, `position`, `player_names`, `week`
   - Analyzes: projections, matchups, trends, injuries, weather, usage, game script

2. **`bye_week_planning`** - Bye week planning and roster management
   - Parameters: `league_key`, `team_key`, `upcoming_weeks`
   - Provides: week-by-week action plan for bye week coverage

3. **`playoff_preparation`** - Championship preparation strategy
   - Parameters: `league_key`, `team_key`, `current_week`
   - Focuses on: playoff schedules, key acquisitions, handcuffs, weather considerations

4. **`trade_proposal_generation`** - Fair trade proposal creation
   - Parameters: `league_key`, `my_team_key`, `target_team_key`, `position_need`
   - Creates: 2-3 trade options with reasoning for both teams

5. **`injury_replacement_strategy`** - Comprehensive injury replacement plans
   - Parameters: `league_key`, `injured_player`, `injury_length`, `position`
   - Provides: short/long-term strategies, waiver targets, FAAB bids, timeline

6. **`streaming_dst_kicker`** - Weekly streaming recommendations
   - Parameters: `league_key`, `week`, `position` (DEF/K)
   - Analyzes: matchups, weather, Vegas lines, 2-3 week preview

7. **`season_long_strategy_check`** - Overall season assessment
   - Parameters: `league_key`, `team_key`, `current_record`, `weeks_remaining`
   - Evaluates: playoff probability, trade deadline strategy, must-win games

8. **`weekly_game_plan`** - Complete weekly game plan
   - Parameters: `league_key`, `team_key`, `opponent_team_key`, `week`
   - Creates: full action plan with lineup, start/sit, opponent analysis, waiver claims

### ✅ 5 New Resource Guides

1. **`guide://weekly-strategy`** - Week-by-week strategic guidance
   - Covers: Weeks 1-4 (early season) through Weeks 15-17 (playoffs)
   - Includes: weekly task checklist for each phase of season

2. **`guide://common-mistakes`** - Common fantasy football mistakes
   - Categories: Draft, In-season, Waiver wire, Trade, Lineup, Strategic
   - Provides: ❌ Mistakes to avoid and ✅ Best practices

3. **`guide://advanced-stats`** - Advanced statistics glossary
   - Covers: Volume metrics, efficiency metrics, situation metrics, opportunity metrics
   - Examples: Snap %, target share, YPRR, air yards, game script, red zone touches

4. **`guide://playoff-strategies`** - Championship preparation tactics
   - Covers: Roster construction, schedule analysis, positional strategy
   - Includes: Week 17 rest considerations, weather impact, streaming strategies

5. **`guide://dynasty-keeper`** - Dynasty and keeper league strategies
   - Covers: Valuation differences, rookie drafts, aging curves, trade windows
   - Includes: Contender vs rebuilder strategies, keeper value calculations

### ✅ Existing Features (Already Present)

**Prompts:**
- `analyze_roster_strengths`
- `draft_strategy_advice`
- `matchup_analysis`
- `waiver_wire_priority`
- `trade_evaluation`

**Resources:**
- `config://scoring` - Standard/PPR scoring rules
- `config://positions` - Position requirements
- `config://strategies` - Draft strategies
- `data://injury-status` - Injury designation guide
- `guide://tool-selection` - Tool usage guide for LLMs
- `meta://version` - Server version info

## Total Count

- **13 Prompt Templates** (5 existing + 8 new)
- **11 Resource Guides** (6 existing + 5 new)

## Updated Files

1. **`fastmcp_server.py`**
   - Added 8 new `@server.prompt` decorated functions
   - Added 5 new `@server.resource` decorated functions
   - Updated `__all__` export list with all new prompts and resources
   - Total additions: ~580 lines

2. **`CLAUDE.md`**
   - Added comprehensive "MCP Prompts & Resources" section
   - Documents all available prompts and resources
   - Includes usage examples and benefits for LLMs
   - Total additions: ~90 lines

## How LLMs Use These

### Prompts
Prompts provide structured templates that guide LLMs to:
- Ask the right questions
- Consider all relevant factors
- Provide consistent output formats
- Include confidence levels and reasoning

Example usage flow:
```
User: "Should I start Derrick Henry or Najee Harris?"
↓
LLM uses start_sit_decision prompt
↓
LLM asks for: projections, matchups, trends, injuries, weather, etc.
↓
LLM provides: structured recommendation with confidence level
```

### Resources
Resources provide domain knowledge that LLMs can reference:
- Scoring rules (understand point values)
- Position requirements (roster construction)
- Strategy frameworks (best practices)
- Common mistakes (pitfalls to avoid)
- Advanced metrics (stat interpretations)

Example usage flow:
```
User: "What's a good target share for a WR1?"
↓
LLM accesses guide://advanced-stats resource
↓
LLM knows: "20%+ is WR1 territory, 25%+ is elite"
↓
LLM provides: informed answer with context
```

## Benefits

1. **Consistency** - All LLMs get the same structured approach
2. **Completeness** - Prompts ensure no factors are overlooked
3. **Context** - Resources provide domain expertise without training
4. **Quality** - Better recommendations through better frameworks
5. **Scalability** - Easy to add new prompts/resources as needed

## Testing

✅ Python syntax validation passed
✅ 13 prompt templates detected and validated
✅ 11 resource guides present and accessible
✅ Updated `__all__` export list
✅ Documentation updated in CLAUDE.md

## Next Steps (Optional Future Enhancements)

- Add more sport-specific prompts (NFL team analysis, schedule strength)
- Create position-specific resource guides (RB strategies, WR route concepts)
- Add dynasty-specific prompts (rookie draft recommendations, trade calculator)
- Create league format resources (Best Ball, DFS, Superflex strategies)
- Add historical data resources (ADP trends, breakout patterns)
