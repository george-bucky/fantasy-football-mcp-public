#!/usr/bin/env python3
"""
Fantasy Football MCP Server - Google Cloud Run HTTP Wrapper
FastAPI-based HTTP server that wraps the Fantasy Football MCP server for Cloud Run deployment.
"""

import asyncio
import json
import os
import logging
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Import the existing MCP server components
import fantasy_football_multi_league as mcp_server

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
    """Verify API key authentication."""
    if credentials.credentials != MCP_API_KEY:
        logger.warning(f"Invalid API key attempt: {credentials.credentials[:10]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

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
            "tools": "/tools"
        }
    }

@app.get("/tools")
async def list_tools(api_key: str = Depends(verify_api_key)):
    """List available MCP tools."""
    try:
        # Get tools from the MCP server
        tools = await mcp_server.list_tools()
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
            tools = await mcp_server.list_tools()
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
                result = await mcp_server.call_tool(tool_name, tool_args)
                
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