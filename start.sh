#!/bin/bash
# start.sh — Friday multi-service launcher for Railway
# Starts API (gunicorn) and Telegram bot as parallel processes.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR" || exit 1

echo "[start] Starting Friday services..."

# ── API (gunicorn) — main process ──
run_api() {
    echo "[start] Launching API (gunicorn) on port ${PORT:-5000}..."
    exec python3 -m gunicorn wsgi:app \
        --bind "0.0.0.0:${PORT:-5000}" \
        --workers 2 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
}

# ── Telegram bot — background ──
run_bot() {
    echo "[start] Launching Telegram bot..."
    while true; do
        python3 interface/telegram_bot.py
        echo "[start] Bot crashed with code $?. Restarting in 5s..."
        sleep 5
    done
}

# Start bot in background
run_bot &
BOT_PID=$!
echo "[start] Bot PID: $BOT_PID"

# Trap to clean up bot on exit
trap 'echo "[start] Shutting down bot (PID $BOT_PID)..."; kill $BOT_PID 2>/dev/null; exit' SIGTERM SIGINT

# Run API in foreground (Railway healthcheck depends on this)
run_api
