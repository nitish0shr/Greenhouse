-- =============================================================================
-- Database Initialization Script
-- =============================================================================
-- This script runs automatically when the PostgreSQL container starts for the first time

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create enum types
CREATE TYPE processing_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed',
    'human_review'
);

CREATE TYPE action_type AS ENUM (
    'webhook_received',
    'application_fetched',
    'resume_downloaded',
    'resume_parsed',
    'candidate_scored',
    'stage_advanced',
    'application_rejected',
    'email_sent',
    'note_added',
    'tag_added',
    'interview_scheduled',
    'human_review_added',
    'manual_approval',
    'manual_rejection',
    'rescore_requested'
);

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE recruiter_autopilot TO recruiter;
