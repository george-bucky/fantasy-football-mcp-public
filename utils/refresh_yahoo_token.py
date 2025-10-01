#!/usr/bin/env python3
"""
Refresh Yahoo Fantasy Sports OAuth2 Token
"""

import os
import json
import requests
from dotenv import load_dotenv
from datetime import datetime

# Load environment
load_dotenv()


def refresh_yahoo_token():
    """Refresh the Yahoo access token using the refresh token."""

    # Get credentials from environment
    client_id = os.getenv("YAHOO_CONSUMER_KEY")
    client_secret = os.getenv("YAHOO_CONSUMER_SECRET")
    refresh_token = os.getenv("YAHOO_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("❌ Missing credentials in .env file")
        print("Required: YAHOO_CONSUMER_KEY, YAHOO_CONSUMER_SECRET, YAHOO_REFRESH_TOKEN")
        return False

    # Yahoo token endpoint
    token_url = "https://api.login.yahoo.com/oauth2/get_token"

    # Prepare refresh request
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    print("🔄 Refreshing Yahoo token...")

    try:
        # Make refresh request
        response = requests.post(token_url, data=data)

        if response.status_code == 200:
            # Parse new tokens
            token_data = response.json()
            new_access_token = token_data.get("access_token")
            new_refresh_token = token_data.get("refresh_token", refresh_token)
            expires_in = token_data.get("expires_in", 3600)

            print("✅ Token refreshed successfully!")
            print(f"   Expires in: {expires_in} seconds ({expires_in/3600:.1f} hours)")

            # Update .env file
            update_env_file(new_access_token, new_refresh_token)

            # Also update claude_desktop_config.json if it exists
            update_claude_config(new_access_token, new_refresh_token)

            print("\n📝 Updated tokens in:")
            print("   - .env file")
            print("   - claude_desktop_config.json")
            print("\n⚠️  IMPORTANT: Restart Claude Desktop to use the new token")

            return True

        else:
            print(f"❌ Failed to refresh token: {response.status_code}")
            print(f"   Response: {response.text}")

            if response.status_code == 400:
                print("\n💡 If refresh token is expired, you need to re-authenticate:")
                print("   Run: python setup_yahoo_auth.py")

            return False

    except Exception as e:
        print(f"❌ Error refreshing token: {e}")
        return False


def update_env_file(access_token, refresh_token):
    """Update the .env file with new tokens."""

    # Read current .env
    env_path = ".env"
    lines = []

    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    # Update or add token lines
    updated = False
    new_lines = []

    for line in lines:
        if line.startswith("YAHOO_ACCESS_TOKEN="):
            new_lines.append(f"YAHOO_ACCESS_TOKEN={access_token}\n")
            updated = True
        elif line.startswith("YAHOO_REFRESH_TOKEN="):
            new_lines.append(f"YAHOO_REFRESH_TOKEN={refresh_token}\n")
        else:
            new_lines.append(line)

    # Add tokens if not found
    if not updated:
        new_lines.append(f"\nYAHOO_ACCESS_TOKEN={access_token}\n")
        new_lines.append(f"YAHOO_REFRESH_TOKEN={refresh_token}\n")

    # Write back
    with open(env_path, "w") as f:
        f.writelines(new_lines)


def update_claude_config(access_token, refresh_token):
    """Update the Claude Desktop config with new tokens."""

    config_path = "claude_desktop_config.json"

    if not os.path.exists(config_path):
        return

    try:
        with open(config_path, "r") as f:
            config = json.load(f)

        # Update tokens in the fantasy-football server env
        if "mcpServers" in config and "fantasy-football" in config["mcpServers"]:
            if "env" not in config["mcpServers"]["fantasy-football"]:
                config["mcpServers"]["fantasy-football"]["env"] = {}

            config["mcpServers"]["fantasy-football"]["env"]["YAHOO_ACCESS_TOKEN"] = access_token
            config["mcpServers"]["fantasy-football"]["env"]["YAHOO_REFRESH_TOKEN"] = refresh_token

            # Write back
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)

    except Exception as e:
        print(f"⚠️  Could not update Claude config: {e}")


def test_new_token():
    """Test if the new token works."""

    load_dotenv(override=True)  # Reload environment
    access_token = os.getenv("YAHOO_ACCESS_TOKEN")

    if not access_token:
        print("❌ No access token found")
        return False

    # Test API call
    url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1?format=json"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            print("\n✅ Token test successful! API is accessible.")
            return True
        else:
            print(f"\n❌ Token test failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"\n❌ Token test error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Yahoo Fantasy Sports Token Refresh")
    print("=" * 60)
    print()

    if refresh_yahoo_token():
        print("\n🧪 Testing new token...")
        test_new_token()

        print("\n" + "=" * 60)
        print("✅ Token refresh complete!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ Token refresh failed")
        print("=" * 60)
        print("\nTroubleshooting:")
        print("1. Check your internet connection")
        print("2. Verify your credentials in .env")
        print("3. If refresh token is expired, run: python setup_yahoo_auth.py")
        print("4. Check Yahoo Developer App settings")
