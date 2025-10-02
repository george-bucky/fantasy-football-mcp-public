#!/bin/bash

# Deploy Fantasy Football MCP Server to Render
# This script deploys the FastMCP server

set -e

echo "🚀 Deploying Fantasy Football MCP Server to Render..."
echo "=================================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "fastmcp_server.py" ]; then
    echo "❌ Error: fastmcp_server.py not found. Please run this from the project root."
    exit 1
fi

# Check if .env file exists (optional, for local testing)
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found. Ensure environment variables are set in Render dashboard."
fi

echo -e "${BLUE}📦 Preparing deployment...${NC}"

# Check git status
echo -e "${BLUE}📋 Checking git status...${NC}"
git status --short

# Stage changes
echo -e "${BLUE}📝 Staging changes...${NC}"
git add .

# Commit if there are changes
if ! git diff --cached --quiet; then
    echo -e "${BLUE}💾 Committing changes...${NC}"
    echo "Enter commit message (or press Enter for default):"
    read -r CUSTOM_MSG
    if [ -z "$CUSTOM_MSG" ]; then
        COMMIT_MSG="chore: Deploy FastMCP server updates

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"
    else
        COMMIT_MSG="$CUSTOM_MSG

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"
    fi
    git commit -m "$COMMIT_MSG"
else
    echo -e "${YELLOW}ℹ️  No changes to commit${NC}"
fi

# Push to main branch (Render auto-deploys from main)
echo -e "${BLUE}🔄 Pushing to GitHub...${NC}"
git push origin main

echo ""
echo -e "${GREEN}✅ Deployment initiated!${NC}"
echo ""
echo "📝 Next steps:"
echo "1. Check deployment status at: https://dashboard.render.com"
echo "2. Ensure environment variables are set in Render dashboard:"
echo "   - YAHOO_CONSUMER_KEY"
echo "   - YAHOO_CONSUMER_SECRET"
echo "   - YAHOO_ACCESS_TOKEN"
echo "   - YAHOO_REFRESH_TOKEN"
echo "   - YAHOO_GUID"
echo ""
echo "3. Monitor logs:"
echo "   render logs fantasy-football-mcp-server -o text"
echo ""
echo "4. Service URL: https://fantasy-football-mcp-server.onrender.com"