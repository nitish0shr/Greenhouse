# Quick Start Guide - Run in Chrome

## Prerequisites

1. Python 3.11+ installed
2. PostgreSQL running (or use Docker)
3. Redis running (or use Docker)
4. Environment variables configured

## Option 1: Quick Start with Docker (Recommended)

```bash
# Start all services (PostgreSQL, Redis, API)
docker-compose up -d

# View logs
docker-compose logs -f

# The API will be available at http://localhost:8000
```

## Option 2: Manual Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Setup Database

```bash
# Create database
createdb recruiter_autopilot

# Run migrations (when ready)
alembic upgrade head
```

### 3. Configure Environment

Create `.env` file:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://recruiter:recruiter_pass@localhost:5432/recruiter_autopilot
DATABASE_URL_SYNC=postgresql://recruiter:recruiter_pass@localhost:5432/recruiter_autopilot

# Redis
REDIS_URL=redis://localhost:6379/0

# Greenhouse (optional for testing)
GREENHOUSE_API_KEY=your_key_here
GREENHOUSE_WEBHOOK_SECRET=your_secret_here

# Microsoft Graph (optional for testing)
MS_TENANT_ID=your_tenant_id
MS_CLIENT_ID=your_client_id
MS_CLIENT_SECRET=your_secret

# Admin
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_this_password

# Mock Mode (for testing without real APIs)
MOCK_MODE=true
```

### 4. Start Redis (if not using Docker)

```bash
redis-server
```

### 5. Start API Server

```bash
# Development mode with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or using Python directly
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Start Celery Worker (Optional, for background tasks)

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

### 7. Start Celery Beat (Optional, for scheduled tasks)

```bash
celery -A app.workers.celery_app beat --loglevel=info
```

## Access in Chrome

Once the server is running:

1. **API Documentation**: http://localhost:8000/docs
   - Interactive Swagger UI
   - Test endpoints directly

2. **Admin Dashboard**: http://localhost:8000/admin
   - Username: `admin` (or from ADMIN_USERNAME env var)
   - Password: `change_this_password` (or from ADMIN_PASSWORD env var)

3. **Health Check**: http://localhost:8000/health

4. **Root Endpoint**: http://localhost:8000/

## Testing Without Real APIs

Set `MOCK_MODE=true` in `.env` to use mock clients:
- No real Greenhouse API calls
- No real Graph API calls
- Perfect for development and testing

## Troubleshooting

### Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill process (replace PID)
kill -9 <PID>

# Or use different port
uvicorn app.main:app --port 8001
```

### Database Connection Error

```bash
# Check PostgreSQL is running
pg_isready

# Check connection string in .env
# Verify database exists
psql -l | grep recruiter_autopilot
```

### Redis Connection Error

```bash
# Check Redis is running
redis-cli ping

# Should return: PONG
```

## Next Steps

1. Open http://localhost:8000/docs in Chrome
2. Explore the API endpoints
3. Test webhook endpoints
4. Check admin dashboard at /admin
5. Review API documentation
