"""Reddit sentiment analysis for fantasy football players."""

import os
from typing import Any, Dict, List

# Reddit configuration
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")

# Check if Reddit packages are available
try:
    import praw
    from textblob import TextBlob

    REDDIT_AVAILABLE = True
except ImportError:
    REDDIT_AVAILABLE = False


async def analyze_reddit_sentiment(
    players: List[str], time_window_hours: int = 48
) -> Dict[str, Any]:
    """Analyze Reddit sentiment for fantasy football players using enhanced analyzer.

    Args:
        players: List of player names to analyze
        time_window_hours: Hours to look back for posts/comments

    Returns:
        Dictionary with sentiment analysis results for each player
    """
    try:
        # Import enhanced Reddit analyzer
        from src.agents.reddit_analyzer import RedditSentimentAgent

        # Create mock settings for the analyzer
        class MockSettings:
            mcp_server_version = "1.0.0"

        # Initialize enhanced analyzer
        analyzer = RedditSentimentAgent(MockSettings())

        # Analyze sentiment with enhanced error handling
        if len(players) == 1:
            # Single player analysis
            result = await analyzer.analyze_player_sentiment(players[0], time_window_hours)

            # Convert to legacy format for compatibility
            return {
                "players": players,
                "analysis_type": "single",
                "time_window_hours": time_window_hours,
                "player_data": {
                    players[0]: {
                        "sentiment_score": result.overall_sentiment or 0.0,
                        "consensus": result.consensus or "MIXED",
                        "posts_analyzed": result.posts_analyzed,
                        "comments_analyzed": result.comments_analyzed,
                        "injury_mentions": result.injury_mentions,
                        "hype_score": result.hype_score,
                        "top_comments": result.top_comments[:3],
                        "status": result.status,
                        "confidence": result.confidence,
                        "fallback_used": result.fallback_used,
                    }
                },
                "enhanced_analyzer": True,  # Flag to indicate enhanced version
            }
        else:
            # Multiple player comparison
            # TODO: Implement compare_players if needed; fallback to single analysis
            comparison = {
                "results": {
                    p: await analyzer.analyze_player_sentiment(p, time_window_hours)
                    for p in players
                }
            }

            # Convert results to legacy format
            player_data = {}
            for player_name, result in comparison.get("results", {}).items():
                player_data[player_name] = {
                    "sentiment_score": result.overall_sentiment or 0.0,
                    "consensus": result.consensus or "MIXED",
                    "posts_analyzed": result.posts_analyzed,
                    "comments_analyzed": result.comments_analyzed,
                    "injury_mentions": result.injury_mentions,
                    "hype_score": result.hype_score,
                    "top_comments": result.top_comments[:3],
                    "status": result.status,
                    "confidence": result.confidence,
                    "fallback_used": result.fallback_used,
                }

            return {
                "players": players,
                "analysis_type": "comparison",
                "time_window_hours": time_window_hours,
                "player_data": player_data,
                "recommendation": comparison.get("recommendation", {}),
                "confidence": comparison.get("confidence", 0),
                "successful_analyses": comparison.get("successful_analyses", 0),
                "total_players": comparison.get("total_players", len(players)),
                "timestamp": comparison.get("timestamp", ""),
                "enhanced_analyzer": True,  # Flag to indicate enhanced version
            }

        # Clean up
        await analyzer.cleanup()

    except ImportError as e:
        # Fallback to basic implementation if enhanced analyzer not available
        return await _analyze_reddit_sentiment_fallback(
            players, time_window_hours, f"Enhanced analyzer unavailable: {e}"
        )
    except Exception as e:
        # Fallback to basic implementation on any error
        return await _analyze_reddit_sentiment_fallback(
            players, time_window_hours, f"Enhanced analyzer failed: {e}"
        )


async def _analyze_reddit_sentiment_fallback(
    players: List[str], time_window_hours: int = 48, error_reason: str = ""
) -> Dict[str, Any]:
    """Fallback Reddit sentiment analysis using basic implementation.

    Args:
        players: List of player names to analyze
        time_window_hours: Hours to look back for posts/comments
        error_reason: Reason for using fallback

    Returns:
        Dictionary with basic sentiment analysis results
    """
    if not REDDIT_AVAILABLE:
        return {
            "error": "Reddit analysis not available. Install 'praw' and 'textblob' packages.",
            "fallback_reason": error_reason,
        }

    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        return {"error": "Reddit API credentials not configured", "fallback_reason": error_reason}

    try:
        # Initialize Reddit client
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=f'fantasy-football-mcp:v1.0 by /u/{REDDIT_USERNAME or "unknown"}',
        )

        results = {
            "players": players,
            "analysis_type": "comparison" if len(players) > 1 else "single",
            "time_window_hours": time_window_hours,
            "player_data": {},
            "fallback_used": True,
            "fallback_reason": error_reason,
        }

        subreddits = ["fantasyfootball", "DynastyFF", "Fantasy_Football", "nfl"]

        for player in players:
            player_sentiments = []
            total_posts = 0
            total_engagement = 0
            injury_mentions = 0
            relevant_comments = []

            # Search across subreddits
            for subreddit_name in subreddits:
                try:
                    subreddit = reddit.subreddit(subreddit_name)
                    posts = list(subreddit.search(player, time_filter="week", limit=5))

                    for post in posts:
                        total_posts += 1
                        total_engagement += post.score + post.num_comments

                        # Analyze sentiment
                        text = f"{post.title} {post.selftext[:500] if post.selftext else ''}"
                        blob = TextBlob(text)
                        sentiment_obj = blob.sentiment
                        sentiment = getattr(sentiment_obj, "polarity", 0.0)
                        player_sentiments.append(sentiment)

                        # Check for injuries
                        injury_keywords = [
                            "injured",
                            "injury",
                            "out",
                            "doubtful",
                            "questionable",
                            "IR",
                        ]
                        if any(keyword.lower() in text.lower() for keyword in injury_keywords):
                            injury_mentions += 1

                        # Get top comments
                        if post.score > 10:
                            relevant_comments.append(
                                {
                                    "text": post.title[:100],
                                    "score": post.score,
                                    "sentiment": sentiment,
                                }
                            )
                except Exception:
                    continue

            # Calculate metrics
            avg_sentiment = (
                sum(player_sentiments) / len(player_sentiments) if player_sentiments else 0
            )

            # Determine consensus
            if avg_sentiment > 0.1:
                consensus = "START"
            elif avg_sentiment < -0.1:
                consensus = "SIT"
            else:
                consensus = "MIXED"

            # Calculate hype score (combination of sentiment and engagement)
            hype_score = ((avg_sentiment + 1) / 2) * min(total_engagement / 100, 1.0)

            results["player_data"][player] = {
                "sentiment_score": round(avg_sentiment, 3),
                "consensus": consensus,
                "posts_analyzed": total_posts,
                "total_engagement": total_engagement,
                "injury_mentions": injury_mentions,
                "hype_score": round(hype_score, 3),
                "top_comments": sorted(relevant_comments, key=lambda x: x["score"], reverse=True)[
                    :3
                ],
            }

        # Add comparison recommendation if multiple players
        if len(players) > 1:
            sorted_players = sorted(
                results["player_data"].items(),
                key=lambda x: x[1]["sentiment_score"] + x[1]["hype_score"],
                reverse=True,
            )

            results["recommendation"] = {
                "start": sorted_players[0][0],
                "sit": [p[0] for p in sorted_players[1:]],
                "confidence": min(
                    abs(
                        sorted_players[0][1]["sentiment_score"]
                        - sorted_players[-1][1]["sentiment_score"]
                    )
                    * 100,
                    100,
                ),
            }

        return results

    except Exception as e:
        return {"error": f"Reddit analysis failed: {str(e)}"}
