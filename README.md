# Fantasy Football FastMCP Server

A Model Context Protocol (MCP) server for Yahoo Fantasy Football that now ships
with a single FastMCP entry point suitable for fastmcp.cloud deployments and
local development.

## Features

- **Multi-League Support** – Automatically discovers and manages every Yahoo
  Fantasy Football league associated with the authenticated account.
- **Complete League Operations** – Standings, rosters, matchups, waiver wire and
  draft tooling are all available through MCP tools.
- **FastMCP Native** – `fastmcp_server.py` exposes each capability with
  `@server.tool` decorators and runs over the HTTP transport by default.
- **Token Refresh Support** – Includes a tool for refreshing Yahoo OAuth tokens
  when access tokens expire.
- **Caching & Rate-Limit Visibility** – Tools to inspect and clear cached Yahoo
  responses for quick troubleshooting.

## Available MCP Tools

### League & Team Management
- `ff_get_leagues` – List all leagues tied to the authenticated Yahoo account.
- `ff_get_league_info` – Retrieve metadata and your team summary for a league.
- `ff_get_standings` – View league standings with wins, losses and points.
- `ff_get_roster` – Inspect roster details for the logged-in team or a specific
  team key.
- `ff_get_matchup` – Review matchup information for a given week.
- `ff_compare_teams` – Compare two teams' rosters inside a league.
- `ff_build_lineup` – Build optimal lineup using strategy-based optimization and
  positional constraints.

### Player Discovery & Draft
- `ff_get_players` – Browse current free agents with ownership context.
- `ff_get_waiver_wire` – Surface top waiver targets with Yahoo stats. (Default: 30 players for comprehensive analysis)
- `ff_get_draft_rankings` – Pull Yahoo pre-draft rankings and ADP data.
- `ff_get_draft_results` – Review draft positions, grades and summary by team.
- `ff_get_draft_recommendation` – Strategy-aware draft pick suggestions.
- `ff_analyze_draft_state` – Summarize positional needs and strategy during a
  draft.
- `ff_analyze_reddit_sentiment` – Gather public sentiment and injury chatter
  from Reddit for one or more players.

### Operations & Maintenance
- `ff_get_api_status` – Check cache metrics and Yahoo rate limiting state.
- `ff_clear_cache` – Clear cached Yahoo responses (optionally by pattern).
- `ff_refresh_token` – Refresh the Yahoo OAuth access token on demand.

## Installation

```bash
git clone https://github.com/derekrbreese/fantasy-football-mcp.git
cd fantasy-football-mcp
pip install -r requirements.txt
```

## Configuration

Create a `.env` file (or configure environment variables in your deployment)
with the Yahoo credentials:

```env
YAHOO_CONSUMER_KEY=your_consumer_key
YAHOO_CONSUMER_SECRET=your_consumer_secret
YAHOO_ACCESS_TOKEN=your_access_token
YAHOO_REFRESH_TOKEN=your_refresh_token
YAHOO_GUID=your_yahoo_guid
```

## Running Locally

1. Ensure the dependencies are installed and environment variables are set.
2. Start the FastMCP HTTP server:
   ```bash
   python fastmcp_server.py
   ```
3. Connect with any MCP-compatible client (e.g. Claude Desktop) using the HTTP
   transport: `http://localhost:8000`.

## Deploying to fastmcp.cloud

1. Push your repository to a Git host accessible from fastmcp.cloud.
2. Create a new service in fastmcp.cloud and point it at the repository.
3. Set the start command to `python fastmcp_server.py`.
4. Configure the required Yahoo environment variables in the deployment UI.
5. Expose port `8000` (or your chosen port) for the HTTP transport.

The compatibility shims (`render_server.py`, `cloud_run_server.py`,
`simple_mcp_server.py`, `no_auth_server.py`, and `app.py`) now delegate to
`fastmcp_server.py`, so existing deployment scripts can continue to import those
modules without modification.

## Testing

Run the full automated suite with:

```bash
pytest
```

The tests exercise each FastMCP tool wrapper and the HTTP runner while mocking
out remote Yahoo API calls to keep the suite fast and deterministic.

## Project Structure

```
fantasy-football-mcp/
├── fastmcp_server.py          # FastMCP entry point and tool definitions
├── fantasy_football_multi_league.py  # Legacy tool implementations
├── render_server.py / cloud_run_server.py / simple_mcp_server.py / no_auth_server.py / app.py
│   └── Compatibility shims that re-export the FastMCP server
├── requirements.txt           # Pinned dependencies
├── tests/                     # Pytest suite for FastMCP integration
├── src/                       # Supporting agents, models, and utilities
└── config/                    # Configuration helpers
```

## Authentication Flow

1. Authenticate with Yahoo once using `reauth_yahoo.py` or the included scripts.
2. Store credentials as environment variables for the server.
3. Use the `ff_refresh_token` tool whenever an access token expires to obtain a
   new one automatically.

## Troubleshooting

- **Only one league showing** – Verify `YAHOO_GUID` and ensure leagues are
  active in the current season.
- **Authentication errors** – Confirm tokens and consumer keys are correct and
  refresh tokens have not been revoked.
- **Stale results** – Use `ff_clear_cache` or inspect `ff_get_api_status` for
  cache hit rates and rate limiting signals.

## License

MIT
