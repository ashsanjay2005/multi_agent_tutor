-- Initialize database for LangGraph checkpointer
-- This ensures the checkpoint tables are created

-- LangGraph checkpoint tables will be auto-created by the checkpointer
-- This file is here for any additional initialization if needed

-- Create extension for UUID support (optional)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- You can add any custom tables or indexes here if needed in the future

-- Video cache table for YouTube resources
CREATE TABLE IF NOT EXISTS video_cache (
    id SERIAL PRIMARY KEY,
    problem_id VARCHAR(255) NOT NULL,
    offset_index INT NOT NULL,
    videos JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(problem_id, offset_index)
);

-- Index for TTL cleanup queries
CREATE INDEX IF NOT EXISTS idx_video_cache_created ON video_cache(created_at);


