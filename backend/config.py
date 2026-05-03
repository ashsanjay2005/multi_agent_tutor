"""
Configuration management for the backend service.

Uses Pydantic Settings for environment variable management and validation.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Database (Supabase — used for LangGraph checkpointer)
    database_url: str = ""  # Supabase connection pooler string
    
    # Supabase
    supabase_url: str = ""      # e.g. https://xxx.supabase.co
    supabase_service_key: str = ""  # Service role key (bypasses RLS)
    
    # API Keys
    openai_api_key: str = ""
    google_api_key: str = ""
    youtube_api_key: str = ""
    
    # Application
    environment: Literal["development", "staging", "production"] = "development"
    backend_port: int = 8000
    
    # CORS
    cors_origins: list[str] = ["*"]
    
    # Redis (for rate limiting)
    redis_url: str = "redis://localhost:6379"
    
    # Rate Limiting
    rate_limit_free: int = 5   # requests per minute for free tier
    rate_limit_pro: int = 50   # requests per minute for pro tier
    rate_limit_window: int = 60  # window in seconds

    # Backend-signed anonymous identities for local mode
    anonymous_token_secret: str = ""
    anonymous_token_ttl_seconds: int = 60 * 60 * 24 * 180  # 180 days
    
    # Confidence Thresholds (for routing logic)
    confidence_threshold_low: float = 0.4
    confidence_threshold_high: float = 0.75
    
    # Default LLM Models
    vision_model: str = "gemini-2.0-flash"
    text_model: str = "gemini-2.0-flash"
    
    # Backboard.io Configuration
    backboard_api_key: str = ""
    # backboard_assistant_id is now PER-USER, stored in profiles table
    backboard_assistant_name: str = "STEM Math Tutor"
    
    # Logging
    log_level: str = "INFO"


# Global settings instance
settings = Settings()
