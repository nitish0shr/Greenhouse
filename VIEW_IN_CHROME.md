# View the Application in Chrome

## Quick Start (Easiest Method)

### Option 1: Use the Start Script

```bash
cd "/Users/nitishshrivastava/Desktop/Greenhouse BOT"
./START_SERVER.sh
```

This script will:
- Create a virtual environment if needed
- Install dependencies
- Start the server on http://localhost:8000
- Work in mock mode (no real API keys needed)

### Option 2: Manual Start

```bash
cd "/Users/nitishshrivastava/Desktop/Greenhouse BOT"

# Create virtual environment (first time only)
python3 -m venv venv
source venv/bin/activate

# Install dependencies (first time only)
pip install -r requirements.txt

# Start server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Open in Chrome

Once the server is running, open these URLs in Chrome:

### 1. API Documentation (Interactive)
**URL**: http://localhost:8000/docs

- Swagger UI interface
- Test all API endpoints
- See request/response schemas
- Try endpoints directly in the browser

### 2. Admin Dashboard
**URL**: http://localhost:8000/admin

**Login Credentials**:
- Username: `admin` (or from ADMIN_USERNAME in .env)
- Password: `admin123` (or from ADMIN_PASSWORD in .env)

**Features**:
- View application queue
- Review candidates
- Monitor processing status
- View audit logs

### 3. Health Check
**URL**: http://localhost:8000/health

- Check system status
- Verify database connection
- Check Redis connection

### 4. Root Endpoint
**URL**: http://localhost:8000/

- API information
- Available endpoints
- System version

## What You'll See

### API Documentation (/docs)
- **Green**: GET endpoints (read operations)
- **Yellow**: POST endpoints (create operations)
- **Red**: DELETE endpoints
- **Blue**: PUT/PATCH endpoints (update operations)

Click "Try it out" on any endpoint to test it!

### Admin Dashboard (/admin)
- **Dashboard**: Overview with statistics
- **Queue**: Applications pending review
- **Candidates**: List of candidates
- **Logs**: Audit trail of all actions

## Troubleshooting

### Port Already in Use
```bash
# Find what's using port 8000
lsof -i :8000

# Kill it (replace PID)
kill -9 <PID>

# Or use different port
uvicorn app.main:app --port 8001
```

### Module Not Found
```bash
# Make sure you're in the virtual environment
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Database Connection Error
The app will work in mock mode even without a database. To use the database:

```bash
# Start PostgreSQL (if using Docker)
docker-compose up -d postgres

# Or install PostgreSQL locally
brew install postgresql  # macOS
```

## Mock Mode

With `MOCK_MODE=true` in `.env`:
- ✅ No real Greenhouse API calls
- ✅ No real Graph API calls
- ✅ Perfect for testing UI
- ✅ All endpoints work with mock data

## Next Steps

1. **Start the server** using one of the methods above
2. **Open Chrome** and navigate to http://localhost:8000/docs
3. **Explore the API** - try different endpoints
4. **Check the Admin Dashboard** at http://localhost:8000/admin
5. **Test webhook endpoints** (they'll work with mock data)

Enjoy exploring the Recruiting Autopilot system! 🚀
