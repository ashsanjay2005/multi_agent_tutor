"""
Video Cache for YouTube Resources

PostgreSQL-backed cache to store video search results by problem_id.
This avoids re-running the LangGraph workflow for the same problem.
"""

import json
import logging
from typing import Optional
from datetime import datetime, timedelta

import asyncpg

from config import settings

logger = logging.getLogger(__name__)

# Cache TTL in hours (videos stay cached for 24 hours)
CACHE_TTL_HOURS = 24


class VideoCache:
    """
    Cache video resources by problem_id to avoid re-fetching.
    Uses PostgreSQL for persistence.
    """
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    async def ensure_table(self):
        """Create the cache table if it doesn't exist."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS video_cache (
                    id SERIAL PRIMARY KEY,
                    problem_id VARCHAR(255) NOT NULL,
                    offset_index INT NOT NULL,
                    videos JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(problem_id, offset_index)
                );
                
                CREATE INDEX IF NOT EXISTS idx_video_cache_created 
                ON video_cache(created_at);
            """)
            logger.info("[VideoCache] Table ensured")
    
    async def get(self, problem_id: str, offset: int) -> Optional[list[dict]]:
        """
        Retrieve cached videos for a problem+offset combo.
        Returns None if not cached or expired.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT videos, created_at 
                FROM video_cache 
                WHERE problem_id = $1 AND offset_index = $2
            """, problem_id, offset)
            
            if row is None:
                logger.info(f"[VideoCache] MISS for {problem_id}:{offset}")
                return None
            
            # Check TTL
            created_at = row["created_at"]
            if datetime.utcnow() - created_at > timedelta(hours=CACHE_TTL_HOURS):
                logger.info(f"[VideoCache] EXPIRED for {problem_id}:{offset}")
                # Optionally delete expired entry
                await conn.execute("""
                    DELETE FROM video_cache 
                    WHERE problem_id = $1 AND offset_index = $2
                """, problem_id, offset)
                return None
            
            logger.info(f"[VideoCache] HIT for {problem_id}:{offset}")
            return json.loads(row["videos"])
    
    async def set(self, problem_id: str, offset: int, videos: list[dict]):
        """
        Store videos in cache.
        Uses upsert to handle race conditions.
        """
        async with self.pool.acquire() as conn:
            videos_json = json.dumps(videos)
            await conn.execute("""
                INSERT INTO video_cache (problem_id, offset_index, videos, created_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (problem_id, offset_index) 
                DO UPDATE SET videos = $3, created_at = NOW()
            """, problem_id, offset, videos_json)
            
            logger.info(f"[VideoCache] SET for {problem_id}:{offset} ({len(videos)} videos)")
    
    async def cleanup_expired(self):
        """Remove entries older than TTL. Call periodically."""
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM video_cache 
                WHERE created_at < NOW() - INTERVAL '%s hours'
            """ % CACHE_TTL_HOURS)
            logger.info(f"[VideoCache] Cleanup: {result}")


# Singleton instance (initialized in main.py lifespan)
_video_cache: Optional[VideoCache] = None


async def init_video_cache(database_url: str) -> VideoCache:
    """Initialize the video cache with a database pool."""
    global _video_cache
    
    pool = await asyncpg.create_pool(database_url)
    _video_cache = VideoCache(pool)
    await _video_cache.ensure_table()
    
    return _video_cache


def get_video_cache() -> Optional[VideoCache]:
    """Get the global video cache instance."""
    return _video_cache
