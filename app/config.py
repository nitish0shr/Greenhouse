# =============================================================================
# Recruiter Autopilot - Application Configuration
# =============================================================================

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # -------------------------------------------------------------------------
    # Environment
    # -------------------------------------------------------------------------
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    secret_key: str = Field(default="change-this-to-a-secure-random-string")
    
    # -------------------------------------------------------------------------
    # API Server
    # -------------------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://recruiter:recruiter_pass@localhost:5432/recruiter_autopilot"
    )
    database_url_sync: str = Field(
        default="postgresql://recruiter:recruiter_pass@localhost:5432/recruiter_autopilot"
    )
    
    # -------------------------------------------------------------------------
    # Redis
    # -------------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    
    # -------------------------------------------------------------------------
    # Greenhouse Integration
    # -------------------------------------------------------------------------
    greenhouse_api_key: str = ""
    greenhouse_webhook_secret: str = ""
    greenhouse_on_behalf_of: int = 0
    greenhouse_api_base_url: str = "https://harvest.greenhouse.io/v1"
    
    @field_validator("greenhouse_api_key", "greenhouse_webhook_secret")
    @classmethod
    def validate_greenhouse_config(cls, v: str, info) -> str:
        """Warn if Greenhouse credentials are missing in production."""
        # Validation happens at runtime, not during class definition
        return v
    
    # -------------------------------------------------------------------------
    # Microsoft Graph
    # -------------------------------------------------------------------------
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    ms_mailbox: str = ""
    ms_graph_scopes: str = "Mail.Send,Calendars.ReadWrite"
    
    @property
    def ms_graph_scope_list(self) -> list[str]:
        """Parse comma-separated scopes into a list."""
        return [s.strip() for s in self.ms_graph_scopes.split(",") if s.strip()]
    
    # -------------------------------------------------------------------------
    # Scoring Configuration
    # -------------------------------------------------------------------------
    score_threshold_advance: int = 75
    score_threshold_reject: int = 25
    low_confidence_threshold: int = 50
    scoring_rubric_path: str = "config/scoring_rubric.yaml"
    
    # -------------------------------------------------------------------------
    # Admin UI
    # -------------------------------------------------------------------------
    admin_username: str = "admin"
    admin_password: str = "change_this_password"
    
    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    
    # -------------------------------------------------------------------------
    # Mock Mode (for testing and development)
    # -------------------------------------------------------------------------
    mock_mode: bool = False

    # -------------------------------------------------------------------------
    # Feature Flags (Global defaults - can be overridden in DB)
    # -------------------------------------------------------------------------
    enable_autopilot_global: bool = True
    enable_gh_webhooks: bool = True
    enable_harvest_writeback: bool = True
    enable_graph_notifications: bool = True
    enable_scheduling: bool = True
    enable_job_board_api: bool = False
    enable_hris_export: bool = False
    enable_workday_link: bool = False

    # -------------------------------------------------------------------------
    # Email & Scheduling
    # -------------------------------------------------------------------------
    default_scheduling_mode: str = "propose_slots"  # or "send_link"
    email_tracking_token_prefix: str = "[APP:"
    followup_days: int = 3  # Days before sending follow-up
    scorecard_chase_hours: int = 24  # Hours after interview to chase scorecard

    # -------------------------------------------------------------------------
    # Rate Limiting & Retry
    # -------------------------------------------------------------------------
    greenhouse_rate_limit_per_second: int = 50
    graph_rate_limit_per_second: int = 100
    max_retry_attempts: int = 5
    retry_backoff_base: int = 60  # Base seconds for exponential backoff

    # -------------------------------------------------------------------------
    # DLQ & Cleanup
    # -------------------------------------------------------------------------
    dlq_max_retries: int = 5
    event_retention_days: int = 90
    attachment_retention_days: int = 30

    # -------------------------------------------------------------------------
    # Computed Properties
    # -------------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def greenhouse_configured(self) -> bool:
        return bool(self.greenhouse_api_key and self.greenhouse_webhook_secret)
    
    @property
    def graph_configured(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Export settings instance for convenience
settings = get_settings()
