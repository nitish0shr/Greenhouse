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
    
    async def propose_slots(
        self,
        application_id: uuid.UUID,
        candidate_email: str,
        candidate_name: str,
        job_title: str,
        interviewer_emails: list[str],
        duration_minutes: int = 60,
        num_slots: int = 3,
        days_out: int = 7,
        working_hours_start: int = 9,
        working_hours_end: int = 17,
        timezone: str = "UTC",
    ) -> dict:
        """
        Propose interview slots using Graph free/busy (availabilityView).
        
        Per First Review requirements:
        - Find 3 available slots by checking interviewer calendars
        - Send email to candidate with slot options
        - Create tracking record for slot acceptance
        
        Args:
            application_id: Application UUID
            candidate_email: Candidate email
            candidate_name: Candidate name
            job_title: Job title
            interviewer_emails: List of interviewer emails to check availability
            duration_minutes: Interview duration
            num_slots: Number of slots to propose (default 3)
            days_out: Number of days to search for slots
            working_hours_start: Start of working hours (0-23)
            working_hours_end: End of working hours (0-23)
            timezone: Timezone for display
        
        Returns:
            Dict with proposed slots and email status
        """
        from app.config import settings
        
        # Get application
        app_result = self.db_session.execute(
            select(Application).where(Application.id == application_id)
        )
        application = app_result.scalar_one_or_none()
        
        if not application:
            raise ValueError(f"Application not found: {application_id}")
        
        # Define search range
        start_range = datetime.utcnow() + timedelta(days=1)  # Start tomorrow
        end_range = start_range + timedelta(days=days_out)
        
        # Find available slots
        try:
            slots = await self.graph_client.find_free_slots(
                interviewer_emails=interviewer_emails,
                start_range=start_range,
                end_range=end_range,
                duration_minutes=duration_minutes,
                num_slots=num_slots,
                working_hours_start=working_hours_start,
                working_hours_end=working_hours_end,
            )
        except GraphAPIError as e:
            logger.error(f"Failed to get free/busy schedule: {e}")
            raise
        
        if not slots:
            logger.warning(f"No available slots found for application {application_id}")
            return {
                "status": "no_slots_available",
                "application_id": str(application_id),
                "slots": [],
            }
        
        # Format slots for email
        slot_options = []
        for i, slot in enumerate(slots, 1):
            start_dt = datetime.fromisoformat(slot["start"])
            end_dt = datetime.fromisoformat(slot["end"])
            
            # Format nicely for email
            date_str = start_dt.strftime("%A, %B %d, %Y")
            time_str = f"{start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')} ({timezone})"
            
            slot_options.append({
                "option": i,
                "start": slot["start"],
                "end": slot["end"],
                "formatted": f"Option {i}: {date_str}, {time_str}",
            })
        
        # Generate tracking token
        tracking_token = f"[APP:{application.greenhouse_application_id}]"
        
        # Send proposal email to candidate
        subject = f"Interview Scheduling - {job_title} {tracking_token}"
        
        body = f"""
<html>
<body>
<p>Dear {candidate_name},</p>

<p>Thank you for your interest in the {job_title} position. We would like to schedule an interview with you.</p>

<p>Please reply to this email with your preferred time slot from the options below:</p>

<ul>
"""
        for slot_opt in slot_options:
            body += f"<li><strong>{slot_opt['formatted']}</strong></li>\n"
        
        body += f"""
</ul>

<p>The interview will be approximately {duration_minutes} minutes. A calendar invitation will be sent once you confirm your preferred time.</p>

<p>If none of these times work for you, please let us know your availability and we will find an alternative.</p>

<p>Best regards,<br>
The Recruiting Team</p>

<p style="color: #888; font-size: 10px;">Reference: {tracking_token}</p>
</body>
</html>
"""
        
        try:
            await self.graph_client.send_mail(
                to=[candidate_email],
                subject=subject,
                body=body,
                body_type="HTML",
            )
            email_sent = True
            logger.info(f"Sent slot proposal email to {candidate_email}")
        except GraphAPIError as e:
            logger.error(f"Failed to send slot proposal email: {e}")
            email_sent = False
        
        # Store proposed slots in mapping for later correlation
        # When candidate replies, we can parse their selected slot
        from app.models.message_mapping import MessageMapping
        
        mapping = MessageMapping(
            application_id=application_id,
            candidate_email=candidate_email.lower(),
            tracking_token=tracking_token,
        )
        self.db_session.add(mapping)
        self.db_session.commit()
        
        # Add note to Greenhouse about proposal
        try:
            note_body = f"""
Interview Slots Proposed by Autopilot
=====================================
Duration: {duration_minutes} minutes
Proposed Slots:
"""
            for slot_opt in slot_options:
                note_body += f"  - {slot_opt['formatted']}\n"
            
            note_body += f"\nEmail sent to: {candidate_email}\nTracking: {tracking_token}"
            
            await self.greenhouse_client.add_note_to_candidate_with_action(
                candidate_id=application.greenhouse_candidate_id,
                note_body=note_body,
                application_id=application_id,
            )
        except Exception as e:
            logger.warning(f"Failed to add proposal note to Greenhouse: {e}")
        
        return {
            "status": "proposed" if email_sent else "proposal_failed",
            "application_id": str(application_id),
            "slots": slot_options,
            "email_sent": email_sent,
            "tracking_token": tracking_token,
        }

