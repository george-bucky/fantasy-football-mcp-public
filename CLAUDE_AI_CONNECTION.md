# Connecting Claude.ai to Fantasy Football MCP Server

## Important: URL Must End with /mcp or /sse

Claude.ai requires the MCP server URL to end with either `/mcp` or `/sse`. This is a critical requirement!

## Connection URLs

Use ONE of these URLs when adding the server to Claude.ai:

### Option 1: HTTP/JSON-RPC (Recommended)
```
https://fantasy-football-mcp-server.onrender.com/mcp
```

### Option 2: Server-Sent Events
```
https://fantasy-football-mcp-server.onrender.com/mcp/sse
```

### Option 3: WebSocket
```
wss://fantasy-football-mcp-server.onrender.com/mcp/ws
```

## Step-by-Step Connection Guide

### In Claude.ai:

1. Go to Settings → Developer → MCP Servers
2. Click "Add Server"
3. Enter the server URL: `https://fantasy-football-mcp-server.onrender.com/mcp`
4. Claude.ai will automatically:
   - Discover OAuth endpoints
   - Initiate authorization flow
   - Register as a client (no credentials needed)
   - Complete the OAuth handshake

### What Happens Behind the Scenes:

1. **Discovery**: Claude.ai fetches `/.well-known/oauth-authorization-server` relative to the base URL
2. **Registration**: Claude.ai calls `/register` to get a client_id (optional)
3. **Authorization**: User is redirected to `/authorize` for consent
4. **Token Exchange**: Claude.ai exchanges the code for a token at `/token`
5. **MCP Connection**: Claude.ai connects to the MCP endpoint with the token

## Troubleshooting

### If Connection Fails:

1. **Check Server Status**:
   ```bash
   curl https://fantasy-football-mcp-server.onrender.com/health
   ```

2. **Verify MCP Endpoint**:
   ```bash
   curl -X POST https://fantasy-football-mcp-server.onrender.com/mcp \
     -H "Content-Type: application/json" \
     -d '{"method":"initialize","params":{},"id":1}'
   ```

3. **Check OAuth Discovery** (must work with /mcp prefix):
   ```bash
   curl https://fantasy-football-mcp-server.onrender.com/mcp/.well-known/oauth-authorization-server
   ```

### Common Issues:

- **Wrong URL**: Must end with `/mcp` or `/sse`, not just the domain
- **OAuth Discovery**: Must be accessible at `/mcp/.well-known/oauth-authorization-server`
- **CORS**: Server allows all origins, but check browser console for errors
- **Token Expiry**: Yahoo tokens expire hourly - server auto-refreshes

## Server Endpoints

### MCP Endpoints (for Claude.ai):
- `/mcp` - JSON-RPC over HTTP
- `/mcp/sse` - Server-Sent Events
- `/mcp/ws` - WebSocket

### OAuth Endpoints:
- `/.well-known/oauth-authorization-server` - OAuth discovery
- `/.well-known/oauth-protected-resource` - Resource metadata
- `/register` - Dynamic client registration
- `/authorize` - Authorization endpoint
- `/token` - Token exchange

### Available MCP Tools:
- `ff_get_leagues` - Get all your fantasy leagues
- `ff_build_lineup` - Build optimal lineup with strategy-based optimization
- `ff_get_waiver_wire` - Get top waiver wire pickups
- `ff_get_draft_recommendation` - Get draft recommendations
- And 12 more fantasy football tools...

## Monitoring Connection

Watch server logs during connection:
```bash
# If deployed on Render:
render logs fantasy-football-mcp-server --tail

# If running locally:
python simple_mcp_server.py
```

Look for:
- OAuth authorization requests
- Client registration attempts
- MCP initialize calls
- Any error messages

## Current Status

Server is deployed and running at:
https://fantasy-football-mcp-server.onrender.com

Last tested: Working with all MCP protocol methods