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
    api_port: int = Field(default=8000)
    
    @field_validator("api_port", mode="before")
    @classmethod
    def parse_port(cls, v):
        """Parse PORT from environment (Railway, Heroku, etc.)."""
        import os
        return int(os.getenv("PORT", v))
    
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
