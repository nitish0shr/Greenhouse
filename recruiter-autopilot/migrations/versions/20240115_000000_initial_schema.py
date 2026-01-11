"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    op.execute("CREATE TYPE applicationstate AS ENUM ('ingested', 'parsed', 'scored', 'actioned', 'contacted', 'scheduling', 'scheduled', 'interviewed', 'decision_pending', 'closed', 'needs_review', 'exception')")
    op.execute("CREATE TYPE applicationtier AS ENUM ('A', 'B', 'C', 'REJECT')")
    op.execute("CREATE TYPE webhooksource AS ENUM ('greenhouse', 'microsoft_graph')")
    op.execute("CREATE TYPE webhookstatus AS ENUM ('received', 'queued', 'processing', 'completed', 'failed', 'ignored')")
    op.execute("CREATE TYPE emailstatus AS ENUM ('pending', 'sent', 'delivered', 'bounced', 'failed')")
    op.execute("CREATE TYPE emaildirection AS ENUM ('outbound', 'inbound')")
    op.execute("CREATE TYPE calendareventstatus AS ENUM ('pending', 'confirmed', 'tentative', 'cancelled', 'completed')")
    op.execute("CREATE TYPE calendareventtype AS ENUM ('phone_screen', 'video_interview', 'onsite_interview', 'technical_interview', 'panel_interview', 'hiring_manager_interview', 'final_round', 'other')")
    op.execute("CREATE TYPE exceptiontype AS ENUM ('parse_error', 'scoring_error', 'api_error', 'validation_error', 'low_confidence', 'borderline_score', 'missing_info', 'conflicting_data', 'email_bounce', 'no_reply', 'unclear_intent', 'scheduling_conflict', 'reschedule_request', 'no_show', 'protected_trait_mention', 'unusual_pattern', 'manual_review', 'hiring_manager_escalation')")
    op.execute("CREATE TYPE exceptionpriority AS ENUM ('low', 'medium', 'high', 'urgent')")
    op.execute("CREATE TYPE slatype AS ENUM ('ingested_to_actioned', 'contacted_to_responded', 'scheduling_to_scheduled', 'scheduled_to_interviewed', 'interviewed_to_decision', 'scorecard_submission', 'custom')")

    # Create candidates table
    op.create_table('candidates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('greenhouse_id', sa.BigInteger(), nullable=False),
        sa.Column('first_name', sa.String(length=255), nullable=True),
        sa.Column('last_name', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('company', sa.String(length=255), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('linkedin_url', sa.String(length=500), nullable=True),
        sa.Column('website_urls', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('resume_text', sa.Text(), nullable=True),
        sa.Column('resume_extracted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('extracted_facts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('source', sa.String(length=255), nullable=True),
        sa.Column('referrer', sa.String(length=255), nullable=True),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('greenhouse_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('greenhouse_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('needs_resync', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_candidates')),
        sa.UniqueConstraint('greenhouse_id', name=op.f('uq_candidates_greenhouse_id'))
    )
    op.create_index(op.f('ix_candidates_email'), 'candidates', ['email'], unique=False)
    op.create_index(op.f('ix_candidates_greenhouse_id'), 'candidates', ['greenhouse_id'], unique=False)

    # Create rubrics table
    op.create_table('rubrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('active_version', sa.String(length=50), nullable=False, default='1.0'),
        sa.Column('dimensions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('hard_constraints', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tier_thresholds', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('confidence_threshold', sa.Float(), nullable=False, default=0.7),
        sa.Column('low_confidence_triggers_review', sa.Boolean(), nullable=False, default=True),
        sa.Column('needs_human_review_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('deprecated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('last_modified_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rubrics')),
        sa.UniqueConstraint('slug', name=op.f('uq_rubrics_slug'))
    )
    op.create_index(op.f('ix_rubrics_slug'), 'rubrics', ['slug'], unique=False)

    # Create rubric_versions table
    op.create_table('rubric_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rubric_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=False),
        sa.Column('changelog', sa.Text(), nullable=True),
        sa.Column('config_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['rubric_id'], ['rubrics.id'], name=op.f('fk_rubric_versions_rubric_id_rubrics')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rubric_versions'))
    )
    op.create_index(op.f('ix_rubric_versions_rubric_id'), 'rubric_versions', ['rubric_id'], unique=False)

    # Create jobs table
    op.create_table('jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('greenhouse_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=500), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, default='open'),
        sa.Column('department', sa.String(length=255), nullable=True),
        sa.Column('office', sa.String(length=255), nullable=True),
        sa.Column('hiring_manager_id', sa.BigInteger(), nullable=True),
        sa.Column('hiring_manager_email', sa.String(length=255), nullable=True),
        sa.Column('recruiter_id', sa.BigInteger(), nullable=True),
        sa.Column('recruiter_email', sa.String(length=255), nullable=True),
        sa.Column('coordinator_id', sa.BigInteger(), nullable=True),
        sa.Column('coordinator_email', sa.String(length=255), nullable=True),
        sa.Column('automation_enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('auto_advance_enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('auto_reject_enabled', sa.Boolean(), nullable=False, default=False),
        sa.Column('auto_email_enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('auto_schedule_enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('rubric_id', sa.Integer(), nullable=True),
        sa.Column('stage_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('email_templates', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('default_rejection_reason_id', sa.BigInteger(), nullable=True),
        sa.Column('rejection_email_template', sa.String(length=100), nullable=True),
        sa.Column('default_interview_duration_minutes', sa.Integer(), nullable=True, default=60),
        sa.Column('interview_buffer_minutes', sa.Integer(), nullable=True, default=15),
        sa.Column('sla_ingested_to_actioned', sa.Integer(), nullable=True),
        sa.Column('sla_contacted_to_responded', sa.Integer(), nullable=True),
        sa.Column('automation_notes', sa.Text(), nullable=True),
        sa.Column('greenhouse_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('greenhouse_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['rubric_id'], ['rubrics.id'], name=op.f('fk_jobs_rubric_id_rubrics')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs')),
        sa.UniqueConstraint('greenhouse_id', name=op.f('uq_jobs_greenhouse_id'))
    )
    op.create_index(op.f('ix_jobs_greenhouse_id'), 'jobs', ['greenhouse_id'], unique=False)

    # Create job_stage_configs table
    op.create_table('job_stage_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('greenhouse_stage_id', sa.BigInteger(), nullable=False),
        sa.Column('stage_name', sa.String(length=255), nullable=False),
        sa.Column('stage_order', sa.Integer(), nullable=False, default=0),
        sa.Column('auto_advance_enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('auto_advance_to_stage_id', sa.BigInteger(), nullable=True),
        sa.Column('auto_advance_tier', sa.String(length=10), nullable=True),
        sa.Column('auto_reject_enabled', sa.Boolean(), nullable=False, default=False),
        sa.Column('rejection_reason_id', sa.BigInteger(), nullable=True),
        sa.Column('email_on_entry', sa.Boolean(), nullable=False, default=False),
        sa.Column('entry_email_template', sa.String(length=100), nullable=True),
        sa.Column('schedule_interview', sa.Boolean(), nullable=False, default=False),
        sa.Column('interview_type', sa.String(length=100), nullable=True),
        sa.Column('interviewer_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('custom_tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('custom_actions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_job_stage_configs_job_id_jobs')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_job_stage_configs'))
    )
    op.create_index(op.f('ix_job_stage_configs_job_id'), 'job_stage_configs', ['job_id'], unique=False)

    # Create kill_switches table
    op.create_table('kill_switches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('stage_id', sa.BigInteger(), nullable=True),
        sa.Column('stage_name', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('activated_by', sa.String(length=255), nullable=True),
        sa.Column('deactivated_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_kill_switches_job_id_jobs')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_kill_switches'))
    )
    op.create_index(op.f('ix_kill_switches_job_id'), 'kill_switches', ['job_id'], unique=False)
    op.create_index(op.f('ix_kill_switches_is_active'), 'kill_switches', ['is_active'], unique=False)

    # Create applications table
    op.create_table('applications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('greenhouse_id', sa.BigInteger(), nullable=False),
        sa.Column('candidate_id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('current_stage_id', sa.BigInteger(), nullable=True),
        sa.Column('current_stage_name', sa.String(length=255), nullable=True),
        sa.Column('state', postgresql.ENUM('ingested', 'parsed', 'scored', 'actioned', 'contacted', 'scheduling', 'scheduled', 'interviewed', 'decision_pending', 'closed', 'needs_review', 'exception', name='applicationstate', create_type=False), nullable=False),
        sa.Column('previous_state', postgresql.ENUM('ingested', 'parsed', 'scored', 'actioned', 'contacted', 'scheduling', 'scheduled', 'interviewed', 'decision_pending', 'closed', 'needs_review', 'exception', name='applicationstate', create_type=False), nullable=True),
        sa.Column('state_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('tier', postgresql.ENUM('A', 'B', 'C', 'REJECT', name='applicationtier', create_type=False), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('rubric_version', sa.String(length=50), nullable=True),
        sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('needs_human_review', sa.Boolean(), nullable=False, default=False),
        sa.Column('human_reviewed', sa.Boolean(), nullable=False, default=False),
        sa.Column('human_reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('human_reviewed_by', sa.String(length=255), nullable=True),
        sa.Column('last_email_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_email_template', sa.String(length=100), nullable=True),
        sa.Column('emails_sent_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_reply_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_reply_intent', sa.String(length=50), nullable=True),
        sa.Column('scheduled_interview_id', sa.BigInteger(), nullable=True),
        sa.Column('scheduled_interview_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('interview_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scorecards_submitted', sa.Boolean(), nullable=False, default=False),
        sa.Column('rejected', sa.Boolean(), nullable=False, default=False),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason_id', sa.BigInteger(), nullable=True),
        sa.Column('rejection_reason', sa.String(length=255), nullable=True),
        sa.Column('outcome', sa.String(length=50), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('error_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source', sa.String(length=255), nullable=True),
        sa.Column('referrer', sa.String(length=255), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('custom_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('automation_notes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], name=op.f('fk_applications_candidate_id_candidates')),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_applications_job_id_jobs')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_applications')),
        sa.UniqueConstraint('greenhouse_id', name=op.f('uq_applications_greenhouse_id'))
    )
    op.create_index(op.f('ix_applications_greenhouse_id'), 'applications', ['greenhouse_id'], unique=False)
    op.create_index(op.f('ix_applications_candidate_id'), 'applications', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_applications_job_id'), 'applications', ['job_id'], unique=False)
    op.create_index(op.f('ix_applications_state'), 'applications', ['state'], unique=False)
    op.create_index(op.f('ix_applications_needs_human_review'), 'applications', ['needs_human_review'], unique=False)

    # Create application_state_transitions table
    op.create_table('application_state_transitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('from_state', postgresql.ENUM('ingested', 'parsed', 'scored', 'actioned', 'contacted', 'scheduling', 'scheduled', 'interviewed', 'decision_pending', 'closed', 'needs_review', 'exception', name='applicationstate', create_type=False), nullable=False),
        sa.Column('to_state', postgresql.ENUM('ingested', 'parsed', 'scored', 'actioned', 'contacted', 'scheduling', 'scheduled', 'interviewed', 'decision_pending', 'closed', 'needs_review', 'exception', name='applicationstate', create_type=False), nullable=False),
        sa.Column('trigger', sa.String(length=100), nullable=False),
        sa.Column('trigger_id', sa.String(length=255), nullable=True),
        sa.Column('triggered_by', sa.String(length=255), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_state_transitions_application_id_applications')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_application_state_transitions'))
    )
    op.create_index(op.f('ix_application_state_transitions_application_id'), 'application_state_transitions', ['application_id'], unique=False)

    # Create scoring_results table
    op.create_table('scoring_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('rubric_id', sa.Integer(), nullable=True),
        sa.Column('rubric_version', sa.String(length=50), nullable=False),
        sa.Column('total_score', sa.Float(), nullable=False),
        sa.Column('max_score', sa.Float(), nullable=False),
        sa.Column('percentage', sa.Float(), nullable=False),
        sa.Column('tier', postgresql.ENUM('A', 'B', 'C', 'REJECT', name='applicationtier', create_type=False), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('dimension_scores', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('hard_constraints_passed', sa.Boolean(), nullable=False),
        sa.Column('failed_constraints', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('missing_info', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('needs_human_review', sa.Boolean(), nullable=False, default=False),
        sa.Column('review_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_scoring_results_application_id_applications')),
        sa.ForeignKeyConstraint(['rubric_id'], ['rubrics.id'], name=op.f('fk_scoring_results_rubric_id_rubrics')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_scoring_results'))
    )
    op.create_index(op.f('ix_scoring_results_application_id'), 'scoring_results', ['application_id'], unique=False)

    # Create webhook_events table
    op.create_table('webhook_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', postgresql.ENUM('greenhouse', 'microsoft_graph', name='webhooksource', create_type=False), nullable=False),
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('status', postgresql.ENUM('received', 'queued', 'processing', 'completed', 'failed', 'ignored', name='webhookstatus', create_type=False), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('greenhouse_application_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_candidate_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_job_id', sa.BigInteger(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('signature_verified', sa.Boolean(), nullable=False, default=False),
        sa.Column('signature_header', sa.String(length=500), nullable=True),
        sa.Column('worker_task_id', sa.String(length=255), nullable=True),
        sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processing_duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('max_retries', sa.Integer(), nullable=False, default=3),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('correlation_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_events'))
    )
    op.create_index(op.f('ix_webhook_events_source'), 'webhook_events', ['source'], unique=False)
    op.create_index(op.f('ix_webhook_events_event_id'), 'webhook_events', ['event_id'], unique=False)
    op.create_index(op.f('ix_webhook_events_event_type'), 'webhook_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_webhook_events_status'), 'webhook_events', ['status'], unique=False)
    op.create_index(op.f('ix_webhook_events_greenhouse_application_id'), 'webhook_events', ['greenhouse_application_id'], unique=False)

    # Create email_logs table
    op.create_table('email_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('direction', postgresql.ENUM('outbound', 'inbound', name='emaildirection', create_type=False), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=True),
        sa.Column('candidate_id', sa.Integer(), nullable=True),
        sa.Column('message_id', sa.String(length=500), nullable=True),
        sa.Column('conversation_id', sa.String(length=500), nullable=True),
        sa.Column('thread_id', sa.String(length=500), nullable=True),
        sa.Column('from_address', sa.String(length=255), nullable=False),
        sa.Column('to_addresses', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('cc_addresses', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('bcc_addresses', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('reply_to', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=1000), nullable=False),
        sa.Column('body_preview', sa.Text(), nullable=True),
        sa.Column('body_html', sa.Text(), nullable=True),
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('template_name', sa.String(length=100), nullable=True),
        sa.Column('template_version', sa.String(length=50), nullable=True),
        sa.Column('template_variables', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', postgresql.ENUM('pending', 'sent', 'delivered', 'bounced', 'failed', name='emailstatus', create_type=False), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('bounced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('bounce_type', sa.String(length=50), nullable=True),
        sa.Column('intent_classified', sa.String(length=50), nullable=True),
        sa.Column('intent_confidence', sa.Float(), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('graph_message_id', sa.String(length=500), nullable=True),
        sa.Column('graph_change_key', sa.String(length=500), nullable=True),
        sa.Column('greenhouse_note_id', sa.BigInteger(), nullable=True),
        sa.Column('correlation_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_email_logs_application_id_applications')),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], name=op.f('fk_email_logs_candidate_id_candidates')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_email_logs'))
    )
    op.create_index(op.f('ix_email_logs_direction'), 'email_logs', ['direction'], unique=False)
    op.create_index(op.f('ix_email_logs_application_id'), 'email_logs', ['application_id'], unique=False)
    op.create_index(op.f('ix_email_logs_candidate_id'), 'email_logs', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_email_logs_message_id'), 'email_logs', ['message_id'], unique=True)
    op.create_index(op.f('ix_email_logs_conversation_id'), 'email_logs', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_email_logs_status'), 'email_logs', ['status'], unique=False)

    # Create email_templates table
    op.create_table('email_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.String(length=50), nullable=False, default='1.0'),
        sa.Column('subject_template', sa.String(length=1000), nullable=False),
        sa.Column('body_html_template', sa.Text(), nullable=False),
        sa.Column('body_text_template', sa.Text(), nullable=True),
        sa.Column('available_variables', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('required_variables', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('default_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('use_cases', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('last_modified_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_email_templates')),
        sa.UniqueConstraint('name', name=op.f('uq_email_templates_name')),
        sa.UniqueConstraint('slug', name=op.f('uq_email_templates_slug'))
    )
    op.create_index(op.f('ix_email_templates_name'), 'email_templates', ['name'], unique=False)

    # Create calendar_events table
    op.create_table('calendar_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('candidate_id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('event_type', postgresql.ENUM('phone_screen', 'video_interview', 'onsite_interview', 'technical_interview', 'panel_interview', 'hiring_manager_interview', 'final_round', 'other', name='calendareventtype', create_type=False), nullable=False),
        sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('scheduled_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('timezone', sa.String(length=50), nullable=False, default='UTC'),
        sa.Column('location', sa.String(length=500), nullable=True),
        sa.Column('meeting_url', sa.String(length=1000), nullable=True),
        sa.Column('meeting_id', sa.String(length=255), nullable=True),
        sa.Column('meeting_passcode', sa.String(length=100), nullable=True),
        sa.Column('organizer_email', sa.String(length=255), nullable=False),
        sa.Column('interviewer_emails', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('candidate_email', sa.String(length=255), nullable=False),
        sa.Column('optional_attendees', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('interview_instructions', sa.Text(), nullable=True),
        sa.Column('status', postgresql.ENUM('pending', 'confirmed', 'tentative', 'cancelled', 'completed', name='calendareventstatus', create_type=False), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('reminder_sent', sa.Boolean(), nullable=False, default=False),
        sa.Column('reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_rescheduled', sa.Boolean(), nullable=False, default=False),
        sa.Column('reschedule_count', sa.Integer(), nullable=False, default=0),
        sa.Column('original_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rescheduled_from_id', sa.Integer(), nullable=True),
        sa.Column('scorecards_expected', sa.Integer(), nullable=False, default=1),
        sa.Column('scorecards_submitted', sa.Integer(), nullable=False, default=0),
        sa.Column('scorecard_reminder_sent', sa.Boolean(), nullable=False, default=False),
        sa.Column('correlation_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_calendar_events_application_id_applications')),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], name=op.f('fk_calendar_events_candidate_id_candidates')),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_calendar_events_job_id_jobs')),
        sa.ForeignKeyConstraint(['rescheduled_from_id'], ['calendar_events.id'], name=op.f('fk_calendar_events_rescheduled_from_id_calendar_events')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_calendar_events'))
    )
    op.create_index(op.f('ix_calendar_events_application_id'), 'calendar_events', ['application_id'], unique=False)
    op.create_index(op.f('ix_calendar_events_candidate_id'), 'calendar_events', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_calendar_events_job_id'), 'calendar_events', ['job_id'], unique=False)
    op.create_index(op.f('ix_calendar_events_scheduled_start'), 'calendar_events', ['scheduled_start'], unique=False)
    op.create_index(op.f('ix_calendar_events_status'), 'calendar_events', ['status'], unique=False)

    # Create calendar_event_mappings table
    op.create_table('calendar_event_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('calendar_event_id', sa.Integer(), nullable=False),
        sa.Column('external_system', sa.String(length=50), nullable=False),
        sa.Column('external_event_id', sa.String(length=500), nullable=False),
        sa.Column('external_calendar_id', sa.String(length=500), nullable=True),
        sa.Column('external_change_key', sa.String(length=500), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sync_error', sa.Text(), nullable=True),
        sa.Column('needs_sync', sa.Boolean(), nullable=False, default=False),
        sa.Column('greenhouse_interview_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_scheduled_interview_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['calendar_event_id'], ['calendar_events.id'], name=op.f('fk_calendar_event_mappings_calendar_event_id_calendar_events')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_calendar_event_mappings'))
    )
    op.create_index(op.f('ix_calendar_event_mappings_calendar_event_id'), 'calendar_event_mappings', ['calendar_event_id'], unique=False)
    op.create_index(op.f('ix_calendar_event_mappings_external_event_id'), 'calendar_event_mappings', ['external_event_id'], unique=False)

    # Create exception_queue table
    op.create_table('exception_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=True),
        sa.Column('candidate_id', sa.Integer(), nullable=True),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('webhook_event_id', sa.Integer(), nullable=True),
        sa.Column('exception_type', postgresql.ENUM('parse_error', 'scoring_error', 'api_error', 'validation_error', 'low_confidence', 'borderline_score', 'missing_info', 'conflicting_data', 'email_bounce', 'no_reply', 'unclear_intent', 'scheduling_conflict', 'reschedule_request', 'no_show', 'protected_trait_mention', 'unusual_pattern', 'manual_review', 'hiring_manager_escalation', name='exceptiontype', create_type=False), nullable=False),
        sa.Column('priority', postgresql.ENUM('low', 'medium', 'high', 'urgent', name='exceptionpriority', create_type=False), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('stack_trace', sa.Text(), nullable=True),
        sa.Column('context_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('processing_stage', sa.String(length=100), nullable=True),
        sa.Column('worker_task_id', sa.String(length=255), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('max_retries', sa.Integer(), nullable=False, default=3),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('can_auto_retry', sa.Boolean(), nullable=False, default=False),
        sa.Column('resolved', sa.Boolean(), nullable=False, default=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.String(length=255), nullable=True),
        sa.Column('resolution_type', sa.String(length=50), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('assigned_to', sa.String(length=255), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('escalated', sa.Boolean(), nullable=False, default=False),
        sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('escalated_to', sa.String(length=255), nullable=True),
        sa.Column('greenhouse_application_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_candidate_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_job_id', sa.BigInteger(), nullable=True),
        sa.Column('correlation_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_exception_queue_application_id_applications')),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], name=op.f('fk_exception_queue_candidate_id_candidates')),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_exception_queue_job_id_jobs')),
        sa.ForeignKeyConstraint(['webhook_event_id'], ['webhook_events.id'], name=op.f('fk_exception_queue_webhook_event_id_webhook_events')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exception_queue'))
    )
    op.create_index(op.f('ix_exception_queue_application_id'), 'exception_queue', ['application_id'], unique=False)
    op.create_index(op.f('ix_exception_queue_candidate_id'), 'exception_queue', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_exception_queue_job_id'), 'exception_queue', ['job_id'], unique=False)
    op.create_index(op.f('ix_exception_queue_exception_type'), 'exception_queue', ['exception_type'], unique=False)
    op.create_index(op.f('ix_exception_queue_priority'), 'exception_queue', ['priority'], unique=False)
    op.create_index(op.f('ix_exception_queue_resolved'), 'exception_queue', ['resolved'], unique=False)
    op.create_index(op.f('ix_exception_queue_greenhouse_application_id'), 'exception_queue', ['greenhouse_application_id'], unique=False)

    # Create audit_logs table
    op.create_table('audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('actor_type', sa.String(length=50), nullable=False),
        sa.Column('actor_id', sa.String(length=255), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('action_category', sa.String(length=50), nullable=False),
        sa.Column('target_type', sa.String(length=50), nullable=True),
        sa.Column('target_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_application_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_candidate_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_job_id', sa.BigInteger(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('previous_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('new_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, default=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('external_api', sa.String(length=50), nullable=True),
        sa.Column('external_request_id', sa.String(length=255), nullable=True),
        sa.Column('external_response_code', sa.Integer(), nullable=True),
        sa.Column('correlation_id', sa.String(length=100), nullable=True),
        sa.Column('parent_audit_id', sa.BigInteger(), nullable=True),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_action_category'), 'audit_logs', ['action_category'], unique=False)
    op.create_index(op.f('ix_audit_logs_target_id'), 'audit_logs', ['target_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_greenhouse_application_id'), 'audit_logs', ['greenhouse_application_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_correlation_id'), 'audit_logs', ['correlation_id'], unique=False)

    # Create sla_configs table
    op.create_table('sla_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('sla_type', postgresql.ENUM('ingested_to_actioned', 'contacted_to_responded', 'scheduling_to_scheduled', 'scheduled_to_interviewed', 'interviewed_to_decision', 'scorecard_submission', 'custom', name='slatype', create_type=False), nullable=False),
        sa.Column('warning_threshold_hours', sa.Integer(), nullable=False),
        sa.Column('critical_threshold_hours', sa.Integer(), nullable=False),
        sa.Column('breach_threshold_hours', sa.Integer(), nullable=False),
        sa.Column('warning_actions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('critical_actions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('breach_actions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('warning_email_template', sa.String(length=100), nullable=True),
        sa.Column('critical_email_template', sa.String(length=100), nullable=True),
        sa.Column('breach_email_template', sa.String(length=100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_sla_configs_job_id_jobs')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sla_configs'))
    )
    op.create_index(op.f('ix_sla_configs_job_id'), 'sla_configs', ['job_id'], unique=False)

    # Create sla_violations table
    op.create_table('sla_violations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('sla_config_id', sa.Integer(), nullable=False),
        sa.Column('sla_type', postgresql.ENUM('ingested_to_actioned', 'contacted_to_responded', 'scheduling_to_scheduled', 'scheduled_to_interviewed', 'interviewed_to_decision', 'scorecard_submission', 'custom', name='slatype', create_type=False), nullable=False),
        sa.Column('sla_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('warning_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('critical_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('breached_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_level', sa.String(length=20), nullable=False, default='normal'),
        sa.Column('hours_elapsed', sa.Integer(), nullable=True),
        sa.Column('hours_over_sla', sa.Integer(), nullable=True),
        sa.Column('warning_notification_sent', sa.Boolean(), nullable=False, default=False),
        sa.Column('critical_notification_sent', sa.Boolean(), nullable=False, default=False),
        sa.Column('breach_notification_sent', sa.Boolean(), nullable=False, default=False),
        sa.Column('resolved', sa.Boolean(), nullable=False, default=False),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('greenhouse_application_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_job_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_sla_violations_application_id_applications')),
        sa.ForeignKeyConstraint(['sla_config_id'], ['sla_configs.id'], name=op.f('fk_sla_violations_sla_config_id_sla_configs')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sla_violations'))
    )
    op.create_index(op.f('ix_sla_violations_application_id'), 'sla_violations', ['application_id'], unique=False)
    op.create_index(op.f('ix_sla_violations_resolved'), 'sla_violations', ['resolved'], unique=False)
    op.create_index(op.f('ix_sla_violations_greenhouse_application_id'), 'sla_violations', ['greenhouse_application_id'], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('sla_violations')
    op.drop_table('sla_configs')
    op.drop_table('audit_logs')
    op.drop_table('exception_queue')
    op.drop_table('calendar_event_mappings')
    op.drop_table('calendar_events')
    op.drop_table('email_templates')
    op.drop_table('email_logs')
    op.drop_table('webhook_events')
    op.drop_table('scoring_results')
    op.drop_table('application_state_transitions')
    op.drop_table('applications')
    op.drop_table('kill_switches')
    op.drop_table('job_stage_configs')
    op.drop_table('jobs')
    op.drop_table('rubric_versions')
    op.drop_table('rubrics')
    op.drop_table('candidates')

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS slatype")
    op.execute("DROP TYPE IF EXISTS exceptionpriority")
    op.execute("DROP TYPE IF EXISTS exceptiontype")
    op.execute("DROP TYPE IF EXISTS calendareventtype")
    op.execute("DROP TYPE IF EXISTS calendareventstatus")
    op.execute("DROP TYPE IF EXISTS emaildirection")
    op.execute("DROP TYPE IF EXISTS emailstatus")
    op.execute("DROP TYPE IF EXISTS webhookstatus")
    op.execute("DROP TYPE IF EXISTS webhooksource")
    op.execute("DROP TYPE IF EXISTS applicationtier")
    op.execute("DROP TYPE IF EXISTS applicationstate")
