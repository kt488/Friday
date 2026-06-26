#!/bin/bash
# start_api.sh - Friday REST API launcher

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

echo "Starting Friday REST API v2..."

if [ -d "venv" ]; then
    PYTHON="./venv/bin/python3"
else
    echo "Warning: venv not found. Trying system python3..."
    PYTHON="python3"
fi

# Defaults
HOST="${FRIDAY_HOST:-0.0.0.0}"
PORT="${FRIDAY_PORT:-5000}"
DEBUG="${FRIDAY_DEBUG:-false}"
# Rate limiting for public endpoints
RATE_LIMIT="${FRIDAY_RATE_LIMIT:-30}"
RATE_WINDOW="${FRIDAY_RATE_WINDOW:-60}"
SSL_ARGS=()
if [ -n "$FRIDAY_SSL_CERT" ]; then
    SSL_ARGS+=(--cert "$FRIDAY_SSL_CERT")
    if [ -n "$FRIDAY_SSL_KEY" ]; then
        SSL_ARGS+=(--key "$FRIDAY_SSL_KEY")
    fi
fi

exec $PYTHON interface/api.py --host "$HOST" --port "$PORT" $( [ "$DEBUG" = "true" ] && echo "--debug" ) "${SSL_ARGS[@]}"
