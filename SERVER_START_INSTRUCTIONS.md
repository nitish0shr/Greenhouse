# Server Start Instructions

## Issue
The server requires a PostgreSQL database connection. The current error is:
```
role "recruiter" does not exist
```

## Quick Solutions

### Option 1: Use Docker (Easiest)
```bash
cd "/Users/nitishshrivastava/Desktop/Greenhouse BOT"
docker-compose up -d
```
This will start PostgreSQL, Redis, and the API server automatically.

### Option 2: Install PostgreSQL Locally
```bash
# macOS
brew install postgresql
brew services start postgresql

# Create database and user
createdb recruiter_autopilot
psql -c "CREATE USER recruiter WITH PASSWORD 'recruiter_pass';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE recruiter_autopilot TO recruiter;"
```

### Option 3: Use SQLite (Quick Demo)
Modify `.env` to use SQLite:
```
DATABASE_URL=sqlite+aiosqlite:///./demo.db
DATABASE_URL_SYNC=sqlite:///./demo.db
```

Then start:
```bash
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Once Server is Running

Open in Chrome:
- **API Docs**: http://localhost:8000/docs
- **Admin Dashboard**: http://localhost:8000/admin
- **Health Check**: http://localhost:8000/health

## Code Already Pushed to GitHub ✅

Your code is already on GitHub: https://github.com/nitish0shr/Greenhouse

You can view it there while setting up the local database!
