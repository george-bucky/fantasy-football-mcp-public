#!/bin/bash

# Run Fantasy Football MCP Server locally for Claude Code
# This script starts the MCP server in stdio mode for Claude Code

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🏈 Starting Fantasy Football MCP Server for Claude Code...${NC}"

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  Warning: .env file not found${NC}"
    exit 1
fi

# Source environment variables
source .env

# Export required Yahoo API credentials
export YAHOO_CONSUMER_KEY
export YAHOO_CONSUMER_SECRET
export YAHOO_ACCESS_TOKEN
export YAHOO_REFRESH_TOKEN
export YAHOO_GUID

# Run the MCP server in stdio mode
echo -e "${GREEN}✅ MCP Server running in stdio mode${NC}"
echo -e "${BLUE}Connect from Claude Code using the configuration below${NC}"

# Run the integrated MCP server with enhanced tools in stdio mode
python integrated_mcp_stdio.py