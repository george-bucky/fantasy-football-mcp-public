# Fantasy Football MCP Server

A comprehensive Model Context Protocol (MCP) server for Yahoo Fantasy Football that provides intelligent lineup optimization, draft assistance, and league management through AI-powered tools.

## 🚀 Features

### Core Capabilities
- **Multi-League Support** – Automatically discovers and manages all Yahoo Fantasy Football leagues associated with your account
- **🆕 Player Enhancement Layer** – Intelligent projection adjustments with bye week detection, recent performance stats, and breakout/declining player flags
- **Intelligent Lineup Optimization** – Advanced algorithms considering matchups, expert projections, and position-normalized value
- **Draft Assistant** – Real-time draft recommendations with strategy-based analysis and VORP calculations
- **Comprehensive Analytics** – Reddit sentiment analysis, team comparisons, and performance metrics
- **Multiple Deployment Options** – FastMCP, traditional MCP, Docker, and cloud deployment support

### Advanced Analytics
- **Position Normalization** – Smart FLEX decisions accounting for different position baselines
- **Multi-Source Projections** – Combines Yahoo and Sleeper expert rankings with matchup analysis
- **Strategy-Based Optimization** – Conservative, aggressive, and balanced approaches
- **Volatility Scoring** – Floor vs ceiling analysis for consistent or boom-bust plays
- **Live Draft Support** – Real-time recommendations during active drafts

## 🆕 Player Enhancement Layer

The enhancement layer enriches player data with real-world context to fix stale projections and prevent common mistakes:

### Key Features

✅ **Bye Week Detection** – Automatically zeros projections and displays "BYE WEEK - DO NOT START" for players on bye, preventing accidental starts

✅ **Recent Performance Stats** – Fetches last 1-3 weeks of actual performance from Sleeper API and displays trends (L3W avg: X.X pts/game)

✅ **Performance Flags** – Intelligent alerts including:
- `BREAKOUT_CANDIDATE` – Recent performance > 150% of projection
- `TRENDING_UP` – Recent performance exceeds projection
- `DECLINING_ROLE` – Recent performance < 70% of projection
- `HIGH_CEILING` – Explosive upside potential
- `CONSISTENT` – Reliable, steady performance

✅ **Adjusted Projections** – Blends recent reality with stale projections for more accurate start/sit decisions (60/40 or 70/30 weighting based on confidence)

### Example

**Before Enhancement:**
```json
{
  "name": "Rico Dowdle",
  "sleeper_projection": 4.0,
  "recommendation": "Bench"
}
```

**After Enhancement:**
```json
{
  "name": "Rico Dowdle",
  "sleeper_projection": 4.0,
  "adjusted_projection": 14.8,
  "performance_flags": ["BREAKOUT_CANDIDATE", "TRENDING_UP"],
  "enhancement_context": "Recent breakout: averaging 18.5 pts over last 3 weeks",
  "recommendation": "Strong Start"
}
```

The enhancement layer is **non-breaking** and automatically applies to:
- `ff_get_roster` (with `include_external_data=True`)
- `ff_get_waiver_wire` (with `include_external_data=True`)
- `ff_get_players` (with `include_external_data=True`)
- `ff_build_lineup` (automatic)

## 🛠️ Available MCP Tools

### League & Team Management
- `ff_get_leagues` – List all leagues for your authenticated Yahoo account
- `ff_get_league_info` – Retrieve detailed league metadata and team information
- `ff_get_standings` – View current league standings with wins, losses, and points
- `ff_get_roster` – Inspect detailed roster information for any team
- `ff_get_matchup` – Analyze weekly matchup details and projections
- `ff_compare_teams` – Side-by-side team roster comparisons for trades/analysis
- `ff_build_lineup` – Generate optimal lineups using advanced optimization algorithms

### Player Discovery & Waiver Wire
- `ff_get_players` – Browse available free agents with ownership percentages
- `ff_get_waiver_wire` – Smart waiver wire targets with expert analysis (configurable count)
- `ff_get_draft_rankings` – Access Yahoo's pre-draft rankings and ADP data

### Draft Assistant Tools
- `ff_prepare_manual_draft` – Build and persist a Yahoo-free 2026 manual-draft value board from an explicit league profile
- `ff_get_draft_recommendation` – AI-powered draft pick suggestions with strategy analysis
- `ff_analyze_draft_state` – Real-time roster needs and positional analysis during drafts
- `ff_get_draft_results` – Post-draft analysis with grades and team summaries

### Optional 2026 Rookie-Year Outlook

Set `use_rookie_intelligence=true` on `ff_get_draft_recommendation`,
`ff_get_waiver_wire`, or `ff_build_lineup` to include the reviewed 2026 rookie
board. The board estimates first-season PPR value. It is not a weekly
projection and does not include opponent context.

- Draft and waiver decisions use the rookie board to order confirmed rookies
  against other confirmed rookies while keeping roster, injury, projection,
  news, and availability evidence visible.
- `rookie_only=true` waiver calls verify the complete paginated Yahoo available
  pool and the exact user team. Rookie-year tier remains primary; verified
  roster need and league-wide starter demand may reorder rookies only within a
  tier, with board rank as the final tie-breaker. Incomplete or stale league
  context returns no rookie-only recommendations instead of guessing.
- Lineup decisions use it only to break a rounded tie between otherwise equal,
  healthy weekly options. It never changes a player's weekly score.
- Player matching accepts only one exact normalized name-and-position match.
  Ordinary veterans are labeled as outside the current rookie board; missing or
  ambiguous identities are quarantined. Fuzzy matching is not used.
- Set `rookie_only=true` on draft recommendations or waivers to return only
  confirmed current-class rookies. This implies rookie intelligence and never
  falls back to veterans.

Normal redraft behavior is unchanged when these options are omitted.

### Yahoo-Free Manual Draft Board

`ff_prepare_manual_draft` prepares an independently useful preseason board without a
Yahoo league key, Yahoo credentials, or a live draft. Supply the full league profile
directly. For example, this is the 12-team Gotham profile with the 11th pick, two
W/R/T slots, no kicker, and its custom half-PPR bonuses:

```json
{
  "profile": {
    "profile_id": "gotham-2026",
    "season": 2026,
    "team_count": 12,
    "draft": {"type": "snake", "slot": 11},
    "roster_slots": {
      "QB": 1,
      "RB": 2,
      "WR": 2,
      "TE": 1,
      "W/R/T": 2,
      "DEF": 1,
      "BN": 5
    },
    "scoring": {
      "passing_yards": 0.04,
      "passing_touchdowns": 4,
      "interceptions": -2,
      "passing_40_yard_touchdowns": 1,
      "fumbles_lost": -2,
      "rushing_yards": 0.1,
      "rushing_touchdowns": 6,
      "receiving_yards": 0.1,
      "receiving_touchdowns": 6,
      "receptions": 0.5,
      "two_point_conversions": 2,
      "rushing_yard_milestones": {"100": 1, "150": 2, "200": 3},
      "receiving_yard_milestones": {"100": 1, "150": 2, "200": 3}
    }
  },
  "preview_limit": 25
}
```

Milestone values are mutually exclusive tier totals: 100 means 100-149 yards, 150
means 150-199 yards, and 200 means 200 or more yards. A 200-yard game earns the
configured 200-yard bonus only.

The board scores ESPN's raw 2026 season projections with the supplied rules, then
calculates FLEX-aware replacement levels and VORP. Its transparent 0-100 score uses
55% league-adjusted projection value, 25% current redraft ECR, 15% current 12-team
half-PPR ADP, and 5% structured availability context. Missing evidence is omitted and
the remaining weights are rebalanced; it is never silently scored as zero. ADP is
market-timing evidence rather than the primary ranking.

Sources are fetched independently with fixed endpoints, response limits, timeouts,
and local cache TTLs:

- ESPN's community-documented public fantasy endpoint supplies raw season stat
  projections (`statSourceId=1`, `statSplitTypeId=0`). Its applied total is used only
  for server-side ordering of the bounded active-player request, never for league
  scoring or board value.
- DynastyProcess's open-data `db_fpecr_latest.csv` supplies current FantasyPros
  redraft-overall ECR.
- Fantasy Football Calculator supplies current 12-team half-PPR ADP.
- Sleeper's public API supplies exact player identity, roster status, depth chart, and
  trending context. Sleeper projections are not used because its preseason projection
  feed returned empty rows during live testing.
- nflverse weekly player stats (CC BY 4.0) estimate milestone categories that are not
  directly projected, especially 150-yard games. Position-level fallbacks are labeled.

Exact normalized name, position, and team matches are used when those fields are
available. Ambiguous identities are quarantined; the service never fuzzy-guesses.
Every score component, source timestamp/checksum, estimate, unsupported scoring field,
coverage warning, and quarantine is returned for inspection.

A last-known-good snapshot is stored under `.cache/manual_draft/` and is reused after a
process restart or a provider outage. This directory is ignored by Git. Delete only the
specific profile snapshot if you intentionally want to discard it, or pass
`force_refresh=true` to bypass the in-memory/source caches. No draft picks or manual
drafted-player state are recorded in this PR.

### Optional Weekly Matchup Evidence

Set `use_matchup_evidence=true` on `ff_build_lineup` to add the current opponent
and a position-specific view of fantasy points allowed by that defense. The
feature uses nflverse schedules and weekly player statistics; it does not use
the old static Sleeper defensive rankings.

- Yahoo supplies the league season and current week. Sleeper is used for the
  current week only when Yahoo omits it and Sleeper reports the same season.
- Defensive strength is available only after all 32 defenses have at least four
  completed games in the selected scoring basis (`standard`, `half_ppr`, or
  `ppr`). Custom scoring receives schedule context only.
- Matchup evidence can only resolve an otherwise equal, positive, comparable
  weekly-score tie when the defensive-percentile gap is at least 12.5 points.
  It never changes either player's score. Bye, health, and attributed news risk
  remain more important, and the rookie outlook remains the final tie-breaker.
- If the source is incomplete, stale, invalid, unavailable, or the game has
  already started, the normal lineup still returns and matchup evidence cannot
  influence the selection.
- The response keeps this data in a separate `weekly_matchup_evidence` object,
  including source version, fetch time, availability reason, and tie-break
  audit. Behavior is unchanged when the option is omitted.

### Advanced Analytics
- `ff_analyze_reddit_sentiment` – Social media sentiment analysis for player buzz and injury updates
- `ff_get_player_news` – Recent RotoWire NFL RSS updates, optionally filtered by player (no credentials required)
- `ff_get_espn_nfl_news` – Broader ESPN NFL reporting and analysis from a public JSON endpoint (no credentials required)
- `ff_get_sportsbook_odds` – Read-only NFL player, team, and futures odds from PropLine
- `ff_get_api_status` – Monitor cache performance and Yahoo API rate limiting
- `ff_clear_cache` – Clear cached responses for fresh data (with pattern support)
- `ff_refresh_token` – Automatically refresh Yahoo OAuth tokens

### Optional PropLine Sportsbook Odds

Set `PROPLINE_API_KEY` to use `ff_get_sportsbook_odds` or the optional draft
enrichment. Sportsbook evidence is read-only and does not change draft
recommendations, projections, scores, or ordering.

For draft recommendations, set `include_sportsbook_odds=true`. The optional
`sportsbook_scope` accepts `auto`, `season`, or `next_game`, and
`sportsbook_shortlist_size` accepts 1-5 (default 5). The recommendation is
ranked and truncated first; only that final shortlist and its deduplicated NFL
teams are queried. Player and team results are returned separately in
`sportsbook_context`, with provider failures, ambiguous identities, and absent
markets reported in `sportsbook_warnings` without failing the recommendation.
Season futures and next-game markets retain their original scope and should not
be treated as equivalent projections. Omitting the option makes no PropLine
request.

- Provide at least one `players` or `teams` entry (up to 10 of each, with names
  no longer than 100 characters).
- Choose `scope="season"` for futures, `scope="next_game"` for upcoming-game
  odds, or the default `scope="auto"` for both.
- Optionally filter to as many as 10 `bookmakers`. Custom `markets` are also
  limited to 10, work only with `season` or `next_game`, and are rejected with
  `auto`. Market and bookmaker keys must be unique, nonempty, lowercase
  letters, numbers, or underscores (up to 64 characters). Next-game custom
  markets must be supported team or player markets.
- Player names and team aliases are matched exactly after normalization. The
  response reports unmatched or ambiguous queries instead of guessing.
- Requests use a 15-second overall limit, at most 16 upcoming events, and at
  most 500 normalized results. Event and next-game odds are cached for 60
  seconds; futures are cached for one hour.

Provider failures can return a partial response when another requested source
completed successfully. Rate limits are reported without automatic retries.

## 📦 Installation

### Quick Start
```bash
git clone https://github.com/derekrbreese/fantasy-football-mcp-public.git
cd fantasy-football-mcp-public
pip install -r requirements.txt
```

### Yahoo API Setup
1. Create a Yahoo Developer App at [developer.yahoo.com](https://developer.yahoo.com)
2. Note your Consumer Key (Client ID) and Consumer Secret (Client Secret)
3. Set up your `.env` file with these credentials
4. Complete OAuth flow using the included authentication scripts

## ⚙️ Configuration

Create a `.env` file with your API credentials:

```env
# Yahoo API Credentials (Required)
YAHOO_CLIENT_ID=your_consumer_key_here
YAHOO_CLIENT_SECRET=your_consumer_secret_here
YAHOO_ACCESS_TOKEN=your_access_token
YAHOO_REFRESH_TOKEN=your_refresh_token
YAHOO_GUID=your_yahoo_guid

# Reddit API Credentials (Optional - for sentiment analysis)
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USERNAME=your_reddit_username

# PropLine API Credentials (Optional - for sportsbook odds)
PROPLINE_API_KEY=your_propline_api_key_here
```

**Note**: Reddit and PropLine credentials are optional. Without them, their
respective sentiment and sportsbook-odds tools are unavailable; other features
continue to work. See [Reddit API Setup Guide](docs/REDDIT_API_SETUP.md) for
detailed Reddit instructions.

`ff_prepare_manual_draft` also requires no credentials. Yahoo credentials remain
required only for tools that read Yahoo leagues, rosters, waivers, or live draft state.

### Initial Authentication

**First-time setup:**
```bash
cd utils
python setup_yahoo_auth.py
```

**Re-authentication (if tokens expired):**
```bash
cd utils
python reauth_yahoo.py
```

**Token refresh (when access token expires):**
```bash
cd utils
python refresh_yahoo_token.py
```

The authentication scripts will:
- Open your browser for Yahoo OAuth authorization
- Automatically update your `.env` file (preserving existing variable line positions)
- Automatically update MCP config files (Claude Desktop, Cursor, Antigravity) if they exist
- Display confirmation messages

**Important**: After authentication or token refresh, restart your MCP client to use the new tokens.

## 🚀 Deployment Options

### Local Development (FastMCP)
```bash
python fastmcp_server.py
```
Connect via HTTP transport at `http://localhost:8000`

### Claude Code Integration (Stdio)
```bash
python fantasy_football_multi_league.py
```

### Docker Deployment
```bash
docker build -t fantasy-football-mcp .
docker run -p 8080:8080 --env-file .env fantasy-football-mcp
```

### Cloud Deployment (Render/Railway/etc.)
The server includes multiple compatibility layers for various cloud platforms:
- `render_server.py` - Render.com deployment
- `simple_mcp_server.py` - Generic HTTP/WebSocket server
- `fastmcp_server.py` - FastMCP cloud deployments

## 🧪 Testing

```bash
# Verify the local MCP installation (safe before Yahoo approval)
.venv/bin/python utils/verify_setup.py

# Run full test suite
pytest

# Test OAuth authentication
python tests/test_oauth.py

# Test MCP connection
python tests/test_mcp_client.py
```

## 📁 Project Structure

```
fantasy-football-mcp-public/
├── fastmcp_server.py              # FastMCP HTTP server implementation
├── fantasy_football_multi_league.py  # Main MCP stdio server
├── lineup_optimizer.py            # Advanced lineup optimization engine
├── matchup_analyzer.py           # Defensive matchup analysis
├── position_normalizer.py        # FLEX position value calculations
├── src/
│   ├── agents/                   # Specialized analysis agents
│   ├── models/                   # Data models for players, lineups, drafts
│   ├── strategies/              # Draft and lineup strategies
│   ├── services/                # Player enhancement and external integrations
│   └── utils/                   # Utility functions and configurations
├── tests/                       # Comprehensive test suite
├── utils/                       # Authentication and token management
└── requirements.txt             # Python dependencies
```

## 🔧 Advanced Configuration

### Strategy Weights (Balanced Default)
```python
{
    "yahoo": 0.40,     # Yahoo expert projections
    "sleeper": 0.40,   # Sleeper expert rankings
    "matchup": 0.10,   # Defensive matchup analysis
    "trending": 0.05,  # Player trending data
    "momentum": 0.05   # Recent performance
}
```

### Draft Strategies
- **Conservative**: Prioritize proven players, minimize risk
- **Aggressive**: Target high-upside breakout candidates
- **Balanced**: Optimal mix of safety and ceiling potential

### Position Scoring Baselines
- RB: ~11 points (standard scoring)
- WR: ~10 points (standard scoring)
- TE: ~7 points (standard scoring)
- FLEX calculations include position scarcity adjustments

## 📊 Performance Metrics

The optimization engine targets:
- **85%+** accuracy on start/sit decisions
- **+2.0** points per optimal decision on average
- **90%+** lineup efficiency vs. manual selection
- **Position-normalized FLEX** decisions to avoid TE traps

## 🔍 Troubleshooting

### Common Issues

**Authentication Errors**
```bash
# Refresh expired tokens (expire hourly)
cd utils
python refresh_yahoo_token.py

# Full re-authentication if refresh fails
cd utils
python reauth_yahoo.py

# Or first-time setup
cd utils
python setup_yahoo_auth.py
```

**Note**: All authentication scripts automatically update your `.env` file and MCP config files. After running any authentication script, restart your MCP client (Claude Desktop, Cursor, etc.) to use the new tokens.

**Only One League Showing**
- Verify `YAHOO_GUID` matches your Yahoo account
- Ensure leagues are active for current season
- Check team ownership detection in logs

**Rate Limiting**
- Yahoo allows 1000 requests/hour
- Server implements 900/hour safety limit
- Use `ff_get_api_status` to monitor usage
- Clear cache with `ff_clear_cache` if needed

**Stale Data**
- Cache TTLs: Leagues (1hr), Standings (5min), Players (15min)
- Force refresh with `ff_clear_cache` tool
- Check last update times in `ff_get_api_status`

## 🤝 Contributing

This is the public version of the Fantasy Football MCP Server. For contributing:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- Yahoo Fantasy Sports API for comprehensive league data
- Sleeper API for expert rankings and defensive analysis
- ESPN public fantasy data for raw preseason stat projections
- DynastyProcess and nflverse open data for redraft ECR and historical player stats
- Fantasy Football Calculator for 12-team half-PPR ADP
- Reddit API for player sentiment analysis
- Model Context Protocol (MCP) framework

---

**Note**: League tools require active Yahoo Fantasy Football leagues and valid
Yahoo API credentials. The standalone manual-draft and PropLine sportsbook-odds
tools do not; Yahoo-backed live draft enrichment still requires normal Yahoo draft
context. Ensure you have proper authorization before accessing provider data.
