"""Compatibility entry point for legacy Render deployments.

Render-specific OAuth logic has been removed because fastmcp.cloud provides
its own authentication layer. Importing this module will simply expose the
FastMCP HTTP server defined in :mod:`fastmcp_server`.
"""

from __future__ import annotations

from fastmcp_server import main, run_http_server, server

__all__ = ["server", "run_http_server", "main"]


if __name__ == "__main__":
    main()
