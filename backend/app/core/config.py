"""Central configuration. Every secret comes from the environment (or backend/.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in os.getenv(name, default).split(",") if p.strip()]


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))

    # Session auth (backend-issued JWT; the Canvas token never leaves the backend)
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", ""))
    jwt_ttl_minutes: int = field(default_factory=lambda: int(os.getenv("JWT_TTL_MINUTES", "720")))
    # Fernet key used to encrypt Canvas tokens at rest
    fernet_key: str = field(default_factory=lambda: os.getenv("FERNET_KEY", ""))

    cors_origins: list[str] = field(
        default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,"
                                                      "http://localhost:4200,http://localhost:4300")
    )

    # Storage. DATABASE_URL=postgresql://... (Supabase) enables pgvector; otherwise local SQLite.
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    sqlite_path: str = field(
        default_factory=lambda: os.getenv("SQLITE_PATH", str(BACKEND_DIR / "data" / "rmit1ne.db"))
    )
    # Legacy academic tables (User/Courses/Assignments/Course_timetable) via Supabase REST
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))

    canvas_base_url: str = field(
        default_factory=lambda: os.getenv("CANVAS_BASE_URL", "https://rmit.instructure.com")
    )
    n8n_webhook_url: str = field(default_factory=lambda: os.getenv("N8N_WEBHOOK_URL", ""))

    # Models
    embedding_provider: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "fastembed")
    )  # fastembed | openai | hash
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    )
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "384")))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    llm_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_SECONDS", "120")))
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "base.en"))

    # Ingestion limits / local content
    local_content_dir: str = field(default_factory=lambda: os.getenv("LOCAL_CONTENT_DIR", ""))
    max_pdf_mb: int = field(default_factory=lambda: int(os.getenv("MAX_PDF_MB", "100")))
    max_video_mb: int = field(default_factory=lambda: int(os.getenv("MAX_VIDEO_MB", "2048")))
    media_cache_dir: str = field(
        default_factory=lambda: os.getenv("MEDIA_CACHE_DIR", str(BACKEND_DIR / "data" / "cache"))
    )
    signed_url_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("SIGNED_URL_TTL_SECONDS", "3600"))
    )
    public_base_url: str = field(
        default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    )

    allow_dev_secrets: bool = field(default_factory=lambda: _bool("ALLOW_DEV_SECRETS", False))

    @property
    def use_postgres(self) -> bool:
        return self.database_url.startswith("postgres")

    @property
    def use_supabase_rest(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key or self.openai_base_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
