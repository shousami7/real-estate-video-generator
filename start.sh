#!/bin/bash
# Real Estate Video Generator Startup Script
# This script ensures the app runs with the correct architecture

echo "Starting Real Estate Video Generator..."
echo "Detecting system architecture..."

# Activate virtual environment if present
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    echo "✓ Using virtual environment at venv/"
    echo ""
fi

# Get the current architecture
ARCH=$(uname -m)
echo "System architecture: $ARCH"

# Run the app in ARM64 mode (required for venv dependencies)
echo "Running in ARM64 mode (required for venv)..."
arch -arm64 python3 app.py
