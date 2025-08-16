#!/usr/bin/env python3
"""
Fantasy Football MCP Server - Google Cloud Run HTTP Wrapper
FastAPI-based HTTP server that wraps the Fantasy Football MCP server for Cloud Run deployment.
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

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends, status, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Import the existing MCP server components
import fantasy_football_multi_league

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
MCP_API_KEY = os.getenv("MCP_API_KEY", "development-key-change-in-production")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# OAuth Configuration for Claude.ai
OAUTH_CLIENT_ID = "fantasy-football-mcp-server"
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", secrets.token_urlsafe(32))
OAUTH_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"

# In-memory storage for OAuth codes and tokens (in production, use a database)
oauth_codes = {}
oauth_tokens = {}

# Security
security = HTTPBearer()

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

class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    timestamp: str
    version: str
    services: Dict[str, str]

class OAuthAuthorizationRequest(BaseModel):
    """OAuth authorization request model."""
    response_type: str
    client_id: str
    redirect_uri: str
    scope: Optional[str] = None
    state: Optional[str] = None

class OAuthTokenRequest(BaseModel):
    """OAuth token request model."""
    grant_type: str
    code: Optional[str] = None
    redirect_uri: Optional[str] = None
    client_id: str
    client_secret: str

class OAuthTokenResponse(BaseModel):
    """OAuth token response model."""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: Optional[str] = None
    scope: Optional[str] = None

# Available MCP tools - these will be dynamically loaded from the MCP server
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
    logger.info("Starting Fantasy Football MCP Server for Cloud Run")
    yield
    logger.info("Shutting down Fantasy Football MCP Server")

# Create FastAPI app
app = FastAPI(
    title="Fantasy Football MCP Server",
    description="Remote MCP server for Yahoo Fantasy Football with Cloud Run deployment",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Verify API key or OAuth token authentication."""
    token = credentials.credentials
    
    # Check OAuth token first
    if token in oauth_tokens:
        token_data = oauth_tokens[token]
        if datetime.utcnow() > token_data["expires_at"]:
            del oauth_tokens[token]
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.info("OAuth token validated successfully")
        return token
    
    # Allow MCP API key for backward compatibility
    if token == MCP_API_KEY:
        return token
    
    # Check if it looks like a Google JWT token (rough validation)
    if len(token) > 100 and token.count('.') == 2:
        logger.info("Accepting Google identity token for Cloud Run access")
        return token
    
    logger.warning(f"Invalid token attempt: {token[:10]}...")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for Cloud Run."""
    try:
        # Quick validation of essential environment variables
        yahoo_token = os.getenv("YAHOO_ACCESS_TOKEN")
        yahoo_key = os.getenv("YAHOO_CONSUMER_KEY")
        
        services = {
            "yahoo_api": "configured" if yahoo_token and yahoo_key else "missing_credentials",
            "mcp_tools": f"{len(AVAILABLE_TOOLS)}_available",
            "environment": "cloud_run"
        }
        
        return HealthResponse(
            status="healthy",
            timestamp=datetime.utcnow().isoformat(),
            version="1.0.0",
            services=services
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint with basic information."""
    return {
        "name": "Fantasy Football MCP Server",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "mcp": "/mcp",
            "tools": "/tools",
            "oauth": {
                "authorize": "/oauth/authorize",
                "token": "/oauth/token"
            }
        }
    }

# OAuth Endpoints for Claude.ai integration
@app.get("/oauth/authorize")
async def oauth_authorize(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    scope: Optional[str] = None,
    state: Optional[str] = None
):
    """OAuth authorization endpoint for Claude.ai."""
    logger.info(f"OAuth authorize request: client_id={client_id}, redirect_uri={redirect_uri}")
    
    # Validate client_id and redirect_uri
    if client_id != "Claude" and client_id != OAUTH_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Invalid client_id")
    
    if redirect_uri != OAUTH_REDIRECT_URI:
        logger.warning(f"Unexpected redirect_uri: {redirect_uri}")
    
    # Generate authorization code
    auth_code = secrets.token_urlsafe(32)
    oauth_codes[auth_code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "expires_at": datetime.utcnow() + timedelta(minutes=10)
    }
    
    # For simplicity, auto-approve (in production, show consent screen)
    callback_url = f"{redirect_uri}?code={auth_code}"
    if state:
        callback_url += f"&state={state}"
    
    logger.info(f"Redirecting to: {callback_url}")
    return RedirectResponse(url=callback_url, status_code=302)

@app.post("/oauth/token", response_model=OAuthTokenResponse)
async def oauth_token(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: str = Form(...),
    client_secret: Optional[str] = Form(None)
):
    """OAuth token endpoint for Claude.ai."""
    logger.info(f"OAuth token request: grant_type={grant_type}, client_id={client_id}")
    
    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant_type")
    
    if not code or code not in oauth_codes:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization code")
    
    code_data = oauth_codes[code]
    
    # Check if code is expired
    if datetime.utcnow() > code_data["expires_at"]:
        del oauth_codes[code]
        raise HTTPException(status_code=400, detail="Authorization code expired")
    
    # Validate client credentials
    if client_id != code_data["client_id"]:
        raise HTTPException(status_code=400, detail="Client ID mismatch")
    
    # Generate access token
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    
    oauth_tokens[access_token] = {
        "client_id": client_id,
        "scope": code_data["scope"],
        "expires_at": datetime.utcnow() + timedelta(hours=1),
        "refresh_token": refresh_token
    }
    
    # Clean up authorization code
    del oauth_codes[code]
    
    return OAuthTokenResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=3600,
        refresh_token=refresh_token,
        scope=code_data["scope"]
    )

# OAuth Discovery endpoint
@app.get("/.well-known/oauth-authorization-server")
async def oauth_discovery():
    """OAuth server metadata endpoint."""
    base_url = "https://fantasy-football-mcp-server-m4atkadqla-uc.a.run.app"
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "scopes_supported": ["read", "write"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    }

@app.get("/tools")
async def list_tools(api_key: str = Depends(verify_api_key)):
    """List available MCP tools."""
    try:
        # Get tools from the MCP server
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

@app.post("/mcp", response_model=MCPResponse)
async def handle_mcp_request(
    request: MCPRequest,
    api_key: str = Depends(verify_api_key)
):
    """Handle MCP protocol requests."""
    logger.info(f"MCP request: {request.method} with params: {request.params}")
    
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
                        "version": "1.0.0"
                    }
                },
                id=request.id
            )
        
        elif request.method == "tools/list":
            # Get tools from the MCP server
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
            
            try:
                # Use the MCP server's call_tool function
                result = await fantasy_football_multi_league.call_tool(tool_name, tool_args)
                
                # Convert TextContent result to MCP response format
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
            except Exception as e:
                logger.error(f"Tool execution error: {e}", exc_info=True)
                return MCPResponse(
                    error={
                        "code": -32603,
                        "message": f"Tool execution failed: {str(e)}"
                    },
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
        logger.error(f"MCP request handling error: {e}", exc_info=True)
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
            "detail": str(exc) if os.getenv("DEBUG") else "An unexpected error occurred"
        }
    )

if __name__ == "__main__":
    # Cloud Run sets PORT environment variable
    port = int(os.getenv("PORT", 8080))
    host = "0.0.0.0"
    
    logger.info(f"Starting Fantasy Football MCP Server on {host}:{port}")
    
    uvicorn.run(
        "cloud_run_server:app",
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        reload=False  # Disable reload in production
    )