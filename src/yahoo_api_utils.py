#!/usr/bin/env python3
"""
Yahoo API utilities for rate limiting and caching
"""

import asyncio
import time
import hashlib
import json
from typing import Any, Dict, Optional, Callable
from functools import wraps
from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    """Rate limiter for Yahoo API calls (1000 requests per hour)."""
    
    def __init__(self, max_requests: int = 900, window_seconds: int = 3600):
        """
        Initialize rate limiter.
        Using 900 instead of 1000 to have safety margin.
        
        Args:
            max_requests: Maximum requests allowed in the window
            window_seconds: Time window in seconds (3600 = 1 hour)
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = deque()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """Wait if necessary to respect rate limits."""
        async with self._lock:
            now = time.time()
            
            # Remove old requests outside the window
            while self.requests and self.requests[0] <= now - self.window_seconds:
                self.requests.popleft()
            
            # If at limit, calculate wait time
            if len(self.requests) >= self.max_requests:
                oldest_request = self.requests[0]
                wait_time = (oldest_request + self.window_seconds) - now
                if wait_time > 0:
                    print(f"Rate limit reached. Waiting {wait_time:.1f} seconds...")
                    await asyncio.sleep(wait_time)
                    # After waiting, clean up old requests again
                    now = time.time()
                    while self.requests and self.requests[0] <= now - self.window_seconds:
                        self.requests.popleft()
            
            # Record this request
            self.requests.append(now)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current rate limiter status."""
        now = time.time()
        # Clean old requests
        while self.requests and self.requests[0] <= now - self.window_seconds:
            self.requests.popleft()
        
        requests_in_window = len(self.requests)
        remaining = self.max_requests - requests_in_window
        
        # Calculate reset time (when oldest request expires)
        reset_time = None
        if self.requests:
            reset_time = self.requests[0] + self.window_seconds
            reset_in_seconds = max(0, reset_time - now)
        else:
            reset_in_seconds = 0
        
        return {
            "requests_used": requests_in_window,
            "requests_remaining": remaining,
            "max_requests": self.max_requests,
            "reset_in_seconds": round(reset_in_seconds),
            "reset_time": datetime.fromtimestamp(reset_time).isoformat() if reset_time else None
        }


class ResponseCache:
    """Simple TTL-based cache for API responses."""
    
    def __init__(self):
        self.cache: Dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()
        
        # Default TTLs for different endpoint types (in seconds)
        self.default_ttls = {
            "leagues": 3600,      # 1 hour - leagues don't change often
            "teams": 1800,        # 30 minutes - team info fairly static
            "standings": 300,     # 5 minutes - standings update after games
            "roster": 300,        # 5 minutes - roster changes matter
            "matchup": 60,        # 1 minute - live scoring during games
            "players": 600,       # 10 minutes - free agents change slowly
            "draft": 86400,       # 24 hours - draft results are static
            "waiver": 300,        # 5 minutes - waiver wire is dynamic
            "user": 3600,         # 1 hour - user info rarely changes
        }
    
    def _get_cache_key(self, endpoint: str) -> str:
        """Generate cache key from endpoint."""
        return hashlib.md5(endpoint.encode()).hexdigest()
    
    def _get_ttl_for_endpoint(self, endpoint: str) -> int:
        """Determine TTL based on endpoint type."""
        # Check endpoint patterns to determine type
        if "leagues" in endpoint or "games" in endpoint:
            return self.default_ttls["leagues"]
        elif "standings" in endpoint:
            return self.default_ttls["standings"]
        elif "roster" in endpoint:
            return self.default_ttls["roster"]
        elif "matchup" in endpoint or "scoreboard" in endpoint:
            return self.default_ttls["matchup"]
        elif "players" in endpoint and "status=A" in endpoint:
            return self.default_ttls["players"]
        elif "draft" in endpoint:
            return self.default_ttls["draft"]
        elif "teams" in endpoint:
            return self.default_ttls["teams"]
        elif "users" in endpoint:
            return self.default_ttls["user"]
        else:
            return 300  # Default 5 minutes
    
    async def get(self, endpoint: str) -> Optional[Any]:
        """Get cached response if valid."""
        async with self._lock:
            cache_key = self._get_cache_key(endpoint)
            
            if cache_key in self.cache:
                data, timestamp = self.cache[cache_key]
                ttl = self._get_ttl_for_endpoint(endpoint)
                
                if time.time() - timestamp < ttl:
                    age = time.time() - timestamp
                    return data
                else:
                    # Expired, remove from cache
                    del self.cache[cache_key]
            
            return None
    
    async def set(self, endpoint: str, data: Any):
        """Store response in cache."""
        async with self._lock:
            cache_key = self._get_cache_key(endpoint)
            self.cache[cache_key] = (data, time.time())
    
    async def clear(self, pattern: Optional[str] = None):
        """Clear cache entries matching pattern or all if no pattern."""
        async with self._lock:
            if pattern:
                keys_to_delete = [
                    key for key in self.cache.keys()
                    if pattern in key
                ]
                for key in keys_to_delete:
                    del self.cache[key]
            else:
                self.cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        now = time.time()
        total_entries = len(self.cache)
        
        expired_count = 0
        total_size = 0
        
        for endpoint_hash, (data, timestamp) in self.cache.items():
            # Estimate size (rough)
            total_size += len(json.dumps(data, default=str))
            
            # Find endpoint type from hash (approximate)
            for endpoint_type in self.default_ttls:
                ttl = self.default_ttls[endpoint_type]
                if now - timestamp >= ttl:
                    expired_count += 1
                    break
        
        return {
            "total_entries": total_entries,
            "expired_entries": expired_count,
            "active_entries": total_entries - expired_count,
            "cache_size_bytes": total_size,
            "cache_size_mb": round(total_size / (1024 * 1024), 2)
        }


# Global instances
rate_limiter = RateLimiter()
response_cache = ResponseCache()


def with_rate_limit(func: Callable) -> Callable:
    """Decorator to add rate limiting to async functions."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        await rate_limiter.acquire()
        return await func(*args, **kwargs)
    return wrapper


def with_cache(ttl_seconds: Optional[int] = None) -> Callable:
    """
    Decorator to add caching to async functions.
    
    Args:
        ttl_seconds: Override default TTL for this function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(endpoint: str, *args, **kwargs):
            # Try to get from cache first
            cached_response = await response_cache.get(endpoint)
            if cached_response is not None:
                return cached_response
            
            # Not in cache, make the actual call
            result = await func(endpoint, *args, **kwargs)
            
            # Store in cache
            if result:  # Only cache successful responses
                await response_cache.set(endpoint, result)
            
            return result
        return wrapper
    return decorator