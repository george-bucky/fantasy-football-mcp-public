"""Analytics MCP tool handlers."""

from src.services import analyze_reddit_sentiment


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
