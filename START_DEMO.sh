#!/bin/bash
# Quick Demo Start Script - Works without database

cd "/Users/nitishshrivastava/Desktop/Greenhouse BOT"

echo "🚀 Starting Recruiting Autopilot Demo..."
echo ""

# Set environment to skip database initialization
export ENVIRONMENT=development
export DATABASE_URL="sqlite+aiosqlite:///./demo.db"
export DATABASE_URL_SYNC="sqlite:///./demo.db"
export MOCK_MODE=true

# Start server
echo "Starting server on http://localhost:8000"
echo ""
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
