#!/bin/bash

# Deploy Fantasy Football MCP Server to Render
# This script deploys the updated OAuth-compatible server

set -e

echo "🚀 Deploying Fantasy Football MCP Server to Render..."
echo "=================================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "render_server.py" ]; then
    echo "❌ Error: render_server.py not found. Please run this from the project root."
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found. Using .env.render as template..."
    cp .env.render .env
    echo "📝 Please edit .env with your Yahoo API credentials"
fi

echo -e "${BLUE}📦 Preparing deployment...${NC}"

# Ensure render_server.py is executable
chmod +x render_server.py

# Create a deployment message
DEPLOY_MSG="Deploy OAuth-compatible server for Claude.ai integration"
COMMIT_MSG="feat: Add flexible OAuth for Claude.ai compatibility

- Relaxed client_id and redirect_uri validation
- Added consent page for debugging
- File-based token storage for persistence
- Enhanced logging for OAuth debugging

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"

# Check git status
echo -e "${BLUE}📋 Checking git status...${NC}"
git status --short

# Stage changes
echo -e "${BLUE}📝 Staging changes...${NC}"
git add render_server.py render.yaml test_oauth.py .env.render deploy_to_render.sh

# Commit if there are changes
if ! git diff --cached --quiet; then
    echo -e "${BLUE}💾 Committing changes...${NC}"
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
echo "2. View logs to monitor OAuth attempts from Claude.ai"
echo "3. Update environment variables on Render dashboard:"
echo "   - Set DEBUG=true for detailed OAuth logs"
echo "   - Ensure ALLOWED_CLIENT_IDS includes '*' initially"
echo "   - Ensure ALLOWED_REDIRECT_URIS includes Claude.ai URLs"
echo ""
echo "4. Test OAuth flow:"
echo "   python test_oauth.py"
echo ""
echo "5. In Claude.ai, connect using:"
echo "   URL: https://your-app-name.onrender.com"
echo ""
echo "6. Monitor logs for actual client_id and redirect_uri from Claude.ai"
echo "   Then update environment variables to be more restrictive"
echo ""
echo "🔍 To view deployment logs:"
echo "   render logs your-app-name -o text"