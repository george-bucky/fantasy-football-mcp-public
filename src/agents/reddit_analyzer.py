"""
Reddit Sentiment Analysis Agent for Fantasy Football
Analyzes Reddit discussions to gauge community sentiment on players
for lineup decisions.
"""

import asyncio
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import praw
from prawcore.exceptions import ResponseException
from loguru import logger
from textblob import TextBlob
import re
from collections import defaultdict

class RedditSentimentAgent:
    """Agent for analyzing Reddit sentiment about fantasy football players."""
    
    def __init__(self, settings):
        """Initialize the Reddit sentiment analyzer."""
        self.settings = settings
        self.reddit = None
        self._initialize_reddit()
        
        # Subreddits to search
        self.subreddits = [
            'fantasyfootball',
            'DynastyFF',
            'Fantasy_Football',
            'nfl'
        ]
        
        # Keywords that indicate strong sentiment
        self.positive_keywords = [
            'start', 'must start', 'locked in', 'smash play', 'league winner',
            'breakout', 'buy low', 'stud', 'elite', 'top tier', 'fire',
            'boom', 'upside', 'target', 'volume'
        ]
        
        self.negative_keywords = [
            'sit', 'bench', 'avoid', 'bust', 'injury', 'questionable',
            'limited', 'fade', 'risky', 'trap', 'decline', 'worry',
            'concern', 'struggling', 'drops'
        ]
        
        self.injury_keywords = [
            'injured', 'injury', 'out', 'doubtful', 'questionable', 'IR',
            'limited', 'DNP', 'game-time decision', 'setback'
        ]
    
    def _initialize_reddit(self):
        """Initialize Reddit API connection."""
        try:
            self.reddit = praw.Reddit(
                client_id=os.getenv('REDDIT_CLIENT_ID'),
                client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
                user_agent=f"fantasy-football-mcp:v{self.settings.mcp_server_version} by /u/{os.getenv('REDDIT_USERNAME', 'YourUsername')}"
            )
            # Test the connection
            self.reddit.user.me()
            logger.info("Reddit API connection established")
        except Exception as e:
            logger.warning(f"Reddit API initialization failed: {e}. Reddit sentiment will be unavailable.")
            self.reddit = None
    
    async def analyze_player_sentiment(
        self,
        player_name: str,
        time_window_hours: int = 48,
        max_posts: int = 50
    ) -> Dict[str, any]:
        """
        Analyze Reddit sentiment for a specific player.
        
        Args:
            player_name: Name of the player to analyze
            time_window_hours: How far back to look for posts (default 48 hours)
            max_posts: Maximum number of posts to analyze
            
        Returns:
            Dictionary containing sentiment analysis results
        """
        if not self.reddit:
            return self._empty_sentiment_result(player_name, "Reddit API not available")
        
        try:
            results = {
                'player': player_name,
                'posts_analyzed': 0,
                'comments_analyzed': 0,
                'overall_sentiment': 0.0,
                'sentiment_breakdown': {
                    'positive': 0,
                    'negative': 0,
                    'neutral': 0
                },
                'injury_mentions': 0,
                'hype_score': 0.0,
                'top_comments': [],
                'consensus': None,
                'timestamp': datetime.now().isoformat()
            }
            
            # Search across multiple subreddits
            all_posts = []
            for subreddit_name in self.subreddits:
                try:
                    subreddit = self.reddit.subreddit(subreddit_name)
                    posts = subreddit.search(
                        player_name,
                        time_filter='week',
                        limit=max_posts // len(self.subreddits)
                    )
                    all_posts.extend(posts)
                except Exception as e:
                    logger.debug(f"Error searching r/{subreddit_name}: {e}")
            
            # Analyze sentiment from posts and comments
            sentiment_scores = []
            relevant_comments = []
            
            for post in all_posts:
                # Skip old posts
                post_age = datetime.now() - datetime.fromtimestamp(post.created_utc)
                if post_age > timedelta(hours=time_window_hours):
                    continue
                
                results['posts_analyzed'] += 1
                
                # Analyze post title and selftext
                post_text = f"{post.title} {post.selftext}"
                if player_name.lower() in post_text.lower():
                    sentiment = self._calculate_sentiment(post_text)
                    sentiment_scores.append(sentiment)
                    
                    # Check for injury mentions
                    if any(keyword in post_text.lower() for keyword in self.injury_keywords):
                        results['injury_mentions'] += 1
                
                # Analyze top comments
                post.comments.replace_more(limit=0)
                for comment in post.comments.list()[:10]:  # Top 10 comments per post
                    if player_name.lower() in comment.body.lower():
                        results['comments_analyzed'] += 1
                        comment_sentiment = self._calculate_sentiment(comment.body)
                        sentiment_scores.append(comment_sentiment)
                        
                        # Store highly upvoted relevant comments
                        if comment.score > 5:
                            relevant_comments.append({
                                'text': comment.body[:200],
                                'score': comment.score,
                                'sentiment': comment_sentiment
                            })
            
            # Calculate aggregate metrics
            if sentiment_scores:
                results['overall_sentiment'] = sum(sentiment_scores) / len(sentiment_scores)
                
                # Categorize sentiments
                for score in sentiment_scores:
                    if score > 0.1:
                        results['sentiment_breakdown']['positive'] += 1
                    elif score < -0.1:
                        results['sentiment_breakdown']['negative'] += 1
                    else:
                        results['sentiment_breakdown']['neutral'] += 1
                
                # Calculate hype score (combination of volume and positivity)
                total_mentions = results['posts_analyzed'] + results['comments_analyzed']
                results['hype_score'] = (
                    (results['overall_sentiment'] + 1) / 2 *  # Normalize sentiment to 0-1
                    min(total_mentions / 20, 1.0)  # Volume factor, capped at 20 mentions
                )
                
                # Determine consensus
                positive_ratio = results['sentiment_breakdown']['positive'] / len(sentiment_scores)
                if positive_ratio > 0.6:
                    results['consensus'] = 'START'
                elif positive_ratio < 0.3:
                    results['consensus'] = 'SIT'
                else:
                    results['consensus'] = 'MIXED'
                
                # Get top comments
                relevant_comments.sort(key=lambda x: x['score'], reverse=True)
                results['top_comments'] = relevant_comments[:5]
            
            return results
            
        except Exception as e:
            logger.error(f"Error analyzing Reddit sentiment for {player_name}: {e}")
            return self._empty_sentiment_result(player_name, str(e))
    
    async def compare_players_sentiment(
        self,
        players: List[str],
        time_window_hours: int = 48
    ) -> Dict[str, any]:
        """
        Compare Reddit sentiment for multiple players (e.g., for Start/Sit decisions).
        
        Args:
            players: List of player names to compare
            time_window_hours: How far back to look for posts
            
        Returns:
            Comparison of sentiment analysis for all players
        """
        # Analyze all players in parallel
        tasks = [
            self.analyze_player_sentiment(player, time_window_hours)
            for player in players
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Create comparison summary
        comparison = {
            'players': players,
            'analysis': {player: result for player, result in zip(players, results)},
            'recommendation': None,
            'confidence': 0.0,
            'timestamp': datetime.now().isoformat()
        }
        
        # Determine recommendation based on sentiment
        if all(r['overall_sentiment'] is not None for r in results):
            # Sort by combined score (sentiment + hype)
            player_scores = [
                (player, result['overall_sentiment'], result['hype_score'])
                for player, result in zip(players, results)
            ]
            player_scores.sort(key=lambda x: x[1] + x[2], reverse=True)
            
            comparison['recommendation'] = {
                'start': player_scores[0][0],
                'sit': [p[0] for p in player_scores[1:]],
                'reasoning': self._generate_reasoning(player_scores, results)
            }
            
            # Calculate confidence based on sentiment difference
            if len(player_scores) > 1:
                score_diff = (player_scores[0][1] + player_scores[0][2]) - (player_scores[1][1] + player_scores[1][2])
                comparison['confidence'] = min(score_diff * 100, 100)
        
        return comparison
    
    def _calculate_sentiment(self, text: str) -> float:
        """
        Calculate sentiment score for text using TextBlob and keyword analysis.
        
        Returns:
            Float between -1 (negative) and 1 (positive)
        """
        # Clean text
        text = re.sub(r'http\S+', '', text)  # Remove URLs
        text = re.sub(r'[^\w\s]', ' ', text)  # Remove special characters
        text_lower = text.lower()
        
        # TextBlob sentiment
        blob = TextBlob(text)
        base_sentiment = blob.sentiment.polarity
        
        # Keyword adjustment
        keyword_score = 0
        for keyword in self.positive_keywords:
            if keyword in text_lower:
                keyword_score += 0.2
        
        for keyword in self.negative_keywords:
            if keyword in text_lower:
                keyword_score -= 0.2
        
        # Combine scores (weighted average)
        final_sentiment = (base_sentiment * 0.7) + (keyword_score * 0.3)
        
        # Clamp to [-1, 1]
        return max(-1, min(1, final_sentiment))
    
    def _empty_sentiment_result(self, player_name: str, error_msg: str) -> Dict:
        """Return empty sentiment result when analysis fails."""
        return {
            'player': player_name,
            'posts_analyzed': 0,
            'comments_analyzed': 0,
            'overall_sentiment': None,
            'sentiment_breakdown': {'positive': 0, 'negative': 0, 'neutral': 0},
            'injury_mentions': 0,
            'hype_score': 0.0,
            'top_comments': [],
            'consensus': None,
            'error': error_msg,
            'timestamp': datetime.now().isoformat()
        }
    
    def _generate_reasoning(
        self,
        player_scores: List[Tuple[str, float, float]],
        results: List[Dict]
    ) -> str:
        """Generate reasoning for the recommendation."""
        reasoning_parts = []
        
        for i, ((player, sentiment, hype), result) in enumerate(zip(player_scores, results)):
            if i == 0:
                reasoning_parts.append(
                    f"{player} has the strongest Reddit sentiment ({sentiment:.2f}) "
                    f"with {result['posts_analyzed']} posts and {result['comments_analyzed']} comments analyzed."
                )
                if result['injury_mentions'] > 0:
                    reasoning_parts.append(f"Note: {result['injury_mentions']} injury mentions found.")
            else:
                if sentiment < -0.1:
                    reasoning_parts.append(
                        f"{player} has negative sentiment ({sentiment:.2f}) - consider sitting."
                    )
        
        return " ".join(reasoning_parts)
