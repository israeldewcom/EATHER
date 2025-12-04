import os
import secrets
from typing import List, Optional, Dict, Any
from pydantic_settings import BaseSettings
from pydantic import validator, PostgresDsn
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    """Enhanced application settings with validation"""
    
    # App
    APP_NAME: str = "AETHER AI Accounting"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"  # development, staging, production
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_LEEWAY: int = 30
    
    # Database
    DATABASE_URL: PostgresDsn = "postgresql://user:password@localhost/aether_db"
    REDIS_URL: str = "redis://localhost:6379"
    
    @validator("DATABASE_URL", pre=True)
    def validate_database_url(cls, v):
        if isinstance(v, str) and not v.startswith("postgresql://"):
            raise ValueError("DATABASE_URL must start with postgresql://")
        return v
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://app.aether.ai"
    ]
    
    # AI Services
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None
    
    # Plaid
    PLAID_CLIENT_ID: Optional[str] = None
    PLAID_SECRET: Optional[str] = None
    PLAID_ENVIRONMENT: str = "sandbox"
    
    # AWS
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    S3_BUCKET_NAME: str = "aether-documents"
    AWS_REGION: str = "us-east-1"
    CLOUDFRONT_URL: Optional[str] = None
    
    # Email
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAIL_FROM: str = "noreply@aether.ai"
    
    # Stripe
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PRICE_IDS: Dict[str, str] = {
        "starter": "price_starter",
        "professional": "price_professional",
        "business": "price_business",
        "enterprise": "price_enterprise"
    }
    
    # Monitoring
    SENTRY_DSN: Optional[str] = None
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 100
    RATE_LIMIT_PER_HOUR: int = 1000
    
    # File Upload
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS: List[str] = [".png", ".jpg", ".jpeg", ".pdf", ".txt", ".csv"]
    UPLOAD_DIR: str = "uploads"
    
    # Cache
    CACHE_TTL: int = 300  # 5 minutes
    CACHE_ENABLED: bool = True
    
    # Job Queue
    JOB_RETRY_LIMIT: int = 3
    JOB_RETRY_DELAY: int = 60  # seconds
    
    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"
    
    # Tax
    TAX_API_ENABLED: bool = False
    TAX_API_URL: Optional[str] = None
    TAX_API_KEY: Optional[str] = None
    
    # Performance
    API_TIMEOUT: int = 30
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 40
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        validate_assignment = True

settings = Settings()
