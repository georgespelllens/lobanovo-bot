"""Application configuration via Pydantic Settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional


class Settings(BaseSettings):
    """Main application settings loaded from environment variables."""

    # Telegram
    telegram_bot_token: str = ""
    admin_chat_id: int = 0
    admin_user_ids: str = ""  # comma-separated telegram IDs

    # xAI (Grok) — chat completions
    xai_api_key: str = ""

    # OpenRouter — embeddings only (google/gemini-embedding-001)
    openrouter_api_key: str = ""

    # OpenAI (Whisper STT)
    openai_api_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/lobanov_bot"

    # App
    app_url: str = "http://localhost:8000"
    app_name: str = "Lobanov AI Mentor"
    secret_key: str = "change-me"

    # Models
    default_model: str = "grok-4"
    embedding_model: str = "google/gemini-embedding-001"

    # Limits
    max_voice_duration_seconds: int = 300
    max_message_length: int = 4000

    # Direct Line
    direct_line_price_rub: int = 1000
    direct_line_weekly_quota: int = 10
    direct_line_response_deadline_hours: int = 48
    direct_line_auto_refund_hours: int = 96
    direct_line_max_question_voice_seconds: int = 180

    @property
    def admin_ids_list(self) -> List[int]:
        """Parse comma-separated admin IDs into a list."""
        if not self.admin_user_ids:
            return []
        return [int(uid.strip()) for uid in self.admin_user_ids.split(",") if uid.strip()]

    @property
    def database_url_async(self) -> str:
        """Ensure the database URL uses asyncpg driver."""
        url = self.database_url
        if "asyncpg" in url:
            return url  # Already has asyncpg driver
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Models for different tasks — all via OpenRouter API
# anthropic/claude-sonnet-4-20250514: flagship ($3/$15 per 1M tokens)
# google/gemini-2.0-flash-001: fast & ultra-cheap ($0.10/$0.40 per 1M)
MODELS = {
    "qa": "anthropic/claude-sonnet-4-20250514",
    "audit": "anthropic/claude-sonnet-4-20250514",
    "task_review": "anthropic/claude-sonnet-4-20250514",
    "summary": "google/gemini-2.0-flash-001",
    "embedding": "google/gemini-embedding-001",
    "categorize": "google/gemini-2.0-flash-001",
    "direct_line_card": "google/gemini-2.0-flash-001",
    "direct_line_followup": "anthropic/claude-sonnet-4-20250514",
    "direct_line_anonymize": "google/gemini-2.0-flash-001",
}

# Tier limits
TIER_LIMITS = {
    "free": {
        "weekly_questions": 999999,
        "weekly_audits": 999999,
        "history_days": 999999,
        "can_escalate": True,
        "web_dashboard": True,
        "direct_line_price": 1000,
        "free_direct_questions_monthly": 0,
    },
    "pro": {
        "weekly_questions": 50,
        "weekly_audits": 20,
        "history_days": 90,
        "can_escalate": True,
        "web_dashboard": True,
        "direct_line_price": 1000,
        "free_direct_questions_monthly": 0,
    },
    "premium": {
        "weekly_questions": 999999,
        "weekly_audits": 999999,
        "history_days": 999999,
        "can_escalate": True,
        "web_dashboard": True,
        "direct_line_price": 1000,
        "free_direct_questions_monthly": 1,
    },
}


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
