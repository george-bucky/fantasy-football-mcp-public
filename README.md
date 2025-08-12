# Fantasy Football MCP Server

A Model Context Protocol (MCP) server for Yahoo Fantasy Football integration with multi-league support, providing comprehensive fantasy football management through Claude Desktop.

## Features

- **Multi-League Support**: Automatically discovers and manages all your Yahoo Fantasy Football leagues
- **Complete League Management**: View standings, rosters, matchups, and free agents
- **Real-time Data**: Direct integration with Yahoo Fantasy Sports API
- **AI-Ready**: Designed for intelligent lineup recommendations and analysis
- **Production Ready**: Comprehensive error handling and robust authentication

## Available MCP Tools (11 Total)

### League Management
- `ff_get_leagues` - List all your fantasy football leagues
- `ff_get_league_info` - Get detailed information about a specific league (includes your team name)
- `ff_get_standings` - View current standings for any league

### Team Management  
- `ff_get_roster` - Get your team roster with team name and draft info
- `ff_get_matchup` - View matchup details for any week
- `ff_get_optimal_lineup` - Get AI lineup recommendations (with strategy options)

### Player Discovery
- `ff_get_players` - Browse available free agent players
- `ff_get_waiver_wire` - Find top waiver wire pickups with trending data
- `ff_get_draft_rankings` - Get pre-draft player rankings with ADP

### Draft & Admin
- `ff_get_draft_results` - View draft results with positions and grades
- `ff_refresh_token` - Refresh Yahoo API access token when expired

## Installation

For detailed step-by-step installation instructions, see **[INSTALLATION.md](INSTALLATION.md)**

### Quick Start

1. Clone this repository:
```bash
git clone https://github.com/derekrbreese/fantasy-football-mcp-public.git
cd fantasy-football-mcp
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run initial Yahoo authentication:
```bash
python reauth_yahoo.py
```

4. Configure Claude Desktop (see [INSTALLATION.md](INSTALLATION.md) for details)

## Configuration

### Environment Variables

Create a `.env` file with:

```env
# Yahoo API Credentials (required)
YAHOO_CONSUMER_KEY=your_consumer_key
YAHOO_CONSUMER_SECRET=your_consumer_secret
YAHOO_ACCESS_TOKEN=your_access_token
YAHOO_REFRESH_TOKEN=your_refresh_token
YAHOO_GUID=your_yahoo_guid
```

### Claude Desktop Configuration

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "fantasy-football": {
      "command": "python",
      "args": [
        "/path/to/fantasy_football_multi_league.py"
      ],
      "env": {
        "YAHOO_ACCESS_TOKEN": "your_token",
        "YAHOO_CONSUMER_KEY": "your_key",
        "YAHOO_CONSUMER_SECRET": "your_secret",
        "YAHOO_REFRESH_TOKEN": "your_refresh",
        "YAHOO_GUID": "your_guid"
      }
    }
  }
}
```

## Usage Examples

Once configured in Claude Desktop:

1. **View all leagues**: 
   - "Show me all my fantasy football leagues"
   - Returns all active leagues with keys

2. **Get standings**: 
   - "What are the standings in league 461.l.900001?"
   - Shows current rankings and records

3. **Check your roster**: 
   - "Show my roster in league 461.l.900001"
   - Lists all your players and positions

4. **View matchups**: 
   - "Show me my week 5 matchup in league 461.l.900001"
   - Displays matchup details

5. **Find free agents**: 
   - "Show available RBs in league 461.l.900001"
   - Lists top available players by position

## Project Structure

```
fantasy-football-mcp/
├── src/
│   ├── agents/           # Specialized agents
│   ├── models/           # Data models
│   ├── strategies/       # Lineup strategies
│   └── utils/           # Utilities
├── config/              # Configuration
├── tests/              # Test suite
├── fantasy_football_multi_league.py  # Main MCP server
├── requirements.txt    # Dependencies
└── .env.example       # Environment template
```

## Authentication Flow

1. Initial setup requires OAuth2 authentication with Yahoo
2. Access tokens are stored and automatically refreshed
3. GUID identifies your account across all leagues
4. Team detection uses both GUID and login status

## Development

### Running Tests
```bash
pytest tests/
```

### Testing the Server
```bash
python test_multi_league_server.py
```

## Security Notes

- Never commit `.env` files or API credentials
- Keep your Yahoo tokens secure
- Store tokens securely and never expose them
- Regularly rotate access tokens if needed

## Troubleshooting

### Only one league showing
- Ensure YAHOO_GUID is set in `.env`
- Verify all leagues are active for current season
- Check team ownership detection is working

### Authentication errors
- Verify Yahoo app settings match redirect URI
- Ensure tokens are current and valid
- Check Consumer Key/Secret are correct

## License

MIT

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute to this project.