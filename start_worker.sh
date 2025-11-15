#!/bin/bash

# Start Celery Worker for Real Estate Video Generator
# This script starts a Celery worker to process video generation tasks in the background

echo "================================================================================"
echo "Starting Celery Worker for Real Estate Video Generator"
echo "================================================================================"
echo ""

# Check if Redis is running
if ! redis-cli ping > /dev/null 2>&1; then
    echo "❌ Redis is not running!"
    echo ""
    echo "Please start Redis first:"
    echo "  macOS:  brew services start redis"
    echo "  Linux:  sudo systemctl start redis"
    echo "  Docker: docker run -d -p 6379:6379 redis:latest"
    echo ""
    exit 1
fi

echo "✓ Redis is running"
echo ""

# Start Celery worker
echo "Starting Celery worker..."
echo "Press Ctrl+C to stop the worker"
echo ""
echo "================================================================================"
echo ""

celery -A celery_app worker --loglevel=info
