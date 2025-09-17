"""
Reddit Sentiment Analysis Agent for Fantasy Football
Analyzes Reddit discussions to gauge community sentiment on players
for lineup decisions with robust error handling and async support.
"""

import asyncio
import logging
import os
import re
import time
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import with error handling
try:
    import praw
    from prawcore.exceptions import ResponseException, RequestException, ServerError, TooManyRequests
    PRAW_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import praw: {e}")
    praw = None
    PRAW_AVAILABLE = False
    ResponseException = Exception
    RequestException = Exception
    ServerError = Exception
    TooManyRequests = Exception

try:
    from textblob import TextBlob
    TEXTBLOB_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import textblob: {e}")
    TextBlob = None
    TEXTBLOB_AVAILABLE = False


class SentimentModel(str, Enum):
    """Available sentiment analysis models."""
    TEXTBLOB = "textblob"
    KEYWORD_BASED = "keyword_based"
    HYBRID = "hybrid"


class RedditAPIStatus(str, Enum):
    """Reddit API status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"


@dataclass
class RedditAnalysisResult:
    """Structured result for Reddit sentiment analysis."""
    player: str
    status: str = "success"  # success, partial, error
    posts_analyzed: int = 0
    comments_analyzed: int = 0
    overall_sentiment: Optional[float] = None
    sentiment_breakdown: Dict[str, int] = field(default_factory=lambda: {'positive': 0, 'negative': 0, 'neutral': 0})
    injury_mentions: int = 0
    hype_score: float = 0.0
    top_comments: List[Dict] = field(default_factory=list)
    consensus: Optional[str] = None
    confidence: float = 0.0
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    data_quality: Dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False


@dataclass
class RateLimitInfo:
    """Reddit API rate limit information."""
    requests_remaining: int
    requests_used: int
    reset_timestamp: int
    is_rate_limited: bool = False

class RedditSentimentAgent:
    """Enhanced Reddit sentiment analyzer with robust error handling and async support."""
    
    def __init__(self, settings, max_workers: int = 2):
        """Initialize the Reddit sentiment analyzer."""
        self.settings = settings
        self.reddit = None
        self.max_workers = max_workers
        self.thread_executor = ThreadPoolExecutor(max_workers=max_workers)
        self.api_status = RedditAPIStatus.UNAVAILABLE
        self.rate_limit_info = None
        self.last_request_time = 0.0
        self.min_request_interval = 1.0  # Minimum seconds between requests
        
        # Enhanced keywords for better sentiment analysis
        self.positive_keywords = [
            'start', 'must start', 'locked in', 'smash play', 'league winner',
            'breakout', 'buy low', 'stud', 'elite', 'top tier', 'fire',
            'boom', 'upside', 'target', 'volume', 'confident', 'strong play',
            'sleeper pick', 'value play', 'bounce back', 'great matchup',
            'high ceiling', 'safe floor', 'consistent', 'reliable', 'hot streak'
        ]
        
        self.negative_keywords = [
            'sit', 'bench', 'avoid', 'bust', 'injury', 'questionable',
            'limited', 'fade', 'risky', 'trap', 'decline', 'worry',
            'concern', 'struggling', 'drops', 'bad matchup', 'tough defense',
            'committee', 'splitting carries', 'target share', 'touchdown dependent',
            'inconsistent', 'unreliable', 'cold streak', 'regression'
        ]
        
        self.injury_keywords = [
            'injured', 'injury', 'out', 'doubtful', 'questionable', 'IR',
            'limited', 'DNP', 'game-time decision', 'setback', 'hamstring',
            'ankle', 'knee', 'shoulder', 'concussion', 'protocol', 'strain',
            'sprain', 'tear', 'surgery', 'week-to-week', 'day-to-day'
        ]
        
        # Subreddits to search with priority order
        self.subreddits = [
            {'name': 'fantasyfootball', 'weight': 1.0, 'priority': 1},
            {'name': 'DynastyFF', 'weight': 0.8, 'priority': 2},
            {'name': 'Fantasy_Football', 'weight': 0.7, 'priority': 3},
            {'name': 'nfl', 'weight': 0.5, 'priority': 4}
        ]
        
        # Cache for sentiment analysis to avoid re-processing
        self.sentiment_cache = {}
        
        # Initialize Reddit connection
        self._initialize_reddit()
    
    def _initialize_reddit(self):
        """Initialize Reddit API connection with comprehensive error handling."""
        if not PRAW_AVAILABLE:
            logger.warning("PRAW not available - Reddit sentiment analysis will be unavailable")
            self.api_status = RedditAPIStatus.UNAVAILABLE
            return
        
        try:
            # Get Reddit credentials from environment
            client_id = os.getenv('REDDIT_CLIENT_ID')
            client_secret = os.getenv('REDDIT_CLIENT_SECRET')
            username = os.getenv('REDDIT_USERNAME', 'unknown')
            
            if not client_id or not client_secret:
                logger.warning("Reddit API credentials not configured - sentiment analysis will be unavailable")
                self.api_status = RedditAPIStatus.UNAVAILABLE
                return
            
            self.reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=f"fantasy-football-mcp:v{getattr(self.settings, 'mcp_server_version', '1.0')} by /u/{username}"
            )
            
            # Test the connection with timeout
            try:
                # This is a lightweight call to test connectivity
                self.reddit.auth.limits
                self.api_status = RedditAPIStatus.HEALTHY
                logger.info("Reddit API connection established successfully")
            except Exception as e:
                logger.warning(f"Reddit API connection test failed: {e}")
                self.api_status = RedditAPIStatus.DEGRADED
                
        except Exception as e:
            logger.error(f"Reddit API initialization failed: {e}")
            self.reddit = None
            self.api_status = RedditAPIStatus.UNAVAILABLE
    
    async def analyze_player_sentiment(
        self,
        player_name: str,
        time_window_hours: int = 48,
        max_posts: int = 50,
        sentiment_model: SentimentModel = SentimentModel.HYBRID
    ) -> RedditAnalysisResult:
        """
        Analyze Reddit sentiment for a specific player with comprehensive error handling.
        
        Args:
            player_name: Name of the player to analyze
            time_window_hours: How far back to look for posts (default 48 hours)
            max_posts: Maximum number of posts to analyze
            sentiment_model: Sentiment analysis model to use
            
        Returns:
            RedditAnalysisResult with comprehensive analysis data
        """
        logger.info(f"Starting Reddit sentiment analysis for {player_name}")
        
        result = RedditAnalysisResult(player=player_name)
        
        # Check API availability
        if not self._is_reddit_available():
            result.status = "error"
            result.errors.append("Reddit API not available")
            result.fallback_used = True
            return await self._generate_fallback_sentiment(player_name, result)
        
        try:
            # Rate limiting check
            await self._wait_for_rate_limit()
            
            # Get Reddit data asynchronously
            reddit_data = await self._fetch_reddit_data_async(player_name, time_window_hours, max_posts)
            
            if not reddit_data['posts'] and not reddit_data['comments']:
                result.status = "error"
                result.errors.append("No Reddit data found for player")
                result.fallback_used = True
                return await self._generate_fallback_sentiment(player_name, result)
            
            # Analyze sentiment with multiple approaches
            sentiment_results = await self._analyze_sentiment_data(
                reddit_data, sentiment_model, player_name
            )
            
            # Populate result
            result.posts_analyzed = reddit_data['stats']['posts_analyzed']
            result.comments_analyzed = reddit_data['stats']['comments_analyzed']
            result.overall_sentiment = sentiment_results['overall_sentiment']
            result.sentiment_breakdown = sentiment_results['sentiment_breakdown']
            result.injury_mentions = sentiment_results['injury_mentions']
            result.hype_score = sentiment_results['hype_score']
            result.top_comments = sentiment_results['top_comments']
            result.consensus = sentiment_results['consensus']
            result.confidence = sentiment_results['confidence']
            result.data_quality = reddit_data['stats']
            
            # Determine final status
            if result.posts_analyzed == 0 and result.comments_analyzed == 0:
                result.status = "error"
                result.errors.append("No analyzable content found")
            elif result.posts_analyzed < 3 and result.comments_analyzed < 10:
                result.status = "partial"
                result.errors.append("Limited data available - results may be unreliable")
            else:
                result.status = "success"
            
            logger.info(f"Reddit analysis complete for {player_name}: {result.status}")
            return result
            
        except TooManyRequests as e:
            logger.warning(f"Reddit API rate limited for {player_name}: {e}")
            result.status = "error"
            result.errors.append("Reddit API rate limited")
            result.fallback_used = True
            self.api_status = RedditAPIStatus.RATE_LIMITED
            return await self._generate_fallback_sentiment(player_name, result)
            
        except (RequestException, ServerError) as e:
            logger.error(f"Reddit API error for {player_name}: {e}")
            result.status = "error"
            result.errors.append(f"Reddit API error: {str(e)}")
            result.fallback_used = True
            self.api_status = RedditAPIStatus.DEGRADED
            return await self._generate_fallback_sentiment(player_name, result)
            
        except Exception as e:
            logger.error(f"Unexpected error analyzing {player_name}: {e}")
            result.status = "error"
            result.errors.append(f"Unexpected error: {str(e)}")
            result.fallback_used = True
            return await self._generate_fallback_sentiment(player_name, result)
    
    async def _fetch_reddit_data_async(
        self, 
        player_name: str, 
        time_window_hours: int, 
        max_posts: int
    ) -> Dict[str, Any]:
        """Fetch Reddit data asynchronously using thread executor."""
        
        def _fetch_reddit_data_sync():
            """Synchronous Reddit data fetching to run in thread."""
            posts_data = []
            comments_data = []
            stats = {
                'posts_analyzed': 0,
                'comments_analyzed': 0,
                'subreddits_searched': 0,
                'api_calls_made': 0,
                'errors': []
            }
            
            cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
            
            for subreddit_info in self.subreddits:
                try:
                    subreddit_name = subreddit_info['name']
                    subreddit_weight = subreddit_info['weight']
                    
                    subreddit = self.reddit.subreddit(subreddit_name)
                    posts_limit = max(5, max_posts // len(self.subreddits))
                    
                    # Search for posts mentioning the player
                    posts = subreddit.search(
                        player_name,
                        time_filter='week',
                        limit=posts_limit,
                        sort='relevance'
                    )
                    
                    stats['api_calls_made'] += 1
                    stats['subreddits_searched'] += 1
                    
                    for post in posts:
                        # Check if post is within time window
                        post_time = datetime.fromtimestamp(post.created_utc)
                        if post_time < cutoff_time:
                            continue
                        
                        # Filter for relevance
                        post_text = f"{post.title} {post.selftext}"
                        if player_name.lower() not in post_text.lower():
                            continue
                        
                        posts_data.append({
                            'text': post_text,
                            'score': post.score,
                            'num_comments': post.num_comments,
                            'created_utc': post.created_utc,
                            'subreddit': subreddit_name,
                            'weight': subreddit_weight,
                            'url': post.url
                        })
                        
                        stats['posts_analyzed'] += 1
                        
                        # Analyze comments
                        try:
                            post.comments.replace_more(limit=0)
                            comment_count = 0
                            
                            for comment in post.comments.list()[:10]:  # Top 10 comments
                                if comment_count >= 10:  # Limit comments per post
                                    break
                                
                                if player_name.lower() in comment.body.lower():
                                    comments_data.append({
                                        'text': comment.body,
                                        'score': comment.score,
                                        'created_utc': comment.created_utc,
                                        'subreddit': subreddit_name,
                                        'weight': subreddit_weight
                                    })
                                    
                                    stats['comments_analyzed'] += 1
                                    comment_count += 1
                        
                        except Exception as e:
                            stats['errors'].append(f"Error processing comments for post: {str(e)}")
                            
                except Exception as e:
                    error_msg = f"Error searching r/{subreddit_info['name']}: {str(e)}"
                    stats['errors'].append(error_msg)
                    logger.debug(error_msg)
            
            return {
                'posts': posts_data,
                'comments': comments_data,
                'stats': stats
            }
        
        # Run the synchronous Reddit API calls in a thread
        try:
            loop = asyncio.get_event_loop()
            reddit_data = await loop.run_in_executor(
                self.thread_executor, 
                _fetch_reddit_data_sync
            )
            return reddit_data
            
        except Exception as e:
            logger.error(f"Error in async Reddit data fetch: {e}")
            return {
                'posts': [],
                'comments': [],
                'stats': {
                    'posts_analyzed': 0,
                    'comments_analyzed': 0,
                    'subreddits_searched': 0,
                    'api_calls_made': 0,
                    'errors': [str(e)]
                }
            }
    
    async def _analyze_sentiment_data(
        self, 
        reddit_data: Dict[str, Any], 
        sentiment_model: SentimentModel,
        player_name: str
    ) -> Dict[str, Any]:
        """Analyze sentiment from Reddit data using specified model."""
        
        all_content = []
        weighted_sentiments = []
        injury_mentions = 0
        top_comments = []
        
        # Process posts
        for post in reddit_data['posts']:
            content_data = {
                'text': post['text'],
                'score': post['score'],
                'weight': post['weight'],
                'type': 'post',
                'subreddit': post['subreddit']
            }
            all_content.append(content_data)
        
        # Process comments
        for comment in reddit_data['comments']:
            content_data = {
                'text': comment['text'],
                'score': comment['score'],
                'weight': comment['weight'],
                'type': 'comment',
                'subreddit': comment['subreddit']
            }
            all_content.append(content_data)
            
            # Store top comments
            if comment['score'] > 5:
                top_comments.append({
                    'text': comment['text'][:200],
                    'score': comment['score'],
                    'subreddit': comment['subreddit']
                })
        
        # Analyze sentiment for each piece of content
        sentiment_breakdown = {'positive': 0, 'negative': 0, 'neutral': 0}
        
        for content in all_content:
            try:
                # Calculate sentiment using specified model
                sentiment_score = await self._calculate_sentiment_async(
                    content['text'], sentiment_model
                )
                
                # Weight sentiment by subreddit importance and content score
                weight_factor = content['weight'] * max(1, min(content['score'] / 10, 3))
                weighted_sentiments.append(sentiment_score * weight_factor)
                
                # Categorize sentiment
                if sentiment_score > 0.1:
                    sentiment_breakdown['positive'] += 1
                elif sentiment_score < -0.1:
                    sentiment_breakdown['negative'] += 1
                else:
                    sentiment_breakdown['neutral'] += 1
                
                # Check for injury mentions
                if any(keyword in content['text'].lower() for keyword in self.injury_keywords):
                    injury_mentions += 1
                    
            except Exception as e:
                logger.warning(f"Error analyzing sentiment for content: {e}")
                continue
        
        # Calculate overall metrics
        if weighted_sentiments:
            overall_sentiment = sum(weighted_sentiments) / len(weighted_sentiments)
            
            # Calculate hype score
            total_mentions = len(all_content)
            positive_ratio = sentiment_breakdown['positive'] / len(weighted_sentiments)
            hype_score = (overall_sentiment + 1) / 2 * min(total_mentions / 20, 1.0)
            
            # Determine consensus
            if positive_ratio > 0.6 and overall_sentiment > 0.2:
                consensus = 'START'
                confidence = min(95, positive_ratio * 100)
            elif positive_ratio < 0.3 or overall_sentiment < -0.2:
                consensus = 'SIT'
                confidence = min(95, (1 - positive_ratio) * 100)
            else:
                consensus = 'MIXED'
                confidence = abs(overall_sentiment) * 50
        else:
            overall_sentiment = 0.0
            hype_score = 0.0
            consensus = None
            confidence = 0.0
        
        # Sort top comments by score
        top_comments.sort(key=lambda x: x['score'], reverse=True)
        
        return {
            'overall_sentiment': overall_sentiment,
            'sentiment_breakdown': sentiment_breakdown,
            'injury_mentions': injury_mentions,
            'hype_score': hype_score,
            'top_comments': top_comments[:5],
            'consensus': consensus,
            'confidence': confidence
        }
    
    async def _calculate_sentiment_async(self, text: str, model: SentimentModel) -> float:
        """Calculate sentiment score asynchronously."""
        
        # Check cache first
        text_hash = hash(text)
        if text_hash in self.sentiment_cache:
            return self.sentiment_cache[text_hash]
        
        try:
            if model == SentimentModel.TEXTBLOB and TEXTBLOB_AVAILABLE:
                sentiment = await self._textblob_sentiment(text)
            elif model == SentimentModel.KEYWORD_BASED:
                sentiment = self._keyword_sentiment(text)
            elif model == SentimentModel.HYBRID:
                # Combine multiple approaches
                textblob_score = await self._textblob_sentiment(text) if TEXTBLOB_AVAILABLE else 0.0
                keyword_score = self._keyword_sentiment(text)
                sentiment = (textblob_score * 0.6) + (keyword_score * 0.4)
            else:
                # Fallback to keyword-based
                sentiment = self._keyword_sentiment(text)
            
            # Cache result
            self.sentiment_cache[text_hash] = sentiment
            return sentiment
            
        except Exception as e:
            logger.warning(f"Error calculating sentiment: {e}")
            return 0.0  # Neutral fallback
    
    async def _textblob_sentiment(self, text: str) -> float:
        """Calculate sentiment using TextBlob."""
        try:
            # Clean text
            cleaned_text = self._clean_text(text)
            
            # Run TextBlob in thread to avoid blocking
            def _get_textblob_sentiment():
                blob = TextBlob(cleaned_text)
                return blob.sentiment.polarity
            
            loop = asyncio.get_event_loop()
            sentiment = await loop.run_in_executor(
                self.thread_executor, _get_textblob_sentiment
            )
            
            return sentiment
            
        except Exception as e:
            logger.warning(f"TextBlob sentiment analysis failed: {e}")
            return 0.0
    
    def _keyword_sentiment(self, text: str) -> float:
        """Calculate sentiment using keyword analysis."""
        text_lower = text.lower()
        
        positive_score = 0
        negative_score = 0
        
        # Count positive keywords with weights
        for keyword in self.positive_keywords:
            if keyword in text_lower:
                # Weight by keyword strength
                if keyword in ['must start', 'smash play', 'league winner', 'elite']:
                    positive_score += 0.3
                elif keyword in ['start', 'stud', 'locked in']:
                    positive_score += 0.2
                else:
                    positive_score += 0.1
        
        # Count negative keywords with weights
        for keyword in self.negative_keywords:
            if keyword in text_lower:
                if keyword in ['avoid', 'bust', 'sit']:
                    negative_score += 0.3
                elif keyword in ['bench', 'fade', 'risky']:
                    negative_score += 0.2
                else:
                    negative_score += 0.1
        
        # Calculate final score
        net_score = positive_score - negative_score
        
        # Normalize to [-1, 1] range
        return max(-1.0, min(1.0, net_score))
    
    def _clean_text(self, text: str) -> str:
        """Clean text for sentiment analysis."""
        # Remove URLs
        text = re.sub(r'http\S+', '', text)
        # Remove special characters but keep basic punctuation
        text = re.sub(r'[^\w\s.,!?-]', ' ', text)
        # Remove extra whitespace
        text = ' '.join(text.split())
        return text.strip()
    
    def _is_reddit_available(self) -> bool:
        """Check if Reddit API is available."""
        return (
            PRAW_AVAILABLE and 
            self.reddit is not None and 
            self.api_status in [RedditAPIStatus.HEALTHY, RedditAPIStatus.DEGRADED]
        )
    
    async def _wait_for_rate_limit(self):
        """Wait if necessary to respect rate limits."""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        if time_since_last_request < self.min_request_interval:
            wait_time = self.min_request_interval - time_since_last_request
            logger.debug(f"Rate limiting: waiting {wait_time:.2f} seconds")
            await asyncio.sleep(wait_time)
        
        self.last_request_time = time.time()
    
    async def _generate_fallback_sentiment(self, player_name: str, result: RedditAnalysisResult) -> RedditAnalysisResult:
        """Generate fallback sentiment analysis when Reddit is unavailable."""
        logger.info(f"Generating fallback sentiment for {player_name}")
        
        # Simple keyword-based fallback using player name analysis
        try:
            # Check if player name contains obvious positive/negative indicators
            name_lower = player_name.lower()
            
            # Basic sentiment based on common fantasy player archetypes
            if any(word in name_lower for word in ['elite', 'stud', 'rb1', 'wr1', 'qb1']):
                result.overall_sentiment = 0.3
                result.consensus = 'START'
                result.confidence = 40
            elif any(word in name_lower for word in ['handcuff', 'backup', 'bench']):
                result.overall_sentiment = -0.2
                result.consensus = 'SIT'
                result.confidence = 30
            else:
                result.overall_sentiment = 0.0
                result.consensus = 'MIXED'
                result.confidence = 20
            
            result.sentiment_breakdown = {
                'positive': 1 if result.overall_sentiment > 0 else 0,
                'negative': 1 if result.overall_sentiment < 0 else 0,
                'neutral': 1 if result.overall_sentiment == 0 else 0
            }
            
            result.hype_score = abs(result.overall_sentiment) * 0.5
            result.top_comments = []
            result.injury_mentions = 0
            
            result.errors.append("Used fallback sentiment analysis - results may be inaccurate")
            
        except Exception as e:
            logger.error(f"Error in fallback sentiment generation: {e}")
            result.overall_sentiment = 0.0
            result.consensus = None
            result.confidence = 0
            result.errors.append(f"Fallback sentiment failed: {str(e)}")
        
        return result
    
    async def compare_players_sentiment(
        self,
        players: List[str],
        time_window_hours: int = 48
    ) -> Dict[str, Any]:
        """
        Compare Reddit sentiment for multiple players with enhanced error handling.
        
        Args:
            players: List of player names to compare
            time_window_hours: How far back to look for posts
            
        Returns:
            Comparison of sentiment analysis for all players
        """
        logger.info(f"Comparing Reddit sentiment for {len(players)} players")
        
        try:
            # Analyze all players in parallel with timeout
            tasks = [
                self.analyze_player_sentiment(player, time_window_hours)
                for player in players
            ]
            
            # Use timeout to prevent hanging
            timeout_seconds = min(60, time_window_hours * 2)  # Reasonable timeout
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout_seconds
            )
            
            # Process results and handle any exceptions
            analysis = {}
            successful_results = []
            
            for i, result in enumerate(results):
                player = players[i]
                if isinstance(result, Exception):
                    logger.error(f"Error analyzing {player}: {result}")
                    # Create error result
                    error_result = RedditAnalysisResult(
                        player=player,
                        status="error",
                        errors=[f"Analysis failed: {str(result)}"]
                    )
                    analysis[player] = error_result
                else:
                    analysis[player] = result
                    if result.status in ["success", "partial"]:
                        successful_results.append((player, result))
            
            # Create comparison summary
            comparison = {
                'players': players,
                'analysis': analysis,
                'recommendation': None,
                'confidence': 0.0,
                'timestamp': datetime.now().isoformat(),
                'successful_analyses': len(successful_results),
                'total_players': len(players)
            }
            
            # Generate recommendation if we have successful results
            if successful_results:
                comparison['recommendation'] = self._generate_comparison_recommendation(successful_results)
                comparison['confidence'] = self._calculate_comparison_confidence(successful_results)
            else:
                comparison['recommendation'] = {
                    'start': None,
                    'sit': players,
                    'reasoning': "Unable to analyze any players - Reddit data unavailable"
                }
            
            return comparison
            
        except asyncio.TimeoutError:
            logger.error(f"Timeout comparing players sentiment (>{timeout_seconds}s)")
            return {
                'players': players,
                'analysis': {player: RedditAnalysisResult(player=player, status="error", errors=["Analysis timeout"]) for player in players},
                'recommendation': {'start': None, 'sit': players, 'reasoning': "Analysis timed out"},
                'confidence': 0.0,
                'timestamp': datetime.now().isoformat(),
                'error': 'Analysis timed out'
            }
            
        except Exception as e:
            logger.error(f"Error comparing players sentiment: {e}")
            return {
                'players': players,
                'analysis': {player: RedditAnalysisResult(player=player, status="error", errors=[str(e)]) for player in players},
                'recommendation': {'start': None, 'sit': players, 'reasoning': f"Comparison failed: {str(e)}"},
                'confidence': 0.0,
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }
    
    def _generate_comparison_recommendation(self, successful_results: List[Tuple[str, RedditAnalysisResult]]) -> Dict[str, Any]:
        """Generate recommendation from successful analysis results."""
        try:
            # Sort by combined score (sentiment + hype + confidence)
            player_scores = []
            
            for player, result in successful_results:
                # Calculate composite score
                sentiment_score = result.overall_sentiment or 0.0
                hype_score = result.hype_score or 0.0
                confidence_factor = result.confidence / 100 if result.confidence else 0.5
                
                composite_score = (sentiment_score + hype_score) * confidence_factor
                player_scores.append((player, composite_score, result))
            
            # Sort by composite score
            player_scores.sort(key=lambda x: x[1], reverse=True)
            
            if not player_scores:
                return {
                    'start': None,
                    'sit': [r[0] for r in successful_results],
                    'reasoning': "No reliable sentiment data available"
                }
            
            best_player, best_score, best_result = player_scores[0]
            
            recommendation = {
                'start': best_player,
                'sit': [p[0] for p in player_scores[1:]],
                'reasoning': self._generate_comparison_reasoning(player_scores)
            }
            
            return recommendation
            
        except Exception as e:
            logger.error(f"Error generating comparison recommendation: {e}")
            return {
                'start': None,
                'sit': [r[0] for r in successful_results],
                'reasoning': f"Error generating recommendation: {str(e)}"
            }
    
    def _calculate_comparison_confidence(self, successful_results: List[Tuple[str, RedditAnalysisResult]]) -> float:
        """Calculate confidence level for comparison."""
        if len(successful_results) < 2:
            return 30.0  # Low confidence with insufficient data
        
        try:
            # Base confidence on data quality and sentiment separation
            total_data_points = sum(
                result.posts_analyzed + result.comments_analyzed 
                for _, result in successful_results
            )
            
            # Confidence based on amount of data
            data_confidence = min(80, total_data_points * 2)
            
            # Check sentiment separation
            sentiments = [result.overall_sentiment or 0.0 for _, result in successful_results]
            sentiment_range = max(sentiments) - min(sentiments)
            separation_confidence = min(20, sentiment_range * 50)  # More separation = more confidence
            
            return min(95, data_confidence + separation_confidence)
            
        except Exception as e:
            logger.warning(f"Error calculating comparison confidence: {e}")
            return 40.0  # Default moderate confidence
    
    def _generate_comparison_reasoning(self, player_scores: List[Tuple[str, float, RedditAnalysisResult]]) -> str:
        """Generate reasoning for the comparison recommendation."""
        try:
            if not player_scores:
                return "No data available for comparison"
            
            best_player, best_score, best_result = player_scores[0]
            reasoning_parts = []
            
            # Describe the top choice
            if best_result.consensus == 'START':
                reasoning_parts.append(
                    f"{best_player} has strong Reddit support with {best_result.posts_analyzed} posts "
                    f"and {best_result.comments_analyzed} comments analyzed (sentiment: {best_result.overall_sentiment:.2f})"
                )
            else:
                reasoning_parts.append(
                    f"{best_player} shows the most positive sentiment among options "
                    f"({best_result.overall_sentiment:.2f}) despite mixed community opinion"
                )
            
            # Note any injury concerns
            if best_result.injury_mentions > 0:
                reasoning_parts.append(f"Note: {best_result.injury_mentions} injury mentions found for {best_player}")
            
            # Comment on other players if significantly negative
            for player, score, result in player_scores[1:]:
                if result.overall_sentiment and result.overall_sentiment < -0.2:
                    reasoning_parts.append(
                        f"{player} has negative sentiment ({result.overall_sentiment:.2f}) - consider sitting"
                    )
            
            return ". ".join(reasoning_parts)
            
        except Exception as e:
            logger.warning(f"Error generating reasoning: {e}")
            return "Recommendation based on available sentiment data"
    
    def get_api_status(self) -> Dict[str, Any]:
        """Get current API status and health information."""
        return {
            'status': self.api_status.value,
            'praw_available': PRAW_AVAILABLE,
            'textblob_available': TEXTBLOB_AVAILABLE,
            'reddit_client_initialized': self.reddit is not None,
            'rate_limit_info': self.rate_limit_info,
            'last_request_time': self.last_request_time,
            'sentiment_cache_size': len(self.sentiment_cache)
        }
    
    async def cleanup(self):
        """Clean up resources."""
        try:
            if self.thread_executor:
                self.thread_executor.shutdown(wait=True)
            
            # Clear cache
            self.sentiment_cache.clear()
            
            logger.info("Reddit sentiment agent cleaned up")
            
        except Exception as e:
            logger.error(f"Error during Reddit agent cleanup: {e}")
