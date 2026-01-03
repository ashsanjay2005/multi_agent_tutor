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
    
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/math_tutor"
    
    # API Keys
    openai_api_key: str = ""
    google_api_key: str = ""
    youtube_api_key: str = ""
    
    # Application
    environment: Literal["development", "staging", "production"] = "development"
    backend_port: int = 8000
    
    # CORS
    cors_origins: list[str] = ["*"]
    
    # Confidence Thresholds (for routing logic)
    confidence_threshold_low: float = 0.4
    confidence_threshold_high: float = 0.75
    
    # LLM Model Names (Default: Google Gemini - GA Versions as of 2025)
    vision_model: str = "gemini-2.0-flash"  # OpenAI: "gpt-4o"
    text_model: str = "gemini-2.0-flash"  # OpenAI: "gpt-4o-mini"
    
    # Logging
    log_level: str = "INFO"


# Global settings instance
settings = Settings()

