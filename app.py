#!/usr/bin/env python3
"""
Main entry point for Render deployment
This file is automatically detected by Render
"""

# Import and run the Render-optimized server
from render_server import app
import uvicorn
import os

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )