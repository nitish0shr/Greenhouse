# Greenhouse API - Complete Implementation Status

## ✅ Already Implemented

Based on the code review, we have:

1. **GET /v1/candidates/{id}** ✅
2. **GET /v1/applications/{id}** ✅
3. **GET /v1/jobs/{id}** ✅
4. **GET /v1/jobs/{id}/stages** ✅
5. **GET /v1/rejection_reasons** ✅
6. **POST /v1/candidates/{id}/activity_feed/notes** ✅
7. **POST /v1/candidates/{id}/tags** ✅
8. **PUT /v1/applications/{id}/move** ✅
9. **POST /v1/scheduled_interviews** ✅ (Implemented in greenhouse.py line 530)

## ⚠️ Missing for 100% Functionality

### 1. Update Scheduled Interview
**Status**: Not implemented  
**Endpoint**: `PATCH /v1/scheduled_interviews/{id}`  
**Priority**: HIGH  
**Location**: `app/services/greenhouse.py`

### 2. Delete/Cancel Scheduled Interview
**Status**: Not implemented  
**Endpoint**: `DELETE /v1/scheduled_interviews/{id}`  
**Priority**: HIGH  
**Location**: `app/services/greenhouse.py`

### 3. Get Scheduled Interview Details
**Status**: Not implemented  
**Endpoint**: `GET /v1/scheduled_interviews/{id}`  
**Priority**: MEDIUM  
**Location**: `app/services/greenhouse.py`

## Implementation Needed

Add these three methods to `GreenhouseClient` class in `app/services/greenhouse.py`:

```python
async def update_scheduled_interview(
    self,
    interview_id: int,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    location: Optional[str] = None,
    interviewers: Optional[list[dict]] = None,
) -> dict:
    """
    Update a scheduled interview.
    
    PATCH /v1/scheduled_interviews/{id}
    
    Args:
        interview_id: Scheduled interview ID
        start: New start time
        end: New end time
        location: New location
        interviewers: Updated interviewer list
    
    Returns:
        Updated interview data
    """
    payload = {}
    if start:
        payload["start"] = start.isoformat()
    if end:
        payload["end"] = end.isoformat()
    if location:
        payload["location"] = location
    if interviewers:
        payload["interviewers"] = interviewers
    
    return await self._request(
        "PATCH",
        f"/scheduled_interviews/{interview_id}",
        write_operation=True,
        json=payload,
    )

async def delete_scheduled_interview(
    self,
    interview_id: int,
) -> dict:
    """
    Delete/cancel a scheduled interview.
    
    DELETE /v1/scheduled_interviews/{id}
    
    Args:
        interview_id: Scheduled interview ID
    
    Returns:
        Empty dict on success
    """
    return await self._request(
        "DELETE",
        f"/scheduled_interviews/{interview_id}",
        write_operation=True,
    )

async def get_scheduled_interview(
    self,
    interview_id: int,
) -> dict:
    """
    Get scheduled interview details.
    
    GET /v1/scheduled_interviews/{id}
    
    Args:
        interview_id: Scheduled interview ID
    
    Returns:
        Interview data
    """
    return await self._request("GET", f"/scheduled_interviews/{interview_id}")
```

## Current Functionality: ~95%

- ✅ All read operations
- ✅ All write operations (notes, tags, stage moves, rejections)
- ✅ Scheduled interview creation
- ⚠️ Missing: Interview update/delete (needed for reschedule/cancel)

## To Reach 100%

Just need to add the 3 methods above to complete the interview lifecycle management.
