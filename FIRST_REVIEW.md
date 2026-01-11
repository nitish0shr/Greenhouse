# First Review: Recruiting Autopilot System Design
**Version**: 1.0  
**Date**: 2026-01-10  
**Status**: Pre-Implementation Review Gate

---

## 1. Event Inventory + Lifecycle Matrix

### 1.1 Greenhouse Event Types (Consumed)

| Event Type | Trigger | Handler Action | Idempotency Key | Loop Prevention |
|------------|---------|----------------|-----------------|-----------------|
| `new_candidate_application` | Application created | Process applicant pipeline (download → parse → score → decide) | `greenhouse_event_id` | Check if application already processed; ignore if `autopilot_action_id` present in notes |
| `candidate_stage_change` | Manual or automated stage move | Update local shadow state; if Autopilot-initiated (via `autopilot_action_id`), ignore | `greenhouse_event_id` | Check marker in stage change metadata; if from Autopilot, reconcile only |
| `application_updated` | Application fields changed | Update local shadow; if Autopilot-initiated, ignore | `greenhouse_event_id` | Check if change has `autopilot_action_id` marker |
| `candidate_created` | New candidate record | Create local shadow record | `greenhouse_event_id` | N/A (read-only event) |
| `interview_created` | Interview scheduled | Update calendar mappings; if Autopilot-initiated, ignore | `greenhouse_event_id` | Check interview notes for `autopilot_action_id` |
| `interview_updated` | Interview rescheduled/cancelled | Update Outlook calendar event; if Autopilot-initiated, ignore | `greenhouse_event_id` | Check interview notes for marker |
| `rejection_created` | Application rejected | Update local state; if Autopilot-initiated, ignore | `greenhouse_event_id` | Check rejection reason/notes for marker |

**Loop Prevention Rules**:
- Every Autopilot writeback (note/tag/stage/interview/rejection) MUST include marker: `AUTOPILOT_ACTION_ID:<uuid>` in structured format
- Before processing any Greenhouse event, check if it references an existing `autopilot_action_id` in our actions table
- If yes: mark event as "reconciled" (status=reconciled), update local state only, DO NOT re-run automation
- If no: process normally

### 1.2 Microsoft Graph Notifications (Consumed)

| Resource Type | Notification Type | Trigger | Handler Action | Correlation Method |
|---------------|-------------------|---------|----------------|-------------------|
| `messages` | `created` | New email in mailbox | Parse reply; extract `conversationId`/`threadId`; lookup `message_mappings`; route to application | Primary: `conversationId` + candidate email<br>Fallback: `tracking_token [APP:application_id]` in subject/body |
| `messages` | `updated` | Email status changed (read/deleted) | Update audit log | Same as `created` |
| `events` | `created` | Calendar event created (external) | Not applicable (we create events, not receive) | N/A |
| `events` | `updated` | Calendar event rescheduled/cancelled | Update Greenhouse interview; if Autopilot-initiated, ignore | `external_event_id` from `calendar_mappings` |
| `events` | `deleted` | Calendar event cancelled | Cancel Greenhouse interview | `external_event_id` from `calendar_mappings` |

**Subscription Handshake**:
- GET/POST with `validationToken` query param → echo token exactly, return 200
- Store subscription metadata in `graph_subscriptions` table
- Renew subscriptions 24 hours before expiry (cron job)

**Reply Correlation Determinism**:
1. Extract `conversationId` from Graph message
2. Lookup `message_mappings` table: `conversationId` → `application_id`
3. If not found, extract `tracking_token` from subject/body (regex: `\[APP:(\d+)\]`)
4. Lookup by `tracking_token` → `application_id`
5. If still not found, use candidate email address + fuzzy match to recent applications
6. If multiple matches or none: create exception record for human review

---

## 2. API Contract Decisions

### 2.1 Greenhouse Harvest API (Write Operations)

**Base URL**: `https://harvest.greenhouse.io/v1`

**Authentication**: HTTP Basic Auth (API key as username, password empty)

**Operations**:

#### 2.1.1 Add Tags
```
POST /v1/candidates/{candidate_id}/tags
Body: { "tag_id": 12345 }
```
- Tag IDs: AI-A (12345), AI-Review (12346), AI-Reject (12347), Missing-Info (12348) [pre-configured in GH]
- Include `on_behalf_of` parameter for audit trail
- Loop prevention: N/A (tags don't have notes/body fields; rely on idempotency by tag_id + candidate_id)

#### 2.1.2 Create Note
```
POST /v1/candidates/{candidate_id}/activity_feed/notes
Body: {
  "user_id": <on_behalf_of>,
  "body": "AUTOPILOT_ACTION_ID:550e8400-e29b-41d4-a716-446655440000\n\n[Structured JSON content here]",
  "visibility": "private" | "public"
}
```
- Marker MUST be first line of body
- Structured content: rubric_version, decision, scores, evidence, gaps (JSON or YAML format)
- Store `autopilot_action_id` in actions table for loop prevention

#### 2.1.3 Update Stage
```
POST /v1/candidates/{candidate_id}/applications/{application_id}/move
Body: {
  "from_stage_id": 123,
  "to_stage_id": 456,
  "on_behalf_of": <user_id>
}
```
- Also create note with `AUTOPILOT_ACTION_ID` marker immediately after move
- Store mapping in actions table

#### 2.1.4 Reject Application
```
PUT /v1/applications/{application_id}/reject
Body: {
  "rejection_reason_id": 12345,
  "on_behalf_of": <user_id>
}
```
- Create note with marker immediately after rejection
- Store in actions table

#### 2.1.5 Create Scheduled Interview
```
POST /v1/applications/{application_id}/scheduled_interviews
Body: {
  "start": "2026-01-15T14:00:00Z",
  "end": "2026-01-15T15:00:00Z",
  "location": "Zoom: https://zoom.us/j/...",
  "interviewers": [{"user_id": 123}],
  "on_behalf_of": <user_id>
}
```
- Response includes `id` (greenhouse_interview_id)
- Store mapping: `external_event_id` ↔ `greenhouse_interview_id` ↔ `application_id`
- Create note with marker + structured content (title, start, end, timezone, location, attendees, external_event_id, greenhouse_interview_id)

#### 2.1.6 Update/Cancel Interview (if supported)
- Check Harvest API docs for update/delete endpoints
- If not supported: update Outlook only, create new GH note with cancellation/reschedule info, create exception for human reconciliation

### 2.2 Microsoft Graph API (Write Operations)

**Base URL**: `https://graph.microsoft.com/v1.0`

**Authentication**: Client credentials flow (app-only) via MSAL

**Operations**:

#### 2.2.1 Send Mail
```
POST /users/{mailbox}/sendMail
Body: {
  "message": {
    "subject": "Your Application - [APP:12345]",
    "body": {
      "contentType": "html",
      "content": "<html>...tracking token [APP:12345] embedded...</html>"
    },
    "toRecipients": [{"emailAddress": {"address": "candidate@example.com"}}],
    "internetMessageId": "<unique-id@domain>"
  }
}
```
- Store mapping: `application_id` ↔ `internetMessageId` ↔ `conversationId` (from response) in `message_mappings`
- Log to Greenhouse as note with marker
- Store in actions table

#### 2.2.2 Create Calendar Event
```
POST /users/{mailbox}/calendar/events
Body: {
  "subject": "Interview: {candidate_name} - {job_title}",
  "start": {"dateTime": "2026-01-15T14:00:00", "timeZone": "UTC"},
  "end": {"dateTime": "2026-01-15T15:00:00", "timeZone": "UTC"},
  "location": {"displayName": "Zoom: https://..."},
  "attendees": [{"emailAddress": {"address": "candidate@example.com"}, "type": "required"}],
  "body": {"contentType": "html", "content": "..."}
}
```
- Response includes `id` (external_event_id)
- Store in `calendar_mappings` table
- Create Greenhouse interview (see 2.1.5)
- Store mapping in actions table

#### 2.2.3 Update/Cancel Calendar Event
```
PATCH /users/{mailbox}/calendar/events/{event_id}
DELETE /users/{mailbox}/calendar/events/{event_id}
```
- Lookup `calendar_mappings` by `external_event_id`
- Update/cancel Greenhouse interview if possible (see 2.1.6)
- Store in actions table

#### 2.2.4 Get Free/Busy (for scheduling)
```
POST /users/{mailbox}/calendar/getFreeBusy
Body: {
  "schedules": ["interviewer@example.com"],
  "startTime": "2026-01-15T00:00:00Z",
  "endTime": "2026-01-20T00:00:00Z",
  "availabilityViewInterval": 60
}
```
- Use to propose 3 available slots
- Store proposed slots in actions table

#### 2.2.5 Subscription Management
```
POST /subscriptions
Body: {
  "changeType": "created,updated,deleted",
  "notificationUrl": "https://your-domain.com/webhooks/graph/notifications",
  "resource": "/users/{mailbox}/messages" | "/users/{mailbox}/calendar/events",
  "expirationDateTime": "2026-01-20T00:00:00Z",
  "clientState": "secret-state-token"
}
```
- Store in `graph_subscriptions` table
- Renew 24h before expiry
- Handle validation handshake (echo `validationToken`)

---

## 3. Idempotency & Ordering Model

### 3.1 Deduplication Keys

| Layer | Key | Storage | Constraint |
|-------|-----|---------|------------|
| Greenhouse events | `greenhouse_event_id` (header) | `events.greenhouse_event_id` | UNIQUE |
| Autopilot actions | `autopilot_action_id` (UUID) | `actions.autopilot_action_id` | UNIQUE |
| Message correlation | `conversation_id` + `candidate_email` | `message_mappings` | UNIQUE(conversation_id, candidate_email) |
| Calendar mapping | `external_event_id` | `calendar_mappings.external_event_id` | UNIQUE |

### 3.2 Out-of-Order Events & Retries

**Greenhouse Events**:
- Store all events in `events` table with `received_at` timestamp
- Process events in order of `received_at` (not Greenhouse timestamp)
- If duplicate `greenhouse_event_id` arrives: return 200 immediately, ignore (idempotency)
- Workers process events sequentially per `application_id` (distributed lock via Redis)

**Graph Notifications**:
- Graph notifications are not guaranteed ordered
- Use `conversationId` + `receivedDateTime` to dedupe
- Process notifications asynchronously; if duplicate, ignore (check `message_mappings`)

**Worker Tasks**:
- Celery tasks use `autopilot_action_id` as idempotency key
- If task with same `autopilot_action_id` already exists in Redis, skip (check before enqueue)
- Retries use exponential backoff (1s, 2s, 4s, 8s, 16s, 32s, 64s) with jitter
- Max retries: 7
- After max retries: move to DLQ (dead-letter queue table)

### 3.3 Distributed Locking

- Use Redis SETNX with TTL for per-`application_id` locks
- Lock key: `autopilot:lock:application:{application_id}`
- TTL: 300 seconds (5 minutes)
- If lock exists, retry enqueue after 10 seconds

---

## 4. Security/Threat Model

### 4.1 Signature Verification (Greenhouse Webhooks)

**Algorithm**: HMAC-SHA256

**Implementation**:
1. Read raw request body as bytes (DO NOT decode/decode JSON yet)
2. Extract `Signature` header: `sha256 <hex_digest>`
3. Compute `HMAC-SHA256(secret, raw_body_bytes)`
4. Compare computed digest with header digest using constant-time comparison (`secrets.compare_digest`)
5. If match: proceed; if not: return 401, log attempt

**Gotchas**:
- Unicode escaping: Greenhouse may send UTF-8 bytes; compute HMAC on exact bytes received
- Do NOT use `request.json()` before verification (it may modify body)
- Use FastAPI `Request.body()` to get raw bytes

**Secret Management**:
- Store `GREENHOUSE_WEBHOOK_SECRET` in environment variable
- In production: use secret manager (AWS Secrets Manager, Azure Key Vault, etc.)
- Never log secret or computed digest (log only "signature verified" / "signature invalid")

### 4.2 Attachment Handling

**Threats**:
- Malicious PDFs (embedded scripts, malware)
- Prompt injection in resume text (if passed to LLM)
- Oversized files (DoS)

**Controls**:
1. Download attachments to isolated temp directory (outside web root)
2. Validate file type (MIME type + extension): PDF, DOCX, TXT, RTF only
3. Size limit: 10 MB max
4. Compute SHA-256 checksum before storage
5. Extract text using libraries (pdfplumber, python-docx) that don't execute scripts
6. Store extracted text in DB; delete original file after 7 days (or immediately after extraction if not needed)
7. Resume text is NEVER passed directly to LLM prompts; only used for keyword matching / structured extraction with sanitization

**Storage**:
- Store attachments in `attachments` table with: `application_id`, `filename`, `content_type`, `size_bytes`, `checksum`, `storage_path`, `extracted_text`, `created_at`
- Storage path: `/var/storage/attachments/{application_id}/{checksum}/{filename}` (or S3 bucket in production)

### 4.3 Prompt Injection Defense

**Rule**: Resume content is untrusted input.

**Implementation**:
- Scoring engine uses keyword matching, regex, structured extraction (NLP libraries), NOT LLM prompts with resume content
- If LLM is used (future enhancement), sanitize input: strip special characters, limit length, use separate system/user prompts
- Store sanitized version separately from raw extracted text

### 4.4 Compliance (Protected Traits)

**Rule**: Never use race, religion, gender, age, disability, etc. for evaluation.

**Controls**:
1. Rubric validator checks for protected trait keywords in YAML config
2. Scoring engine ignores any fields that could indicate protected traits
3. Audit log records what data was used for scoring (evidence snippets only)
4. Admin UI shows compliance warnings if rubric contains protected terms

### 4.5 Secret Management (Local vs Prod)

**Local (Development)**:
- `.env` file (gitignored)
- `.env.example` with placeholders (no secrets)

**Production**:
- Environment variables injected at runtime (Docker/K8s secrets, CI/CD secrets)
- Or secret manager (AWS Secrets Manager, Azure Key Vault)
- Never commit secrets to git

---

## 5. Data Model Draft (Postgres)

### 5.1 Core Tables

```sql
-- Events (webhook ingress)
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    greenhouse_event_id VARCHAR(255) UNIQUE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    raw_body_json JSONB NOT NULL,
    signature_valid BOOLEAN NOT NULL,
    status VARCHAR(50) NOT NULL, -- 'pending', 'processed', 'failed', 'reconciled'
    received_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    INDEX idx_events_status (status),
    INDEX idx_events_received_at (received_at)
);

-- Candidates (local shadow)
CREATE TABLE candidates (
    id BIGSERIAL PRIMARY KEY,
    greenhouse_candidate_id BIGINT UNIQUE NOT NULL,
    email VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    INDEX idx_candidates_email (email)
);

-- Applications (local shadow)
CREATE TABLE applications (
    id BIGSERIAL PRIMARY KEY,
    greenhouse_application_id BIGINT UNIQUE NOT NULL,
    candidate_id BIGINT REFERENCES candidates(id),
    greenhouse_job_id BIGINT NOT NULL,
    current_stage_id BIGINT,
    status VARCHAR(50), -- 'active', 'rejected', 'hired'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    INDEX idx_applications_job_id (greenhouse_job_id),
    INDEX idx_applications_status (status)
);

-- Actions (audit log)
CREATE TABLE actions (
    id BIGSERIAL PRIMARY KEY,
    autopilot_action_id UUID UNIQUE NOT NULL,
    application_id BIGINT REFERENCES applications(id),
    action_type VARCHAR(100) NOT NULL, -- 'tag_added', 'note_created', 'stage_moved', 'rejected', 'email_sent', 'interview_created'
    request_payload JSONB,
    response_payload JSONB,
    status VARCHAR(50) NOT NULL, -- 'pending', 'completed', 'failed'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    INDEX idx_actions_application_id (application_id),
    INDEX idx_actions_status (status),
    INDEX idx_actions_autopilot_action_id (autopilot_action_id)
);

-- Job Configs (per-job automation settings)
CREATE TABLE job_configs (
    id BIGSERIAL PRIMARY KEY,
    greenhouse_job_id BIGINT UNIQUE NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    advance_threshold INTEGER DEFAULT 75,
    reject_threshold INTEGER DEFAULT 25,
    human_review_threshold INTEGER DEFAULT 50,
    scheduling_mode VARCHAR(50) DEFAULT 'propose_slots', -- 'send_link', 'propose_slots'
    email_templates JSONB, -- {rejection: "...", scheduling: "..."}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Rubric Versions
CREATE TABLE rubric_versions (
    id BIGSERIAL PRIMARY KEY,
    version VARCHAR(50) UNIQUE NOT NULL,
    rubric_yaml TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Exceptions (DLQ + error tracking)
CREATE TABLE exceptions (
    id BIGSERIAL PRIMARY KEY,
    application_id BIGINT REFERENCES applications(id),
    exception_type VARCHAR(100) NOT NULL, -- 'api_failure', 'missing_mapping', 'scheduling_mismatch', 'reply_correlation_failed'
    reason TEXT NOT NULL,
    status VARCHAR(50) NOT NULL, -- 'open', 'resolved', 'retrying'
    retry_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    payload_refs JSONB, -- {greenhouse_event_id: "...", autopilot_action_id: "..."}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE,
    INDEX idx_exceptions_status (status),
    INDEX idx_exceptions_next_retry_at (next_retry_at)
);

-- Graph Subscriptions
CREATE TABLE graph_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    resource VARCHAR(255) NOT NULL, -- "/users/{mailbox}/messages"
    subscription_id VARCHAR(255) UNIQUE NOT NULL,
    expiry TIMESTAMP WITH TIME ZONE NOT NULL,
    client_state VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    INDEX idx_graph_subscriptions_expiry (expiry)
);

-- Message Mappings (email correlation)
CREATE TABLE message_mappings (
    id BIGSERIAL PRIMARY KEY,
    application_id BIGINT REFERENCES applications(id),
    conversation_id VARCHAR(255),
    internet_message_id VARCHAR(255),
    tracking_token VARCHAR(255), -- "[APP:12345]"
    candidate_email VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(conversation_id, candidate_email),
    INDEX idx_message_mappings_conversation_id (conversation_id),
    INDEX idx_message_mappings_tracking_token (tracking_token),
    INDEX idx_message_mappings_candidate_email (candidate_email)
);

-- Calendar Mappings (interview sync)
CREATE TABLE calendar_mappings (
    id BIGSERIAL PRIMARY KEY,
    application_id BIGINT REFERENCES applications(id),
    external_event_id VARCHAR(255) UNIQUE NOT NULL,
    greenhouse_interview_id BIGINT,
    status VARCHAR(50) NOT NULL, -- 'scheduled', 'rescheduled', 'cancelled'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    INDEX idx_calendar_mappings_application_id (application_id)
);

-- Attachments
CREATE TABLE attachments (
    id BIGSERIAL PRIMARY KEY,
    application_id BIGINT REFERENCES applications(id),
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(100),
    size_bytes BIGINT,
    checksum VARCHAR(64), -- SHA-256 hex
    storage_path VARCHAR(500),
    extracted_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    INDEX idx_attachments_application_id (application_id)
);

-- Scoring Results (cache + audit)
CREATE TABLE scoring_results (
    id BIGSERIAL PRIMARY KEY,
    application_id BIGINT REFERENCES applications(id),
    rubric_version VARCHAR(50) NOT NULL,
    score_json JSONB NOT NULL, -- Strict schema from evaluator
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    INDEX idx_scoring_results_application_id (application_id)
);
```

### 5.2 Indexes Summary

- `events.greenhouse_event_id`: UNIQUE (idempotency)
- `actions.autopilot_action_id`: UNIQUE (idempotency)
- `message_mappings(conversation_id, candidate_email)`: UNIQUE (correlation)
- `calendar_mappings.external_event_id`: UNIQUE (mapping)
- Performance indexes on foreign keys and status fields (as shown above)

---

## 6. Rubric + Scoring Contract

### 6.1 Rubric YAML Schema

```yaml
version: "1.0.0"
dimensions:
  - name: "technical_skills"
    weight: 40
    scoring_method: "keyword_match"  # or "structured_extraction"
    criteria:
      - keywords: ["python", "django", "fastapi"]
        required: true
        evidence_required: true
      - keywords: ["postgresql", "sql"]
        required: false
        evidence_required: true
  - name: "experience_years"
    weight: 30
    scoring_method: "numeric_range"
    criteria:
      - field: "years_experience"
        minimum: 3
        ideal: 5
        evidence_required: true
  - name: "education"
    weight: 15
    scoring_method: "keyword_match"
    criteria:
      - keywords: ["bachelor", "master", "phd"]
        required: false
        evidence_required: false
  - name: "certifications"
    weight: 15
    scoring_method: "keyword_match"
    criteria:
      - keywords: ["aws", "gcp", "azure"]
        required: false
        evidence_required: true

hard_constraints:
  - type: "years_experience"
    minimum: 3
    reject_reason_id: 12345  # Greenhouse rejection reason ID
  - type: "keyword_required"
    keywords: ["python"]
    reject_reason_id: 12346

protected_traits_check: true  # Validator will reject if protected traits detected
```

### 6.2 Scoring Engine Output Schema (Strict JSON)

```json
{
  "hard_reject": false,
  "hard_reject_reasons": [],
  "dimension_scores": {
    "technical_skills": {
      "score": 85,
      "evidence": [
        {"snippet": "5 years of Python development using Django and FastAPI", "source": "resume"}
      ]
    },
    "experience_years": {
      "score": 90,
      "evidence": [
        {"snippet": "Senior Software Engineer (2020-2025)", "source": "resume"}
      ]
    },
    "education": {
      "score": 100,
      "evidence": [
        {"snippet": "BS in Computer Science, University of X (2015)", "source": "resume"}
      ]
    },
    "certifications": {
      "score": 70,
      "evidence": [
        {"snippet": "AWS Certified Solutions Architect (2023)", "source": "resume"}
      ]
    }
  },
  "weighted_score": 82,
  "tier": "A",
  "confidence": 0.85,
  "needs_human_review": false,
  "needs_human_review_reasons": [],
  "evidence_snippets": [
    {"snippet": "5 years of Python development using Django and FastAPI", "source": "resume"},
    {"snippet": "Senior Software Engineer (2020-2025)", "source": "resume"}
  ],
  "missing_info_questions": [],
  "rubric_version": "1.0.0"
}
```

### 6.3 Schema Validation

- Use Pydantic model for strict validation
- Reject any output that doesn't match exact schema (no extra keys, correct types)
- Store validated JSON in `scoring_results.score_json`
- If validation fails: create exception, move to human review

### 6.4 Versioning

- Store rubric YAML in `rubric_versions` table
- Reference `rubric_version` in scoring output
- Allow per-job rubric version selection (future enhancement)

---

## 7. Test Plan Mapping to Acceptance Tests

### 7.1 Unit Tests (pytest)

| Test | File | Assertions |
|------|------|------------|
| Signature verification (raw bytes) | `tests/unit/test_webhook_verification.py` | HMAC-SHA256 computed correctly; constant-time compare; rejects invalid signatures |
| Idempotency (duplicate events) | `tests/unit/test_webhook_idempotency.py` | Duplicate `greenhouse_event_id` returns 200; no duplicate processing |
| Loop prevention marker | `tests/unit/test_loop_prevention.py` | Events with `autopilot_action_id` marker are ignored/reconciled |
| Scoring schema validation | `tests/unit/test_scoring_schema.py` | Valid JSON passes; invalid JSON (extra keys, wrong types) fails |
| Decision thresholds | `tests/unit/test_decision_engine.py` | Hard reject triggers rejection; tier A + confidence → advance; needs_review → human review |

### 7.2 Integration Tests (Mock GH + Graph)

| Test | File | Mock Setup | Assertions |
|------|------|------------|------------|
| Rate limiting → retries | `tests/integration/test_rate_limiting.py` | Mock GH API to return 429; mock retry logic | Retries with exponential backoff; succeeds after retries |
| API failures → DLQ | `tests/integration/test_dlq.py` | Mock GH API to fail after max retries | Exception created; moved to DLQ; replay works |
| Graph subscription renewal | `tests/integration/test_graph_subscriptions.py` | Mock Graph API; simulate expiry | Renewal job runs; subscription renewed 24h before expiry |

### 7.3 End-to-End Tests (Mock Mode)

| Scenario | File | Setup | Assertions |
|----------|------|-------|------------|
| 10 applicants processed | `tests/e2e/test_pipeline.py` | Mock GH webhooks (10 events); mock Graph API | 3 A-tier + scheduled, 4 human review, 3 hard reject + email sent |
| Duplicate webhook delivery | `tests/e2e/test_idempotency.py` | Send same webhook twice | No double email; no double stage move; idempotency maintained |
| Reply "Tue 3pm works" → scheduled | `tests/e2e/test_scheduling.py` | Mock Graph notification (reply); mock free/busy | Outlook event created; GH interview created; mappings stored |
| Reply "need sponsorship" → exception | `tests/e2e/test_exceptions.py` | Mock Graph notification (reply with sponsorship request) | Exception created; moved to human review; email sent to recruiter |
| Graph subscription renewal | `tests/e2e/test_subscription_renewal.py` | Mock Graph API; simulate expiry | Renewal prevents outage; alerts on failure |

**Mock Mode Setup**:
- Use `responses` library or `httpx.AsyncClient` with mock transport
- Fixture-driven: `conftest.py` provides mock GH and Graph clients
- Run with `pytest tests/e2e/ --mock-mode` (env var: `MOCK_MODE=true`)

---

## 8. Definition of Done

### Milestone 1: Webhook Ingress ✅
- [ ] POST `/webhooks/greenhouse` verifies HMAC-SHA256 signature (raw bytes, constant-time)
- [ ] Idempotency: duplicate `greenhouse_event_id` returns 200 immediately
- [ ] Events stored in `events` table with status='pending'
- [ ] Fast response (< 100ms) after verify + store + enqueue
- [ ] Unit tests: signature verification, idempotency (100% coverage)

### Milestone 2: Database + Migrations ✅
- [ ] All tables created (events, candidates, applications, actions, job_configs, rubric_versions, exceptions, graph_subscriptions, message_mappings, calendar_mappings, attachments, scoring_results)
- [ ] Alembic migrations: initial schema + indexes
- [ ] Models (SQLAlchemy) with relationships
- [ ] `.env.example` with all required variables

### Milestone 3: Greenhouse Client + Writebacks ✅
- [ ] Harvest API client (read application/candidate/job)
- [ ] Write operations: tags, notes, stage moves, reject, interviews
- [ ] Loop prevention: all writebacks include `AUTOPILOT_ACTION_ID` marker
- [ ] Actions stored in `actions` table
- [ ] Integration tests: mock GH API, verify writebacks

### Milestone 4: Graph Subscriptions + Correlation ✅
- [ ] Subscription creation + renewal (cron job)
- [ ] Validation handshake (echo `validationToken`)
- [ ] Notification endpoint: `/webhooks/graph/notifications`
- [ ] Reply correlation: `conversationId` → `application_id` (deterministic)
- [ ] `message_mappings` table populated
- [ ] Integration tests: subscription lifecycle, reply correlation

### Milestone 5: Worker Pipeline (Attachments → Score → Decide) ✅
- [ ] Download attachments immediately (from GH URLs)
- [ ] Text extraction: PDF (pdfplumber), DOCX (python-docx)
- [ ] Scoring engine: rubric YAML → strict JSON schema (validated)
- [ ] Decision engine: thresholds → stage movement/emails/rejection
- [ ] Greenhouse writeback: tags, notes, stage moves
- [ ] End-to-end test: 10 applicants processed correctly

### Milestone 6: Scheduling (Outlook + GH) ✅
- [ ] Create Outlook event via Graph
- [ ] Create GH interview via Harvest
- [ ] Store mappings in `calendar_mappings`
- [ ] Reschedule/cancel logic (both systems)
- [ ] Structured notes with mappings
- [ ] End-to-end test: reply "Tue 3pm works" → scheduled

### Milestone 7: Exceptions + DLQ + Admin ✅
- [ ] Exception creation on failures
- [ ] Retry logic (exponential backoff, max 7 retries)
- [ ] DLQ table (`exceptions.status='retrying'` after max retries)
- [ ] Admin endpoints: kill switch, re-run scoring, replay DLQ, exception triage
- [ ] Integration tests: DLQ, replay

### Milestone 8: Mock Mode + Documentation ✅
- [ ] Mock GH and Graph clients (fixture-driven)
- [ ] All end-to-end tests runnable in mock mode (`docker compose up` + `pytest`)
- [ ] README: setup, config, architecture, mock mode instructions
- [ ] Runbooks: webhook failures, Graph renewal, DLQ replay, rotating secrets

### Final Acceptance Criteria ✅
- [ ] All 8 milestones complete
- [ ] All tests pass (unit, integration, e2e)
- [ ] Mock mode works end-to-end (10 applicants scenario)
- [ ] Documentation complete (README + runbooks)
- [ ] Docker Compose setup works (`docker compose up` starts all services)
- [ ] Code review: security, compliance, loop prevention verified

---

## 9. Open Questions / Decisions Needed

1. **Interview Update/Delete in Harvest API**: Confirm if endpoints exist; if not, fallback strategy (update Outlook only + GH note + exception) is defined.

2. **Scheduling Mode "Send Link"**: If using external scheduling tool (Calendly), how to integrate? (Assume: not in scope for v1; only "propose_slots" mode)

3. **LLM Usage**: Current design uses keyword matching only. If LLM is added later, ensure prompt injection defense (sanitization) is in place.

4. **Rubric Version per Job**: For v1, use global rubric version; per-job versioning is future enhancement.

5. **Free/Busy API**: Use `getFreeBusy` or `availabilityView`? (Assume: `getFreeBusy` for v1)

---

**REVIEW COMPLETE** ✅

Proceed to implementation after this review is approved.
