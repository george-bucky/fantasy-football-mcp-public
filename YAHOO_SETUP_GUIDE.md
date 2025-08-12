# Yahoo Fantasy Sports API - Complete Setup Guide

## ⚠️ The Reality of Yahoo's API

Yahoo's Fantasy Sports API is notoriously difficult to work with. Here's what you're dealing with:

1. **Non-standard OAuth2** - Yahoo doesn't follow OAuth2 specs exactly
2. **1-hour token expiration** - Tokens expire quickly and must be refreshed
3. **Complex permission model** - Fantasy data requires specific app permissions
4. **Poor documentation** - Yahoo's docs are outdated and incomplete
5. **Redirect URI strictness** - Must match EXACTLY what's registered

## 🔐 Step-by-Step Yahoo App Creation

### Step 1: Create Yahoo Account Requirements

Before starting, you need:
- A Yahoo account that's part of at least one fantasy league
- Access to create apps (some accounts are restricted)

### Step 2: Register Your App (The Tricky Part)

1. **Go to Yahoo App Dashboard**
   ```
   https://developer.yahoo.com/apps/
   ```
   
2. **Click "Create an App"**

3. **CRITICAL: Fill These Fields Correctly**
   
   ⚠️ **Application Name**: 
   - Must be unique across ALL Yahoo apps
   - Try: "YourName Fantasy Assistant 2024"
   - If taken, add random numbers

   ⚠️ **Application Type**:
   - Select: "Installed Application" (NOT Web Application!)
   
   ⚠️ **Redirect URI(s)**: 
   - For local development: `http://localhost:8090`
   - **NO HTTPS for localhost!** (Yahoo blocks it)
   - **NO trailing slash!**
   - This MUST match exactly in your code

   ⚠️ **API Permissions**:
   - Click "Fantasy Sports" → Then "Read"
   - Do NOT select "Read/Write" (more restrictive)
   
   ⚠️ **Description**:
   - Keep it simple: "Personal fantasy football assistant"

### Step 3: Get Your Credentials

After creation, you'll see:
- **Client ID (Consumer Key)**: Looks like `dj0yJmk9...`
- **Client Secret (Consumer Secret)**: Long random string

⚠️ **SAVE THESE IMMEDIATELY!** Yahoo doesn't show the secret again.

## 🛠️ Local Setup

### Step 1: Environment Configuration

Create `.env` file:
```bash
# EXACT format Yahoo expects
YAHOO_CLIENT_ID=your_client_id_here
YAHOO_CLIENT_SECRET=YourActualSecretHere

# MUST match your registered redirect URI exactly
YAHOO_REDIRECT_URI=http://localhost:8090

# Optional but recommended
YAHOO_CALLBACK_PORT=8090
YAHOO_CALLBACK_HOST=localhost
```

### Step 2: Test Authentication

```bash
cd fantasy-football-mcp
python examples/yahoo_auth_example.py auth
```

What should happen:
1. Browser opens to Yahoo login
2. You login and click "Allow"
3. Browser redirects to localhost:8090
4. Terminal shows "Authentication successful!"

## 🔥 Common Issues & Solutions

### Issue 1: "Invalid redirect_uri"

**Error**: `redirect_uri_mismatch`

**Solution**:
```python
# In your code, make sure redirect URI matches EXACTLY
redirect_uri = "http://localhost:8090"  # NO trailing slash
# NOT "http://localhost:8090/" 
# NOT "https://localhost:8090"
```

### Issue 2: "Invalid client"

**Error**: `invalid_client` or `unauthorized_client`

**Causes**:
- Wrong Client ID or Secret
- Spaces/newlines in credentials
- App not approved yet (can take 5 minutes)

**Solution**:
```python
# Check for hidden characters
client_id = os.getenv("YAHOO_CLIENT_ID").strip()
client_secret = os.getenv("YAHOO_CLIENT_SECRET").strip()
```

### Issue 3: "Token expired"

**Error**: Token works for ~1 hour then fails

**Solution**: Our auth module handles this automatically:
```python
# Token refresh happens automatically
async with auth.authenticated_session() as session:
    # Tokens are refreshed if needed before each request
    response = await session.get(yahoo_endpoint)
```

### Issue 4: "Insufficient permissions"

**Error**: Can't access fantasy data

**Solution**:
1. Go back to Yahoo Apps dashboard
2. Edit your app
3. Ensure "Fantasy Sports - Read" is checked
4. Save and wait 5 minutes

### Issue 5: "Connection refused on localhost"

**Error**: Browser can't connect to localhost:8090

**Causes**:
- Firewall blocking local connections
- Port already in use
- Antivirus software interference

**Solution**:
```bash
# Check if port is available
lsof -i :8090  # Mac/Linux
netstat -an | findstr 8090  # Windows

# Try different port
YAHOO_CALLBACK_PORT=8091
# Update redirect URI in Yahoo app to match!
```

## 🧪 Testing Your Connection

### Quick Test Script

Create `test_yahoo.py`:
```python
import asyncio
from src.agents.yahoo_auth import YahooAuth
from config.settings import Settings

async def test_connection():
    settings = Settings()
    auth = YahooAuth(settings)
    
    # Check if already authenticated
    if await auth.is_authenticated():
        print("✅ Already authenticated!")
    else:
        print("🔄 Starting authentication...")
        tokens = await auth.authenticate()
        print("✅ Authentication successful!")
    
    # Test API call
    async with auth.authenticated_session() as session:
        url = f"{auth.YAHOO_API_BASE}/users;use_login=1/games;game_keys=nfl/leagues"
        async with session.get(url) as response:
            if response.status == 200:
                print("✅ API call successful!")
                data = await response.json()
                leagues = data.get('fantasy_content', {}).get('users', {})
                print(f"Found {len(leagues)} leagues")
            else:
                print(f"❌ API call failed: {response.status}")

asyncio.run(test_connection())
```

### Expected Output
```
🔄 Starting authentication...
Opening browser for Yahoo authorization...
Starting callback server on http://localhost:8090
Waiting for authorization (timeout in 300 seconds)...

[Browser opens - you login and authorize]

Received authorization code!
Exchanging code for tokens...
✅ Authentication successful!
✅ API call successful!
Found 3 leagues
```

## 📊 Understanding Yahoo's API Structure

### The Weird Parts

1. **Collection Syntax**:
```python
# Yahoo uses semicolons and weird syntax
url = "/users;use_login=1/games;game_keys=nfl/leagues"
# NOT standard REST like "/users/me/games/nfl/leagues"
```

2. **XML Default Response**:
```python
# Must specify JSON format
headers = {"Accept": "application/json"}
# Otherwise you get XML!
```

3. **Game Keys**:
```python
# NFL game key changes each year
# 2023: "414"
# 2024: "423" 
# Format: "423.l.12345" (game.league.leagueID)
```

4. **Resource Collections**:
```python
# Yahoo uses "collection" resources
"/players;player_keys=423.p.12345,423.p.67890"
# Can batch multiple players in one call
```

## 🚀 Using with the MCP Server

Once authentication works, integrate with MCP:

### 1. Update MCP Configuration

```json
{
  "mcpServers": {
    "fantasy-football": {
      "command": "python",
      "args": ["/path/to/fantasy-football-mcp/src/mcp_server.py"],
      "env": {
        "YAHOO_CLIENT_ID": "your_client_id",
        "YAHOO_CLIENT_SECRET": "your_secret",
        "YAHOO_REDIRECT_URI": "http://localhost:8090",
        "PYTHONPATH": "/path/to/fantasy-football-mcp"
      }
    }
  }
}
```

### 2. First Run

When the MCP server first connects:
1. It will check for existing tokens in `.cache/yahoo_tokens.json`
2. If not found, it will open browser for auth
3. After auth, tokens are saved and reused
4. Tokens auto-refresh every hour

### 3. Verify in Your AI Assistant

```
You: "Check my Yahoo fantasy leagues"