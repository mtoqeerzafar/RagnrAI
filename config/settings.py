from pydantic_settings import BaseSettings
from .constants import MAX_FILE_SIZE, MAX_TOTAL_SIZE, ALLOWED_TYPES
import os
import sys
import logging

# Reconfigure stdout and stderr to UTF-8 to handle Unicode characters on Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Disable anonymized telemetry warnings from ChromaDB
os.environ["ANONYMIZED_TELEMETRY"] = "False"
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

class Settings(BaseSettings):
    # Required settings - Changed from OPENAI_API_KEY to GOOGLE_API_KEY
    # Azure OpenAI Config (Fallback/Production)
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    AZURE_OPENAI_DEPLOYMENT_NAME: str = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-40-mini")
    
    # Provider Switcher (azure, github, groq)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "github")
    
    # Groq Config
    GROQ_API_KEYS: str = os.getenv("GROQ_API_KEYS", "")
    
    # GitHub Models Config
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    # Optional settings with defaults
    MAX_FILE_SIZE: int = MAX_FILE_SIZE
    MAX_TOTAL_SIZE: int = MAX_TOTAL_SIZE
    ALLOWED_TYPES: list = ALLOWED_TYPES

    # Database settings
    CHROMA_DB_PATH: str = "./chroma_db"
    CHROMA_COLLECTION_NAME: str = "documents"

    # Retrieval & Reranking settings
    VECTOR_SEARCH_K: int = 30
    HYBRID_RETRIEVER_WEIGHTS: list = [0.4, 0.6]
    RERANKER_TOP_K: int = 6
    RERANKER_THRESHOLD: float = 0.0

    # Chunking settings
    PARAGRAPH_BATCH_SIZE: int = 3
    MAX_TABLE_ROWS_PER_CHUNK: int = 10
    TABLE_ROW_BATCH_SIZE: int = 5
    
    # Confidence Thresholds
    CONFIDENCE_THRESHOLD_HIGH: float = 0.75
    CONFIDENCE_THRESHOLD_LOW: float = 0.40

    # Logging settings
    LOG_LEVEL: str = "INFO"

    # Observability & Debug settings
    DEBUG_RETRIEVAL: bool = False
    ENABLE_RETRIEVAL_TRACE: bool = False
    ENABLE_CACHE_TRACE: bool = False
    ENABLE_WORKFLOW_TRACE: bool = False

    # Cache settings with type annotations
    CACHE_DIR: str = "document_cache"
    CACHE_EXPIRE_DAYS: int = 7

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()