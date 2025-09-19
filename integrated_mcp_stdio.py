#!/usr/bin/env python3
"""
Integrated MCP Server - STDIO Entry Point
Runs the integrated server with enhanced tools in stdio mode for local development.
"""

import asyncio
from integrated_mcp_server import integrated_server
from mcp.server.stdio import stdio_server

async def main():
    """Run the integrated MCP server in stdio mode."""
    async with stdio_server() as (read_stream, write_stream):
        await integrated_server.run(read_stream, write_stream, integrated_server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())