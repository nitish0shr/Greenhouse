# Loop Prevention Implementation

## ✅ Created: GreenhouseWritebackClient

A new client class `GreenhouseWritebackClient` extends `GreenhouseClient` with loop prevention markers and Action record creation per First Review requirements.

## Features Implemented

### 1. AUTOPILOT_ACTION_ID Markers
- All notes include marker as first line: `AUTOPILOT_ACTION_ID:<uuid>`
- Marker format matches First Review specification exactly
- Helper method `_format_note_with_marker()` ensures consistent formatting

### 2. Action Record Creation
- Every writeback creates an Action record in the database
- Stores request/response payloads for audit trail
- Tracks status (pending → completed/failed)
- Links to application_id for correlation

### 3. Writeback Methods with Actions

#### `add_note_to_candidate_with_action()`
- Adds note with AUTOPILOT_ACTION_ID marker
- Creates Action record with type "note_created"
- Returns (note_data, autopilot_action_id)

#### `add_tag_with_action()`
- Adds tag to candidate
- Creates Action record with type "tag_added"
- Note: Tags don't have body fields, so markers are in Action records only
- Returns (tag_data, autopilot_action_id)

#### `move_stage_with_action()`
- Moves application to new stage
- Creates Action record with type "stage_moved"
- Returns (stage_data, autopilot_action_id)
- Note: Caller should create note separately if needed (requires candidate_id)

#### `reject_application_with_action()`
- Rejects application
- Creates Action record with type "rejected"
- Attempts to create note with marker (requires candidate_id from response)
- Returns (rejection_data, autopilot_action_id)

## Usage

```python
from app.services.greenhouse_writeback import GreenhouseWritebackClient
from app.database import SyncSessionLocal

session = SyncSessionLocal()
client = GreenhouseWritebackClient(db_session=session)

# Add note with marker and action record
note_data, action_id = await client.add_note_to_candidate_with_action(
    candidate_id=12345,
    note_body="Scoring results: Score 85, Tier A",
    application_id=application_uuid,
    visibility="public",
)

# Add tag with action record
tag_data, action_id = await client.add_tag_with_action(
    candidate_id=12345,
    tag="AI-A",
    application_id=application_uuid,
)

# Move stage with action record
stage_data, action_id = await client.move_stage_with_action(
    application_id=67890,
    to_stage_id=456,
    from_stage_id=123,
    application_uuid=application_uuid,
)

# Reject with action record
rejection_data, action_id = await client.reject_application_with_action(
    application_id=67890,
    rejection_reason_id=789,
    application_uuid=application_uuid,
    notes="Low score: 20/100",
)
```

## Loop Prevention Mechanism

1. **Writeback**: Client creates Action record with autopilot_action_id
2. **Marker**: Note includes AUTOPILOT_ACTION_ID marker in body
3. **Webhook**: Greenhouse sends webhook event for the change
4. **Check**: Event handler checks if autopilot_action_id exists in actions table
5. **Skip**: If found, mark event as "reconciled" and skip processing

## Next Steps

1. **Update tasks.py** to use GreenhouseWritebackClient instead of GreenhouseClient
2. **Implement loop prevention checks** in process_greenhouse_event task
3. **Add candidate_id fetching** for move_stage and reject operations that need notes
4. **Test** writeback operations with Action record creation
5. **Integrate** with existing worker pipeline

## Files Created

- `app/services/greenhouse_writeback.py` - GreenhouseWritebackClient class

## Integration Points

- Workers should use GreenhouseWritebackClient for all writeback operations
- Action records enable loop prevention and audit trail
- Markers in notes enable event reconciliation
