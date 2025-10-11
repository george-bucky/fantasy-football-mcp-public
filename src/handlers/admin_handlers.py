"""Admin and system management handlers for MCP tools."""

from typing import Dict

from src.api import refresh_yahoo_token
from src.api.yahoo_utils import rate_limiter, response_cache


async def handle_ff_refresh_token(arguments: Dict) -> Dict:
    """Refresh the Yahoo OAuth access token.

    Args:
        arguments: Empty dict (no arguments required)

    Returns:
        Status dict with refresh result
    """
    return await refresh_yahoo_token()


async def handle_ff_get_api_status(arguments: Dict) -> Dict:
    """Get current API rate limit and cache status.

    Args:
        arguments: Empty dict (no arguments required)

    Returns:
        Dict with rate_limit and cache statistics
    """
    return {
        "rate_limit": rate_limiter.get_status(),
        "cache": response_cache.get_stats(),
    }


async def handle_ff_clear_cache(arguments: Dict) -> Dict:
    """Clear the Yahoo API response cache.

    Args:
        arguments: Optional 'pattern' to clear specific cache entries

    Returns:
        Status dict confirming cache clear
    """
    pattern = arguments.get("pattern")
    await response_cache.clear(pattern)
    suffix = f" for pattern: {pattern}" if pattern else " completely"
    return {
        "status": "success",
        "message": f"Cache cleared{suffix}",
    }
