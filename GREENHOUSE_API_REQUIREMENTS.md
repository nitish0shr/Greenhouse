# Greenhouse API Requirements for 100% Functionality

## Current Implementation Status

### ✅ Implemented Endpoints

1. **GET /v1/candidates/{id}** - Get candidate details
2. **GET /v1/applications/{id}** - Get application details
3. **GET /v1/attachments/{id}/download** - Download attachments (via URL)
4. **POST /v1/candidates/{id}/activity_feed** - Add notes to candidates
5. **POST /v1/candidates/{id}/tags** - Add tags to candidates
6. **PUT /v1/applications/{id}/move** - Move application to new stage

### ⚠️ Missing for 100% Functionality

#### 1. Create Scheduled Interview (CRITICAL)
**Endpoint**: `POST /v1/scheduled_interviews`

**Why Needed**:
- Required for interview scheduling workflow
- Currently marked as TODO in `scheduler.py`
- Needed to create Greenhouse interview records linked to Outlook calendar events

**Request Body**:
```json
{
  "application_id": 12345,
  "interview": {
    "interviewer_ids": [67890, 67891],
    "start": "2026-01-20T14:00:00Z",
    "end": "2026-01-20T15:00:00Z",
    "location": "Conference Room A",
    "external_event_id": "outlook-event-id-123"
  }
}
```

**Implementation Location**: `app/services/greenhouse.py` - Add `create_scheduled_interview()` method

---

#### 2. Update Scheduled Interview (IMPORTANT)
**Endpoint**: `PATCH /v1/scheduled_interviews/{id}`

**Why Needed**:
- Required for interview rescheduling
- Currently marked as TODO in `scheduler.py`

**Request Body**:
```json
{
  "start": "2026-01-21T14:00:00Z",
  "end": "2026-01-21T15:00:00Z"
}
```

---

#### 3. Delete/Cancel Scheduled Interview (IMPORTANT)
**Endpoint**: `DELETE /v1/scheduled_interviews/{id}`

**Why Needed**:
- Required for interview cancellation
- Currently marked as TODO in `scheduler.py`

---

#### 4. Get Rejection Reasons (HELPFUL)
**Endpoint**: `GET /v1/rejection_reasons`

**Why Needed**:
- To get available rejection reasons for automated rejections
- Currently hardcoded rejection_reason_id in code

**Response**:
```json
{
  "rejection_reasons": [
    {"id": 12345, "name": "Insufficient Experience"},
    {"id": 12346, "name": "Missing Required Skills"}
  ]
}
```

---

#### 5. Get Job Stages (HELPFUL)
**Endpoint**: `GET /v1/jobs/{id}/stages`

**Why Needed**:
- To dynamically get stage IDs for job-specific automation
- Currently might be hardcoded or configured manually

**Response**:
```json
{
  "stages": [
    {"id": 1, "name": "Application Review"},
    {"id": 2, "name": "Phone Screen"},
    {"id": 3, "name": "Technical Interview"}
  ]
}
```

---

## Priority Order for Implementation

1. **HIGH PRIORITY** (Blocking full functionality):
   - Create Scheduled Interview
   - Update Scheduled Interview
   - Delete Scheduled Interview

2. **MEDIUM PRIORITY** (Improves automation):
   - Get Rejection Reasons
   - Get Job Stages

3. **LOW PRIORITY** (Nice to have):
   - Get Scorecards
   - Get Custom Fields
   - Other metadata endpoints

---

## Implementation Notes

### For Scheduled Interviews

The Greenhouse Harvest API documentation for scheduled interviews:
- Base URL: `https://harvest.greenhouse.io/v1/scheduled_interviews`
- Authentication: Basic Auth with API key
- Required fields: application_id, interviewer_ids, start, end
- Optional fields: location, external_event_id (for mapping to Outlook)

### Error Handling

All new endpoints should:
- Handle 404 (interview/application not found)
- Handle 422 (validation errors)
- Handle rate limiting (429)
- Return proper error messages

### Testing

Test with:
- Valid interview data
- Invalid application_id
- Invalid interviewer_ids
- Overlapping interviews
- Past dates (should be rejected)

---

## Current Workarounds

Until these endpoints are implemented:

1. **Scheduled Interviews**: 
   - Create Outlook event only
   - Store mapping in `calendar_mappings` table
   - Create exception for manual Greenhouse interview creation

2. **Rejection Reasons**:
   - Use hardcoded IDs from Greenhouse settings
   - Or fetch once and cache in JobConfig

3. **Job Stages**:
   - Configure stage IDs in JobConfig table
   - Or fetch once and cache

---

## Next Steps

1. Add `create_scheduled_interview()` to `GreenhouseClient`
2. Add `update_scheduled_interview()` to `GreenhouseClient`
3. Add `delete_scheduled_interview()` to `GreenhouseClient`
4. Update `Scheduler` service to use these methods
5. Test with real Greenhouse account
6. Update documentation
