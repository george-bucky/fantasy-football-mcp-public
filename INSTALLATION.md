# Installation Guide

## Prerequisites

- Python 3.9 or higher
- Claude Desktop application
- Yahoo Fantasy Sports account
- Git

## Step 1: Clone Repository

```bash
git clone https://github.com/derekrbreese/fantasy-football-mcp-public.git
cd fantasy-football-mcp-public
```

## Step 2: Install Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

## Step 3: Yahoo API Setup

### Create Yahoo Developer App

1. Go to https://developer.yahoo.com/apps/
2. Click "Create an App"
3. Configure:
   - **Application Name**: Your choice (e.g., "My Fantasy Football App")
   - **Application Type**: Installed Application
   - **Redirect URI**: `http://localhost:8000/callback`
   - **API Permissions**: Fantasy Sports - Read
4. Save your **Client ID** and **Client Secret**

### Configure Environment

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

2. Edit `.env` with your Yahoo credentials:
```env
YAHOO_CLIENT_ID=your_client_id_here
YAHOO_CLIENT_SECRET=your_client_secret_here
```

### Authenticate

Run the authentication script:
```bash
python utils/setup_yahoo_auth.py
```

This will:
1. Open your browser for Yahoo login
2. Generate access and refresh tokens
3. Update your `.env` file

## Step 4: Configure Claude Desktop

### Find Config File Location

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### Add MCP Server Configuration

Edit the config file and add:

```json
{
  "mcpServers": {
    "fantasy-football": {
      "command": "python",
      "args": [
        "/absolute/path/to/fantasy_football_multi_league.py"
      ],
      "env": {
        "YAHOO_ACCESS_TOKEN": "your_access_token",
        "YAHOO_REFRESH_TOKEN": "your_refresh_token",
        "YAHOO_CONSUMER_KEY": "your_consumer_key",
        "YAHOO_CONSUMER_SECRET": "your_consumer_secret",
        "YAHOO_GUID": "your_yahoo_guid"
      }
    }
  }
}
```

### Get Your Credentials

After running `setup_yahoo_auth.py`, find your credentials in `.env`:
- YAHOO_ACCESS_TOKEN
- YAHOO_REFRESH_TOKEN
- YAHOO_CONSUMER_KEY (same as CLIENT_ID)
- YAHOO_CONSUMER_SECRET (same as CLIENT_SECRET)
- YAHOO_GUID (your Yahoo user ID)

## Step 5: Verify Installation

1. Restart Claude Desktop
2. Look for "fantasy-football" in the MCP tools list
3. Test with: "Show me my fantasy football leagues"

## Troubleshooting

### Token Expiration
Yahoo tokens expire hourly. The server auto-refreshes, but you can manually refresh:
```bash
python utils/refresh_token.py
```

### Connection Issues
- Verify Python path is correct in Claude config
- Check all environment variables are set
- Ensure `.env` file is in the project root

### No Leagues Showing
- Verify YAHOO_GUID is set correctly
- Ensure you have active leagues for current season
- Check token is valid

## Support

For issues, please check the [GitHub repository](https://github.com/derekrbreese/fantasy-football-mcp-public/issues).