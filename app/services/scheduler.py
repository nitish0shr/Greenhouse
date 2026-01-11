# =============================================================================
# Scheduler - Interview Scheduling Service
# =============================================================================

import logging
from datetime import datetime, timedelta
from typing import Optional
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.application import Application
from app.models.calendar_mapping import CalendarMapping
from app.models.job_config import JobConfig
from app.services.greenhouse_writeback import GreenhouseWritebackClient
from app.services.microsoft_graph import GraphClient, GraphAPIError

logger = logging.getLogger(__name__)


class Scheduler:
    """
    Interview scheduling service.
    
    Per First Review requirements:
    - Create Outlook calendar event via Graph
    - Create Greenhouse scheduled interview via Harvest
    - Store mappings: external_event_id ↔ greenhouse_interview_id ↔ application_id
    - Write structured Greenhouse note with mappings
    - Handle reschedules/cancellations
    """
    
    def __init__(
        self,
        db_session: Session,
        greenhouse_client: GreenhouseWritebackClient,
        graph_client: Optional[GraphClient] = None,
    ):
        """
        Initialize scheduler.
        
        Args:
            db_session: Database session
            greenhouse_client: GreenhouseWritebackClient for interviews
            graph_client: GraphClient for calendar events
        """
        self.db_session = db_session
        self.greenhouse_client = greenhouse_client
        self.graph_client = graph_client or GraphClient()
    
    async def schedule_interview(
        self,
        application_id: uuid.UUID,
        candidate_email: str,
        candidate_name: str,
        job_title: str,
        start_time: datetime,
        end_time: datetime,
        location: Optional[str] = None,
        interviewer_emails: Optional[list[str]] = None,
        timezone: str = "UTC",
    ) -> dict:
        """
        Schedule an interview in both Outlook and Greenhouse.
        
        Args:
            application_id: Application UUID
            candidate_email: Candidate email
            candidate_name: Candidate name
            job_title: Job title
            start_time: Interview start time
            end_time: Interview end time
            location: Meeting location/URL
            interviewer_emails: List of interviewer emails
            timezone: Timezone (default UTC)
        
        Returns:
            Dict with external_event_id, greenhouse_interview_id, and mapping record
        """
        # Get application
        app_result = self.db_session.execute(
            select(Application).where(Application.id == application_id)
        )
        application = app_result.scalar_one_or_none()
        
        if not application:
            raise ValueError(f"Application not found: {application_id}")
        
        # Get job config for scheduling mode
        job_config = self.db_session.execute(
            select(JobConfig).where(JobConfig.greenhouse_job_id == application.greenhouse_job_id)
        ).scalar_one_or_none()
        
        scheduling_mode = job_config.scheduling_mode if job_config else "propose_slots"
        
        # Create Outlook calendar event
        subject = f"Interview: {candidate_name} - {job_title}"
        attendees = [candidate_email]
        if interviewer_emails:
            attendees.extend(interviewer_emails)
        
        try:
            event_data = await self.graph_client.create_calendar_event(
                subject=subject,
                start=start_time,
                end=end_time,
                attendees=attendees,
                location=location,
                body=f"Interview for {job_title} position",
                is_online_meeting=bool(location and ("zoom" in location.lower() or "teams" in location.lower() or "meet" in location.lower())),
            )
            
            external_event_id = event_data["id"]
            logger.info(f"Created Outlook event: {external_event_id}")
        except GraphAPIError as e:
            logger.error(f"Failed to create Outlook event: {e}")
            raise
        
        # Create Greenhouse scheduled interview
        greenhouse_interview_id = None
        
        try:
            # Get interview type ID (default to first available, or configure in JobConfig)
            # For now, we'll use a default interview type ID of 1
            # In production, this should come from JobConfig or be fetched from job settings
            interview_type_id = 1  # Default, should be configurable
            
            # Convert interviewer emails to interviewer IDs
            # Note: This is simplified - in production, you'd need to look up user IDs by email
            interviewer_ids = []
            # TODO: Lookup interviewer IDs from emails
            # For now, using empty list - Greenhouse will require at least one interviewer
            
            interview_data = await self.greenhouse_client.create_scheduled_interview(
                application_id=application.greenhouse_application_id,
                interview_id=interview_type_id,
                interviewers=interviewer_ids if interviewer_ids else [{"user_id": self.greenhouse_client.on_behalf_of}],  # Fallback to on-behalf-of user
                start=start_time,
                end=end_time,
                external_event_id=external_event_id,
                location=location,
            )
            greenhouse_interview_id = interview_data.get("id")
            logger.info(f"Created Greenhouse interview: {greenhouse_interview_id}")
        except Exception as e:
            logger.error(f"Failed to create Greenhouse interview: {e}")
            # Continue with Outlook event only - create exception for human reconciliation
        
        # Store calendar mapping
        mapping = CalendarMapping(
            application_id=application_id,
            external_event_id=external_event_id,
            greenhouse_interview_id=greenhouse_interview_id,
            status="scheduled",
        )
        self.db_session.add(mapping)
        self.db_session.commit()
        
        # Create structured Greenhouse note with mappings
        note_body = self._format_scheduling_note(
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            location=location,
            attendees=attendees,
            external_event_id=external_event_id,
            greenhouse_interview_id=greenhouse_interview_id,
        )
        
        try:
            await self.greenhouse_client.add_note_to_candidate_with_action(
                candidate_id=application.greenhouse_candidate_id,
                note_body=note_body,
                application_id=application_id,
                visibility="public",
            )
        except Exception as e:
            logger.warning(f"Failed to add scheduling note: {e}")
        
        return {
            "external_event_id": external_event_id,
            "greenhouse_interview_id": greenhouse_interview_id,
            "mapping_id": mapping.id,
        }
    
    def _format_scheduling_note(
        self,
        start_time: datetime,
        end_time: datetime,
        timezone: str,
        location: Optional[str],
        attendees: list[str],
        external_event_id: str,
        greenhouse_interview_id: Optional[int],
    ) -> str:
        """
        Format structured scheduling note.
        
        Args:
            start_time: Interview start
            end_time: Interview end
            timezone: Timezone
            location: Location/URL
            attendees: List of attendee emails
            external_event_id: Outlook event ID
            greenhouse_interview_id: Greenhouse interview ID
        
        Returns:
            Formatted note body
        """
        lines = [
            "Interview Scheduled by Autopilot",
            "=" * 40,
            f"Start: {start_time.isoformat()} ({timezone})",
            f"End: {end_time.isoformat()} ({timezone})",
            f"Location: {location or 'TBD'}",
            f"Attendees: {', '.join(attendees)}",
            "",
            "External References:",
            f"  Outlook Event ID: {external_event_id}",
        ]
        
        if greenhouse_interview_id:
            lines.append(f"  Greenhouse Interview ID: {greenhouse_interview_id}")
        
        return "\n".join(lines)
    
    async def reschedule_interview(
        self,
        mapping_id: uuid.UUID,
        new_start_time: datetime,
        new_end_time: datetime,
    ) -> dict:
        """
        Reschedule an interview in both systems.
        
        Args:
            mapping_id: CalendarMapping ID
            new_start_time: New start time
            new_end_time: New end time
        
        Returns:
            Updated mapping record
        """
        mapping = self.db_session.get(CalendarMapping, mapping_id)
        if not mapping:
            raise ValueError(f"Calendar mapping not found: {mapping_id}")
        
        # Update Outlook event
        try:
            await self.graph_client.update_calendar_event(
                event_id=mapping.external_event_id,
                start=new_start_time,
                end=new_end_time,
            )
            logger.info(f"Updated Outlook event: {mapping.external_event_id}")
        except GraphAPIError as e:
            logger.error(f"Failed to update Outlook event: {e}")
            # Create exception for human reconciliation
        
        # Update Greenhouse interview
        if mapping.greenhouse_interview_id:
            try:
                await self.greenhouse_client.update_scheduled_interview(
                    interview_id=mapping.greenhouse_interview_id,
                    start=new_start_time,
                    end=new_end_time,
                )
                logger.info(f"Updated Greenhouse interview: {mapping.greenhouse_interview_id}")
            except Exception as e:
                logger.error(f"Failed to update Greenhouse interview: {e}")
                # Create exception for human reconciliation
        
        # Update mapping
        mapping.status = "rescheduled"
        mapping.updated_at = datetime.utcnow()
        self.db_session.commit()
        
        return mapping
    
    async def cancel_interview(
        self,
        mapping_id: uuid.UUID,
    ) -> dict:
        """
        Cancel an interview in both systems.
        
        Args:
            mapping_id: CalendarMapping ID
        
        Returns:
            Updated mapping record
        """
        mapping = self.db_session.get(CalendarMapping, mapping_id)
        if not mapping:
            raise ValueError(f"Calendar mapping not found: {mapping_id}")
        
        # Delete Outlook event
        try:
            await self.graph_client.delete_calendar_event(
                event_id=mapping.external_event_id,
            )
            logger.info(f"Deleted Outlook event: {mapping.external_event_id}")
        except GraphAPIError as e:
            logger.error(f"Failed to delete Outlook event: {e}")
            # Create exception for human reconciliation
        
        # Cancel Greenhouse interview
        if mapping.greenhouse_interview_id:
            try:
                await self.greenhouse_client.delete_scheduled_interview(
                    interview_id=mapping.greenhouse_interview_id,
                )
                logger.info(f"Cancelled Greenhouse interview: {mapping.greenhouse_interview_id}")
            except Exception as e:
                logger.error(f"Failed to cancel Greenhouse interview: {e}")
                # Create exception for human reconciliation
        
        # Update mapping
        mapping.status = "cancelled"
        mapping.updated_at = datetime.utcnow()
        self.db_session.commit()
        
        return mapping
