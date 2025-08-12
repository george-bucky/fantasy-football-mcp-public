# Yahoo Fantasy Football MCP - Setup Instructions

## Quick Start Authentication

Since you have your Yahoo API credentials, here's exactly how to authenticate:

### Step 1: Install Dependencies

```bash
cd fantasy-football-mcp
pip install yfpy yahoo-oauth
```

### Step 2: Run Initial Authentication

Since we can't do interactive authentication in this environment, you'll need to run this on your local machine:

```bash
# On your local machine with a browser
python3 setup_yahoo_auth.py
```

**What will happen:**
1. A browser window will open to Yahoo
2. Login with your Yahoo account
3. Click "Agree" to authorize the app
4. Yahoo will show a verification code
5. Copy that code and paste it back in the terminal
6. A token file will be saved

### Step 3: Alternative - Direct URL Method

If the script doesn't work, you can authenticate manually:

1. **Open this URL in your browser:**
```
https://api.login.yahoo.com/oauth2/request_auth?client_id=YOUR_CLIENT_ID&redirect_uri=oob&response_type=code&language=en-us
```

2. **Login to Yahoo and click "Agree"**

3. **Copy the verification code shown**

4. **Create a Python script to exchange the code for tokens:**

```python
import requests
import base64
import json

# Your credentials
CLIENT_ID = "YOUR_CLIENT_ID_HERE"
CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"

# The code you got from Yahoo
AUTH_CODE = "paste_your_code_here"

# Exchange code for tokens
auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

response = requests.post(
    "https://api.login.yahoo.com/oauth2/get_token",
    headers={
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded"
    },
    data={
        "grant_type": "authorization_code",
        "code": AUTH_CODE,
        "redirect_uri": "oob"
    }
)

if response.status_code == 200:
    tokens = response.json()
    with open(".yahoo_token.json", "w") as f:
        json.dump(tokens, f)
    print("✅ Token saved!")
else:
    print(f"❌ Error: {response.text}")
```

### Step 4: Using yfpy (Easiest Method)

The simplest way is to use yfpy directly:

```python
from yfpy import YahooFantasySportsQuery

# This will handle the entire OAuth flow
query = YahooFantasySportsQuery(
    league_id="",  # Leave empty to get all leagues
    game_code="nfl",
    game_id=423,  # 2024 season
    yahoo_consumer_key="YOUR_CONSUMER_KEY_HERE",
    yahoo_consumer_secret="YOUR_CONSUMER_SECRET_HERE",
    browser_callback=True
)

# When prompted, enter the verification code
# Token will be saved automatically
```

## After Authentication

Once you have the token saved, the MCP server can use it:

### Configure MCP (Claude Desktop, etc.)

Add to your MCP configuration:

```json
{
  "mcpServers": {
    "fantasy-football": {
      "command": "python",
      "args": ["/path/to/fantasy-football-mcp/src/mcp_server.py"],
      "env": {
        "YAHOO_CLIENT_ID": "YOUR_CLIENT_ID_HERE",
        "YAHOO_CLIENT_SECRET": "YOUR_CLIENT_SECRET_HERE",
        "PYTHONPATH": "/path/to/fantasy-football-mcp"
      }
    }
  }
}
```

### Test Your Connection

Once authenticated, test with:

```python
from yfpy import YahooFantasySportsQuery

# Load saved token
query = YahooFantasySportsQuery(
    league_id="",
    game_code="nfl",
    yahoo_consumer_key="your_key",
    yahoo_consumer_secret="your_secret"
)

# Get your leagues
leagues = query.get_user_leagues()
for league in leagues:
    print(f"League: {league.name} (ID: {league.league_id})")
```

## Troubleshooting

### "Invalid client" Error
- Your app might not be approved yet (can take a few minutes)
- Check the client ID and secret are correct

### "Redirect URI mismatch"
- Make sure your Yahoo app has `oob` as the redirect URI
- Or use `http://localhost:8090` if you set that up

### "Invalid grant" Error
- The verification code expires in 10 minutes
- Get a new code and try again quickly

### Can't See Leagues
- Make sure you're logged into the Yahoo account that has fantasy leagues
- Check that your app has "Fantasy Sports - Read" permission

## The Bottom Line

1. **One-time setup**: Authenticate once with Yahoo
2. **Token saved**: The token is saved locally
3. **MCP uses token**: The server uses the saved token
4. **Auto-refresh**: Token refreshes automatically

After this one-time setup, your Fantasy Football MCP server will work seamlessly!