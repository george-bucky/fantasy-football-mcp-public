"""Compatibility shim for the previous simple MCP server implementation."""

from __future__ import annotations

from fastmcp_server import main, run_http_server, server

__all__ = ["server", "run_http_server", "main"]


if __name__ == "__main__":
    main()
