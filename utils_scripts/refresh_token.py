#!/usr/bin/env python3
"""
Refresh Yahoo OAuth tokens
"""

import os
import requests
import json
import time
from dotenv import load_dotenv

# Load current credentials
load_dotenv()

client_id = os.getenv('YAHOO_CONSUMER_KEY')
client_secret = os.getenv('YAHOO_CONSUMER_SECRET')
refresh_token = os.getenv('YAHOO_REFRESH_TOKEN')

print('Refreshing Yahoo OAuth tokens...')
print('=' * 50)

# Yahoo OAuth2 token refresh endpoint
token_url = 'https://api.login.yahoo.com/oauth2/get_token'

# Prepare refresh request
data = {
    'client_id': client_id,
    'client_secret': client_secret,
    'redirect_uri': 'oob',
    'refresh_token': refresh_token,
    'grant_type': 'refresh_token'
}

headers = {
    'Content-Type': 'application/x-www-form-urlencoded'
}

# Request new tokens
response = requests.post(token_url, data=data, headers=headers)

if response.status_code == 200:
    tokens = response.json()
    
    new_access_token = tokens.get('access_token')
    new_refresh_token = tokens.get('refresh_token', refresh_token)  # Sometimes same refresh token
    expires_in = tokens.get('expires_in', 3600)
    
    print('✓ Token refresh successful!')
    print(f'Access Token: {new_access_token[:50]}...')
    print(f'Expires in: {expires_in} seconds')
    print(f'Token type: {tokens.get("token_type", "bearer")}')
    
    # Update .env file
    with open('.env', 'r') as f:
        lines = f.readlines()
    
    with open('.env', 'w') as f:
        for line in lines:
            if line.startswith('YAHOO_ACCESS_TOKEN='):
                f.write(f'YAHOO_ACCESS_TOKEN={new_access_token}\n')
            elif line.startswith('YAHOO_REFRESH_TOKEN=') and new_refresh_token != refresh_token:
                f.write(f'YAHOO_REFRESH_TOKEN={new_refresh_token}\n')
            elif line.startswith('YAHOO_TOKEN_TIME='):
                f.write(f'YAHOO_TOKEN_TIME={time.time()}\n')
            else:
                f.write(line)
    
    print('✓ Updated .env file with new tokens')
    
    # Update Claude config
    config_path = 'claude_desktop_config.json'
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Update the fantasy-football server env
        if 'mcpServers' in config and 'fantasy-football' in config['mcpServers']:
            config['mcpServers']['fantasy-football']['env']['YAHOO_ACCESS_TOKEN'] = new_access_token
            if new_refresh_token != refresh_token:
                config['mcpServers']['fantasy-football']['env']['YAHOO_REFRESH_TOKEN'] = new_refresh_token
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            print('✓ Updated claude_desktop_config.json')
    
    # Also update the main Claude config
    main_config_path = '/home/derek/.config/Claude/claude_desktop_config.json'
    if os.path.exists(main_config_path):
        with open(main_config_path, 'r') as f:
            config = json.load(f)
        
        if 'mcpServers' in config and 'fantasy-football' in config['mcpServers']:
            config['mcpServers']['fantasy-football']['env']['YAHOO_ACCESS_TOKEN'] = new_access_token
            if new_refresh_token != refresh_token:
                config['mcpServers']['fantasy-football']['env']['YAHOO_REFRESH_TOKEN'] = new_refresh_token
            
            with open(main_config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            print('✓ Updated main Claude Desktop config')
    
    print()
    print('✅ Token refresh complete! New access token is valid for 1 hour.')
    
else:
    print(f'✗ Token refresh failed: {response.status_code}')
    print(f'Response: {response.text}')
    print()
    print('The refresh token may have expired (they last ~60 days).')
    print('You need to run full re-authentication:')
    print()
    print('python reauth_yahoo.py')
    print()
    print('This will open a browser for you to log in to Yahoo.')