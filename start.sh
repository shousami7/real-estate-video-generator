#!/bin/bash
# Real Estate Video Generator Startup Script
# This script ensures the app runs with the correct architecture

echo "Starting Real Estate Video Generator..."
echo "Detecting system architecture..."

# Get the current architecture
ARCH=$(uname -m)
echo "System architecture: $ARCH"

# Run the app
if [ "$ARCH" = "arm64" ]; then
    echo "Running in native ARM64 mode..."
    python3 app.py
else
    echo "Running in x86_64 mode..."
    arch -x86_64 python3 app.py
fi
