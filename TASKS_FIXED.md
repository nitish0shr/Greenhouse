# Tasks.py Fixes Applied

## Fixed Issues

1. ✅ Updated `process_new_application` and `process_stage_change` to use `greenhouse_event_id` parameter instead of `webhook_event_id`
2. ✅ Changed all `WebhookEvent` references to `Event` model
3. ✅ Updated Event status updates to use `greenhouse_event_id` instead of UUID
4. ✅ Fixed `Candidate.greenhouse_id` → `Candidate.greenhouse_candidate_id`
5. ✅ Fixed `Application.greenhouse_id` → `Application.greenhouse_application_id`
6. ✅ Fixed `Application.job_id` → `Application.greenhouse_job_id`
7. ✅ Fixed HumanReviewQueue job_id reference to use `application.greenhouse_job_id`

## Remaining Field Name Issues

The Application model per First Review schema only has:
- `greenhouse_job_id` (no `job_name` field)

However, HumanReviewQueue model still has:
- `job_id` 
- `job_name`

For HumanReviewQueue creation, we get `job_name` from `job_data` that was fetched earlier in the process.

## Status

All Event model references have been fixed. The tasks now use the new Event model with `greenhouse_event_id` for idempotency tracking.
