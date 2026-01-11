# Operational Runbooks - Recruiting Autopilot

Comprehensive operational procedures for the Recruiting Autopilot system.

---

## Table of Contents

1. [Greenhouse Harvest API Setup](#1-greenhouse-harvest-api-setup)
2. [Greenhouse Webhooks Setup](#2-greenhouse-webhooks-setup)
3. [Microsoft Graph App Setup](#3-microsoft-graph-app-setup)
4. [DLQ Replay Procedure](#4-dlq-replay-procedure)
5. [Kill Switch Usage](#5-kill-switch-usage)
6. [Deployment](#6-deployment)
7. [Monitoring & Alerts](#7-monitoring--alerts)
8. [Troubleshooting Guide](#8-troubleshooting-guide)
9. [Maintenance Procedures](#9-maintenance-procedures)

---

## 1. Greenhouse Harvest API Setup

### 1.1 Create API Credential

1. Log into Greenhouse as an admin
2. Navigate to **Configure → Dev Center → API Credential Management**
3. Click **Create New API Key**
4. Configure:
   - **Type**: Harvest
   - **Description**: "Recruiter Autopilot"
   - **Partner**: None (internal tool)

### 1.2 Required Permissions Matrix

Grant these permissions to the API key:

| Permission | Access Level | Purpose |
|------------|--------------|---------|
| Applications | Read/Write | Fetch and update applications |
| Candidates | Read/Write | Access candidate data, add tags/notes |
| Jobs | Read | Get job configuration |
| Scheduled Interviews | Read/Write | Create/update interviews |
| Users | Read | Lookup interviewer IDs |
| Rejection Reasons | Read | Get valid rejection reason IDs |
| Stages | Read | Get pipeline stages |
| Custom Fields | Read/Write | Update scoring metadata |
| Email Templates | Read | Access email template IDs |
| Activity Feed | Read | Verify automation actions |

### 1.3 Configure Environment

```bash
# Add to .env file
GREENHOUSE_API_KEY=your_harvest_api_key_here
GREENHOUSE_ON_BEHALF_OF=12345  # Your user ID for audit trail
GREENHOUSE_WEBHOOK_SECRET=your_webhook_secret  # Set when creating webhooks
GREENHOUSE_API_BASE_URL=https://harvest.greenhouse.io/v1
```

### 1.4 Key Rotation Procedure

1. Create new API key in Greenhouse (keep old one active)
2. Update `.env` with new key
3. Restart application:
   ```bash
   docker-compose restart app worker
   ```
4. Verify health:
   ```bash
   curl http://localhost:8000/health/ready
   ```
5. Test API call:
   ```bash
   curl -X GET "https://harvest.greenhouse.io/v1/users" \
     -H "Authorization: Basic $(echo -n 'YOUR_NEW_API_KEY:' | base64)"
   ```
6. Delete old API key in Greenhouse once verified

### 1.5 Verify API Access

```bash
# Test API connectivity
curl -X GET "https://harvest.greenhouse.io/v1/users" \
  -H "Authorization: Basic $(echo -n $GREENHOUSE_API_KEY: | base64)" \
  -H "On-Behalf-Of: $GREENHOUSE_ON_BEHALF_OF"
```

---

## 2. Greenhouse Webhooks Setup

### 2.1 Create Webhook

1. Navigate to **Configure → Dev Center → Webhooks**
2. Click **Create New Webhook**
3. Configure:
   - **Name**: "Recruiter Autopilot"
   - **When**: Select events (see 2.2)
   - **Endpoint URL**: `https://your-domain.com/api/webhooks/greenhouse`
   - **Secret Key**: Generate and save securely (use strong random value)

### 2.2 Required Events

Enable these webhook events:

| Event | Purpose |
|-------|---------|
| `application.created` (new_candidate_application) | Trigger scoring for new applications |
| `application.updated` | Track status changes |
| `candidate_stage_change` | Handle stage transitions |
| `candidate.hired` | End automation for hired candidates |
| `candidate.rejected` | Track rejection confirmations |
| `interview.created` | Track scheduled interviews |
| `interview.updated` | Handle interview changes |

### 2.3 Webhook Secret Configuration

```bash
# Add to .env
GREENHOUSE_WEBHOOK_SECRET=your_webhook_secret_here
```

**IMPORTANT**: The secret is used to verify webhook signatures. The signature format is:
```
Signature: sha256 <hex_digest>
```

The system verifies using HMAC-SHA256 over the **raw request body bytes** with constant-time comparison.

### 2.4 Verify Webhook Delivery

1. In Greenhouse, go to **Configure → Dev Center → Webhooks**
2. Click on your webhook, then **Test**
3. Check application logs:
   ```bash
   docker-compose logs app | grep -i "webhook\|signature"
   ```
4. Verify event stored:
   ```sql
   SELECT greenhouse_event_id, event_type, status, received_at
   FROM events ORDER BY received_at DESC LIMIT 5;
   ```

### 2.5 Troubleshooting Webhook Failures

**Signature Verification Failed (401)**
- Check `GREENHOUSE_WEBHOOK_SECRET` matches Greenhouse config exactly
- Verify raw body is not modified before verification
- Check for encoding issues (UTF-8 required)

**Event Not Processing (stored but stuck)**
- Check Celery worker status: `docker-compose ps worker`
- Check queue: `docker-compose exec redis redis-cli LLEN celery`
- Review worker logs: `docker-compose logs --tail=100 worker`

**Duplicate Detection**
- Events are deduplicated by `Greenhouse-Event-ID` header
- Check events table for unique constraint violations

---

## 3. Microsoft Graph App Setup

### 3.1 Register Azure AD Application

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory → App registrations**
3. Click **New registration**:
   - **Name**: "Recruiter Autopilot"
   - **Supported account types**: Single tenant
   - **Redirect URI**: Leave blank (daemon/service app)

### 3.2 Configure API Permissions

Add these **Application** permissions (not Delegated):

| Permission | Type | Purpose |
|------------|------|---------|
| `Mail.Send` | Application | Send emails to candidates |
| `Mail.Read` | Application | Read candidate replies |
| `Calendars.ReadWrite` | Application | Create calendar events |
| `User.Read.All` | Application | Get user info, free/busy |

**Grant admin consent** for all permissions.

### 3.3 Create Client Secret

1. Go to **Certificates & secrets**
2. Click **New client secret**
3. Set expiration (recommend 12-24 months)
4. **Copy the secret value immediately** - it won't be shown again

### 3.4 Configure Environment

```bash
# Add to .env
MS_TENANT_ID=your_tenant_id_guid
MS_CLIENT_ID=your_client_id_guid
MS_CLIENT_SECRET=your_client_secret_value
MS_MAILBOX=recruiting@yourcompany.com  # Shared mailbox for sending
MS_GRAPH_SCOPES=Mail.Send,Calendars.ReadWrite
```

### 3.5 Webhook Subscription Setup

Graph subscriptions are created automatically on startup. To manually manage:

**Create subscription:**
```bash
curl -X POST http://localhost:8000/api/admin/graph/subscriptions/create \
  -H "Content-Type: application/json" \
  -d '{
    "resource": "/users/recruiting@yourcompany.com/messages",
    "changeTypes": ["created"],
    "notificationUrl": "https://your-domain.com/api/graph/notifications"
  }'
```

**List subscriptions:**
```sql
SELECT subscription_id, resource, expiry, renewal_failures
FROM graph_subscriptions ORDER BY expiry;
```

### 3.6 Subscription Renewal

Subscriptions auto-renew via Celery Beat (hourly check, renews 24h before expiry).

**Manual renewal:**
```bash
# Via Celery task
docker-compose exec worker celery -A app.workers.celery_app call app.workers.renewal_tasks.renew_graph_subscriptions
```

**Check renewal status:**
```sql
SELECT subscription_id, resource, expiry,
       expiry - NOW() as time_until_expiry,
       renewal_failures
FROM graph_subscriptions
WHERE expiry < NOW() + INTERVAL '24 hours';
```

### 3.7 Troubleshooting Graph Issues

**Validation Token Error**
- Notification URL must be HTTPS
- URL must be publicly accessible
- Check firewall allows Microsoft IP ranges

**Subscription Creation Failed**
- Verify API permissions granted and consented
- Check tenant ID matches
- Ensure mailbox exists and app has access

**Email Not Sending**
- Verify `Mail.Send` permission granted
- Check mailbox exists: try sending via Graph Explorer
- Check rate limits (throttling)

---

## 4. DLQ Replay Procedure

### 4.1 Check DLQ Status

**Via API:**
```bash
curl http://localhost:8000/api/admin/dlq/stats
```

**Via database:**
```sql
-- Exception counts by status
SELECT status, exception_type, COUNT(*)
FROM exceptions
GROUP BY status, exception_type
ORDER BY COUNT(*) DESC;

-- Recent open exceptions
SELECT id, exception_type, reason, created_at
FROM exceptions
WHERE status = 'open'
ORDER BY created_at DESC
LIMIT 20;
```

### 4.2 Replay Single Exception

```bash
curl -X POST http://localhost:8000/api/admin/dlq/replay/{exception_uuid} \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

### 4.3 Replay by Greenhouse Event ID

```bash
curl -X POST http://localhost:8000/api/admin/dlq/replay/by-event/evt-abc123 \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

### 4.4 Replay by Application ID

```bash
curl -X POST http://localhost:8000/api/admin/dlq/replay/by-application/{application_uuid} \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

### 4.5 Replay by Time Window

Useful for recovering from outages:

```bash
curl -X POST "http://localhost:8000/api/admin/dlq/replay/by-time-window?\
start_time=2026-01-10T00:00:00Z&\
end_time=2026-01-10T23:59:59Z&\
status_filter=failed" \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

### 4.6 Force Replay (Already Processed)

Add `force: true` to replay events that were already processed:

```bash
curl -X POST http://localhost:8000/api/admin/dlq/replay/{id} \
  -H "Content-Type: application/json" \
  -d '{"force": true}'
```

### 4.7 Bulk Replay via CLI Script

```bash
docker-compose exec app python << 'EOF'
from datetime import datetime, timedelta
from app.database import SyncSessionLocal
from sqlalchemy import select
from app.models.event import Event
from app.workers.tasks import process_greenhouse_event

session = SyncSessionLocal()
cutoff = datetime.utcnow() - timedelta(hours=2)

events = session.execute(
    select(Event).where(
        Event.status == 'failed',
        Event.received_at >= cutoff
    )
).scalars().all()

print(f"Found {len(events)} failed events")
for event in events:
    event.status = 'pending'
    process_greenhouse_event.delay(
        event.greenhouse_event_id,
        event.event_type,
        event.raw_body_json,
    )
    print(f"Replayed: {event.greenhouse_event_id}")

session.commit()
print(f"Done. Replayed {len(events)} events")
EOF
```

### 4.8 Resolve Exception (Manual Fix)

If you've manually fixed the issue:

```bash
curl -X POST http://localhost:8000/api/admin/exceptions/{exception_id}/resolve
```

---

## 5. Kill Switch Usage

### 5.1 Global Kill Switch

**Disable ALL automation immediately:**
```bash
curl -X POST http://localhost:8000/api/admin/kill-switch/global \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

**Re-enable:**
```bash
curl -X POST http://localhost:8000/api/admin/kill-switch/global \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

When disabled:
- Webhooks still received and stored
- Events NOT processed
- No tags/notes/emails sent
- No Greenhouse API calls made

### 5.2 Per-Job Kill Switch

**Disable for specific job:**
```bash
curl -X POST http://localhost:8000/api/admin/kill-switch/job/12345 \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### 5.3 Check Current Status

```bash
curl http://localhost:8000/api/admin/kill-switch/status | jq
```

### 5.4 Feature Flags

**List all flags:**
```bash
curl http://localhost:8000/api/admin/feature-flags | jq
```

**Disable specific feature:**
```bash
# Disable scheduling
curl -X POST "http://localhost:8000/api/admin/feature-flags/ENABLE_SCHEDULING" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'

# Disable Greenhouse writeback
curl -X POST "http://localhost:8000/api/admin/feature-flags/ENABLE_HARVEST_WRITEBACK" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### 5.5 Emergency Procedures

1. **Immediate stop all processing:**
   ```bash
   # Kill switch
   curl -X POST http://localhost:8000/api/admin/kill-switch/global \
     -d '{"enabled": false}'

   # Also stop workers as backup
   docker-compose stop worker beat
   ```

2. **Investigate:**
   ```bash
   docker-compose logs --tail=200 worker
   docker-compose logs --tail=200 app
   ```

3. **Fix the issue**

4. **Resume operations:**
   ```bash
   docker-compose start worker beat
   curl -X POST http://localhost:8000/api/admin/kill-switch/global \
     -d '{"enabled": true}'
   ```

---

## 6. Deployment

### 6.1 Initial Setup

```bash
# Clone repository
git clone <repo-url>
cd Greenhouse\ BOT

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials

# Start all services
docker-compose up -d

# Run database migrations
docker-compose exec app alembic upgrade head

# Verify health
curl http://localhost:8000/health/ready
```

### 6.2 Docker Compose Services

| Service | Port | Purpose |
|---------|------|---------|
| app | 8000 | FastAPI application |
| worker | - | Celery task worker |
| beat | - | Celery scheduler |
| flower | 5555 | Celery monitoring |
| postgres | 5432 | Database |
| redis | 6379 | Message broker |

### 6.3 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GREENHOUSE_API_KEY` | Yes | Harvest API key |
| `GREENHOUSE_WEBHOOK_SECRET` | Yes | Webhook signature secret |
| `GREENHOUSE_ON_BEHALF_OF` | Yes | User ID for API calls |
| `MS_TENANT_ID` | Yes | Azure AD tenant |
| `MS_CLIENT_ID` | Yes | Azure app client ID |
| `MS_CLIENT_SECRET` | Yes | Azure app secret |
| `MS_MAILBOX` | Yes | Email mailbox |
| `DATABASE_URL` | Yes | PostgreSQL async URL |
| `DATABASE_URL_SYNC` | Yes | PostgreSQL sync URL |
| `REDIS_URL` | Yes | Redis connection |

### 6.4 Running in Mock Mode

For testing without credentials:

```bash
# Set mock mode in .env
MOCK_MODE=true

# Run tests
docker-compose run app pytest tests/e2e/
```

---

## 7. Monitoring & Alerts

### 7.1 Health Checks

```bash
# Basic health
curl http://localhost:8000/health

# Full readiness (DB, Redis, APIs)
curl http://localhost:8000/health/ready
```

### 7.2 Key Metrics

| Metric | Alert Threshold | Check Command |
|--------|-----------------|---------------|
| Failed events | >10 in 1 hour | See SQL below |
| Open exceptions | >50 total | See SQL below |
| Queue depth | >1000 | `redis-cli LLEN celery` |
| Sub expiry | <24 hours | See SQL below |
| Worker status | Not running | `docker-compose ps` |

**SQL Queries:**
```sql
-- Failed events in last hour
SELECT COUNT(*) FROM events
WHERE status = 'failed'
AND received_at > NOW() - INTERVAL '1 hour';

-- Open exceptions
SELECT COUNT(*) FROM exceptions WHERE status = 'open';

-- Expiring subscriptions
SELECT * FROM graph_subscriptions
WHERE expiry < NOW() + INTERVAL '24 hours';
```

### 7.3 Flower Dashboard

Access at: `http://localhost:5555`

Shows:
- Active tasks
- Task history
- Worker status
- Queue lengths

### 7.4 Recommended Alerts

1. **High Priority:**
   - Global kill switch triggered
   - Webhook failures >10/hour
   - Worker not running
   - Database connection failures

2. **Medium Priority:**
   - DLQ size growing >20/hour
   - Graph subscription renewal failures
   - API rate limit warnings

3. **Low Priority:**
   - Queue depth >500
   - Processing time >30s

---

## 8. Troubleshooting Guide

### 8.1 Webhooks Not Processing

1. **Check webhook received:**
   ```sql
   SELECT greenhouse_event_id, status, error_message
   FROM events WHERE status != 'processed'
   ORDER BY received_at DESC LIMIT 10;
   ```

2. **Check worker running:**
   ```bash
   docker-compose ps worker
   docker-compose logs --tail=50 worker
   ```

3. **Check queue:**
   ```bash
   docker-compose exec redis redis-cli LLEN celery
   ```

4. **Check kill switch:**
   ```bash
   curl http://localhost:8000/api/admin/kill-switch/status
   ```

### 8.2 Signature Verification Failures

1. Check secret matches exactly (no whitespace)
2. Verify signature header format: `sha256 <hex>`
3. Check logs for raw signature value
4. Test with known payload:
   ```python
   import hmac, hashlib
   payload = b'{"test": true}'
   secret = b'your_secret'
   sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
   print(f"sha256 {sig}")
   ```

### 8.3 Loop Prevention Issues

If seeing repeated processing of same application:

1. Check for AUTOPILOT_ACTION_ID marker:
   ```sql
   SELECT * FROM actions
   WHERE application_id = 'your-app-id'
   ORDER BY created_at DESC;
   ```

2. Check event reconciliation:
   ```sql
   SELECT * FROM events
   WHERE status = 'reconciled'
   ORDER BY received_at DESC LIMIT 10;
   ```

### 8.4 Database Issues

1. **Check connection:**
   ```bash
   docker-compose exec postgres pg_isready
   ```

2. **Check pool:**
   ```sql
   SELECT count(*) FROM pg_stat_activity
   WHERE datname = 'recruiter_autopilot';
   ```

3. **Restart connections:**
   ```bash
   docker-compose restart app worker
   ```

---

## 9. Maintenance Procedures

### 9.1 Regular Tasks

**Daily:**
- Monitor exception queue (should be <50)
- Check failed event count
- Review Flower dashboard for errors

**Weekly:**
- Review scoring accuracy metrics
- Check patterns in exceptions
- Review audit logs for anomalies

**Monthly:**
- Archive old events (>90 days)
- Review and update rubrics
- Performance optimization review
- Rotate API credentials (recommended quarterly)

### 9.2 Database Maintenance

**Cleanup old events:**
```sql
-- Delete events older than 90 days
DELETE FROM events
WHERE received_at < NOW() - INTERVAL '90 days'
AND status = 'processed';

-- Vacuum after large deletes
VACUUM ANALYZE events;
```

**Backup:**
```bash
# Full backup
docker-compose exec postgres pg_dump -U recruiter recruiter_autopilot > backup_$(date +%Y%m%d).sql

# Compressed backup
docker-compose exec postgres pg_dump -U recruiter recruiter_autopilot | gzip > backup_$(date +%Y%m%d).sql.gz
```

### 9.3 Log Rotation

Docker handles log rotation. To configure limits in `docker-compose.yml`:

```yaml
services:
  app:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## Quick Reference

### API Endpoints Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Basic health |
| `/health/ready` | GET | Full readiness |
| `/api/webhooks/greenhouse` | POST | Greenhouse webhooks |
| `/api/graph/notifications` | POST | Graph notifications |
| `/api/admin/kill-switch/global` | POST | Global kill switch |
| `/api/admin/kill-switch/job/{id}` | POST | Job kill switch |
| `/api/admin/kill-switch/status` | GET | Status of all switches |
| `/api/admin/dlq/stats` | GET | DLQ statistics |
| `/api/admin/dlq/replay/{id}` | POST | Replay exception |
| `/api/admin/dlq/replay/by-event/{id}` | POST | Replay by event ID |
| `/api/admin/dlq/replay/by-application/{id}` | POST | Replay by app ID |
| `/api/admin/dlq/replay/by-time-window` | POST | Replay by time range |
| `/api/admin/exceptions` | GET | List exceptions |
| `/api/admin/exceptions/{id}` | GET | Get exception detail |
| `/api/admin/exceptions/{id}/resolve` | POST | Resolve exception |
| `/api/admin/feature-flags` | GET | List feature flags |
| `/api/admin/feature-flags/{name}` | POST | Set feature flag |
| `/api/admin/applications/{id}/rescore` | POST | Re-run scoring |

### Common Commands

```bash
# View all logs
docker-compose logs -f

# View specific service
docker-compose logs -f worker

# Restart services
docker-compose restart app worker

# Check queue depth
docker-compose exec redis redis-cli LLEN celery

# Run migrations
docker-compose exec app alembic upgrade head

# Database shell
docker-compose exec postgres psql -U recruiter recruiter_autopilot

# Run tests
docker-compose run app pytest tests/

# Stop everything
docker-compose down

# Full rebuild
docker-compose down && docker-compose build && docker-compose up -d
```

---

*Last updated: 2026-01-11*
