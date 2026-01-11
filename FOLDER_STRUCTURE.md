# Folder Structure: Recruiting Autopilot System

```
greenhouse-autopilot/
├── alembic/                          # Database migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
│
├── app/                              # Main application package
│   ├── __init__.py
│   ├── main.py                       # FastAPI app entry point
│   ├── config.py                     # Configuration (Pydantic Settings)
│   ├── database.py                   # Database connection & session management
│   │
│   ├── api/                          # API routes
│   │   ├── __init__.py
│   │   ├── webhooks.py               # POST /webhooks/greenhouse
│   │   ├── graph_webhooks.py         # POST /webhooks/graph/notifications
│   │   ├── admin.py                  # Admin endpoints (kill switch, replay, etc.)
│   │   └── health.py                 # GET /health, /health/ready
│   │
│   ├── models/                       # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── event.py                  # events table
│   │   ├── candidate.py              # candidates table
│   │   ├── application.py            # applications table
│   │   ├── action.py                 # actions table
│   │   ├── job_config.py             # job_configs table
│   │   ├── rubric_version.py         # rubric_versions table
│   │   ├── exception.py              # exceptions table (DLQ)
│   │   ├── graph_subscription.py     # graph_subscriptions table
│   │   ├── message_mapping.py        # message_mappings table
│   │   ├── calendar_mapping.py       # calendar_mappings table
│   │   ├── attachment.py             # attachments table
│   │   └── scoring_result.py         # scoring_results table
│   │
│   ├── services/                     # Business logic services
│   │   ├── __init__.py
│   │   ├── greenhouse_client.py      # Harvest API client (read/write)
│   │   ├── graph_client.py           # Microsoft Graph API client
│   │   ├── attachment_service.py     # Download & storage
│   │   ├── resume_parser.py          # Text extraction (PDF/DOCX)
│   │   ├── scorer.py                 # Scoring engine (rubric → JSON)
│   │   ├── decision_engine.py        # Decision logic (thresholds → actions)
│   │   ├── scheduler.py              # Scheduling (Outlook + GH interviews)
│   │   └── exception_service.py      # Exception handling & DLQ
│   │
│   ├── workers/                      # Celery workers
│   │   ├── __init__.py
│   │   ├── celery_app.py             # Celery app configuration
│   │   └── tasks.py                  # Task definitions (process_application, etc.)
│   │
│   ├── utils/                        # Utilities
│   │   ├── __init__.py
│   │   ├── security.py               # HMAC signature verification, constant-time compare
│   │   ├── compliance.py             # Protected traits validator
│   │   ├── idempotency.py            # Idempotency helpers
│   │   └── schema_validator.py       # Scoring JSON schema validator (Pydantic)
│   │
│   └── schemas/                      # Pydantic schemas (request/response)
│       ├── __init__.py
│       ├── webhook.py                # Greenhouse webhook payloads
│       ├── graph.py                  # Graph notification payloads
│       ├── scoring.py                # Scoring output schema (strict JSON)
│       └── admin.py                  # Admin request/response schemas
│
├── config/                           # Configuration files
│   ├── rubrics/                      # Rubric YAML files
│   │   └── default.yaml
│   └── email_templates/              # Email templates (Jinja2)
│       ├── rejection.html
│       ├── scheduling_request.html
│       ├── followup_nudge.html
│       └── missing_info.html
│
├── tests/                            # Test suite
│   ├── __init__.py
│   ├── conftest.py                   # Pytest fixtures (mock clients, DB, etc.)
│   │
│   ├── unit/                         # Unit tests
│   │   ├── __init__.py
│   │   ├── test_webhook_verification.py
│   │   ├── test_webhook_idempotency.py
│   │   ├── test_loop_prevention.py
│   │   ├── test_scoring_schema.py
│   │   ├── test_decision_engine.py
│   │   └── test_compliance.py
│   │
│   ├── integration/                  # Integration tests (mock APIs)
│   │   ├── __init__.py
│   │   ├── test_rate_limiting.py
│   │   ├── test_dlq.py
│   │   └── test_graph_subscriptions.py
│   │
│   └── e2e/                          # End-to-end tests (mock mode)
│       ├── __init__.py
│       ├── test_pipeline.py          # 10 applicants scenario
│       ├── test_idempotency.py       # Duplicate webhook
│       ├── test_scheduling.py        # Reply → scheduled
│       ├── test_exceptions.py        # Reply → exception
│       └── test_subscription_renewal.py
│
├── scripts/                          # Utility scripts
│   ├── init_db.py                    # Initialize database (dev)
│   ├── renew_graph_subscriptions.py  # Cron job for subscription renewal
│   └── replay_dlq.py                 # CLI tool for replaying DLQ events
│
├── storage/                          # Local storage (attachments) - gitignored
│   └── attachments/
│       └── .gitkeep
│
├── docs/                             # Documentation
│   ├── RUNBOOK_WEBHOOK_FAILURES.md
│   ├── RUNBOOK_GRAPH_RENEWAL.md
│   ├── RUNBOOK_DLQ_REPLAY.md
│   └── RUNBOOK_ROTATING_SECRETS.md
│
├── docker-compose.yml                # Docker Compose (Postgres + Redis + App + Worker)
├── Dockerfile                        # App Docker image
├── .dockerignore
├── .env.example                      # Environment variable template
├── .gitignore
├── pyproject.toml                    # Python dependencies (Poetry) or requirements.txt
├── alembic.ini                       # Alembic config
├── README.md                         # Main documentation
└── FIRST_REVIEW.md                   # This design review document
```

## Key Decisions

1. **Package Structure**: Flat `app/` package with clear separation (api, models, services, workers, utils, schemas)
2. **Database Migrations**: Alembic (industry standard for SQLAlchemy)
3. **Testing**: Three-tier (unit, integration, e2e) with `conftest.py` for shared fixtures
4. **Configuration**: YAML files in `config/` directory, loaded at runtime
5. **Storage**: Local filesystem for dev (`storage/attachments/`), S3 for production (configurable)
6. **Documentation**: Runbooks in `docs/` directory for operational procedures
