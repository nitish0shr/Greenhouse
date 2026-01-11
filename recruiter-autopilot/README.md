# Recruiter Autopilot

A production-grade automation system for Greenhouse ATS and Microsoft Outlook that handles the complete recruiting workflow from application ingestion to interview scheduling.

## Features

- **Webhook-Driven Architecture**: Real-time processing via Greenhouse webhooks and Microsoft Graph notifications
- **Intelligent Scoring**: Configurable YAML-based rubrics for consistent candidate evaluation
- **Resume Parsing**: Extract structured facts from PDF/DOCX resumes
- **Email Automation**: Template-based email sending via Microsoft Graph
- **Interview Scheduling**: Free/busy queries and calendar management
- **SLA Monitoring**: Prevent stuck candidates with automated alerts
- **Human Override**: Review queue and per-job/stage kill switches
- **Compliance**: EEOC-safe scoring, PII redaction, audit logging

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Greenhouse    │     │   Microsoft     │     │    Admin UI     │
│   Webhooks      │     │   Graph API     │     │    (HTMX)       │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                          │
│  • Webhook receivers  • REST API  • Admin dashboard              │
└────────────────────────────────┬─────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│     Redis       │     │   PostgreSQL    │     │  Celery Workers │
│  (Task Queue)   │     │  (State/Audit)  │     │  (Processing)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)
- Greenhouse API key and webhook secret
- Microsoft Azure AD app with Graph API permissions

### 1. Clone and Configure

```bash
cd recruiter-autopilot
cp .env.example .env
# Edit .env with your credentials
```

### 2. Start with Docker Compose

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f api

# Run migrations
docker-compose exec api alembic upgrade head
```

### 3. Access the Application

- **API**: http://localhost:8000
- **Admin UI**: http://localhost:8000/admin (default: admin/change-me)
- **API Docs**: http://localhost:8000/docs
- **Flower (Celery)**: http://localhost:5555

### 4. Configure Greenhouse Webhooks

1. Go to Greenhouse → Configure → Dev Center → Web Hooks
2. Create a new webhook pointing to: `https://your-domain.com/webhooks/greenhouse`
3. Enable events: `Application Updated`, `New Candidate Application`, `Offer Events`
4. Copy the secret key to your `.env` file

## Configuration

### Environment Variables

See `.env.example` for all available configuration options.

Key variables:
- `GREENHOUSE_API_KEY`: Your Greenhouse Harvest API key
- `GREENHOUSE_WEBHOOK_SECRET`: Webhook signature verification secret
- `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`: Azure AD app credentials
- `MS_SHARED_MAILBOX`: Email address for sending emails
- `MOCK_MODE`: Set to `true` for local testing without real APIs

### Scoring Rubrics

Rubrics are defined in YAML format in `config/rubrics/`. Example:

```yaml
name: "Software Engineer Rubric"
version: "1.0"

dimensions:
  experience:
    weight: 0.35
    scoring:
      0-2_years: 3
      2-5_years: 6
      5-10_years: 8
      10+_years: 10

  skills:
    weight: 0.40
    required_any:
      - python
      - java
      - go
    preferred:
      - kubernetes
      - aws

hard_constraints:
  - name: min_experience
    type: years
    min: 2
    reject_message: "Less than 2 years experience"

tier_thresholds:
  A: 0.80
  B: 0.65
  C: 0.45
```

### Adding a New Role Rubric

1. Create a new YAML file in `config/rubrics/`:
   ```bash
   cp config/rubrics/software_engineer.yaml config/rubrics/product_manager.yaml
   ```

2. Customize dimensions, weights, and thresholds

3. Link the rubric to jobs via the API or admin UI

## Development

### Local Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e ".[dev]"

# Start services
docker-compose up -d postgres redis

# Run migrations
alembic upgrade head

# Start API server
python main.py

# In another terminal, start worker
celery -A src.workers.celery_app worker --loglevel=info
```

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit

# With coverage
pytest --cov=src --cov-report=html

# Specific test
pytest tests/unit/test_scoring.py -v
```

### Code Quality

```bash
# Linting
ruff check src tests

# Type checking
mypy src

# Formatting
ruff format src tests
```

## API Endpoints

### Webhooks

- `POST /webhooks/greenhouse` - Receive Greenhouse webhooks
- `POST /webhooks/graph` - Receive Microsoft Graph notifications
- `GET /webhooks/greenhouse/status/{event_id}` - Check webhook status

### Applications

- `GET /api/applications` - List applications (paginated, filterable)
- `GET /api/applications/{id}` - Get application details
- `GET /api/applications/{id}/timeline` - Get automation timeline
- `GET /api/applications/review-queue` - Get applications needing review
- `POST /api/applications/{id}/mark-reviewed` - Mark as reviewed
- `POST /api/applications/{id}/rescore` - Trigger re-scoring

### Jobs

- `GET /api/jobs` - List jobs
- `GET /api/jobs/{id}` - Get job details
- `GET /api/jobs/{id}/stats` - Get job statistics
- `PATCH /api/jobs/{id}/automation` - Update automation settings
- `POST /api/jobs/{id}/kill-switch/activate` - Activate kill switch

### Admin

- `GET /admin` - Dashboard
- `GET /admin/review-queue` - Review queue UI
- `GET /admin/exceptions` - Exception queue UI
- `GET /admin/jobs` - Job management UI

## Application State Machine

```
ingested → parsed → scored → actioned → contacted → scheduling →
scheduled → interviewed → decision_pending → closed

Any failure → exception_queue (with retry controls)
```

## Security Considerations

1. **Webhook Signature Verification**: All Greenhouse webhooks are verified using HMAC-SHA256
2. **Protected Traits**: Rubrics are validated to prevent EEOC violations
3. **PII Redaction**: Sensitive data is redacted from logs
4. **Prompt Injection Defense**: Resume content is sanitized before processing
5. **Least Privilege**: Graph API permissions are scoped to minimum required

## Production Deployment

### Recommended Setup

1. Use managed PostgreSQL (AWS RDS, Google Cloud SQL)
2. Use managed Redis (ElastiCache, Memorystore)
3. Deploy behind a load balancer with HTTPS
4. Use environment-specific configurations
5. Enable structured JSON logging for log aggregation
6. Set up monitoring with Prometheus/Grafana

### Environment Variables for Production

```bash
APP_ENV=production
DEBUG=false
LOG_LEVEL=INFO
MOCK_MODE=false
DRY_RUN=false
ADMIN_PASSWORD=<secure-password>
SECRET_KEY=<secure-random-string>
```

### Health Checks

- `/health` - Application health
- `/ready` - Readiness (DB/Redis connectivity)

## Troubleshooting

### Webhook Not Processing

1. Check webhook signature secret matches
2. Verify webhook event is enabled in Greenhouse
3. Check Celery worker logs: `docker-compose logs worker`
4. Look for exceptions in `/admin/exceptions`

### Scoring Issues

1. Check rubric validation: errors logged on startup
2. Verify resume parsing: check `candidates.resume_text`
3. Review scoring results in `/admin/applications/{id}/timeline`

### Email Not Sending

1. Verify Graph API credentials
2. Check shared mailbox permissions
3. Look for bounces in `email_logs` table
4. Ensure `MOCK_MODE=false` for production

## Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - See LICENSE file for details
