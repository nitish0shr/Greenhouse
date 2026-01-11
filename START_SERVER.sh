#!/bin/bash
# Quick Start Script - Start the Recruiting Autopilot Server

echo "🚀 Starting Recruiting Autopilot Server..."
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found"
    echo "Creating .env from defaults..."
    cat > .env << EOF
# Database
DATABASE_URL=postgresql+asyncpg://recruiter:recruiter_pass@localhost:5432/recruiter_autopilot
DATABASE_URL_SYNC=postgresql://recruiter:recruiter_pass@localhost:5432/recruiter_autopilot

# Redis
REDIS_URL=redis://localhost:6379/0

# Mock Mode (set to true for testing without real APIs)
MOCK_MODE=true

# Admin
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123

# Environment
ENVIRONMENT=development
DEBUG=true
EOF
    echo "✅ Created .env file with defaults"
    echo ""
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.11+"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
if [ ! -f "venv/.installed" ]; then
    echo "📥 Installing dependencies..."
    pip install -q -r requirements.txt
    touch venv/.installed
fi

# Check if PostgreSQL is running (optional)
if command -v pg_isready &> /dev/null; then
    if ! pg_isready -q; then
        echo "⚠️  Warning: PostgreSQL doesn't appear to be running"
        echo "   The app will work in mock mode, but database features may not work"
    fi
fi

# Check if Redis is running (optional)
if command -v redis-cli &> /dev/null; then
    if ! redis-cli ping &> /dev/null; then
        echo "⚠️  Warning: Redis doesn't appear to be running"
        echo "   Celery workers won't work, but API will still function"
    fi
fi

echo ""
echo "✅ Starting server on http://localhost:8000"
echo ""
echo "📖 Available endpoints:"
echo "   - API Docs: http://localhost:8000/docs"
echo "   - Admin Dashboard: http://localhost:8000/admin"
echo "   - Health Check: http://localhost:8000/health"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
