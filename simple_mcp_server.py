#!/usr/bin/env python3
"""
Simplified Fantasy Football MCP Server for Claude.ai
Based on SimpleScraper's OAuth implementation pattern
"""

import asyncio
import json
import os
import logging
import secrets
import hashlib
import base64
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Query, Form, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, StreamingResponse
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

# Simple in-memory storage (replace with Redis/DB in production)
registered_clients = {}
authorization_codes = {}
access_tokens = {}

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

class ClientRegistration(BaseModel):
    """OAuth client registration request."""
    client_name: str
    redirect_uris: List[str]
    grant_types: List[str] = ["authorization_code"]
    response_types: List[str] = ["code"]
    scope: str = "read write"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    logger.info("Starting Simplified MCP Server")
    
    # Preload tools for performance
    try:
        tools = await fantasy_football_multi_league.list_tools()
        app.cached_tools = []
        for tool in tools:
            app.cached_tools.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema
            })
        logger.info(f"Preloaded {len(app.cached_tools)} tools")
    except Exception as e:
        logger.error(f"Failed to preload tools: {e}")
        app.cached_tools = []
    
    yield
    logger.info("Shutting down MCP Server")

# Create FastAPI app
app = FastAPI(
    title="Fantasy Football MCP Server",
    version="3.0.0",
    lifespan=lifespan
)

# CORS - Allow everything for Claude.ai
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OAuth Discovery Endpoints (SimpleScraper style)
# Serve at both root and under /mcp for Claude.ai compatibility
@app.get("/.well-known/oauth-authorization-server")
@app.get("/mcp/.well-known/oauth-authorization-server")
@app.get("/sse/.well-known/oauth-authorization-server")
async def oauth_authorization_server():
    """OAuth authorization server metadata."""
    base_url = os.getenv("RENDER_EXTERNAL_URL", "https://fantasy-football-mcp-server.onrender.com")
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "registration_endpoint": f"{base_url}/register",
        "token_endpoint_auth_methods_supported": ["none"],  # No client auth required
        "scopes_supported": ["read", "write"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"]  # PKCE support
    }

@app.get("/.well-known/oauth-protected-resource")
@app.get("/mcp/.well-known/oauth-protected-resource")
@app.get("/sse/.well-known/oauth-protected-resource")
async def oauth_protected_resource():
    """OAuth protected resource metadata."""
    base_url = os.getenv("RENDER_EXTERNAL_URL", "https://fantasy-football-mcp-server.onrender.com")
    return {
        # Minimal list used by some clients
        "authorization_servers": [
            {
                "issuer": base_url,
                "authorization_endpoint": f"{base_url}/authorize"
            }
        ],
        # Additional fields used by other clients
        "resource": base_url,
        "oauth_authorization_server": f"{base_url}/.well-known/oauth-authorization-server",
        "scopes_supported": ["read", "write"],
        "bearer_methods_supported": ["header"]
    }

# Public tools endpoint to manually verify tool discovery
@app.get("/tools")
async def list_tools_public():
    try:
        tools = await fantasy_football_multi_league.list_tools()
        tools_info = []
        for tool in tools:
            tools_info.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema
            })
        return {"tools": tools_info, "count": len(tools_info)}
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        return {"tools": [], "count": 0, "error": str(e)}

# Dynamic Client Registration (SimpleScraper style)
@app.post("/register")
async def register_client(registration: ClientRegistration):
    """Dynamic OAuth client registration."""
    client_id = secrets.token_urlsafe(32)
    client_secret = secrets.token_urlsafe(32)
    
    # Store client info
    registered_clients[client_id] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": registration.client_name,
        "redirect_uris": registration.redirect_uris,
        "grant_types": registration.grant_types,
        "response_types": registration.response_types,
        "scope": registration.scope,
        "created_at": datetime.utcnow().isoformat()
    }
    
    logger.info(f"Registered new client: {registration.client_name} ({client_id})")
    
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": registration.client_name,
        "redirect_uris": registration.redirect_uris,
        "grant_types": registration.grant_types,
        "response_types": registration.response_types
    }

# OAuth Authorization Endpoint
@app.get("/authorize")
async def authorize(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    code_challenge: Optional[str] = Query(None),
    code_challenge_method: Optional[str] = Query(None)
):
    """OAuth authorization endpoint with PKCE support."""
    logger.info(f"Authorization request: client_id={client_id}, redirect_uri={redirect_uri}")
    
    # For simplicity, auto-approve all requests
    # In production, show a consent screen
    
    # Generate authorization code
    code = secrets.token_urlsafe(32)
    
    # Store authorization details
    authorization_codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope or "read write",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "expires_at": (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    }
    
    # Redirect back to client
    callback_url = f"{redirect_uri}?code={code}"
    if state:
        callback_url += f"&state={state}"
    
    logger.info(f"Redirecting to: {callback_url}")
    return RedirectResponse(url=callback_url, status_code=302)

# OAuth Token Endpoint
@app.post("/token")
async def token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None)
):
    """OAuth token endpoint with PKCE verification."""
    logger.info(f"Token request: grant_type={grant_type}, client_id={client_id}")
    
    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant_type")
    
    # Validate authorization code
    if code not in authorization_codes:
        raise HTTPException(status_code=400, detail="Invalid authorization code")
    
    auth_details = authorization_codes[code]
    
    # Check expiration
    if datetime.fromisoformat(auth_details["expires_at"]) < datetime.utcnow():
        del authorization_codes[code]
        raise HTTPException(status_code=400, detail="Authorization code expired")
    
    # Verify PKCE if present
    if auth_details.get("code_challenge") and code_verifier:
        # Verify S256 challenge
        verifier_hash = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode().rstrip("=")
        
        if verifier_hash != auth_details["code_challenge"]:
            raise HTTPException(status_code=400, detail="Invalid code_verifier")
    
    # Generate access token
    access_token = secrets.token_urlsafe(32)
    
    # Store token
    access_tokens[access_token] = {
        "client_id": client_id or auth_details["client_id"],
        "scope": auth_details["scope"],
        "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat()
    }
    
    # Clean up used code
    del authorization_codes[code]
    
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 86400,
        "scope": auth_details["scope"]
    }

# MCP Endpoints (No auth required for testing)
@app.post("/mcp")
@app.post("/mcp/message")  # Alternative endpoint Claude.ai might use
async def mcp_handler(
    request: MCPRequest,
    authorization: Optional[str] = Header(None)
):
    """Handle MCP protocol requests."""
    # Log request details for debugging
    logger.info(f"MCP request: {request.method}")
    logger.info(f"Auth header: {authorization[:20] if authorization else 'None'}")
    logger.info(f"Request ID: {request.id}")
    logger.info(f"Request params: {request.params}")
    
    try:
        if request.method == "initialize":
            return MCPResponse(
                result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": True},
                        "resources": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": "fantasy-football-mcp",
                        "version": "3.0.0"
                    }
                },
                id=request.id
            )
        
        elif request.method == "tools/list":
            # Use cached tools for fast response
            return MCPResponse(
                result={"tools": app.cached_tools},
                id=request.id
            )
        
        elif request.method == "tools/call":
            tool_name = request.params.get("name") if request.params else None
            tool_args = request.params.get("arguments", {}) if request.params else {}
            
            # Call the actual tool
            result = await fantasy_football_multi_league.call_tool(tool_name, tool_args)
            
            # Format response
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
        logger.error(f"MCP error: {e}", exc_info=True)
        return MCPResponse(
            error={
                "code": -32603,
                "message": str(e)
            },
            id=request.id
        )

# Root endpoint
@app.get("/")
async def root():
    """Basic server info."""
    return {
        "name": "Fantasy Football MCP Server",
        "version": "3.0.0",
        "type": "simplified",
        "oauth": "SimpleScraper-style with PKCE",
        "endpoints": {
            "mcp": "/mcp",
            "oauth_discovery": "/.well-known/oauth-authorization-server",
            "oauth_resource": "/.well-known/oauth-protected-resource",
            "register": "/register",
            "authorize": "/authorize",
            "token": "/token"
        }
    }

# Health check
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# SSE endpoint for Claude.ai (if it prefers SSE)
@app.get("/mcp/sse")
async def mcp_sse(authorization: Optional[str] = Header(None)):
    """Server-Sent Events endpoint for MCP."""
    async def event_generator():
        # Send initial connection event
        yield f"data: {json.dumps({'type': 'connection', 'status': 'connected'})}\n\n"
        
        # Keep connection alive
        while True:
            await asyncio.sleep(30)
            yield f"data: {json.dumps({'type': 'ping'})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable Nginx buffering
        }
    )

# WebSocket endpoint for MCP (Claude.ai likely uses this)
@app.websocket("/mcp")
@app.websocket("/mcp/ws")
async def mcp_websocket(websocket: WebSocket):
    """WebSocket endpoint for MCP protocol."""
    # Echo back requested subprotocol (e.g., 'mcp') if provided by client
    requested_subprotocols = websocket.headers.get("sec-websocket-protocol")
    selected_subprotocol = None
    if requested_subprotocols:
        # Header may be a comma-separated list
        requested = [p.strip() for p in requested_subprotocols.split(",")]
        if "mcp" in requested:
            selected_subprotocol = "mcp"
        elif requested:
            selected_subprotocol = requested[0]
    await websocket.accept(subprotocol=selected_subprotocol)
    logger.info("WebSocket connection accepted")
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            request = json.loads(data)
            logger.info(f"WebSocket MCP request: {request.get('method')}")
            
            # Process MCP request
            if request.get("method") == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {"listChanged": True},
                            "resources": {"listChanged": False}
                        },
                        "serverInfo": {
                            "name": "fantasy-football-mcp",
                            "version": "3.0.0"
                        }
                    },
                    "id": request.get("id")
                }
            elif request.get("method") == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "result": {"tools": app.cached_tools},
                    "id": request.get("id")
                }
            elif request.get("method") == "tools/call":
                tool_name = request.get("params", {}).get("name")
                tool_args = request.get("params", {}).get("arguments", {})
                
                try:
                    result = await fantasy_football_multi_league.call_tool(tool_name, tool_args)
                    content = []
                    for text_content in result:
                        content.append({
                            "type": "text",
                            "text": text_content.text
                        })
                    response = {
                        "jsonrpc": "2.0",
                        "result": {"content": content},
                        "id": request.get("id")
                    }
                except Exception as e:
                    response = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32603,
                            "message": str(e)
                        },
                        "id": request.get("id")
                    }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {request.get('method')}"
                    },
                    "id": request.get("id")
                }
            
            # Send response
            await websocket.send_text(json.dumps(response))
            
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()

# Additional transport endpoint
@app.options("/mcp")
@app.options("/mcp/message")
async def mcp_options():
    """Handle OPTIONS requests for CORS preflight."""
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400"
        }
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")