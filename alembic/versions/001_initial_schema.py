"""Initial schema with all models

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-01-11

Creates all tables for the Recruiting Autopilot system:
- events: Greenhouse webhook event tracking (idempotency)
- candidates: Candidate shadow data
- applications: Application state and scoring
- actions: Autopilot action audit log (loop prevention)
- job_configs: Per-job automation settings
- rubric_versions: Scoring rubric versioning
- exceptions: DLQ and error tracking
- graph_subscriptions: Microsoft Graph subscription tracking
- message_mappings: Email reply correlation
- calendar_mappings: Interview calendar sync
- attachments: Resume/file storage metadata
- audit_logs: General audit logging
- human_review_queue: Human review items
- scoring_results: Detailed scoring results
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # CANDIDATES TABLE
    # ==========================================================================
    op.create_table(
        'candidates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('greenhouse_candidate_id', sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column('first_name', sa.String(255), nullable=True),
        sa.Column('last_name', sa.String(255), nullable=True),
        sa.Column('email', sa.String(255), nullable=True, index=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('resume_text', sa.Text(), nullable=True),
        sa.Column('raw_data', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # ==========================================================================
    # APPLICATIONS TABLE
    # ==========================================================================
    op.create_table(
        'applications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('greenhouse_application_id', sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('candidates.id'), nullable=False, index=True),
        sa.Column('greenhouse_candidate_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('greenhouse_job_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('current_stage_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('status', sa.String(50), nullable=True, index=True),
        sa.Column('source', sa.String(255), nullable=True),
        sa.Column('processing_status', sa.String(50), nullable=False, server_default='pending', index=True),
        sa.Column('score', sa.Float(), nullable=True, index=True),
        sa.Column('score_breakdown', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('auto_decision', sa.String(50), nullable=True),
        sa.Column('hard_reject_reasons', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('rejection_reason_id', sa.BigInteger(), nullable=True),
        sa.Column('resume_url', sa.Text(), nullable=True),
        sa.Column('resume_downloaded', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('resume_download_error', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('raw_data', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('greenhouse_applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_applications_job_status', 'applications', ['greenhouse_job_id', 'status'])

    # ==========================================================================
    # EVENTS TABLE (Webhook idempotency)
    # ==========================================================================
    op.create_table(
        'events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('greenhouse_event_id', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('raw_body_json', postgresql.JSONB(), nullable=False),
        sa.Column('signature_valid', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending', index=True),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
    )
    op.create_index('ix_events_status_received_at', 'events', ['status', 'received_at'])

    # ==========================================================================
    # ACTIONS TABLE (Audit log with autopilot_action_id for loop prevention)
    # ==========================================================================
    op.create_table(
        'actions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('autopilot_action_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True, index=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id'), nullable=True, index=True),
        sa.Column('action_type', sa.String(100), nullable=False),
        sa.Column('request_payload', postgresql.JSONB(), nullable=True),
        sa.Column('response_payload', postgresql.JSONB(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending', index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
    )
    op.create_index('ix_actions_application_status', 'actions', ['application_id', 'status'])

    # ==========================================================================
    # JOB_CONFIGS TABLE
    # ==========================================================================
    op.create_table(
        'job_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('greenhouse_job_id', sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('advance_threshold', sa.Integer(), nullable=False, server_default='75'),
        sa.Column('reject_threshold', sa.Integer(), nullable=False, server_default='25'),
        sa.Column('human_review_threshold', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('scheduling_mode', sa.String(50), nullable=False, server_default="'propose_slots'"),
        sa.Column('email_templates', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('enabled_stages', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('feature_flags', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # ==========================================================================
    # RUBRIC_VERSIONS TABLE
    # ==========================================================================
    op.create_table(
        'rubric_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('version', sa.String(50), nullable=False, unique=True, index=True),
        sa.Column('job_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('rubric_yaml', sa.Text(), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=True),
    )

    # ==========================================================================
    # EXCEPTIONS TABLE (DLQ)
    # ==========================================================================
    op.create_table(
        'exceptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id'), nullable=True, index=True),
        sa.Column('exception_type', sa.String(100), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='open', index=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('payload_refs', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.String(255), nullable=True),
    )
    op.create_index('ix_exceptions_status_next_retry', 'exceptions', ['status', 'next_retry_at'])

    # ==========================================================================
    # GRAPH_SUBSCRIPTIONS TABLE
    # ==========================================================================
    op.create_table(
        'graph_subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('resource', sa.String(255), nullable=False),
        sa.Column('subscription_id', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('expiry', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('client_state', sa.String(255), nullable=True),
        sa.Column('notification_url', sa.String(500), nullable=True),
        sa.Column('change_types', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('last_renewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('renewal_failures', sa.Integer(), nullable=False, server_default='0'),
    )

    # ==========================================================================
    # MESSAGE_MAPPINGS TABLE (Reply correlation)
    # ==========================================================================
    op.create_table(
        'message_mappings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id'), nullable=False, index=True),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('candidates.id'), nullable=True, index=True),
        sa.Column('conversation_id', sa.String(255), nullable=True, index=True),
        sa.Column('internet_message_id', sa.String(500), nullable=True, index=True),
        sa.Column('tracking_token', sa.String(255), nullable=True, index=True),
        sa.Column('candidate_email', sa.String(255), nullable=False, index=True),
        sa.Column('subject', sa.String(500), nullable=True),
        sa.Column('direction', sa.String(20), nullable=False, server_default="'outbound'"),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        'uq_message_mappings_conversation_email',
        'message_mappings',
        ['conversation_id', 'candidate_email']
    )

    # ==========================================================================
    # CALENDAR_MAPPINGS TABLE (Interview sync)
    # ==========================================================================
    op.create_table(
        'calendar_mappings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id'), nullable=False, index=True),
        sa.Column('external_event_id', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('greenhouse_interview_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('status', sa.String(50), nullable=False, server_default="'scheduled'"),
        sa.Column('interview_type', sa.String(100), nullable=True),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('location', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # ==========================================================================
    # ATTACHMENTS TABLE
    # ==========================================================================
    op.create_table(
        'attachments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id'), nullable=True, index=True),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('candidates.id'), nullable=True, index=True),
        sa.Column('greenhouse_attachment_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(100), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('checksum_sha256', sa.String(64), nullable=True),
        sa.Column('storage_path', sa.String(500), nullable=True),
        sa.Column('storage_type', sa.String(50), nullable=False, server_default="'local'"),
        sa.Column('original_url', sa.Text(), nullable=True),
        sa.Column('download_status', sa.String(50), nullable=False, server_default="'pending'"),
        sa.Column('download_error', sa.Text(), nullable=True),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('downloaded_at', sa.DateTime(timezone=True), nullable=True),
    )

    # ==========================================================================
    # AUDIT_LOGS TABLE
    # ==========================================================================
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('action_type', sa.String(100), nullable=False, index=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column('greenhouse_application_id', sa.BigInteger(), nullable=True),
        sa.Column('greenhouse_candidate_id', sa.BigInteger(), nullable=True),
        sa.Column('triggered_by', sa.String(100), nullable=False, server_default="'system'"),
        sa.Column('status', sa.String(50), nullable=False, server_default="'success'"),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )

    # ==========================================================================
    # HUMAN_REVIEW_QUEUE TABLE
    # ==========================================================================
    op.create_table(
        'human_review_queue',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id'), nullable=False, index=True),
        sa.Column('greenhouse_application_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('greenhouse_candidate_id', sa.BigInteger(), nullable=False),
        sa.Column('job_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('job_name', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default="'pending'", index=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('review_reasons', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('auto_score', sa.Float(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('suggested_action', sa.String(50), nullable=True),
        sa.Column('reviewer_id', sa.String(255), nullable=True),
        sa.Column('reviewer_decision', sa.String(50), nullable=True),
        sa.Column('reviewer_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_human_review_queue_status_priority', 'human_review_queue', ['status', 'priority'])

    # ==========================================================================
    # SCORING_RESULTS TABLE
    # ==========================================================================
    op.create_table(
        'scoring_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id'), nullable=False, index=True),
        sa.Column('rubric_version', sa.String(50), nullable=False),
        sa.Column('hard_reject', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('hard_reject_reasons', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('dimension_scores', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('weighted_score', sa.Integer(), nullable=False),
        sa.Column('tier', sa.String(10), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('needs_human_review', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('needs_human_review_reasons', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('evidence_snippets', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('missing_info_questions', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('raw_output', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ==========================================================================
    # FEATURE_FLAGS TABLE (Global feature flags)
    # ==========================================================================
    op.create_table(
        'feature_flags',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scope', sa.String(50), nullable=False, server_default="'global'"),
        sa.Column('scope_id', sa.BigInteger(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_feature_flags_scope', 'feature_flags', ['scope', 'scope_id'])

    # ==========================================================================
    # Insert default feature flags
    # ==========================================================================
    op.execute("""
        INSERT INTO feature_flags (id, name, enabled, description, scope) VALUES
        (gen_random_uuid(), 'ENABLE_AUTOPILOT_GLOBAL', true, 'Global autopilot kill switch', 'global'),
        (gen_random_uuid(), 'ENABLE_GH_WEBHOOKS', true, 'Process Greenhouse webhooks', 'global'),
        (gen_random_uuid(), 'ENABLE_HARVEST_WRITEBACK', true, 'Write back to Greenhouse Harvest API', 'global'),
        (gen_random_uuid(), 'ENABLE_GRAPH_NOTIFICATIONS', true, 'Process Microsoft Graph notifications', 'global'),
        (gen_random_uuid(), 'ENABLE_SCHEDULING', true, 'Enable interview scheduling', 'global'),
        (gen_random_uuid(), 'ENABLE_JOB_BOARD_API', false, 'Enable Job Board API (optional)', 'global'),
        (gen_random_uuid(), 'ENABLE_HRIS_EXPORT', false, 'Enable HRIS export (optional)', 'global'),
        (gen_random_uuid(), 'ENABLE_WORKDAY_LINK', false, 'Enable Workday integration (optional)', 'global')
    """)


def downgrade() -> None:
    op.drop_table('feature_flags')
    op.drop_table('scoring_results')
    op.drop_table('human_review_queue')
    op.drop_table('audit_logs')
    op.drop_table('attachments')
    op.drop_table('calendar_mappings')
    op.drop_table('message_mappings')
    op.drop_table('graph_subscriptions')
    op.drop_table('exceptions')
    op.drop_table('rubric_versions')
    op.drop_table('job_configs')
    op.drop_table('actions')
    op.drop_table('events')
    op.drop_table('applications')
    op.drop_table('candidates')
