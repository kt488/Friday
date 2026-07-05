#!/data/data/com.termux/files/usr/bin/bash
# Start Friday API server + optional Cloudflare tunnel
#
# VPS mode (no cloudflared installed):
#   bash start_tunnel.sh
#
# Termux / tunnel mode:
#   bash start_tunnel.sh                   (auto-detects named tunnel if configured)
#   bash start_tunnel.sh quick             (random URL each time)
#   bash start_tunnel.sh 5000              (custom port)

set -e

# ── Path resolution (matches start_api.sh) ──
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# ── Python detection ──
if [ -d "venv" ]; then
    PYTHON="./venv/bin/python3"
else
    PYTHON="python3"
fi

# ── Config ──
HOST="${FRIDAY_HOST:-0.0.0.0}"
PORT="${FRIDAY_PORT:-5000}"
DEBUG="${FRIDAY_DEBUG:-false}"
TUNNEL_NAME="${TUNNEL_NAME:-friday-api}"
CLOUDFLARE_DIR="${HOME}/.cloudflared"
CREDENTIALS_FILE="${CLOUDFLARE_DIR}/${TUNNEL_NAME}.json"
CONFIG_FILE="${CLOUDFLARE_DIR}/${TUNNEL_NAME}.yml"
SSL_ARGS=()
if [ -n "$FRIDAY_SSL_CERT" ]; then
    SSL_ARGS+=(--cert "$FRIDAY_SSL_CERT")
    if [ -n "$FRIDAY_SSL_KEY" ]; then
        SSL_ARGS+=(--key "$FRIDAY_SSL_KEY")
    fi
fi

# ── Detect VPS vs Termux ──
if ! command -v cloudflared &>/dev/null; then
  MODE="vps"
  echo "cloudflared not found — running in VPS mode (no tunnel)"
else
  if [ "$1" = "quick" ]; then
    MODE="quick"
    PORT="${2:-$PORT}"
  else
    PORT="${1:-$PORT}"
    if [ -f "$CREDENTIALS_FILE" ] && [ -f "$CONFIG_FILE" ]; then
      MODE="named"
    else
      MODE="quick"
    fi
  fi
fi

# ── Kill existing processes ──
pkill -f "$PYTHON main.py api" 2>/dev/null || true
if [ "$MODE" != "vps" ]; then
  pkill -f "cloudflared tunnel" 2>/dev/null || true
fi
sleep 1

# ── Start API server ──
$PYTHON main.py api --host "$HOST" --port "$PORT" $( [ "$DEBUG" = "true" ] && echo "--debug" ) "${SSL_ARGS[@]}" &
API_PID=$!
echo "API server started (PID: $API_PID) on $HOST:$PORT"

# Wait for Flask to be ready
sleep 2

# ── Start tunnel (VPS mode skips this) ──
if [ "$MODE" = "vps" ]; then
  echo ""
  echo "---"
  echo "API is running directly on http://0.0.0.0:$PORT"
  echo "To stop: kill $API_PID"
  echo ""
  wait $API_PID

elif [ "$MODE" = "named" ]; then
  echo "Starting named tunnel: ${TUNNEL_NAME} (static URL)"
  cloudflared tunnel run "$TUNNEL_NAME" &
  TUNNEL_PID=$!
  echo "Check your tunnel URL at: https://one.dash.cloudflare.com/"
  echo "Or run: cloudflared tunnel info $TUNNEL_NAME"
  echo ""
  echo "---"
  echo "To stop: kill $API_PID $TUNNEL_PID"
  echo ""
  echo "Tunnel is static — same URL every time!"

else
  echo "Starting quick tunnel (random URL each time)"
  cloudflared tunnel --url "http://localhost:$PORT" &
  TUNNEL_PID=$!
  echo ""
  echo "---"
  echo "To stop: kill $API_PID $TUNNEL_PID"
  echo ""
  echo "Tunnel URL will appear in cloudflared output above."
  echo "To get a static URL, run: bash setup_tunnel.sh"
fi

# Background wait — keep script alive so ctrl+c kills everything
wait
