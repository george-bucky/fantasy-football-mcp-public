#!/usr/bin/env python3
"""
Fantasy Football MCP Server - No Authentication Version
Simple MCP server without OAuth for Claude.ai compatibility
"""

import asyncio
import json
import os
import logging
from typing import Any, Dict, Optional, Union
from datetime import datetime
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
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

class MCPRequest(BaseModel):
    """MCP request model."""
    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None

class MCPResponse(BaseModel):
    """MCP response model."""
    jsonrpc: str = "2.0"
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    logger.info("Starting No-Auth Fantasy Football MCP Server")
    
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
    title="Fantasy Football MCP Server (No Auth)",
    version="4.0.0",
    lifespan=lifespan
)

# CORS - Allow everything
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint
@app.get("/")
async def root():
    """Basic server info."""
    return {
        "name": "Fantasy Football MCP Server",
        "version": "4.0.0",
        "type": "no-auth",
        "description": "MCP server without authentication for Claude.ai",
        "endpoints": {
            "mcp": "/mcp",
            "mcp_sse": "/mcp/sse",
            "mcp_ws": "/mcp/ws",
            "tools": "/tools",
            "health": "/health"
        }
    }

# Health check
@app.get("/health")
async def health():
    """Health check endpoint."""
    yahoo_token = os.getenv("YAHOO_ACCESS_TOKEN")
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "tools_loaded": len(app.cached_tools) if hasattr(app, 'cached_tools') else 0,
        "yahoo_configured": bool(yahoo_token)
    }

# Tools endpoint for debugging
@app.get("/tools")
async def list_tools_debug():
    """List all available tools (debug endpoint)."""
    if hasattr(app, 'cached_tools'):
        return {
            "tools": app.cached_tools,
            "count": len(app.cached_tools)
        }
    return {"tools": [], "count": 0, "error": "Tools not loaded"}

# Main MCP endpoint - NO AUTHENTICATION
@app.post("/mcp")
async def mcp_handler(request: MCPRequest):
    """Handle MCP protocol requests without authentication."""
    logger.info(f"MCP request: {request.method}")
    
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
                        "version": "4.0.0"
                    }
                },
                id=request.id
            )
        
        elif request.method == "tools/list":
            return MCPResponse(
                result={"tools": app.cached_tools},
                id=request.id
            )
        
        elif request.method == "tools/call":
            tool_name = request.params.get("name") if request.params else None
            tool_args = request.params.get("arguments", {}) if request.params else {}
            
            if not tool_name or tool_name not in [t["name"] for t in app.cached_tools]:
                return MCPResponse(
                    error={
                        "code": -32602,
                        "message": f"Unknown tool: {tool_name}"
                    },
                    id=request.id
                )
            
            # Call the tool
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

# SSE endpoint for Claude.ai
@app.get("/mcp/sse")
async def mcp_sse():
    """Server-Sent Events endpoint for MCP - NO AUTH."""
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
            "X-Accel-Buffering": "no"
        }
    )

# WebSocket endpoint for MCP
@app.websocket("/mcp/ws")
async def mcp_websocket(websocket: WebSocket):
    """WebSocket endpoint for MCP protocol - NO AUTH."""
    await websocket.accept()
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
                            "version": "4.0.0"
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

# Alternative simplified MCP endpoint paths
@app.post("/")
async def mcp_root(request: MCPRequest):
    """Handle MCP at root for maximum compatibility."""
    return await mcp_handler(request)

@app.get("/sse")
async def sse_root():
    """SSE at root path."""
    return await mcp_sse()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    host = "0.0.0.0"
    
    logger.info(f"Starting No-Auth Fantasy Football MCP Server on {host}:{port}")
    logger.info("NO AUTHENTICATION REQUIRED - Server is public")
    
    uvicorn.run(
        "no_auth_server:app",
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        reload=False
    )