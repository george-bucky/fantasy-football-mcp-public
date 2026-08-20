"""Analytics MCP tool handlers."""

from src.services import (
    analyze_reddit_sentiment,
    get_espn_nfl_news,
    get_rotowire_player_news,
)


async def handle_ff_analyze_reddit_sentiment(arguments: dict) -> dict:
    """Analyze Reddit sentiment for specified players.

    Args:
        arguments: Dict containing:
            - players: List of player names to analyze
            - time_window_hours: Time window in hours (default: 48)

    Returns:
        Dict with sentiment analysis results
    """
    players = arguments.get("players", [])
    time_window = arguments.get("time_window_hours", 48)

    if not players:
        return {"error": "No players specified for sentiment analysis"}

    return await analyze_reddit_sentiment(players, time_window)


async def handle_ff_get_player_news(arguments: dict) -> dict:
    """Get recent RotoWire NFL news, optionally filtered by player."""
    try:
        return await get_rotowire_player_news(
            players=arguments.get("players"),
            limit=arguments.get("limit", 5),
        )
    except (RuntimeError, ValueError) as exc:
        return {
            "status": "error",
            "source": "RotoWire NFL RSS",
            "error": str(exc),
        }


async def handle_ff_get_espn_nfl_news(arguments: dict) -> dict:
    """Get recent ESPN NFL news, optionally filtered by player."""
    try:
        return await get_espn_nfl_news(
            players=arguments.get("players"),
            limit=arguments.get("limit", 5),
        )
    except (RuntimeError, ValueError) as exc:
        return {
            "status": "error",
            "source": "ESPN NFL News API",
            "error": str(exc),
        }
