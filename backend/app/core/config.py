import json
from typing import Annotated, Any
from pydantic import BeforeValidator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors_origins(v: Any) -> list[str]:
    if isinstance(v, str):
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            try:
                return json.loads(v)
            except Exception:
                pass
        return [origin.strip() for origin in v.split(",") if origin.strip()]
    elif isinstance(v, list):
        return [str(origin) for origin in v]
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


class Settings(BaseSettings):
    PROJECT_NAME: str = "NeuroForge AI"
    VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    ENVIRONMENT: str | None = None
    HOST: str = "127.0.0.1"
    APP_PORT: int = 8020
    PORT: int | None = None
    CORS_ORIGINS: Annotated[list[str], BeforeValidator(parse_cors_origins)] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Database (PostgreSQL mandatory for NeuroForge AI)
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5440
    POSTGRES_DB: str = "neuroforge"
    POSTGRES_USER: str = "neuroforge_app"
    POSTGRES_PASSWORD: str = ""
    DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True

    # Security & Authentication
    JWT_SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # Docker Sandbox Execution
    SANDBOX_IMAGE: str = "neuroforge-sandbox:local"
    SANDBOX_TIMEOUT_SECONDS: int = 60
    SANDBOX_MAX_TIMEOUT_SECONDS: int = 120
    SANDBOX_MEMORY_LIMIT: str = "1024m"
    SANDBOX_CPU_LIMIT: str = "1.0"
    SANDBOX_PIDS_LIMIT: int = 64
    SANDBOX_MAX_OUTPUT_BYTES: int = 65536
    SANDBOX_MAX_ARTIFACT_COUNT: int = 20
    SANDBOX_MAX_TOTAL_ARTIFACT_BYTES: int = 25 * 1024 * 1024  # 25 MB

    # LangGraph PostgreSQL Checkpoint Persistence
    CHECKPOINT_DATABASE_URL: str = ""

    # File Storage Paths
    UPLOAD_DIR: str = "data/uploads"
    ARTIFACT_DIR: str = "data/artifacts"
    WORKSPACE_DIR: str = "data/workspaces"
    KNOWLEDGE_DIR: str = "data/knowledge"
    VECTOR_DB_PATH: str = "data/vector_store.db"

    # Scientific Knowledge & Vector RAG (Qdrant + Vultr)
    QDRANT_HOST: str = "127.0.0.1"
    QDRANT_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_URL: str | None = None
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "scientific_knowledge"
    QDRANT_PREFER_GRPC: bool = False
    ALLOW_MOCK_EMBEDDINGS: bool = False

    VULTR_EMBEDDING_MODEL: str = "qwen3-embedding-4b"
    EMBEDDING_DIMENSION: int = 2560
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.05

    # Vultr Serverless Inference
    VULTR_INFERENCE_API_KEY: str | None = None
    VULTR_INFERENCE_BASE_URL: str = "https://api.vultrinference.com/v1"
    VULTR_INFERENCE_MODEL: str = "llama-3.3-70b-instruct-fp8"
    VULTR_INFERENCE_TIMEOUT_SECONDS: int = 45
    VULTR_INFERENCE_MAX_RETRIES: int = 3
    VULTR_INFERENCE_MAX_TOKENS: int = 2048
    VULTR_INFERENCE_TEMPERATURE: float = 0.2

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if not self.JWT_SECRET_KEY:
            if self.current_env == "test":
                self.JWT_SECRET_KEY = "test-secret-key-only-for-unit-testing-neuroforge"
            else:
                raise RuntimeError(
                    "JWT_SECRET_KEY must be configured in environment. Failed to start securely."
                )

        # Enforce PostgreSQL as mandatory database architecture
        if not self.DATABASE_URL or self.DATABASE_URL.startswith("sqlite"):
            if self.POSTGRES_PASSWORD:
                self.DATABASE_URL = f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

        if "@localhost:" in self.DATABASE_URL:
            self.DATABASE_URL = self.DATABASE_URL.replace("@localhost:", "@127.0.0.1:")

        if not self.CHECKPOINT_DATABASE_URL or self.CHECKPOINT_DATABASE_URL.startswith("sqlite"):
            if self.DATABASE_URL.startswith("postgresql+psycopg://"):
                self.CHECKPOINT_DATABASE_URL = self.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
            elif self.POSTGRES_PASSWORD:
                self.CHECKPOINT_DATABASE_URL = f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

        if "@localhost:" in self.CHECKPOINT_DATABASE_URL:
            self.CHECKPOINT_DATABASE_URL = self.CHECKPOINT_DATABASE_URL.replace("@localhost:", "@127.0.0.1:")

        if not self.VULTR_INFERENCE_MODEL:
            self.VULTR_INFERENCE_MODEL = "llama-3.3-70b-instruct-fp8"

        if self.current_env == "test":
            self.ALLOW_MOCK_EMBEDDINGS = True

        return self

    @property
    def current_env(self) -> str:
        return self.APP_ENV or self.ENVIRONMENT or "development"

    @property
    def current_port(self) -> int:
        return self.APP_PORT or self.PORT or 8020

    model_config = SettingsConfigDict(
        env_file=("backend/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
