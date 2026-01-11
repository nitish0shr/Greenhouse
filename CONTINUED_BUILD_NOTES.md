# Continued Build Notes

## Current Status

I've been working on integrating the new Event model and creating the process_greenhouse_event task. The system has:

1. ✅ All database models created (Event, Action, etc.)
2. ✅ Webhook handler updated to use Event model
3. 🚧 Celery tasks being updated (process_greenhouse_event added, but tasks.py still has WebhookEvent references)
4. ⏳ Greenhouse client needs loop prevention markers added to writeback operations

## Next Critical Steps

### 1. Complete Celery Tasks Update
The tasks.py file still references WebhookEvent in several places. Need to:
- Update all references to use Event model with greenhouse_event_id
- Or maintain backward compatibility with both models

### 2. Add Loop Prevention to Greenhouse Client
Per First Review, all writeback operations must include AUTOPILOT_ACTION_ID markers:
- `add_note_to_candidate()` - Add marker as first line: "AUTOPILOT_ACTION_ID:<uuid>"
- `add_tag()` - Store action_id in actions table (tags don't have body fields)
- `move_stage()` - Create note with marker immediately after move
- `reject_application()` - Create note with marker immediately after rejection

### 3. Create Action Records
All writeback operations must create Action records with autopilot_action_id for loop prevention.

### 4. Continue with Other Components
- Graph client and subscriptions
- Worker pipeline (attachments → scoring → decisions)
- Scheduling logic
- Admin endpoints
- Testing infrastructure

## Decision Needed

The existing tasks.py uses WebhookEvent model. Options:
1. Update all references to use Event model (breaking change for existing code)
2. Keep both models and migrate gradually
3. Create wrapper/adapter to support both

Given the First Review requirements, option 1 is preferred but requires updating all task code.
