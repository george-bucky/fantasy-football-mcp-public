#!/usr/bin/env python3
"""
Fantasy Football MCP Server - Render Deployment with Claude.ai OAuth
Optimized for Render.com deployment with flexible OAuth 2.0 for Claude.ai
"""

import asyncio
import json
import os
import logging
import secrets
import uuid
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from urllib.parse import urlparse, parse_qs

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends, status, Form, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Import the existing MCP server components
import fantasy_football_multi_league

# Load environment variables
load_dotenv()

# Configure logging with more detail for OAuth debugging
logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG") == "true" else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration - More flexible for Claude.ai
ALLOWED_REDIRECT_URIS = os.getenv(
    "ALLOWED_REDIRECT_URIS", 
    "https://claude.ai/api/mcp/auth_callback,https://claude.ai/oauth/callback"
).split(",")

ALLOWED_CLIENT_IDS = os.getenv(
    "ALLOWED_CLIENT_IDS",
    "Claude,claude-ai,claude.ai,fantasy-football-mcp,mcp-client"
).split(",")

OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", secrets.token_urlsafe(32))

# CORS - Allow Claude.ai domains
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", 
    "https://claude.ai,https://*.claude.ai,http://localhost:*"
).split(",")

# File-based token storage for Render (persists across deploys in /tmp)
TOKEN_STORAGE_FILE = "/tmp/oauth_tokens.json"
CODE_STORAGE_FILE = "/tmp/oauth_codes.json"

# Security
security = HTTPBearer(auto_error=False)

class MCPRequest(BaseModel):
    """MCP request model."""
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None

class MCPResponse(BaseModel):
    """MCP response model."""
    jsonrpc: str = "2.0"
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None

class TokenStore:
    """Simple file-based token storage for Render"""
    
    @staticmethod
    def load_tokens():
        try:
            if os.path.exists(TOKEN_STORAGE_FILE):
                with open(TOKEN_STORAGE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading tokens: {e}")
        return {}
    
    @staticmethod
    def save_tokens(tokens):
        try:
            with open(TOKEN_STORAGE_FILE, 'w') as f:
                json.dump(tokens, f)
        except Exception as e:
            logger.error(f"Error saving tokens: {e}")
    
    @staticmethod
    def load_codes():
        try:
            if os.path.exists(CODE_STORAGE_FILE):
                with open(CODE_STORAGE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading codes: {e}")
        return {}
    
    @staticmethod
    def save_codes(codes):
        try:
            with open(CODE_STORAGE_FILE, 'w') as f:
                json.dump(codes, f)
        except Exception as e:
            logger.error(f"Error saving codes: {e}")

# Available MCP tools
AVAILABLE_TOOLS = [
    "ff_get_leagues", "ff_get_league_info", "ff_get_standings", "ff_get_roster", 
    "ff_get_matchup", "ff_get_optimal_lineup", "ff_get_players", "ff_get_waiver_wire", 
    "ff_get_draft_rankings", "ff_get_draft_results", "ff_get_draft_recommendation", 
    "ff_analyze_draft_state", "ff_refresh_token", "ff_get_api_status", "ff_clear_cache",
    "ff_analyze_reddit_sentiment"
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    logger.info("Starting Fantasy Football MCP Server on Render")
    logger.info(f"Allowed redirect URIs: {ALLOWED_REDIRECT_URIS}")
    logger.info(f"Allowed client IDs: {ALLOWED_CLIENT_IDS}")
    yield
    logger.info("Shutting down Fantasy Football MCP Server")

# Create FastAPI app
app = FastAPI(
    title="Fantasy Football MCP Server",
    description="Remote MCP server for Yahoo Fantasy Football with Claude.ai OAuth support",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware with more permissive settings for Claude.ai
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for Claude.ai compatibility
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[str]:
    """Verify OAuth token or allow public access for certain endpoints"""
    if not credentials:
        return None
        
    token = credentials.credentials
    tokens = TokenStore.load_tokens()
    
    # Check if it's a valid OAuth token
    if token in tokens:
        token_data = tokens[token]
        # Check expiration
        if datetime.fromisoformat(token_data["expires_at"]) > datetime.utcnow():
            logger.debug(f"Valid OAuth token for client: {token_data.get('client_id')}")
            return token
        else:
            # Remove expired token
            del tokens[token]
            TokenStore.save_tokens(tokens)
            logger.info("OAuth token expired and removed")
    
    # For public endpoints, we don't require auth
    return None

@app.get("/")
@app.post("/")  # Claude.ai might POST to root
@app.head("/")  # Claude.ai might HEAD to root
async def root():
    """Root endpoint with basic information."""
    return {
        "name": "Fantasy Football MCP Server",
        "version": "2.0.0",
        "status": "running",
        "deployment": "render",
        "endpoints": {
            "health": "/health",
            "mcp": "/mcp (public)",
            "tools": "/tools (public)",
            "oauth": {
                "authorize": "/oauth/authorize",
                "token": "/oauth/token",
                "discovery": "/.well-known/oauth-authorization-server",
                "resource": "/.well-known/oauth-protected-resource"
            }
        },
        "authentication": "OAuth 2.0 supported but not required for MCP endpoints"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint for Render."""
    try:
        yahoo_token = os.getenv("YAHOO_ACCESS_TOKEN")
        yahoo_key = os.getenv("YAHOO_CONSUMER_KEY")
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "2.0.0",
            "services": {
                "yahoo_api": "configured" if yahoo_token and yahoo_key else "missing_credentials",
                "mcp_tools": f"{len(AVAILABLE_TOOLS)}_available",
                "oauth": "enabled",
                "deployment": "render"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# OAuth Discovery endpoint - Critical for Claude.ai
@app.get("/.well-known/oauth-authorization-server")
async def oauth_discovery():
    """OAuth server metadata endpoint for Claude.ai discovery."""
    base_url = os.getenv("RENDER_EXTERNAL_URL", "https://fantasy-football-mcp-server.onrender.com")
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "scopes_supported": ["read", "write"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
        "code_challenge_methods_supported": ["plain", "S256"]
    }

# OAuth Protected Resource metadata - Required by Claude.ai
@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource():
    """OAuth protected resource metadata for Claude.ai."""
    base_url = os.getenv("RENDER_EXTERNAL_URL", "https://fantasy-football-mcp-server.onrender.com")
    return {
        "resource": base_url,
        "oauth_authorization_server": f"{base_url}/.well-known/oauth-authorization-server",
        "scopes_supported": ["read", "write"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base_url}/docs",
        "resource_signing_alg_values_supported": ["RS256", "HS256"]
    }

@app.get("/oauth/authorize")
async def oauth_authorize(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    code_challenge: Optional[str] = Query(None),
    code_challenge_method: Optional[str] = Query(None)
):
    """OAuth authorization endpoint with flexible validation for Claude.ai."""
    logger.info(f"OAuth authorize request from client_id: {client_id}")
    logger.info(f"Redirect URI: {redirect_uri}")
    logger.info(f"State: {state}")
    
    # More flexible client_id validation - log unknown clients
    if client_id not in ALLOWED_CLIENT_IDS:
        logger.warning(f"Unknown client_id: {client_id} - allowing for debugging")
        # Don't reject, just log for now to identify Claude.ai's actual client_id
    
    # More flexible redirect_uri validation
    redirect_valid = False
    for allowed_uri in ALLOWED_REDIRECT_URIS:
        if redirect_uri.startswith(allowed_uri) or allowed_uri == "*":
            redirect_valid = True
            break
    
    if not redirect_valid:
        logger.warning(f"Redirect URI not in allowlist: {redirect_uri} - allowing for debugging")
        # Don't reject for now, to debug Claude.ai's actual redirect URI
    
    # Generate authorization code
    auth_code = secrets.token_urlsafe(32)
    
    # Store code with metadata
    codes = TokenStore.load_codes()
    codes[auth_code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope or "read write",
        "state": state,
        "code_challenge": code_challenge,
        "expires_at": (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    }
    TokenStore.save_codes(codes)
    
    # Show a simple consent page
    consent_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authorize Fantasy Football MCP</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }}
            h1 {{ color: #333; }}
            .info {{ background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            .button {{ background: #4CAF50; color: white; padding: 10px 20px; border: none; 
                      border-radius: 5px; cursor: pointer; font-size: 16px; }}
            .button:hover {{ background: #45a049; }}
        </style>
    </head>
    <body>
        <h1>🏈 Fantasy Football MCP Authorization</h1>
        <div class="info">
            <p><strong>Client:</strong> {client_id}</p>
            <p><strong>Scope:</strong> {scope or 'read write'}</p>
            <p>This application is requesting access to your Fantasy Football MCP server.</p>
        </div>
        <form action="/oauth/authorize/confirm" method="get">
            <input type="hidden" name="code" value="{auth_code}">
            <input type="hidden" name="state" value="{state or ''}">
            <input type="hidden" name="redirect_uri" value="{redirect_uri}">
            <button type="submit" class="button">Authorize Access</button>
        </form>
    </body>
    </html>
    """
    
    return HTMLResponse(content=consent_html)

@app.get("/oauth/authorize/confirm")
async def oauth_authorize_confirm(
    code: str = Query(...),
    state: Optional[str] = Query(None),
    redirect_uri: str = Query(...)
):
    """Confirm authorization and redirect back to Claude.ai"""
    logger.info(f"Authorization confirmed, redirecting to: {redirect_uri}")
    
    # Build callback URL
    callback_url = f"{redirect_uri}?code={code}"
    if state:
        callback_url += f"&state={state}"
    
    return RedirectResponse(url=callback_url, status_code=302)

@app.post("/oauth/token")
async def oauth_token(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None)
):
    """OAuth token endpoint with relaxed validation for Claude.ai."""
    logger.info(f"Token request - grant_type: {grant_type}, client_id: {client_id}")
    
    if grant_type != "authorization_code":
        logger.error(f"Unsupported grant_type: {grant_type}")
        raise HTTPException(status_code=400, detail="Unsupported grant_type")
    
    # Load codes
    codes = TokenStore.load_codes()
    
    if not code or code not in codes:
        logger.error(f"Invalid authorization code: {code}")
        raise HTTPException(status_code=400, detail="Invalid authorization code")
    
    code_data = codes[code]
    
    # Check expiration
    if datetime.fromisoformat(code_data["expires_at"]) < datetime.utcnow():
        del codes[code]
        TokenStore.save_codes(codes)
        logger.error("Authorization code expired")
        raise HTTPException(status_code=400, detail="Authorization code expired")
    
    # Generate tokens
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    
    # Store token
    tokens = TokenStore.load_tokens()
    tokens[access_token] = {
        "client_id": client_id or code_data["client_id"],
        "scope": code_data["scope"],
        "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
        "refresh_token": refresh_token
    }
    TokenStore.save_tokens(tokens)
    
    # Remove used code
    del codes[code]
    TokenStore.save_codes(codes)
    
    logger.info(f"Token issued successfully to client: {client_id}")
    
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 86400,  # 24 hours
        "refresh_token": refresh_token,
        "scope": code_data["scope"]
    }

@app.get("/tools")
async def list_tools():
    """List available MCP tools - PUBLIC endpoint."""
    try:
        tools = await fantasy_football_multi_league.list_tools()
        tools_info = []
        
        for tool in tools:
            tools_info.append({
                "name": tool.name,
                "description": tool.description,
                "type": "function",
                "inputSchema": tool.inputSchema
            })
        
        return {
            "tools": tools_info,
            "count": len(tools_info)
        }
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        return {
            "tools": [],
            "count": 0,
            "error": str(e)
        }

@app.post("/mcp")
async def handle_mcp_request(
    request: MCPRequest,
    token: Optional[str] = Depends(verify_token)
):
    """Handle MCP protocol requests - PUBLIC endpoint (auth optional)."""
    logger.debug(f"MCP request: {request.method}")
    
    try:
        if request.method == "initialize":
            return MCPResponse(
                result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": "fantasy-football-mcp",
                        "version": "2.0.0"
                    }
                },
                id=request.id
            )
        
        elif request.method == "tools/list":
            tools = await fantasy_football_multi_league.list_tools()
            tools_list = []
            
            for tool in tools:
                tools_list.append({
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                })
            
            return MCPResponse(
                result={"tools": tools_list},
                id=request.id
            )
        
        elif request.method == "tools/call":
            tool_name = request.params.get("name") if request.params else None
            tool_args = request.params.get("arguments", {}) if request.params else {}
            
            if tool_name not in AVAILABLE_TOOLS:
                return MCPResponse(
                    error={
                        "code": -32602,
                        "message": f"Unknown tool: {tool_name}"
                    },
                    id=request.id
                )
            
            result = await fantasy_football_multi_league.call_tool(tool_name, tool_args)
            
            content = []
            for text_content in result:
                content.append({
                    "type": "text",
                    "text": text_content.text
                })
            
            return MCPResponse(
                result={"content": content},
                id=request.id
            )
        
        else:
            return MCPResponse(
                error={
                    "code": -32601,
                    "message": f"Method not found: {request.method}"
                },
                id=request.id
            )
    
    except Exception as e:
        logger.error(f"MCP request error: {e}", exc_info=True)
        return MCPResponse(
            error={
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            },
            id=request.id
        )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if os.getenv("DEBUG") == "true" else "An unexpected error occurred"
        }
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    host = "0.0.0.0"
    
    logger.info(f"Starting Fantasy Football MCP Server on {host}:{port}")
    
    uvicorn.run(
        "render_server:app",
        host=host,
        port=port,
        log_level="debug" if os.getenv("DEBUG") == "true" else "info",
        access_log=True,
        reload=False
    )