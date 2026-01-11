# =============================================================================
# Decision Engine - Threshold-Based Action Decision with Full Implementation
# =============================================================================

import logging
from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.config import settings
from app.models.application import Application
from app.models.job_config import JobConfig
from app.models.exception import Exception as ExceptionModel
from app.models.scoring_result import ScoringResult
from app.models.human_review import HumanReviewQueue
from app.schemas.scoring import ScoringOutput
from app.services.greenhouse_writeback import GreenhouseWritebackClient
from app.services.microsoft_graph import GraphClient, GraphAPIError
from app.services.greenhouse import GreenhouseAPIError

logger = logging.getLogger(__name__)


class DecisionEngine:
    """
    Decision engine that takes scoring output and decides on actions.

    Per First Review requirements:
    - hard_reject=true → reject in GH + send rejection email + tag AI-Reject
    - tier="A" and confidence >= threshold → advance stage + start scheduling + tag AI-A
    - tier="B" → tag AI-B, may advance or review based on config
    - tier="C" or needs_human_review=true → move to Human Review stage + tag AI-Review
    - tier="REJECT" → auto-reject if confidence high enough
    """

    def __init__(
        self,
        db_session: Session,
        greenhouse_client: GreenhouseWritebackClient,
        graph_client: Optional[GraphClient] = None,
    ):
        """
        Initialize decision engine.

        Args:
            db_session: Database session
            greenhouse_client: GreenhouseWritebackClient for writebacks
            graph_client: GraphClient for sending emails (optional)
        """
        self.db_session = db_session
        self.greenhouse_client = greenhouse_client
        self.graph_client = graph_client or GraphClient()

    async def decide_and_act(
        self,
        application: Application,
        scoring_output: dict,
        candidate_email: Optional[str] = None,
    ) -> dict:
        """
        Make decision based on scoring output and take action.

        Args:
            application: Application record
            scoring_output: ScoringOutput dict (validated)
            candidate_email: Candidate email for sending notifications

        Returns:
            Dict with decision, actions taken, and any errors
        """
        # Get job config for thresholds and templates
        job_config = self._get_job_config(application.greenhouse_job_id)
        thresholds = self._get_thresholds(job_config)

        # Store scoring result
        self._store_scoring_result(application, scoring_output)

        # Extract scoring values
        hard_reject = scoring_output["hard_reject"]
        hard_reject_reasons = scoring_output.get("hard_reject_reasons", [])
        weighted_score = scoring_output["weighted_score"]
        tier = scoring_output["tier"]
        confidence = scoring_output["confidence"]
        needs_human_review = scoring_output["needs_human_review"]
        needs_human_review_reasons = scoring_output.get("needs_human_review_reasons", [])

        # Get candidate_id for writebacks
        candidate_id = application.greenhouse_candidate_id
        if not candidate_id:
            logger.error(f"Cannot take action: missing candidate_id for application {application.id}")
            self._create_exception(
                application.id,
                "missing_candidate_id",
                "Cannot take decision action: missing candidate_id",
            )
            return {
                "decision": "error",
                "error": "Missing candidate_id",
                "actions_taken": [],
            }

        actions_taken = []
        errors = []

        # =======================================================================
        # Decision 1: Hard Reject (failed hard constraints)
        # =======================================================================
        if hard_reject:
            logger.info(
                f"Hard rejecting application {application.greenhouse_application_id}: "
                f"{hard_reject_reasons}"
            )
            return await self._execute_hard_reject(
                application=application,
                candidate_id=candidate_id,
                candidate_email=candidate_email,
                scoring_output=scoring_output,
                job_config=job_config,
            )

        # =======================================================================
        # Decision 2: Tier REJECT with high confidence
        # =======================================================================
        if tier == "REJECT" and confidence >= thresholds["confidence_for_auto_reject"]:
            logger.info(
                f"Auto-rejecting low-scorer application {application.greenhouse_application_id}: "
                f"score={weighted_score}, confidence={confidence}"
            )
            return await self._execute_soft_reject(
                application=application,
                candidate_id=candidate_id,
                candidate_email=candidate_email,
                scoring_output=scoring_output,
                job_config=job_config,
            )

        # =======================================================================
        # Decision 3: Tier A - Advance and optionally schedule
        # =======================================================================
        if tier == "A" and confidence >= thresholds["confidence_for_advance"]:
            logger.info(
                f"Auto-advancing A-tier application {application.greenhouse_application_id}: "
                f"score={weighted_score}, tier={tier}, confidence={confidence}"
            )
            return await self._execute_advance(
                application=application,
                candidate_id=candidate_id,
                candidate_email=candidate_email,
                scoring_output=scoring_output,
                job_config=job_config,
            )

        # =======================================================================
        # Decision 4: Tier B - May advance or review based on config
        # =======================================================================
        if tier == "B":
            if confidence >= thresholds["confidence_for_advance"]:
                logger.info(
                    f"Auto-advancing B-tier application {application.greenhouse_application_id}: "
                    f"score={weighted_score}"
                )
                return await self._execute_advance(
                    application=application,
                    candidate_id=candidate_id,
                    candidate_email=candidate_email,
                    scoring_output=scoring_output,
                    job_config=job_config,
                    tier_tag="AI-B",
                )
            else:
                # B tier with lower confidence goes to review
                return await self._execute_human_review(
                    application=application,
                    candidate_id=candidate_id,
                    scoring_output=scoring_output,
                    review_reasons=["B-tier with low confidence"],
                )

        # =======================================================================
        # Decision 5: Tier C or needs_human_review - Human Review
        # =======================================================================
        if tier == "C" or needs_human_review:
            logger.info(
                f"Moving to human review: application {application.greenhouse_application_id}: "
                f"score={weighted_score}, tier={tier}, confidence={confidence}"
            )
            return await self._execute_human_review(
                application=application,
                candidate_id=candidate_id,
                scoring_output=scoring_output,
                review_reasons=needs_human_review_reasons or [f"Tier {tier} requires review"],
            )

        # =======================================================================
        # Default: Human review for safety
        # =======================================================================
        logger.warning(
            f"Unhandled decision case for application {application.greenhouse_application_id}, "
            f"defaulting to human review"
        )
        return await self._execute_human_review(
            application=application,
            candidate_id=candidate_id,
            scoring_output=scoring_output,
            review_reasons=["Unhandled decision case - requires manual review"],
        )

    def _get_job_config(self, job_id: int) -> Optional[JobConfig]:
        """Get job configuration for thresholds."""
        return self.db_session.execute(
            select(JobConfig).where(JobConfig.greenhouse_job_id == job_id)
        ).scalar_one_or_none()

    def _get_thresholds(self, job_config: Optional[JobConfig]) -> dict:
        """Get decision thresholds from job config or defaults."""
        if job_config:
            return {
                "advance_threshold": job_config.advance_threshold,
                "reject_threshold": job_config.reject_threshold,
                "human_review_threshold": job_config.human_review_threshold,
                "confidence_for_advance": 0.70,  # 70% confidence for auto-advance
                "confidence_for_auto_reject": 0.80,  # 80% confidence for auto-reject
            }
        return {
            "advance_threshold": settings.score_threshold_advance,
            "reject_threshold": settings.score_threshold_reject,
            "human_review_threshold": settings.low_confidence_threshold,
            "confidence_for_advance": 0.70,
            "confidence_for_auto_reject": 0.80,
        }

    def _store_scoring_result(self, application: Application, scoring_output: dict) -> None:
        """Store detailed scoring result in database."""
        try:
            result = ScoringResult(
                application_id=application.id,
                rubric_version=scoring_output["rubric_version"],
                hard_reject=scoring_output["hard_reject"],
                hard_reject_reasons=scoring_output.get("hard_reject_reasons", []),
                dimension_scores=scoring_output.get("dimension_scores", {}),
                weighted_score=scoring_output["weighted_score"],
                tier=scoring_output["tier"],
                confidence=scoring_output["confidence"],
                needs_human_review=scoring_output["needs_human_review"],
                needs_human_review_reasons=scoring_output.get("needs_human_review_reasons", []),
                evidence_snippets=scoring_output.get("evidence_snippets", []),
                missing_info_questions=scoring_output.get("missing_info_questions", []),
                raw_output=scoring_output,
            )
            self.db_session.add(result)
            self.db_session.commit()
        except Exception as e:
            logger.error(f"Failed to store scoring result: {e}")
            self.db_session.rollback()

    def _create_exception(
        self,
        application_id: uuid.UUID,
        exception_type: str,
        reason: str,
        payload_refs: Optional[dict] = None,
    ) -> None:
        """Create an exception record for tracking."""
        try:
            exc = ExceptionModel(
                application_id=application_id,
                exception_type=exception_type,
                reason=reason,
                status="open",
                payload_refs=payload_refs or {},
            )
            self.db_session.add(exc)
            self.db_session.commit()
        except Exception as e:
            logger.error(f"Failed to create exception record: {e}")
            self.db_session.rollback()

    async def _execute_hard_reject(
        self,
        application: Application,
        candidate_id: int,
        candidate_email: Optional[str],
        scoring_output: dict,
        job_config: Optional[JobConfig],
    ) -> dict:
        """Execute hard reject decision."""
        actions_taken = []
        errors = []

        # 1. Tag as AI-Reject
        try:
            await self.greenhouse_client.add_tag_with_action(
                candidate_id=candidate_id,
                tag="AI-Reject",
                application_id=application.id,
            )
            actions_taken.append("tagged_AI-Reject")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to add AI-Reject tag: {e}")
            logger.error(f"Failed to add AI-Reject tag: {e}")

        # 2. Create note with scoring results
        note_body = self._format_scoring_note(scoring_output)
        try:
            await self.greenhouse_client.add_note_to_candidate_with_action(
                candidate_id=candidate_id,
                note_body=note_body,
                application_id=application.id,
                visibility="public",
            )
            actions_taken.append("added_scoring_note")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to add scoring note: {e}")
            logger.error(f"Failed to add scoring note: {e}")

        # 3. Reject application in Greenhouse
        try:
            rejection_reason_id = self._get_rejection_reason_id(scoring_output, job_config)
            await self.greenhouse_client.reject_application_with_action(
                application_id=application.greenhouse_application_id,
                rejection_reason_id=rejection_reason_id,
                application_uuid=application.id,
                notes=f"Auto-rejected: {', '.join(scoring_output.get('hard_reject_reasons', []))}",
            )
            actions_taken.append("rejected_application")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to reject application: {e}")
            logger.error(f"Failed to reject application: {e}")
            self._create_exception(
                application.id,
                "rejection_failure",
                f"Failed to reject application: {e}",
                {"greenhouse_application_id": application.greenhouse_application_id},
            )

        # 4. Send rejection email via Graph (if configured)
        if candidate_email and job_config and job_config.email_templates.get("rejection"):
            try:
                await self._send_rejection_email(
                    candidate_email=candidate_email,
                    application=application,
                    job_config=job_config,
                )
                actions_taken.append("sent_rejection_email")
            except GraphAPIError as e:
                errors.append(f"Failed to send rejection email: {e}")
                logger.error(f"Failed to send rejection email: {e}")

        # Update application status
        application.auto_decision = "reject"
        application.processing_status = "completed"
        application.processed_at = datetime.utcnow()
        self.db_session.commit()

        return {
            "decision": "hard_reject",
            "actions_taken": actions_taken,
            "errors": errors,
        }

    async def _execute_soft_reject(
        self,
        application: Application,
        candidate_id: int,
        candidate_email: Optional[str],
        scoring_output: dict,
        job_config: Optional[JobConfig],
    ) -> dict:
        """Execute soft reject (low score, not hard constraint failure)."""
        actions_taken = []
        errors = []

        # Similar to hard reject but with different messaging
        try:
            await self.greenhouse_client.add_tag_with_action(
                candidate_id=candidate_id,
                tag="AI-Reject",
                application_id=application.id,
            )
            actions_taken.append("tagged_AI-Reject")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to add tag: {e}")

        note_body = self._format_scoring_note(scoring_output)
        try:
            await self.greenhouse_client.add_note_to_candidate_with_action(
                candidate_id=candidate_id,
                note_body=note_body,
                application_id=application.id,
            )
            actions_taken.append("added_scoring_note")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to add note: {e}")

        try:
            await self.greenhouse_client.reject_application_with_action(
                application_id=application.greenhouse_application_id,
                application_uuid=application.id,
                notes=f"Auto-rejected: Score {scoring_output['weighted_score']}/100",
            )
            actions_taken.append("rejected_application")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to reject: {e}")
            self._create_exception(
                application.id,
                "rejection_failure",
                f"Failed to reject application: {e}",
            )

        application.auto_decision = "reject"
        application.processing_status = "completed"
        application.processed_at = datetime.utcnow()
        self.db_session.commit()

        return {
            "decision": "soft_reject",
            "actions_taken": actions_taken,
            "errors": errors,
        }

    async def _execute_advance(
        self,
        application: Application,
        candidate_id: int,
        candidate_email: Optional[str],
        scoring_output: dict,
        job_config: Optional[JobConfig],
        tier_tag: str = "AI-A",
    ) -> dict:
        """Execute advance decision with optional scheduling."""
        actions_taken = []
        errors = []

        # 1. Tag with tier
        try:
            await self.greenhouse_client.add_tag_with_action(
                candidate_id=candidate_id,
                tag=tier_tag,
                application_id=application.id,
            )
            actions_taken.append(f"tagged_{tier_tag}")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to add {tier_tag} tag: {e}")

        # 2. Add scoring note
        note_body = self._format_scoring_note(scoring_output)
        try:
            await self.greenhouse_client.add_note_to_candidate_with_action(
                candidate_id=candidate_id,
                note_body=note_body,
                application_id=application.id,
            )
            actions_taken.append("added_scoring_note")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to add note: {e}")

        # 3. Advance to next stage
        if job_config and job_config.feature_flags.get("auto_advance", True):
            try:
                await self.greenhouse_client.advance_application(
                    application_id=application.greenhouse_application_id,
                    from_stage_id=application.current_stage_id,
                )
                actions_taken.append("advanced_stage")
            except GreenhouseAPIError as e:
                errors.append(f"Failed to advance stage: {e}")
                self._create_exception(
                    application.id,
                    "stage_advance_failure",
                    f"Failed to advance stage: {e}",
                )

        # 4. Send scheduling email or trigger scheduling
        if candidate_email and job_config and job_config.feature_flags.get("auto_schedule", False):
            try:
                await self._send_scheduling_email(
                    candidate_email=candidate_email,
                    application=application,
                    job_config=job_config,
                )
                actions_taken.append("sent_scheduling_email")
            except GraphAPIError as e:
                errors.append(f"Failed to send scheduling email: {e}")

        application.auto_decision = "advance"
        application.processing_status = "completed"
        application.processed_at = datetime.utcnow()
        self.db_session.commit()

        return {
            "decision": "advance",
            "tier": tier_tag,
            "actions_taken": actions_taken,
            "errors": errors,
        }

    async def _execute_human_review(
        self,
        application: Application,
        candidate_id: int,
        scoring_output: dict,
        review_reasons: list[str],
    ) -> dict:
        """Execute human review decision."""
        actions_taken = []
        errors = []

        # 1. Tag as AI-Review
        try:
            await self.greenhouse_client.add_tag_with_action(
                candidate_id=candidate_id,
                tag="AI-Review",
                application_id=application.id,
            )
            actions_taken.append("tagged_AI-Review")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to add AI-Review tag: {e}")

        # 2. Add scoring note
        note_body = self._format_scoring_note(scoring_output)
        try:
            await self.greenhouse_client.add_note_to_candidate_with_action(
                candidate_id=candidate_id,
                note_body=note_body,
                application_id=application.id,
            )
            actions_taken.append("added_scoring_note")
        except GreenhouseAPIError as e:
            errors.append(f"Failed to add note: {e}")

        # 3. Add to human review queue
        try:
            review_item = HumanReviewQueue(
                application_id=application.id,
                greenhouse_application_id=application.greenhouse_application_id,
                greenhouse_candidate_id=application.greenhouse_candidate_id,
                job_id=application.greenhouse_job_id,
                status="pending",
                review_reasons=review_reasons,
                auto_score=scoring_output["weighted_score"],
                confidence_score=scoring_output["confidence"],
                suggested_action="review",
            )
            self.db_session.add(review_item)
            self.db_session.commit()
            actions_taken.append("added_to_review_queue")
        except Exception as e:
            errors.append(f"Failed to add to review queue: {e}")
            self.db_session.rollback()

        application.auto_decision = "human_review"
        application.processing_status = "human_review"
        self.db_session.commit()

        return {
            "decision": "human_review",
            "review_reasons": review_reasons,
            "actions_taken": actions_taken,
            "errors": errors,
        }

    def _format_scoring_note(self, scoring_output: dict) -> str:
        """Format scoring results as a structured note."""
        lines = [
            "Autopilot Scoring Results",
            "=" * 40,
            f"Score: {scoring_output['weighted_score']}/100",
            f"Tier: {scoring_output['tier']}",
            f"Confidence: {scoring_output['confidence']:.2%}",
            f"Needs Human Review: {'Yes' if scoring_output['needs_human_review'] else 'No'}",
            "",
            "Dimension Scores:",
        ]

        for dim_name, dim_score in scoring_output.get("dimension_scores", {}).items():
            score_val = dim_score.get("score", 0) if isinstance(dim_score, dict) else dim_score
            lines.append(f"  {dim_name}: {score_val}/100")

        if scoring_output.get("hard_reject_reasons"):
            lines.extend(["", "Hard Reject Reasons:"])
            for reason in scoring_output["hard_reject_reasons"]:
                lines.append(f"  - {reason}")

        if scoring_output.get("needs_human_review_reasons"):
            lines.extend(["", "Review Reasons:"])
            for reason in scoring_output["needs_human_review_reasons"]:
                lines.append(f"  - {reason}")

        if scoring_output.get("evidence_snippets"):
            lines.extend(["", "Key Evidence:"])
            for i, evidence in enumerate(scoring_output["evidence_snippets"][:3], 1):
                snippet = evidence.get("snippet", str(evidence))[:100]
                lines.append(f"  {i}. {snippet}...")

        lines.extend([
            "",
            f"Rubric Version: {scoring_output['rubric_version']}",
        ])

        return "\n".join(lines)

    def _get_rejection_reason_id(
        self,
        scoring_output: dict,
        job_config: Optional[JobConfig],
    ) -> Optional[int]:
        """Get rejection reason ID from config or scoring output."""
        # Check if hard constraint has rejection_reason_id
        # This would typically come from the rubric
        return None  # Default - Greenhouse will use default reason

    async def _send_rejection_email(
        self,
        candidate_email: str,
        application: Application,
        job_config: JobConfig,
    ) -> None:
        """Send rejection email via Graph."""
        template = job_config.email_templates.get("rejection", {})
        subject = template.get("subject", "Update on your application")
        body = template.get("body", "Thank you for your interest. Unfortunately...")

        # Add tracking token
        tracking_token = f"[APP:{application.greenhouse_application_id}]"
        body_with_token = f"{body}\n\n{tracking_token}"

        await self.graph_client.send_mail(
            to=[candidate_email],
            subject=subject,
            body=body_with_token,
            body_type="HTML",
        )

    async def _send_scheduling_email(
        self,
        candidate_email: str,
        application: Application,
        job_config: JobConfig,
    ) -> None:
        """Send scheduling email via Graph."""
        template = job_config.email_templates.get("scheduling", {})
        subject = template.get("subject", "Interview Scheduling")
        body = template.get("body", "We would like to schedule an interview...")

        tracking_token = f"[APP:{application.greenhouse_application_id}]"
        body_with_token = f"{body}\n\n{tracking_token}"

        await self.graph_client.send_mail(
            to=[candidate_email],
            subject=subject,
            body=body_with_token,
            body_type="HTML",
        )
