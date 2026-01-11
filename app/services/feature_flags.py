# =============================================================================
# Feature Flags Service - Query and Manage Feature Flags
# =============================================================================

import logging
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models.feature_flag import FeatureFlag, FeatureFlags, DEFAULT_FLAGS
from app.models.job_config import JobConfig

logger = logging.getLogger(__name__)


class FeatureFlagService:
    """
    Service for querying and managing feature flags.

    Supports global, job-level, and stage-level flags with inheritance.
    """

    def __init__(self, db_session: Session):
        """
        Initialize feature flag service.

        Args:
            db_session: Database session
        """
        self.db_session = db_session

    def is_enabled(
        self,
        flag_name: str,
        job_id: Optional[int] = None,
        stage_id: Optional[int] = None,
    ) -> bool:
        """
        Check if a feature flag is enabled.

        Flag hierarchy (most specific wins):
        1. Stage-level flag (if stage_id provided)
        2. Job-level flag (if job_id provided)
        3. Global flag

        Args:
            flag_name: Feature flag name
            job_id: Optional job ID for job-scoped check
            stage_id: Optional stage ID for stage-scoped check

        Returns:
            True if enabled, False otherwise
        """
        # Check global kill switch first
        if flag_name != FeatureFlags.ENABLE_AUTOPILOT_GLOBAL:
            if not self.is_enabled(FeatureFlags.ENABLE_AUTOPILOT_GLOBAL):
                logger.debug(f"Flag {flag_name} disabled: global autopilot is off")
                return False

        # Check stage-level override
        if stage_id:
            stage_flag = self._get_flag(flag_name, scope="stage", scope_id=stage_id)
            if stage_flag is not None:
                return stage_flag.enabled

        # Check job-level override
        if job_id:
            # First check JobConfig.enabled
            job_config = self.db_session.execute(
                select(JobConfig).where(JobConfig.greenhouse_job_id == job_id)
            ).scalar_one_or_none()

            if job_config and not job_config.enabled:
                logger.debug(f"Flag {flag_name} disabled: job {job_id} autopilot is off")
                return False

            # Check job-specific flag
            job_flag = self._get_flag(flag_name, scope="job", scope_id=job_id)
            if job_flag is not None:
                return job_flag.enabled

        # Check global flag
        global_flag = self._get_flag(flag_name, scope="global")
        if global_flag is not None:
            return global_flag.enabled

        # Default: enabled for core features, disabled for optional
        return self._get_default_state(flag_name)

    def _get_flag(
        self,
        flag_name: str,
        scope: str,
        scope_id: Optional[int] = None,
    ) -> Optional[FeatureFlag]:
        """Get a specific flag record."""
        query = select(FeatureFlag).where(
            and_(
                FeatureFlag.name == flag_name,
                FeatureFlag.scope == scope,
            )
        )

        if scope_id is not None:
            query = query.where(FeatureFlag.scope_id == scope_id)
        else:
            query = query.where(FeatureFlag.scope_id.is_(None))

        return self.db_session.execute(query).scalar_one_or_none()

    def _get_default_state(self, flag_name: str) -> bool:
        """Get default enabled state for a flag."""
        # Optional modules default to disabled
        optional_modules = [
            FeatureFlags.ENABLE_JOB_BOARD_API,
            FeatureFlags.ENABLE_HRIS_EXPORT,
            FeatureFlags.ENABLE_WORKDAY_LINK,
        ]

        if flag_name in optional_modules:
            return False

        # Core features default to enabled
        return True

    def set_flag(
        self,
        flag_name: str,
        enabled: bool,
        scope: str = "global",
        scope_id: Optional[int] = None,
        description: Optional[str] = None,
    ) -> FeatureFlag:
        """
        Set a feature flag value.

        Args:
            flag_name: Feature flag name
            enabled: Whether flag is enabled
            scope: Flag scope (global, job, stage)
            scope_id: Scope identifier (job_id or stage_id)
            description: Optional description

        Returns:
            Updated or created FeatureFlag record
        """
        flag = self._get_flag(flag_name, scope, scope_id)

        if flag:
            flag.enabled = enabled
            if description:
                flag.description = description
        else:
            flag = FeatureFlag(
                name=flag_name,
                enabled=enabled,
                scope=scope,
                scope_id=scope_id,
                description=description,
            )
            self.db_session.add(flag)

        self.db_session.commit()
        logger.info(f"Set feature flag {flag_name} ({scope}) = {enabled}")
        return flag

    def get_all_flags(self) -> list[dict]:
        """
        Get all feature flags with their current states.

        Returns:
            List of flag dictionaries
        """
        flags = self.db_session.execute(
            select(FeatureFlag).order_by(FeatureFlag.scope, FeatureFlag.name)
        ).scalars().all()

        return [
            {
                "name": flag.name,
                "enabled": flag.enabled,
                "scope": flag.scope,
                "scope_id": flag.scope_id,
                "description": flag.description,
            }
            for flag in flags
        ]

    def initialize_default_flags(self) -> None:
        """Initialize default feature flags if they don't exist."""
        for flag_def in DEFAULT_FLAGS:
            existing = self._get_flag(flag_def["name"], flag_def.get("scope", "global"))
            if not existing:
                flag = FeatureFlag(
                    name=flag_def["name"],
                    enabled=flag_def["enabled"],
                    scope=flag_def.get("scope", "global"),
                    description=flag_def.get("description"),
                )
                self.db_session.add(flag)
                logger.info(f"Initialized feature flag: {flag_def['name']}")

        self.db_session.commit()

    # =========================================================================
    # Convenience methods for specific flags
    # =========================================================================

    def is_autopilot_enabled(self, job_id: Optional[int] = None) -> bool:
        """Check if autopilot is enabled globally and for a specific job."""
        return self.is_enabled(FeatureFlags.ENABLE_AUTOPILOT_GLOBAL, job_id=job_id)

    def is_harvest_writeback_enabled(self) -> bool:
        """Check if Harvest API writeback is enabled."""
        return self.is_enabled(FeatureFlags.ENABLE_HARVEST_WRITEBACK)

    def is_scheduling_enabled(self) -> bool:
        """Check if interview scheduling is enabled."""
        return self.is_enabled(FeatureFlags.ENABLE_SCHEDULING)

    def is_graph_notifications_enabled(self) -> bool:
        """Check if Graph notifications are enabled."""
        return self.is_enabled(FeatureFlags.ENABLE_GRAPH_NOTIFICATIONS)

    # =========================================================================
    # Kill switch methods
    # =========================================================================

    def enable_global_autopilot(self) -> None:
        """Enable global autopilot."""
        self.set_flag(FeatureFlags.ENABLE_AUTOPILOT_GLOBAL, True)

    def disable_global_autopilot(self) -> None:
        """Disable global autopilot (kill switch)."""
        self.set_flag(FeatureFlags.ENABLE_AUTOPILOT_GLOBAL, False)

    def enable_job_autopilot(self, job_id: int) -> None:
        """Enable autopilot for a specific job."""
        self.set_flag(
            FeatureFlags.ENABLE_JOB_AUTOPILOT,
            True,
            scope="job",
            scope_id=job_id,
        )

    def disable_job_autopilot(self, job_id: int) -> None:
        """Disable autopilot for a specific job."""
        self.set_flag(
            FeatureFlags.ENABLE_JOB_AUTOPILOT,
            False,
            scope="job",
            scope_id=job_id,
        )
