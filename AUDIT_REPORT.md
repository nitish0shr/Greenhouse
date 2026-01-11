# AUDIT REPORT: Recruiting Autopilot System

**Date**: 2026-01-11
**Auditor**: Claude Opus 4.5
**Repository**: `/Users/nitishshrivastava/Desktop/Greenhouse BOT`

---

## A) REPOSITORY INVENTORY

### Annotated Folder Tree

```
Greenhouse BOT/
├── app/                          # PRIMARY APPLICATION CODE
│   ├── __init__.py
│   ├── config.py                 # Settings via pydantic-settings
│   ├── database.py               # SQLAlchemy async/sync sessions
│   ├── main.py                   # FastAPI app, routers, health checks
│   │
│   ├── api/                      # HTTP ENDPOINTS
│   │   ├── webhooks.py           # POST /webhooks/greenhouse (CRITICAL)
│   │   ├── graph_webhooks.py     # POST /notifications (Graph)
│   │   ├── admin.py              # Admin UI (basic)
│   │   └── admin_endpoints.py    # Kill switches, DLQ replay, exceptions
│   │
│   ├── models/                   # SQLALCHEMY MODELS (12 tables)
│   │   ├── event.py              # events table (greenhouse_event_id UNIQUE)
│   │   ├── action.py             # actions table (autopilot_action_id UNIQUE)
│   │   ├── application.py        # applications table
│   │   ├── candidate.py          # candidates table
│   │   ├── job_config.py         # job_configs table
│   │   ├── rubric_version.py     # rubric_versions table (EXISTS)
│   │   ├── exception.py          # exceptions table (DLQ)
│   │   ├── graph_subscription.py # graph_subscriptions table
│   │   ├── message_mapping.py    # message_mappings table
│   │   ├── calendar_mapping.py   # calendar_mappings table
│   │   ├── attachment.py         # attachments table
│   │   ├── scoring_result.py     # scoring_results table
│   │   ├── human_review.py       # human_review queue
│   │   ├── audit_log.py          # audit_log table
│   │   └── webhook_event.py      # (legacy, use Event instead)
│   │
│   ├── services/                 # BUSINESS LOGIC
│   │   ├── greenhouse.py         # GreenhouseClient (Harvest API)
│   │   ├── greenhouse_writeback.py # GreenhouseWritebackClient (loop prevention)
│   │   ├── microsoft_graph.py    # GraphClient (sendMail, calendar, subscriptions)
│   │   ├── graph_subscription_manager.py # Subscription persistence/renewal
│   │   ├── scoring_engine.py     # ScoringEngine (rubric-based)
│   │   ├── decision_engine.py    # (EXISTS but empty)
│   │   ├── scheduler.py          # Interview scheduling (Outlook + GH)
│   │   ├── reply_correlator.py   # Email reply correlation
│   │   ├── resume_parser.py      # PDF/DOCX text extraction
│   │   ├── attachment_service.py # Attachment handling
│   │   ├── exception_service.py  # Exception/DLQ management
│   │   ├── scorer.py             # (legacy scorer, use ScoringEngine)
│   │   ├── mock_greenhouse.py    # Mock mode services
│   │   └── mock_graph.py         # Mock mode services
│   │
│   ├── workers/                  # CELERY BACKGROUND TASKS
│   │   ├── celery_app.py         # Celery config, beat schedule
│   │   ├── tasks.py              # process_greenhouse_event, process_new_application, etc.
│   │   └── renewal_tasks.py      # renew_graph_subscriptions
│   │
│   ├── schemas/                  # PYDANTIC MODELS
│   │   └── scoring.py            # ScoringOutput strict schema
│   │
│   └── utils/                    # UTILITIES
│       ├── security.py           # HMAC verification, sanitization, injection detection
│       └── compliance.py         # Rubric validation (protected traits)
│
├── config/
│   └── scoring_rubric.yaml       # Default scoring rubric
│
├── tests/                        # PYTEST TESTS
│   ├── conftest.py               # Fixtures
│   ├── test_webhooks.py          # Webhook tests (basic)
│   ├── test_scoring.py           # Scoring tests
│   ├── test_security.py          # Security tests
│   ├── test_webhook_verification.py
│   └── test_stage_transitions.py
│
├── alembic/                      # DATABASE MIGRATIONS
│   └── env.py                    # (needs versions/)
│
├── scripts/
│   └── init-db.sql               # Initial DB setup
│
├── docker-compose.yml            # Docker Compose (app, worker, beat, flower, postgres, redis)
├── Dockerfile                    # Application Dockerfile
├── requirements.txt              # Python dependencies
├── pyproject.toml                # Project metadata
├── README.md                     # Project README
├── RUNBOOKS.md                   # Operational runbooks (EXISTS)
└── [various status/progress .md files]
```

### Component Summary

| Component | Files | Status |
|-----------|-------|--------|
| Webhook Handlers | `webhooks.py`, `graph_webhooks.py` | PARTIAL |
| Greenhouse Client | `greenhouse.py`, `greenhouse_writeback.py` | DONE |
| Graph Client | `microsoft_graph.py` | DONE |
| Subscription Manager | `graph_subscription_manager.py` | DONE |
| Scoring Engine | `scoring_engine.py`, `scoring.py` | DONE |
| Decision Engine | `decision_engine.py` | MISSING (file exists, empty) |
| Reply Correlator | `reply_correlator.py` | PARTIAL |
| Scheduler | `scheduler.py` | PARTIAL |
| Workers | `tasks.py`, `renewal_tasks.py` | PARTIAL |
| Admin Endpoints | `admin_endpoints.py` | PARTIAL |
| Database Models | 12+ models | DONE |
| Tests | 5 test files | PARTIAL |
| Docker Compose | `docker-compose.yml` | DONE |
| Migrations | `alembic/` | MISSING (no versions/) |

---

## B) CRITICAL REQUIREMENTS VERIFICATION

### 1. GREENHOUSE WEBHOOK SIGNATURE VERIFICATION

**Status: DONE**

**File**: `app/utils/security.py:13-58`

```python
def verify_greenhouse_signature(payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
    # Parse signature format: "sha256 <hex_digest>" (space, not equals) per First Review
    # Handle both formats for compatibility: "sha256 <digest>" or "sha256=<digest>"
    if signature.startswith("sha256 "):
        provided_digest = signature[7:]
    elif signature.startswith("sha256="):
        provided_digest = signature[7:]
    ...
    # Use constant-time comparison
    return hmac.compare_digest(expected_digest, provided_digest)
```

**Verification**:
- Uses raw bytes ✓
- Parses `sha256 <hex>` format correctly ✓
- Uses constant-time comparison (`hmac.compare_digest`) ✓
- Handles both `sha256 ` and `sha256=` formats ✓

---

### 2. WEBHOOK IDEMPOTENCY (Greenhouse-Event-ID)

**Status: DONE**

**File**: `app/api/webhooks.py:87-102`

```python
# Check for duplicate event (idempotency)
existing = await session.execute(
    select(Event).where(Event.greenhouse_event_id == event_id)
)
if existing.scalar_one_or_none():
    logger.info(f"Ignoring duplicate webhook event (idempotent): {event_id}")
    return {"status": "duplicate", "event_id": event_id}
```

**Model**: `app/models/event.py:34-38`
```python
greenhouse_event_id: Mapped[str] = mapped_column(
    String(255),
    unique=True,  # UNIQUE constraint
    nullable=False,
    index=True,
)
```

**Verification**:
- Uses `Greenhouse-Event-ID` header ✓
- UNIQUE constraint in database ✓
- Returns 200 for duplicates (idempotent) ✓
- Stores event before processing ✓

---

### 3. FAST ACK + QUEUE HEAVY WORK

**Status: DONE**

**File**: `app/api/webhooks.py:125-142`

```python
# Enqueue to Celery worker (async, non-blocking)
try:
    process_greenhouse_event.delay(
        greenhouse_event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
except Exception as e:
    logger.error(f"Failed to enqueue event {event_id}: {e}", exc_info=True)
    # Don't fail the request - event is stored, can retry later

# Return 200 OK quickly
return {"status": "accepted", ...}
```

**Verification**:
- Verifies signature ✓
- Stores event in DB ✓
- Enqueues to Celery with `.delay()` ✓
- Returns 200 immediately ✓
- Handles queue failure gracefully ✓

---

### 4. LOOP PREVENTION (AUTOPILOT_ACTION_ID Markers)

**Status: DONE**

**File**: `app/services/greenhouse_writeback.py:86-104`

```python
def _format_note_with_marker(self, autopilot_action_id: uuid.UUID, note_body: str) -> str:
    marker = f"AUTOPILOT_ACTION_ID:{autopilot_action_id}"
    return f"{marker}\n\n{note_body}"  # Marker is FIRST LINE

async def add_note_to_candidate_with_action(...):
    autopilot_action_id = uuid.uuid4()
    formatted_note = self._format_note_with_marker(autopilot_action_id, note_body)
    # Creates Action record for audit
    action = self._create_action_record(...)
    # Calls parent API method
    note_data = await super().add_note_to_candidate(...)
```

**Verification**:
- Generates UUID for each action ✓
- Marker is first line of note body ✓
- Action record created with autopilot_action_id ✓
- Works for notes, tags, stage moves, rejections ✓

**PARTIAL GAP**: Inbound event filtering for autopilot actions not fully implemented in worker. The worker should check if the inbound event contains an `AUTOPILOT_ACTION_ID` marker and skip re-processing.

---

### 5. GRAPH VALIDATION TOKEN HANDSHAKE

**Status: DONE**

**File**: `app/api/graph_webhooks.py:22-42`

```python
@router.post("/notifications", status_code=status.HTTP_202_ACCEPTED)
async def graph_notifications(
    request: Request,
    validation_token: Optional[str] = Query(None, alias="validationToken"),
    ...
):
    # Handle subscription validation
    if validation_token:
        logger.info("Received Graph subscription validation request")
        return Response(
            content=validation_token,
            media_type="text/plain",
            status_code=status.HTTP_200_OK,
        )
```

**Verification**:
- Checks `validationToken` query param ✓
- Returns token as plain text ✓
- Returns 200 status ✓

---

### 6. GRAPH SUBSCRIPTION RENEWAL

**Status: DONE**

**Files**:
- `app/services/graph_subscription_manager.py` - Full implementation
- `app/workers/renewal_tasks.py` - Celery task
- `app/workers/celery_app.py:59-63` - Beat schedule

```python
# Beat schedule
"renew-graph-subscriptions": {
    "task": "app.workers.renewal_tasks.renew_graph_subscriptions",
    "schedule": 3600.0,  # Hourly
},
```

**Verification**:
- Subscriptions stored in `graph_subscriptions` table ✓
- Renewal 24h before expiry ✓
- Celery Beat schedules hourly check ✓
- Error handling and logging ✓

**PARTIAL GAP**: Alert/metrics for renewal failures not implemented. Should emit metrics or alerts when renewals fail.

---

### 7. REPLY CORRELATION

**Status: PARTIAL**

**File**: `app/services/reply_correlator.py`

**What's Done**:
- `MessageMapping` model with conversationId, internetMessageId, tracking_token ✓
- `create_mapping_from_sent_email()` - stores mapping when sending ✓
- `correlate_reply()` - correlates by conversationId + email, then tracking token ✓
- Tracking token pattern: `[APP:<application_id>]` ✓

**GAPS**:
1. **Not integrated into email sending flow**: `send_candidate_email` task in `tasks.py` doesn't call `create_mapping_from_sent_email()`
2. **Graph sendMail doesn't return conversationId**: Need to fetch the sent message after sending to get conversationId
3. **Exception creation for ambiguous correlation**: Not implemented
4. **Reply processing not implemented**: `handle_email_notification()` in `graph_webhooks.py` is a stub

---

### 8. SCHEDULING (Outlook + Greenhouse + Mappings)

**Status: PARTIAL**

**File**: `app/services/scheduler.py`

**What's Done**:
- `schedule_interview()` creates Outlook event ✓
- Creates Greenhouse scheduled interview ✓
- Stores `CalendarMapping` with external_event_id ↔ greenhouse_interview_id ✓
- Creates structured note with mappings ✓
- `reschedule_interview()` and `cancel_interview()` implemented ✓

**GAPS**:
1. **Not integrated into decision flow**: After scoring tier A, scheduling is not automatically triggered
2. **No free/busy lookup**: `propose_slots` mode needs Graph `getSchedule` API
3. **Interviewer ID lookup not implemented**: Comment says "TODO: Lookup interviewer IDs from emails"
4. **Interview type ID hardcoded**: Should come from JobConfig
5. **Exception creation on partial failure**: Should create exception if Outlook succeeds but GH fails

---

### 9. DECISION ENGINE

**Status: MISSING**

**File**: `app/services/decision_engine.py` exists but is empty or minimal.

**What's Needed**:
- Decision policy execution based on scoring output
- Tier-based routing (A → advance/schedule, B/C → human review, REJECT → reject)
- Per-job threshold configuration from `JobConfig`
- Integration with GreenhouseWritebackClient for writebacks
- Email sending based on decision

---

### 10. DLQ + REPLAY

**Status: PARTIAL**

**What's Done**:
- `Exception` model with status, retry_count, next_retry_at, payload_refs ✓
- Admin endpoints: `/admin/dlq/replay/{exception_id}`, `/admin/exceptions` ✓
- Celery retry with exponential backoff ✓

**GAPS**:
1. **Replay by greenhouse_event_id**: Endpoint exists but implementation is stub
2. **Replay by application_id**: Not implemented
3. **Replay by time window**: Not implemented
4. **Exception creation not wired**: Services don't create Exception records on failures
5. **CLI/script for replay**: Not provided

---

### 11. FEATURE FLAGS

**Status: PARTIAL**

**What's Done**:
- `JobConfig.enabled` - per-job kill switch ✓
- Admin endpoints for global/job kill switches ✓

**GAPS - Missing flags**:
- `ENABLE_AUTOPILOT_GLOBAL` (stored in config/DB?)
- `ENABLE_GH_WEBHOOKS`
- `ENABLE_HARVEST_WRITEBACK`
- `ENABLE_GRAPH_NOTIFICATIONS`
- `ENABLE_SCHEDULING`
- `ENABLE_STAGE_AUTOPILOT[job_id, stage_id]`
- `ENABLE_JOB_BOARD_API` (optional)
- `ENABLE_HRIS_EXPORT` (optional)
- `ENABLE_WORKDAY_LINK` (optional)

**File to modify**: `app/config.py` and `app/models/job_config.py`

---

### 12. SCORING ENGINE OUTPUT SCHEMA

**Status: DONE**

**File**: `app/schemas/scoring.py`

```python
class ScoringOutput(BaseModel):
    hard_reject: bool
    hard_reject_reasons: list[str]
    dimension_scores: dict[str, DimensionScore]
    weighted_score: int  # 0-100
    tier: Literal["A", "B", "C", "REJECT"]
    confidence: float  # 0.0-1.0
    needs_human_review: bool
    needs_human_review_reasons: list[str]
    evidence_snippets: list[EvidenceSnippet]
    missing_info_questions: list[str]
    rubric_version: str

    class Config:
        extra = "forbid"  # STRICT - no extra keys
```

**Verification**:
- All required fields present ✓
- Strict schema validation (extra="forbid") ✓
- Validated in `scoring_engine.py` ✓

---

### 13. MOCK MODE

**Status: PARTIAL**

**What's Done**:
- `settings.mock_mode` flag in config ✓
- `mock_greenhouse.py` and `mock_graph.py` exist ✓

**GAPS**:
1. **Mock services not integrated**: Clients don't switch to mock mode automatically
2. **No mock database seeding**: No fixtures for testing scenarios
3. **E2E test infrastructure**: Missing `tests/e2e/` directory
4. **Docker Compose mock mode**: No separate mock compose file

---

### 14. DATABASE MIGRATIONS

**Status: MISSING**

**File**: `alembic/env.py` exists but no `versions/` directory with migrations.

**What's Needed**:
- Initial migration with all 12+ tables
- Indexes as defined in models
- Run `alembic revision --autogenerate -m "initial"`

---

### 15. ATTACHMENT DOWNLOAD (Expiry Handling)

**Status: PARTIAL**

**File**: `app/services/greenhouse.py:262-290`

```python
async def download_attachment(self, url: str) -> bytes:
    """
    IMPORTANT: Attachment URLs expire! Download immediately when received.
    """
```

**What's Done**:
- Download method with timeout ✓
- Error handling ✓

**GAPS**:
1. **Not stored with checksum/metadata**: Should store in `attachments` table
2. **No immediate download on webhook**: Worker downloads later, URLs may expire
3. **No retry on 403/404**: Expired URLs should create exception

---

## C) OPERATIONAL FAILURE POINTS CHECK

| Check | Status | Risk if Unaddressed |
|-------|--------|---------------------|
| GH signature uses RAW body | ✓ DONE | Invalid signatures rejected |
| GH signature format `sha256 <hex>` | ✓ DONE | Webhook auth fails |
| Constant-time comparison | ✓ DONE | Timing attacks possible |
| Idempotency on greenhouse_event_id | ✓ DONE | Duplicate processing, double emails |
| ACK fast + queue heavy work | ✓ DONE | Greenhouse retries, webhook failures |
| Loop prevention markers written | ✓ DONE | Infinite automation loops |
| Loop prevention markers checked | PARTIAL | May re-process own updates |
| Graph validationToken handshake | ✓ DONE | Subscription creation fails |
| Graph subscription renewal | ✓ DONE | Notifications stop after 3 days |
| Subscription renewal monitoring | MISSING | Silent failures undetected |
| Reply correlation stored | PARTIAL | Cannot match replies to apps |
| Reply correlation used | MISSING | Lost candidate responses |
| Scheduling creates both systems | ✓ DONE | Half-synced interviews |
| Scheduling mappings stored | ✓ DONE | Cannot reschedule/cancel |
| Scheduling exceptions on partial | MISSING | Silent sync failures |
| DLQ + replay works | PARTIAL | Failed events lost |
| Mock mode runs E2E | MISSING | Cannot verify without credentials |

---

## D) DEFINITION OF DONE CHECKLIST

### Infrastructure (MUST HAVE)

- [ ] **Database migrations exist and run**: `alembic/versions/001_initial.py`
- [ ] **All 12 tables created with proper indexes**
- [ ] **Docker Compose runs locally**: `docker-compose up` works
- [ ] **Health checks pass**: `/health` and `/health/ready` functional
- [ ] **Celery worker starts**: No import errors
- [ ] **Celery Beat schedules run**: Subscription renewal executes

### Webhook Processing (MUST HAVE)

- [x] **Greenhouse signature verification**: Raw bytes, constant-time
- [x] **Greenhouse idempotency**: Unique constraint, duplicate handling
- [x] **Fast ACK + queue**: Returns 200, enqueues to Celery
- [x] **Graph validation handshake**: Returns validationToken
- [ ] **Loop prevention checking**: Worker ignores AUTOPILOT_ACTION_ID events

### Core Pipeline (MUST HAVE)

- [x] **Fetch application/candidate from Harvest**
- [ ] **Download attachments immediately** (currently deferred)
- [x] **Resume text extraction**: PDF/DOCX supported
- [x] **Scoring with strict schema**: Validated output
- [ ] **Decision engine**: Tier routing, writeback execution
- [ ] **Rejection email via Graph**: With tracking token
- [ ] **Stage advancement with note**: AUTOPILOT_ACTION_ID marker

### Scheduling (MUST HAVE)

- [x] **Create Outlook event via Graph**
- [x] **Create GH scheduled interview**
- [x] **Store CalendarMapping**
- [x] **Write structured GH note with mappings**
- [ ] **Reschedule/cancel updates both systems with exceptions**
- [ ] **Free/busy lookup for propose_slots mode**

### Reply Handling (MUST HAVE)

- [x] **MessageMapping model**
- [ ] **Create mapping on outbound email**
- [ ] **Correlate inbound replies**
- [ ] **Process reply content** (slot acceptance, questions)
- [ ] **Exception for ambiguous correlation**

### Admin & Operations (MUST HAVE)

- [x] **Kill switch endpoints**
- [ ] **Feature flags in config** (full set)
- [x] **Exception listing/resolution endpoints**
- [ ] **DLQ replay by event_id/app_id/time window**
- [ ] **Re-run scoring endpoint** (implemented but stub)
- [ ] **Resend email endpoint**

### Testing (MUST HAVE)

- [ ] **10 applicants scenario**: 3 advance, 4 review, 3 reject
- [ ] **Reply correlation test**
- [ ] **Duplicate webhook test**
- [ ] **Rate limiting recovery test**
- [ ] **Subscription renewal test**
- [ ] **Mock mode runs without credentials**

### Documentation (MUST HAVE)

- [ ] **Greenhouse Harvest API setup runbook**
- [ ] **Greenhouse webhooks setup runbook**
- [ ] **Microsoft Graph app setup runbook**
- [ ] **DLQ replay procedure**
- [ ] **Kill switch usage guide**
- [ ] **Architecture diagram**
- [ ] **Mock mode instructions**

---

## PRIORITIZED GAP LIST

### Priority 1: CRITICAL (Blocks Production)

| Gap | Files to Modify | Risk |
|-----|----------------|------|
| Database migrations missing | Create `alembic/versions/` | Tables don't exist |
| Loop prevention check in worker | `app/workers/tasks.py` | Infinite loops |
| Decision engine implementation | `app/services/decision_engine.py` | No automated decisions |
| Attachment immediate download | `app/workers/tasks.py` | Expired URLs |
| Feature flags complete set | `app/config.py`, `app/models/job_config.py` | No kill switches |

### Priority 2: HIGH (Core Functionality)

| Gap | Files to Modify | Risk |
|-----|----------------|------|
| Reply correlation integration | `app/workers/tasks.py`, `app/api/graph_webhooks.py` | Lost replies |
| Exception creation on failures | All services | Silent failures |
| DLQ replay implementation | `app/api/admin_endpoints.py`, new CLI | Cannot recover |
| Scheduling integration | `app/services/decision_engine.py` | Manual scheduling |
| E2E test scenarios | `tests/e2e/` | Unverified behavior |

### Priority 3: MEDIUM (Operational)

| Gap | Files to Modify | Risk |
|-----|----------------|------|
| Subscription renewal monitoring | `app/workers/renewal_tasks.py` | Undetected failures |
| Mock mode services | `app/services/mock_*.py` | Cannot test locally |
| Runbooks completion | `RUNBOOKS.md` | Ops confusion |
| Free/busy lookup | `app/services/scheduler.py` | Manual slot selection |

### Priority 4: LOW (Nice to Have)

| Gap | Files to Modify | Risk |
|-----|----------------|------|
| Metrics/observability | New files | Limited visibility |
| Admin UI enhancements | `app/api/admin.py` | CLI-only ops |
| Optional module flags | `app/config.py` | Feature creep |

---

## NEXT STEPS

1. **Create database migrations** - Generate Alembic migration for all models
2. **Implement loop prevention check** - Parse inbound notes for AUTOPILOT_ACTION_ID
3. **Complete decision engine** - Wire scoring → decision → writeback → email
4. **Fix attachment download** - Download in webhook handler, not worker
5. **Add feature flags** - Full set in config with defaults
6. **Integrate reply correlation** - Create mappings on send, process on receive
7. **Wire exception creation** - All services create Exception on failure
8. **Complete DLQ replay** - Full implementation with CLI
9. **Create E2E tests** - All 6 required scenarios
10. **Complete runbooks** - API setup, webhook config, troubleshooting

---

**END OF AUDIT REPORT**
