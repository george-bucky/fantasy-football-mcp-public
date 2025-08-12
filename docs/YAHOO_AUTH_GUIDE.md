# Yahoo Fantasy Sports API Authentication Guide

This guide provides comprehensive documentation for the Yahoo Fantasy Sports API authentication system, covering setup, usage, troubleshooting, and all Yahoo-specific requirements.

## Table of Contents

1. [Overview](#overview)
2. [Yahoo API Setup](#yahoo-api-setup)
3. [Environment Configuration](#environment-configuration)
4. [Quick Start](#quick-start)
5. [Advanced Usage](#advanced-usage)
6. [Error Handling](#error-handling)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)
9. [API Reference](#api-reference)

## Overview

Yahoo's Fantasy Sports API uses OAuth2 for authentication, but with several non-standard requirements and limitations:

### Key Challenges Addressed

- **Non-standard OAuth2 flow**: Yahoo requires exact redirect URI matching
- **Short token lifetime**: Access tokens expire after 1 hour
- **Limited auth code validity**: Authorization codes expire after 10 minutes
- **Complex refresh logic**: Refresh tokens can also expire unexpectedly
- **Callback handling**: Requires a web server to catch the OAuth callback

### Features Provided

✅ **Complete OAuth2 Flow**: Handles authorization, callback, and token exchange  
✅ **Automatic Token Refresh**: Refreshes tokens before expiration  
✅ **Persistent Storage**: Securely stores and manages tokens  
✅ **Error Recovery**: Comprehensive error handling with retry logic  
✅ **Local Callback Server**: Built-in web server for OAuth callbacks  
✅ **Thread-Safe**: Safe for concurrent usage  
✅ **Rich Logging**: Detailed logging for debugging  

## Yahoo API Setup

### 1. Create Yahoo Developer Application

1. Go to [Yahoo Developer Console](https://developer.yahoo.com/apps/)
2. Click "Create an App"
3. Fill in application details:
   - **Application Name**: Your application name
   - **Description**: Brief description of your app
   - **Home Page URL**: Your application homepage (can be localhost for development)
   - **Redirect URI(s)**: `http://localhost:8080/callback` (must match exactly)
   - **API Permissions**: Select "Fantasy Sports" and check "Read"

### 2. Note Your Credentials

After creating the app, note down:
- **Client ID** (Consumer Key)
- **Client Secret** (Consumer Secret)

⚠️ **Important**: The redirect URI must match exactly what you configure in the application.

## Environment Configuration

### 1. Environment Variables

Create a `.env` file in your project root:

```bash
# Yahoo API Configuration
YAHOO_CLIENT_ID=your_client_id_here
YAHOO_CLIENT_SECRET=your_client_secret_here

# Optional: Customize callback server
YAHOO_CALLBACK_HOST=localhost
YAHOO_CALLBACK_PORT=8080

# Optional: Cache configuration
CACHE_DIR=./.cache
CACHE_TTL_SECONDS=3600

# Optional: Logging
LOG_LEVEL=INFO
LOG_FILE=./logs/fantasy_football.log
```

### 2. Firewall Configuration

Ensure your firewall allows connections to the callback port (default: 8080):

```bash
# Ubuntu/Debian
sudo ufw allow 8080/tcp

# macOS
# Usually not needed for localhost

# Windows
# Add inbound rule for port 8080
```

## Quick Start

### 1. Basic Authentication

```python
import asyncio
from config.settings import Settings
from src.agents.yahoo_auth import YahooAuth

async def authenticate():
    settings = Settings()
    auth = YahooAuth(settings)
    
    # Perform authentication (opens browser)
    tokens = await auth.authenticate(timeout=300)
    print(f"✅ Authenticated! Token expires at: {tokens.expires_at}")
    
    return auth

# Run authentication
auth = asyncio.run(authenticate())
```

### 2. Making Authenticated Requests

```python
async def get_user_leagues(auth):
    async with auth.authenticated_session() as session:
        url = f"{auth.YAHOO_API_BASE}/users;use_login=1/games;game_keys=nfl/leagues"
        
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.text()
                print("✅ Got leagues data!")
                return data
            else:
                print(f"❌ Request failed: {response.status}")

# Use with existing auth
data = asyncio.run(get_user_leagues(auth))
```

### 3. Using the Example Script

The provided example script handles common operations:

```bash
# Perform initial authentication
python examples/yahoo_auth_example.py auth

# Check authentication status
python examples/yahoo_auth_example.py status

# Refresh tokens
python examples/yahoo_auth_example.py refresh

# Test API request
python examples/yahoo_auth_example.py test-api

# Revoke tokens
python examples/yahoo_auth_example.py revoke
```

## Advanced Usage

### 1. Custom Configuration

```python
from pathlib import Path
from src.agents.yahoo_auth import YahooAuth

# Custom callback server configuration
auth = YahooAuth(
    settings=settings,
    callback_host="127.0.0.1",  # Custom host
    callback_port=9090,          # Custom port
    token_storage_path=Path("./custom_tokens.json")  # Custom storage
)
```

### 2. Token Management

```python
# Check if authenticated
if auth.is_authenticated:
    print("Ready to make requests")
else:
    print("Authentication required")

# Get current status
status = auth.get_status()
print(f"State: {status['state']}")
print(f"Expires in: {status.get('expires_in_seconds', 0)} seconds")

# Ensure authentication (auto-refresh if needed)
try:
    tokens = await auth.ensure_authenticated()
    print("✅ Authentication ensured")
except YahooTokenExpiredError:
    print("❌ Re-authentication required")
    tokens = await auth.authenticate()
```

### 3. Error Handling

```python
from src.agents.yahoo_auth import (
    YahooAuthError,
    YahooTokenExpiredError,
    YahooAuthTimeoutError,
    YahooInvalidGrantError
)

try:
    tokens = await auth.authenticate(timeout=180)
except YahooAuthTimeoutError:
    print("❌ User didn't authorize within timeout")
except YahooInvalidGrantError:
    print("❌ Authorization code expired or invalid")
except YahooAuthError as e:
    print(f"❌ Authentication failed: {e}")
```

### 4. Background Token Refresh

```python
import asyncio
from datetime import datetime, timedelta

async def token_refresh_daemon(auth):
    """Background task to refresh tokens before expiration."""
    while True:
        try:
            if auth.tokens and auth.tokens.expires_in_seconds < 300:  # 5 minutes
                print("🔄 Refreshing tokens...")
                await auth.refresh_tokens()
                print("✅ Tokens refreshed")
            
            await asyncio.sleep(60)  # Check every minute
            
        except YahooTokenExpiredError:
            print("❌ Token refresh failed, re-authentication needed")
            break
        except Exception as e:
            print(f"⚠️  Token refresh error: {e}")
            await asyncio.sleep(300)  # Wait 5 minutes on error

# Start background refresh
asyncio.create_task(token_refresh_daemon(auth))
```

## Error Handling

### Common Errors and Solutions

#### 1. `YahooAuthTimeoutError`

**Cause**: User didn't complete authorization within timeout period.

**Solutions**:
- Increase timeout: `await auth.authenticate(timeout=600)`
- Check if browser opened correctly
- Verify redirect URI configuration

#### 2. `YahooInvalidGrantError`

**Cause**: Authorization code expired (Yahoo codes expire in 10 minutes).

**Solutions**:
- Complete authorization flow more quickly
- Restart authentication process
- Check system clock accuracy

#### 3. `YahooTokenExpiredError`

**Cause**: Refresh token expired or invalid.

**Solutions**:
- Perform new authentication: `await auth.authenticate()`
- Check if application permissions were revoked
- Verify client credentials

#### 4. Callback Server Errors

**Cause**: Port already in use or firewall blocking.

**Solutions**:
```python
# Use different port
auth = YahooAuth(settings, callback_port=8081)

# Check port availability
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('localhost', 8080))
if result == 0:
    print("Port 8080 is in use")
sock.close()
```

#### 5. Network Errors

**Cause**: Connection issues, timeouts, or Yahoo API downtime.

**Solutions**:
- Check internet connectivity
- Verify Yahoo API status
- Increase timeout values
- Implement retry logic

## Troubleshooting

### Debug Logging

Enable detailed logging for troubleshooting:

```python
import logging
from loguru import logger

# Enable debug logging
logger.remove()
logger.add(sys.stderr, level="DEBUG")

# Or configure specific loggers
logging.getLogger("aiohttp").setLevel(logging.DEBUG)
```

### Common Issues

#### Browser Doesn't Open

```python
# Manually open browser
auth_url, state = auth.get_authorization_url()
print(f"Please visit: {auth_url}")

# Then continue with authentication
tokens = await auth.authenticate(auto_open_browser=False)
```

#### Redirect URI Mismatch

Ensure exact match between Yahoo app config and code:
- Yahoo app: `http://localhost:8080/callback`
- Code: `YahooAuth(settings, callback_host="localhost", callback_port=8080)`

#### Permission Denied Errors

```bash
# Fix cache directory permissions
chmod 755 ~/.cache
mkdir -p ~/.cache/fantasy-football
chmod 755 ~/.cache/fantasy-football
```

#### SSL Certificate Issues

```python
import ssl
import aiohttp

# Disable SSL verification (not recommended for production)
connector = aiohttp.TCPConnector(ssl=ssl.create_default_context())
```

### Testing Authentication

Use the provided test script to validate your setup:

```bash
# Run authentication tests
python -m pytest tests/test_yahoo_auth.py -v

# Run specific test
python -m pytest tests/test_yahoo_auth.py::TestYahooAuth::test_authorization_url_generation -v
```

## Best Practices

### 1. Security

```python
# ✅ Store credentials securely
# Use environment variables, not hardcoded values
YAHOO_CLIENT_SECRET="your_secret_here"

# ✅ Protect token storage
# Set appropriate file permissions
os.chmod(token_file, 0o600)  # Owner read/write only

# ✅ Use secure callback URLs in production
# For production, use HTTPS callbacks
callback_uri = "https://yourapp.com/auth/yahoo/callback"
```

### 2. Error Handling

```python
# ✅ Comprehensive error handling
async def safe_api_request(auth, url):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with auth.authenticated_session() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    return await response.json()
                    
        except YahooTokenExpiredError:
            if attempt == max_retries - 1:
                raise
            await auth.authenticate()  # Re-authenticate
        except aiohttp.ClientError as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

### 3. Performance

```python
# ✅ Reuse authentication instances
# Don't create new YahooAuth instances frequently
auth = YahooAuth(settings)  # Create once, reuse many times

# ✅ Use session context manager
# Reuse HTTP sessions for multiple requests
async with auth.authenticated_session() as session:
    # Make multiple requests with same session
    response1 = await session.get(url1)
    response2 = await session.get(url2)

# ✅ Proactive token refresh
# Refresh before expiration
if auth.tokens.expires_in_seconds < 300:  # 5 minutes
    await auth.refresh_tokens()
```

### 4. Development Workflow

```python
# ✅ Development helper
async def ensure_auth(auth):
    """Helper to ensure authentication during development."""
    if not auth.is_authenticated:
        try:
            await auth.ensure_authenticated()
        except YahooTokenExpiredError:
            print("Authentication required - opening browser...")
            await auth.authenticate(timeout=300)
    return auth
```

## API Reference

### YahooAuth Class

#### Constructor

```python
YahooAuth(
    settings: Settings,
    callback_host: str = "localhost",
    callback_port: int = 8080,
    token_storage_path: Optional[Path] = None
)
```

#### Key Methods

##### authenticate()
```python
async def authenticate(
    timeout: int = 300,
    scopes: str = "fspt-r",
    auto_open_browser: bool = True
) -> YahooTokens
```
Performs complete OAuth2 authentication flow.

##### ensure_authenticated()
```python
async def ensure_authenticated() -> YahooTokens
```
Ensures valid authentication, refreshing if needed.

##### refresh_tokens()
```python
async def refresh_tokens() -> YahooTokens
```
Refreshes access token using refresh token.

##### authenticated_session()
```python
@asynccontextmanager
async def authenticated_session()
```
Context manager for authenticated HTTP sessions.

#### Properties

- `is_authenticated: bool` - Check if currently authenticated
- `redirect_uri: str` - OAuth redirect URI
- `tokens: Optional[YahooTokens]` - Current tokens
- `auth_state: AuthState` - Current authentication state

### YahooTokens Class

#### Properties

- `access_token: str` - OAuth access token
- `refresh_token: str` - OAuth refresh token  
- `token_type: str` - Token type (usually "Bearer")
- `expires_at: datetime` - Token expiration time
- `scope: str` - Granted permissions scope
- `is_expired: bool` - Whether token is expired
- `expires_in_seconds: int` - Seconds until expiration

### Exception Classes

- `YahooAuthError` - Base authentication exception
- `YahooTokenExpiredError` - Token expired, re-auth needed
- `YahooAuthTimeoutError` - Authentication timeout
- `YahooInvalidGrantError` - Invalid authorization grant

### Utility Functions

```python
# Get configured auth instance
auth = await get_yahoo_auth_instance(settings)

# Quick authentication with defaults
tokens = await quick_authenticate(settings, timeout=300)
```

---

## Support and Contributing

For issues, questions, or contributions:

1. Check existing GitHub issues
2. Review troubleshooting section
3. Enable debug logging
4. Create detailed issue report

**Important**: Never include actual client credentials or tokens in issue reports!