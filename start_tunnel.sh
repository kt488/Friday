#!/data/data/com.termux/files/usr/bin/bash
# Start Friday API server + Cloudflare tunnel
#
# Static tunnel (recommended — URL stays the same each run):
#   1. Run:  bash setup_tunnel.sh
#   2. Start: bash start_tunnel.sh
#
# Quick tunnel (random URL each time — no setup needed):
#   bash start_tunnel.sh quick

set -e

PORT=${1:-5000}
TUNNEL_NAME=${TUNNEL_NAME:-friday-api}
CLOUDFLARE_DIR="${HOME}/.cloudflared"
CREDENTIALS_FILE="${CLOUDFLARE_DIR}/${TUNNEL_NAME}.json"
CONFIG_FILE="${CLOUDFLARE_DIR}/${TUNNEL_NAME}.yml"

# If first arg is "quick" (or numeric, meaning a port), force quick tunnel
if [ "$1" = "quick" ]; then
  MODE="quick"
  PORT=${2:-5000}
else
  PORT=${1:-5000}
  # Default to named tunnel if credentials exist
  if [ -f "$CREDENTIALS_FILE" ] && [ -f "$CONFIG_FILE" ]; then
    MODE="named"
  else
    MODE="quick"
  fi
fi

# Kill any existing friday-api or cloudflared processes
pkill -f "python main.py api" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 1

# Start API server
cd "$(dirname "$0")"
python main.py api --port "$PORT" &
API_PID=$!
echo "API server started (PID: $API_PID) on port $PORT"

# Wait for Flask to be ready
sleep 2

# Start tunnel
if [ "$MODE" = "named" ]; then
  echo "Starting named tunnel: ${TUNNEL_NAME} (static URL)"
  cloudflared tunnel run "$TUNNEL_NAME" &
  TUNNEL_PID=$!
  # Named tunnels log the URL once; remind where to find it
  echo "Check your tunnel URL at: https://one.dash.cloudflare.com/"
  echo "Or run: cloudflared tunnel info $TUNNEL_NAME"
else
  echo "Starting quick tunnel (random URL each time)"
  cloudflared tunnel --url "http://localhost:$PORT" &
  TUNNEL_PID=$!
fi

echo ""
echo "---"
echo "To stop: kill $API_PID $TUNNEL_PID"
echo ""
if [ "$MODE" = "named" ]; then
  echo "Tunnel is static — same URL every time."
else
  echo "Tunnel URL will appear in cloudflared output above."
  echo "To get a static URL, run: bash setup_tunnel.sh"
fi
