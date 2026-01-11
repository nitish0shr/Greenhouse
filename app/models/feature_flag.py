# =============================================================================
# Feature Flag Model - Global and Scoped Feature Flags
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, String, Text, func, BigInteger, Boolean
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FeatureFlag(Base):
    """
    Feature flags for controlling automation behavior.

    Supports global, job-level, and stage-level scopes.
    """

    __tablename__ = "feature_flags"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Flag name (unique)
    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    # Enabled state
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    # Description
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Scope: global, job, stage
    scope: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="global",
    )

    # Scope ID (job_id or stage_id, null for global)
    scope_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
    )

    # Additional metadata
    metadata_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<FeatureFlag {self.name}={self.enabled} scope={self.scope}>"


# =============================================================================
# Feature Flag Constants
# =============================================================================

class FeatureFlags:
    """Constants for feature flag names."""

    # Global autopilot kill switch
    ENABLE_AUTOPILOT_GLOBAL = "ENABLE_AUTOPILOT_GLOBAL"

    # Webhook processing
    ENABLE_GH_WEBHOOKS = "ENABLE_GH_WEBHOOKS"
    ENABLE_GRAPH_NOTIFICATIONS = "ENABLE_GRAPH_NOTIFICATIONS"

    # Harvest API operations
    ENABLE_HARVEST_WRITEBACK = "ENABLE_HARVEST_WRITEBACK"

    # Scheduling
    ENABLE_SCHEDULING = "ENABLE_SCHEDULING"

    # Optional modules
    ENABLE_JOB_BOARD_API = "ENABLE_JOB_BOARD_API"
    ENABLE_HRIS_EXPORT = "ENABLE_HRIS_EXPORT"
    ENABLE_WORKDAY_LINK = "ENABLE_WORKDAY_LINK"

    # Per-job flags (use with scope="job" and scope_id=job_id)
    ENABLE_JOB_AUTOPILOT = "ENABLE_JOB_AUTOPILOT"

    # Per-stage flags (use with scope="stage" and scope_id=stage_id)
    ENABLE_STAGE_AUTOPILOT = "ENABLE_STAGE_AUTOPILOT"


# Default flag definitions for initialization
DEFAULT_FLAGS = [
    {
        "name": FeatureFlags.ENABLE_AUTOPILOT_GLOBAL,
        "enabled": True,
        "description": "Global autopilot kill switch - disables all automation when off",
        "scope": "global",
    },
    {
        "name": FeatureFlags.ENABLE_GH_WEBHOOKS,
        "enabled": True,
        "description": "Process incoming Greenhouse webhooks",
        "scope": "global",
    },
    {
        "name": FeatureFlags.ENABLE_HARVEST_WRITEBACK,
        "enabled": True,
        "description": "Write back to Greenhouse Harvest API (tags, notes, stage moves)",
        "scope": "global",
    },
    {
        "name": FeatureFlags.ENABLE_GRAPH_NOTIFICATIONS,
        "enabled": True,
        "description": "Process Microsoft Graph notifications (email replies)",
        "scope": "global",
    },
    {
        "name": FeatureFlags.ENABLE_SCHEDULING,
        "enabled": True,
        "description": "Enable interview scheduling automation",
        "scope": "global",
    },
    {
        "name": FeatureFlags.ENABLE_JOB_BOARD_API,
        "enabled": False,
        "description": "Enable Greenhouse Job Board API (optional module)",
        "scope": "global",
    },
    {
        "name": FeatureFlags.ENABLE_HRIS_EXPORT,
        "enabled": False,
        "description": "Enable HRIS export functionality (optional module)",
        "scope": "global",
    },
    {
        "name": FeatureFlags.ENABLE_WORKDAY_LINK,
        "enabled": False,
        "description": "Enable Workday integration (optional module)",
        "scope": "global",
    },
]
