"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Recruiter Autopilot"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: SecretStr = Field(default=SecretStr("change-me-in-production"))

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/recruiter_autopilot"
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_default_queue: str = "default"

    # Greenhouse API
    greenhouse_api_key: SecretStr = Field(default=SecretStr(""))
    greenhouse_webhook_secret: SecretStr = Field(default=SecretStr(""))
    greenhouse_api_base_url: str = "https://harvest.greenhouse.io/v1"
    greenhouse_rate_limit_per_second: int = 50
    greenhouse_retry_max_attempts: int = 3
    greenhouse_retry_base_delay: float = 1.0

    # Microsoft Graph / Outlook
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: SecretStr = Field(default=SecretStr(""))
    ms_shared_mailbox: str = ""  # The email address of the shared mailbox
    ms_graph_base_url: str = "https://graph.microsoft.com/v1.0"
    ms_graph_scopes: list[str] = Field(
        default=["https://graph.microsoft.com/.default"]
    )

    # Email Settings
    email_from_name: str = "Recruiting Team"
    email_reply_to: str = ""

    # Webhook URLs (for Graph subscriptions)
    webhook_base_url: str = "https://your-domain.com"  # Must be HTTPS in production

    # SLA Settings (in hours)
    sla_ingested_to_actioned: int = 24
    sla_contacted_to_responded: int = 72
    sla_scheduled_to_interviewed: int = 168  # 1 week
    sla_interviewed_to_decision: int = 48
    sla_scorecard_reminder_hours: int = 24
    sla_scorecard_escalation_hours: int = 48

    # Scoring Settings
    rubrics_directory: str = "config/rubrics"
    default_confidence_threshold: float = 0.7
    auto_reject_enabled: bool = True
    needs_review_on_low_confidence: bool = True

    # Feature Flags
    mock_mode: bool = False  # Use mocked APIs for local development
    dry_run: bool = False  # Log actions without executing them
    enable_auto_scheduling: bool = True
    enable_auto_rejection: bool = False  # Disabled by default for safety
    enable_scorecard_chasing: bool = True
    enable_sla_monitoring: bool = True

    # Admin UI
    admin_enabled: bool = True
    admin_username: str = "admin"
    admin_password: SecretStr = Field(default=SecretStr("change-me"))

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure database URL uses asyncpg for async operations."""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def sync_database_url(self) -> str:
        """Return synchronous database URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "")

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
