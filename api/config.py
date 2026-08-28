"""
Configuration management using Pydantic BaseSettings.
Environment variables are loaded from .env file.
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings from environment variables."""

    # API Configuration
    API_KEY: str
    API_TITLE: str = "Borges Knowledge Graph API"
    API_VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"

    # Database Configuration (PostgreSQL)
    DATABASE_URL: str  # postgresql+asyncpg://user:password@localhost/dbname

    # AWS S3 Configuration
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str
    S3_PRESIGNED_URL_EXPIRY: int = 3600  # 1 hour in seconds

    # LLM API Keys (for pipeline execution)
    OPENAI_API_KEY: str
    BACKUP_OPENAI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

    # Qdrant Configuration
    QDRANT_API_KEY: str
    QDRANT_URL: str

    # LangChain Configuration
    LANGCHAIN_API_KEY: Optional[str] = None
    LANGCHAIN_TRACING_V2: bool = True
    LANGCHAIN_PROJECT: str = "Borges Knowledge Graph"

    # Pipeline Configuration (Fixed defaults - not client-configurable)
    DEFAULT_EXTRACTION_MODEL: str = "gpt-4.1"
    DEFAULT_MERGING_MODEL: str = "gpt-4.1-mini"
    USE_ITERATIVE_DEDUP: bool = True
    ITERATIVE_DEDUP_MAX_ROUNDS: int = 10
    ENABLE_COST_TRACKING: bool = True
    CHUNK_SIZE: int = 8000
    CHUNK_OVERLAP: int = 300
    BATCH_SIZE: int = 50
    MAX_CONCURRENT_CHUNKS: int = 5  # Number of chunks to process in parallel
    # MAX_CONCURRENT_DEDUP_ENTITIES: int = 10  # Number of entities to deduplicate in parallel

    # File Upload Limits
    MAX_FILE_SIZE_MB: int = 100
    MAX_FILES_PER_REQUEST: int = 20
    ALLOWED_FILE_EXTENSIONS: list = [".pdf", ".xml"]

    # Temporary Storage
    TEMP_UPLOAD_DIR: str = "temp_uploads"

    class Config:
        # Look for .env in the api/ directory
        env_file = os.path.join(Path(__file__).parent, ".env")
        case_sensitive = True


# Global settings instance
settings = Settings()
