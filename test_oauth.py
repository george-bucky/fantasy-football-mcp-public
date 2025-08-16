#!/usr/bin/env python3
"""
Test OAuth flow for Fantasy Football MCP Server
Helps debug OAuth issues with Claude.ai
"""

import requests
import json
import sys
from urllib.parse import urlencode, parse_qs, urlparse

def test_oauth_flow(base_url="https://fantasy-football-mcp-server.onrender.com"):
    """Test the OAuth flow to identify issues"""
    
    print(f"🔍 Testing OAuth flow for: {base_url}")
    print("=" * 60)
    
    # Step 1: Check discovery endpoint
    print("\n1️⃣ Testing OAuth Discovery Endpoint...")
    try:
        response = requests.get(f"{base_url}/.well-known/oauth-authorization-server")
        if response.status_code == 200:
            discovery = response.json()
            print("✅ Discovery endpoint working")
            print(f"   Authorization: {discovery.get('authorization_endpoint')}")
            print(f"   Token: {discovery.get('token_endpoint')}")
        else:
            print(f"❌ Discovery failed: {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ Discovery error: {e}")
    
    # Step 2: Test authorization endpoint
    print("\n2️⃣ Testing Authorization Endpoint...")
    auth_params = {
        "response_type": "code",
        "client_id": "Claude",
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "scope": "read write",
        "state": "test123"
    }
    
    auth_url = f"{base_url}/oauth/authorize?{urlencode(auth_params)}"
    print(f"   Auth URL: {auth_url}")
    
    try:
        response = requests.get(auth_url, allow_redirects=False)
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Authorization endpoint returns consent page")
            if "Authorize" in response.text:
                print("   Consent page detected")
        elif response.status_code == 302:
            print("✅ Authorization endpoint redirects (auto-approve)")
            location = response.headers.get('Location')
            print(f"   Redirect to: {location}")
            
            # Extract code from redirect
            if location and 'code=' in location:
                parsed = urlparse(location)
                code = parse_qs(parsed.query).get('code', [None])[0]
                if code:
                    print(f"   Authorization code: {code[:10]}...")
                    return code
        else:
            print(f"❌ Unexpected status: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
    except Exception as e:
        print(f"❌ Authorization error: {e}")
    
    # Step 3: Test public endpoints
    print("\n3️⃣ Testing Public MCP Endpoints...")
    
    # Test /mcp endpoint
    try:
        mcp_request = {
            "method": "initialize",
            "id": 1
        }
        response = requests.post(f"{base_url}/mcp", json=mcp_request)
        if response.status_code == 200:
            result = response.json()
            if "result" in result:
                print("✅ MCP endpoint working (public access)")
                print(f"   Protocol: {result['result'].get('protocolVersion')}")
            else:
                print("⚠️ MCP endpoint returns error")
                print(f"   Error: {result.get('error')}")
        else:
            print(f"❌ MCP endpoint failed: {response.status_code}")
    except Exception as e:
        print(f"❌ MCP error: {e}")
    
    # Test /tools endpoint
    try:
        response = requests.get(f"{base_url}/tools")
        if response.status_code == 200:
            tools = response.json()
            print(f"✅ Tools endpoint working")
            print(f"   Available tools: {tools.get('count', 0)}")
        else:
            print(f"❌ Tools endpoint failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Tools error: {e}")
    
    print("\n" + "=" * 60)
    print("📋 Summary:")
    print("- Make sure ALLOWED_CLIENT_IDS includes 'Claude' or '*'")
    print("- Make sure ALLOWED_REDIRECT_URIS includes Claude.ai URLs")
    print("- Check server logs for actual client_id and redirect_uri from Claude.ai")
    print("- Consider setting DEBUG=true for more detailed logs")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_oauth_flow(sys.argv[1])
    else:
        test_oauth_flow()