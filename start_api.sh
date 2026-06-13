#!/bin/bash
# start_api.sh - Simplified startup script for Friday Backend API

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

echo "Starting Friday Backend API..."

# Check if venv exists
if [ -d "venv" ]; then
    ./venv/bin/python3 interface/api.py
else
    echo "Warning: venv not found. Trying system python3..."
    python3 interface/api.py
fi
