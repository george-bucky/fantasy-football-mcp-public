# Reddit API Setup Guide

This guide will walk you through setting up Reddit API access for the Fantasy Football MCP server.

## Prerequisites

- A Reddit account
- Access to Reddit's developer portal

## Step-by-Step Setup

### 1. Create a Reddit App

1. Go to https://www.reddit.com/prefs/apps
2. Scroll down and click **"Create App"** or **"Create Another App"**
3. Fill in the application form:
   - **Name**: Choose any name (e.g., "Fantasy Football MCP")
   - **App Type**: Select **"script"** for personal use
   - **Description**: Optional (e.g., "Fantasy football data analysis")
   - **About URL**: Leave blank
   - **Redirect URI**: Enter `http://localhost:8080` (required even though we don't use it)
   - **Permissions**: Leave blank
4. Click **"Create app"**

### 2. Get Your Credentials

After creating the app, you'll see your app listed with the following information:

- **Client ID**: This is the string of random characters directly under "personal use script"
  - Example: `ABC123def456GHI`
- **Client Secret**: Click "edit" on your app to see the "secret" field
  - Example: `xYz789_SecretKey_123ABC`

### 3. Configure Environment Variables

Add these credentials to your `.env` file:

```bash
# Reddit API Configuration
REDDIT_CLIENT_ID=your_client_id_here
REDDIT_CLIENT_SECRET=your_client_secret_here
REDDIT_USER_AGENT=FantasyFootballMCP/1.0 by YourRedditUsername
```

**Important Notes:**
- Replace `your_client_id_here` with your actual Client ID
- Replace `your_client_secret_here` with your actual Client Secret
- Update `YourRedditUsername` in the user agent with your Reddit username
- Keep these credentials secret and never commit them to version control

### 4. User Agent Best Practices

Reddit requires a descriptive user agent. Format:
```
<platform>:<app ID>:<version string> (by /u/<reddit username>)
```

Example:
```
FantasyFootballMCP:v1.0.0 (by /u/your_username)
```

### 5. Rate Limiting

Reddit API has rate limits:
- **60 requests per minute** for OAuth2 authenticated requests
- Be respectful of the API and implement appropriate delays between requests
- The MCP server handles rate limiting automatically

### 6. Testing Your Setup

You can test your Reddit API credentials by running:

```python
import os
import praw
from dotenv import load_dotenv

load_dotenv()

reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT")
)

# Test by fetching a subreddit
subreddit = reddit.subreddit("fantasyfootball")
print(f"Successfully connected! Subreddit has {subreddit.subscribers} subscribers")
```

## Common Issues

### "401 Unauthorized" Error
- Double-check your Client ID and Client Secret
- Ensure there are no extra spaces or quotes in your `.env` file

### "429 Too Many Requests" Error
- You're hitting rate limits
- Implement delays between requests
- Check if you're making requests in a loop

### "User-Agent" Error
- Make sure your user agent string is descriptive
- Include your Reddit username in the format shown above

## Security Best Practices

1. **Never commit credentials**: Add `.env` to your `.gitignore`
2. **Use environment variables**: Don't hardcode credentials in your code
3. **Rotate secrets regularly**: If exposed, regenerate your app's secret immediately
4. **Limit scope**: Only request the permissions you need

## Additional Resources

- [Reddit API Documentation](https://www.reddit.com/dev/api/)
- [PRAW Documentation](https://praw.readthedocs.io/)
- [Reddit API Terms of Use](https://www.reddit.com/wiki/api-terms)

## Support

If you encounter issues with Reddit API setup:
1. Check the [Reddit API subreddit](https://www.reddit.com/r/redditdev/)
2. Review PRAW's [Quick Start Guide](https://praw.readthedocs.io/en/stable/getting_started/quick_start.html)
3. Open an issue in this repository with details about your setup problem