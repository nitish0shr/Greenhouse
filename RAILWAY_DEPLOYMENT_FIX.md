# Railway Deployment Fix

## Issue Fixed
The deployment was failing with:
```
ModuleNotFoundError: No module named 'psycopg2'
```

## Changes Made

### 1. Added psycopg2-binary to requirements.txt
```python
psycopg2-binary==2.9.9
```
This is required for PostgreSQL connections in the sync database engine.

### 2. Created Procfile
```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
Railway uses this to start the application and passes the PORT environment variable.

### 3. Updated config.py
- Added PORT environment variable support (Railway sets this automatically)
- Added DATABASE_URL environment variable parsing (Railway provides this)

## Railway Environment Variables

Railway will automatically provide:
- `PORT` - The port to listen on
- `DATABASE_URL` - PostgreSQL connection string

You may also need to set:
- `GREENHOUSE_API_KEY` - Your Greenhouse API key
- `GREENHOUSE_WEBHOOK_SECRET` - Webhook secret
- `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` - Microsoft Graph credentials (optional)
- `ENVIRONMENT=production`
- `DEBUG=false`

## Deployment Status

✅ Code pushed to GitHub
✅ Railway should auto-deploy from GitHub
✅ Missing dependency added
✅ PORT configuration added
✅ DATABASE_URL parsing added

The deployment should now work! Check Railway dashboard for the new deployment.
