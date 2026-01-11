# Railway Database Connection Fix

## Issue
The app was crashing with `ConnectionRefusedError` because it was trying to initialize the database on startup, even in production.

## Fix Applied
Modified `app/main.py` to:
1. **Skip database initialization in production** - Use Alembic migrations instead
2. **Only initialize in local development** - Only when DATABASE_URL points to localhost
3. **Handle connection errors gracefully** - Log warning instead of crashing

## What Changed

### Before
- Always tried to initialize database in development mode
- Crashed if database wasn't available

### After
- Only initializes database in development AND if DATABASE_URL is localhost
- Skips initialization in production (Railway)
- Logs warnings instead of crashing

## Railway Setup

### 1. Set Environment Variable
In Railway dashboard → Variables:
```
ENVIRONMENT=production
```

### 2. Connect PostgreSQL Service
Railway should automatically provide `DATABASE_URL` when you add a PostgreSQL service.

### 3. Run Migrations
After deployment, run migrations to create tables:
```bash
railway run alembic upgrade head
```

Or via Railway CLI:
```bash
railway link
railway run alembic upgrade head
```

## Deployment Status

✅ Code pushed to GitHub
✅ Railway will auto-deploy
✅ Database initialization skipped in production
✅ App will start even if database connection fails initially

The app should now start successfully! It will skip database initialization and wait for you to run migrations manually.
