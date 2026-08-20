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
- Lineup decisions use it only to break a rounded tie between otherwise equal,
  healthy weekly options. It never changes a player's weekly score.
- Player matching accepts only one exact normalized name-and-position match.
  Missing or ambiguous matches are shown as quarantined; fuzzy matching is not
  used.
- Set `rookie_only=true` on draft recommendations or waivers to return only
  confirmed current-class rookies. This implies rookie intelligence and never
  falls back to veterans.

Normal redraft behavior is unchanged when these options are omitted.

### Advanced Analytics
- `ff_analyze_reddit_sentiment` – Social media sentiment analysis for player buzz and injury updates
- `ff_get_player_news` – Recent RotoWire NFL RSS updates, optionally filtered by player (no credentials required)
- `ff_get_espn_nfl_news` – Broader ESPN NFL reporting and analysis from a public JSON endpoint (no credentials required)
- `ff_get_api_status` – Monitor cache performance and Yahoo API rate limiting
- `ff_clear_cache` – Clear cached responses for fresh data (with pattern support)
- `ff_refresh_token` – Automatically refresh Yahoo OAuth tokens

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
```

**Note**: Reddit credentials are optional. The app will work without them, but Reddit sentiment analysis features will be unavailable. See [Reddit API Setup Guide](docs/REDDIT_API_SETUP.md) for detailed instructions.

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
- Reddit API for player sentiment analysis
- Model Context Protocol (MCP) framework

---

**Note**: This server requires active Yahoo Fantasy Football leagues and valid API credentials. Ensure you have proper authorization before accessing league data.
