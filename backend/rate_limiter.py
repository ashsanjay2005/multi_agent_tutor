"""
Redis-based Rate Limiter using Token Bucket Algorithm.

Supports per-user rate limiting with different tiers (free/pro).
Uses Redis for distributed state across multiple backend instances.
"""

import time
import redis.asyncio as redis
from typing import Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting tiers."""
    free_limit: int = 5       # requests per window
    pro_limit: int = 50       # requests per window
    window_seconds: int = 60  # 1 minute window
    

class RateLimiter:
    """
    Token Bucket Rate Limiter backed by Redis.
    
    Keys used:
    - rate_limit:{user_id}:tokens  → remaining tokens
    - rate_limit:{user_id}:last    → last request timestamp
    """
    
    def __init__(
        self, 
        redis_url: str,
        config: Optional[RateLimitConfig] = None
    ):
        self.redis_url = redis_url
        self.config = config or RateLimitConfig()
        self._client: Optional[redis.Redis] = None
        
    async def connect(self) -> None:
        """Initialize Redis connection."""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            await self._client.ping()
            logger.info("Rate limiter connected to Redis")
    
    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            
    def _get_limit_for_tier(self, tier: str) -> int:
        """Get the rate limit for a user tier."""
        if tier == "pro":
            return self.config.pro_limit
        return self.config.free_limit
    
    async def check_rate_limit(
        self, 
        user_id: str, 
        tier: str = "free"
    ) -> Tuple[bool, int, int]:
        """
        Check if a request is allowed under the rate limit.
        
        Args:
            user_id: The user's unique identifier
            tier: User tier ('free' or 'pro')
            
        Returns:
            Tuple of (allowed, remaining_tokens, reset_in_seconds)
        """
        if not self._client:
            raise RuntimeError("Rate limiter not connected. Call connect() first.")
        
        limit = self._get_limit_for_tier(tier)
        now = time.time()
        window = self.config.window_seconds
        
        tokens_key = f"rate_limit:{user_id}:tokens"
        last_key = f"rate_limit:{user_id}:last"
        
        # Use pipeline for atomic operations
        pipe = self._client.pipeline()
        
        # Get current state
        pipe.get(tokens_key)
        pipe.get(last_key)
        results = await pipe.execute()
        
        current_tokens = float(results[0]) if results[0] else float(limit)
        last_time = float(results[1]) if results[1] else now
        
        # Calculate token refill
        time_passed = now - last_time
        tokens_to_add = time_passed * (limit / window)  # Gradual refill
        new_tokens = min(limit, current_tokens + tokens_to_add)
        
        # Calculate reset time
        if new_tokens < 1:
            reset_in = int((1 - new_tokens) * (window / limit))
        else:
            reset_in = 0
        
        # Check if request is allowed
        if new_tokens >= 1:
            # Consume a token
            new_tokens -= 1
            allowed = True
        else:
            allowed = False
            
        # Update Redis
        pipe2 = self._client.pipeline()
        pipe2.set(tokens_key, str(new_tokens), ex=window * 2)
        pipe2.set(last_key, str(now), ex=window * 2)
        await pipe2.execute()
        
        remaining = max(0, int(new_tokens))
        
        if not allowed:
            logger.warning(
                f"Rate limit exceeded for user {user_id} (tier={tier}, limit={limit}/min)"
            )
        
        return allowed, remaining, reset_in
    
    async def get_quota_status(
        self, 
        user_id: str, 
        tier: str = "free"
    ) -> dict:
        """
        Get current quota status for a user.
        
        Returns dict with:
        - remaining: tokens left
        - limit: max tokens per window
        - reset_in: seconds until refill
        """
        if not self._client:
            raise RuntimeError("Rate limiter not connected")
            
        limit = self._get_limit_for_tier(tier)
        now = time.time()
        window = self.config.window_seconds
        
        tokens_key = f"rate_limit:{user_id}:tokens"
        last_key = f"rate_limit:{user_id}:last"
        
        pipe = self._client.pipeline()
        pipe.get(tokens_key)
        pipe.get(last_key)
        results = await pipe.execute()
        
        current_tokens = float(results[0]) if results[0] else float(limit)
        last_time = float(results[1]) if results[1] else now
        
        # Calculate current tokens with refill
        time_passed = now - last_time
        tokens_to_add = time_passed * (limit / window)
        current = min(limit, current_tokens + tokens_to_add)
        
        # Calculate reset time
        tokens_needed = limit - current
        if tokens_needed > 0:
            reset_in = int(tokens_needed * (window / limit))
        else:
            reset_in = 0
            
        return {
            "remaining": max(0, int(current)),
            "limit": limit,
            "window_seconds": window,
            "reset_in_seconds": reset_in,
            "tier": tier
        }
    
    async def reset_user(self, user_id: str) -> None:
        """Reset rate limit for a user (admin function)."""
        if not self._client:
            raise RuntimeError("Rate limiter not connected")
            
        tokens_key = f"rate_limit:{user_id}:tokens"
        last_key = f"rate_limit:{user_id}:last"
        
        await self._client.delete(tokens_key, last_key)
        logger.info(f"Reset rate limit for user {user_id}")


# Global instance (initialized on startup)
rate_limiter: Optional[RateLimiter] = None


async def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    if rate_limiter is None:
        raise RuntimeError("Rate limiter not initialized")
    return rate_limiter


async def init_rate_limiter(redis_url: str) -> RateLimiter:
    """Initialize the global rate limiter."""
    global rate_limiter
    rate_limiter = RateLimiter(redis_url)
    await rate_limiter.connect()
    return rate_limiter


async def close_rate_limiter() -> None:
    """Close the global rate limiter."""
    global rate_limiter
    if rate_limiter:
        await rate_limiter.close()
        rate_limiter = None
