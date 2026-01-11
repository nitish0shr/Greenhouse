# Recruiter Autopilot

A production-ready system that automates high-volume applicant processing in Greenhouse, with official email capabilities via Microsoft 365 Outlook.

## Features

- **Greenhouse Webhook Integration**: Receives and processes `new_candidate_application` and `candidate_stage_change` events with HMAC signature verification and idempotency handling
- **Automated Scoring**: Configurable rubric-based candidate scoring with hard-reject rules
- **Stage Automation**: Auto-advance high scorers, auto-reject low scorers, queue uncertain cases for human review
- **Resume Parsing**: Extract text from PDF, DOCX, TXT, and RTF resumes
- **Outlook Email**: Send official emails via Microsoft Graph and log back to Greenhouse
- **Interview Scheduling**: Create interviews in both Greenhouse and Outlook calendar with event sync
- **Admin Dashboard**: Monitor queue status, review uncertain candidates, audit logs
- **Security**: Prompt-injection defense, compliance checks (no protected traits in scoring)

## Tech Stack

- **Backend**: Python 3.11 + FastAPI
- **Worker**: Celery with Redis broker
- **Database**: PostgreSQL
- **Deploy**: Docker Compose

## Quick Start

### 1. Clone and Configure

```bash
# Clone the repository
git clone <repo-url>
cd recruiter-autopilot

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
# - GREENHOUSE_API_KEY
# - GREENHOUSE_WEBHOOK_SECRET
# - MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET
# - Database and Redis URLs (defaults work with Docker Compose)
```

### 2. Start with Docker Compose

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f app

# Run database migrations
docker-compose exec app alembic upgrade head
```

### 3. Configure Greenhouse Webhooks

1. Go to Greenhouse > Configure > Dev Center > Web Hooks
2. Create a new webhook with:
   - **Endpoint URL**: `https://your-domain.com/api/greenhouse/webhook`
   - **Secret Key**: Copy to `GREENHOUSE_WEBHOOK_SECRET` in `.env`
   - **Events**: `new_candidate_application`, `candidate_stage_change`

### 4. Configure Microsoft Graph

1. Register an app in Azure AD
2. Add permissions: `Mail.Send`, `Calendars.ReadWrite`
3. Copy tenant ID, client ID, and client secret to `.env`

### 5. Access Admin Dashboard

Open `http://localhost:8000/admin/` and login with credentials from `.env`:
- Username: `ADMIN_USERNAME` (default: admin)
- Password: `ADMIN_PASSWORD` (default: change_this_password)

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Greenhouse  │────▶│   FastAPI    │────▶│    Celery    │
│   Webhooks   │     │   (app)      │     │   (worker)   │
└──────────────┘     └──────────────┘     └──────────────┘
                            │                     │
                            ▼                     ▼
                     ┌──────────────┐     ┌──────────────┐
                     │   PostgreSQL │     │    Redis     │
                     │   (database) │     │   (broker)   │
                     └──────────────┘     └──────────────┘
```

### Processing Pipeline

1. **Webhook Received** → Verify signature, check idempotency
2. **Fetch Data** → Get application + candidate from Greenhouse
3. **Download Resume** → Immediately (URLs expire)
4. **Parse Resume** → Extract text from PDF/DOCX
5. **Score Candidate** → Apply rubric, check hard constraints
6. **Take Action** → Advance, reject, or queue for review
7. **Write Back** → Add tags, notes, update custom fields

## Configuration

### Scoring Rubric

Edit `config/scoring_rubric.yaml`:

```yaml
required_skills:
  - name: "Python"
    weight: 20
    keywords: ["python", "django", "fastapi"]

hard_constraints:
  - type: "years_experience"
    minimum: 3
    reject_reason_id: 12345

thresholds:
  advance: 75
  reject: 25
  human_review: 50
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `GREENHOUSE_API_KEY` | Harvest API key |
| `GREENHOUSE_WEBHOOK_SECRET` | Webhook HMAC secret |
| `GREENHOUSE_ON_BEHALF_OF` | User ID for write operations |
| `MS_TENANT_ID` | Azure AD tenant ID |
| `MS_CLIENT_ID` | App registration client ID |
| `MS_CLIENT_SECRET` | App registration secret |
| `MS_MAILBOX` | Email address for sending |
| `SCORE_THRESHOLD_ADVANCE` | Min score to auto-advance (default: 75) |
| `SCORE_THRESHOLD_REJECT` | Max score to auto-reject (default: 25) |

## API Endpoints

### Webhooks
- `POST /api/greenhouse/webhook` - Receive Greenhouse events
- `POST /api/graph/notifications` - Receive Graph notifications

### Admin
- `GET /admin/` - Dashboard
- `GET /admin/queue` - Queue status
- `GET /admin/review` - Human review queue
- `POST /admin/api/candidates/{id}/rescore` - Re-run scoring
- `POST /admin/api/review/{id}/approve` - Approve application
- `POST /admin/api/review/{id}/reject` - Reject application

### Health
- `GET /health` - Basic health check
- `GET /health/ready` - Readiness check with dependencies

## Development

### Run Locally (without Docker)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL and Redis (via Docker or locally)
docker-compose up -d postgres redis

# Run migrations
alembic upgrade head

# Start FastAPI
uvicorn app.main:app --reload

# Start Celery worker (in another terminal)
celery -A app.workers.celery_app worker --loglevel=info
```

### Run Tests

```bash
# Create test database
createdb recruiter_autopilot_test

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=app --cov-report=html
```

## Security

### Webhook Verification
All Greenhouse webhooks are verified using HMAC-SHA256 signatures.

### Prompt Injection Defense
Resume content is treated as untrusted. The scoring engine uses keyword matching only—never passes resume content to LLM prompts.

### Compliance
The rubric validator checks for protected traits (race, gender, age, etc.) and rejects non-compliant configurations.

## Monitoring

### Celery Flower
Access Flower at `http://localhost:5555` for queue monitoring.

### Audit Logs
All actions are logged in the `audit_logs` table and visible in the admin UI.

## License

MIT
