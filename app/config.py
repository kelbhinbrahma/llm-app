# All settings come from environment variables.
# This way no password or API key is written inside the code.
# For local runs, put them in a .env file (see .env.example).

import os

from dotenv import load_dotenv

load_dotenv()  # reads the .env file (if there is one) into os.environ

# Database (PostgreSQL in Docker, SQLite file is fine for quick local testing)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))

# JWT
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

# LLM
# LLM_PROVIDER = "gemini" -> real Google Gemini API
# LLM_PROVIDER = "mock"   -> fake answers, useful when there is no API key (and in tests)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "gemini-2.5-flash-lite")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# Demo users created when the app starts (passwords come from env, not code)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
USER_PASSWORD = os.getenv("USER_PASSWORD", "")
READONLY_PASSWORD = os.getenv("READONLY_PASSWORD", "")
