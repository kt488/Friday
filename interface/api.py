"""
Friday REST API v2
=================
Full-featured REST API with streaming, file management, agent control, memory, and tools.
"""
import os
import sys
import json
import re
import time
import logging
import uuid
from functools import wraps
from datetime import datetime

# Ensure project root is on sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

try:
    from core.friday import FridayCore
except ImportError:
    FridayCore = None
try:
    from core.config import Config
except ImportError:
    Config = None
try:
    from core.saas import SaaSService
except ImportError:
    SaaSService = None
from interface.universal_api import bp as universal_api_bp

load_dotenv()

app = Flask(__name__)
app.register_blueprint(universal_api_bp)
try:
    friday = FridayCore()
except Exception as e:
    print(f"[FATAL] FridayCore() failed: {e}", flush=True)
    friday = None

try:
    saas = SaaSService()
except Exception as e:
    print(f"[FATAL] SaaSService() failed: {e}", flush=True)
    saas = None

TEMP_DIR = Config.TEMP_DIR
os.makedirs(TEMP_DIR, exist_ok=True)

API_KEY = os.getenv("FRIDAY_API_KEY", "")

# ── Public rate limiting ──

RATE_LIMIT = int(os.getenv("FRIDAY_RATE_LIMIT", "30"))
RATE_WINDOW = int(os.getenv("FRIDAY_RATE_WINDOW", "60"))
_rate_store: dict[str, list[float]] = {}


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    cutoff = now - RATE_WINDOW
    if ip in _rate_store:
        _rate_store[ip] = [t for t in _rate_store[ip] if t > cutoff]
        if len(_rate_store[ip]) >= RATE_LIMIT:
            return False
        _rate_store[ip].append(now)
    else:
        _rate_store[ip] = [now]
    return True

# ── Internal marker cleanup ──

_MARKER_PATTERN = re.compile(
    r'(?:\[TOOL:|\*\*TOOL:).*?(?:\]|\*\*)|'
    r'(?:\[SEND_FILE:|\*\*SEND_FILE:).*?(?:\]|\*\*)|'
    r'(?:\[SEND_FILE_NOW:|\*\*SEND_FILE_NOW:).*?(?:\]|\*\*)|'
    r'(?:\[Executed|\*\*\[?Executed).*?(?:\]|\*\*)',
    flags=re.DOTALL
)


def strip_markers(text):
    return _MARKER_PATTERN.sub('', text).strip()


# ── Auth decorator ──

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if API_KEY:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] != API_KEY:
                return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Logging ──

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s %(message)s')
logger = logging.getLogger(__name__)


# ── User ID extraction ──


def _get_user_id():
    """Extract user_id from JWT in Authorization header.

    Returns the authenticated user's ID from the JWT token.
    Falls back to 'default' if no valid JWT is present (legacy API key auth).
    """
    if saas is None or saas.auth is None:
        return "default"
    auth_header = request.headers.get("Authorization", "")
    user_id, role = saas.auth.authenticate_request(auth_header)
    if user_id:
        return user_id
    return "default"


# ── CORS helpers ──

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


# ── Error handlers ──

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request", "detail": str(e)}), 400


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


# ══════════════════════════════════════════════════════════════
# Chat
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/chat", methods=["POST"])
@require_auth
def chat():
    """Send a message and receive a full response.

    Request body (JSON):
      message:         str (required unless image_path set)
      image_path:      str (optional, path to an image)
      agent:           str (optional, activate an agent before responding)
      conversation_id: str (optional, for multi-conversation support)

    Returns: { response, model, metadata, agent, conversation_id }
    """
    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    agent = data.get("agent")
    conversation_id = data.get("conversation_id")

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    user_id = _get_user_id()
    logger.info(f"[v1/chat] user_id={user_id}, conversation_id={conversation_id}, message_len={len(message)}")

    # Temporarily activate agent if specified
    try:
        full_response = friday.process_message(message, image_path=image_path, user_id=user_id, conversation_id=conversation_id, agent_name=agent)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    cleaned = strip_markers(full_response)

    return jsonify({
        "response": cleaned,
        "reply": cleaned,
        "timestamp": datetime.utcnow().isoformat(),
        "model": Config.PRIMARY_MODEL,
        "agent": agent,
        "conversation_id": conversation_id,
    })


@app.route("/api/v1/chat/stream", methods=["POST"])
@require_auth
def chat_stream():
    """Stream a response via Server-Sent Events.

    Request body (JSON): same as /api/v1/chat.

    Each event has the shape::

        data: {"text": "<partial chunk>"}
        data: {"text": "<next chunk>"}
        ...
        data: {"done": true}
    """
    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    agent = data.get("agent")
    conversation_id = data.get("conversation_id")

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    user_id = _get_user_id()
    logger.info(f"[v1/chat/stream] user_id={user_id}, conversation_id={conversation_id}, message_len={len(message)}")

    def generate():
        try:
            for chunk in friday.process_message_stream(message, image_path=image_path, user_id=user_id, conversation_id=conversation_id, agent_name=agent):
                cleaned = strip_markers(chunk)
                if cleaned:
                    yield f"data: {json.dumps({'text': cleaned})}\n\n"
            yield f"data: {json.dumps({'done': True, 'conversation_id': conversation_id})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


# ══════════════════════════════════════════════════════════════
# SaaS v2 Chat (gateway-protected)
# ══════════════════════════════════════════════════════════════


@app.route("/api/v2/chat", methods=["POST"])
@saas.gateway.require_key
def chat_v2(user_id, plan_limits):
    """Gateway-protected AI chat endpoint (API key auth via SaaS).

    Requires ``Authorization: Bearer frd_live_xxxxx`` header.
    Injects ``user_id`` and ``plan_limits`` from the API gateway.

    Request body (JSON):
      message:    str (required unless image_path set)
      image_path: str (optional)
      agent:      str (optional)
      conversation_id: str (optional)

    Returns: { response, model, plan, usage, conversation_id }
    """
    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    agent = data.get("agent")
    conversation_id = data.get("conversation_id")

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    try:
        full_response = friday.process_message(message, image_path=image_path, user_id=user_id, conversation_id=conversation_id, agent_name=agent)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    cleaned = strip_markers(full_response)

    return jsonify({
        "response": cleaned,
        "model": Config.PRIMARY_MODEL,
        "plan": plan_limits.get("name", "unknown"),
        "conversation_id": conversation_id,
    })


@app.route("/api/v2/chat/stream", methods=["POST"])
@saas.gateway.require_key
def chat_v2_stream(user_id, plan_limits):
    """Gateway-protected streaming chat endpoint (API key auth).

    Returns SSE events like /api/v1/chat/stream.
    """
    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    agent = data.get("agent")
    conversation_id = data.get("conversation_id")

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    def generate():
        try:
            for chunk in friday.process_message_stream(message, image_path=image_path, user_id=user_id, conversation_id=conversation_id, agent_name=agent):
                cleaned = strip_markers(chunk)
                if cleaned:
                    yield f"data: {json.dumps({'text': cleaned})}\n\n"
            yield f"data: {json.dumps({'done': True, 'conversation_id': conversation_id})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


# ══════════════════════════════════════════════════════════════
# History
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/history", methods=["GET"])
@require_auth
def get_history():
    """Return conversation history.

    Query params:
      limit:            int (default 50)
      conversation_id:  str (optional, scope to specific conversation)
    """
    limit = request.args.get("limit", 50, type=int)
    conversation_id = request.args.get("conversation_id")

    user_id = _get_user_id()

    # Stateless: return empty history (conversation context passed per-request)
    return jsonify({"history": [], "count": 0, "conversation_id": conversation_id})


@app.route("/api/v1/history", methods=["DELETE"])
@require_auth
def clear_history():
    """Delete conversation history.

    Body (JSON):
      conversation_id: str (optional, if omitted clears all for user)
    """
    data = request.json or {}
    conversation_id = data.get("conversation_id")
    user_id = _get_user_id()
    # Stateless: no history to clear
    msg = f"Conversation {'conversation_id=' + conversation_id + ' ' if conversation_id else ''}history cleared"
    return jsonify({"message": msg})


# ══════════════════════════════════════════════════════════════
# Files
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/files", methods=["GET"])
@require_auth
def list_files():
    """List files in the temp directory."""
    files = []
    for name in os.listdir(TEMP_DIR):
        fp = os.path.join(TEMP_DIR, name)
        if os.path.isfile(fp):
            stat = os.stat(fp)
            files.append({
                "name": name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return jsonify({"files": files, "count": len(files)})


@app.route("/api/v1/files/upload", methods=["POST"])
@require_auth
def upload_file():
    """Upload a file. Optionally analyze it with Friday.

    Multipart form:
      file:    required
      analyze: "true" | "false" (default false)

    Returns: { message, path, supabase_url, analysis }
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    filename = secure_filename(f.filename)
    filepath = os.path.join(TEMP_DIR, filename)
    f.save(filepath)

    supabase_url = friday.executive.supabase.upload_file(filepath)

    result = {
        "message": f"Uploaded {filename}",
        "path": filepath,
        "supabase_url": supabase_url,
    }

    analyze = request.form.get("analyze", "false").lower() == "true"
    if analyze:
        full = ""
        for chunk in friday.process_message_stream(f"[FILE: {filepath}] Analyze this file: {filename}"):
            full += chunk
        result["analysis"] = strip_markers(full)

    return jsonify(result), 201


@app.route("/api/v1/files/<filename>", methods=["GET"])
@require_auth
def download_file(filename):
    """Download a file from the temp directory."""
    safe = secure_filename(filename)
    if not os.path.exists(os.path.join(TEMP_DIR, safe)):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(TEMP_DIR, safe, as_attachment=True)


@app.route("/api/v1/files/<filename>", methods=["DELETE"])
@require_auth
def delete_file(filename):
    """Delete a file from the temp directory."""
    safe = secure_filename(filename)
    filepath = os.path.join(TEMP_DIR, safe)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    os.remove(filepath)
    return jsonify({"message": f"Deleted {filename}"})


# ══════════════════════════════════════════════════════════════
# Agents
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/agents", methods=["GET"])
@require_auth
def list_agents():
    """List available agent profiles and the currently active one."""
    agents = friday.brain.list_agents()
    return jsonify({
        "agents": agents,
        "active": None,  # stateless — agent set per-request
    })


@app.route("/api/v1/agents/activate", methods=["POST"])
@require_auth
def activate_agent():
    """Activate an agent persona.

    Body: { "name": "agent_name" }
    """
    data = request.json or {}
    name = data.get("name", "")
    if not name:
        return jsonify({"error": "Agent name required"}), 400

    prompt = friday.brain.load_agent_prompt(name)
    if prompt is None:
        return jsonify({"error": f"Agent '{name}' not found"}), 404

    # Stateless: agent is set per-request via agent_name parameter
    return jsonify({"message": f"Agent '{name}' is available for next request", "agent": name})


@app.route("/api/v1/agents/deactivate", methods=["POST"])
@require_auth
def deactivate_agent():
    """Deactivate (clear) the active agent persona."""
    # Stateless: agent is set per-request
    return jsonify({"message": "Agent deactivated"})


# ══════════════════════════════════════════════════════════════
# Memory
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/memory/<key>", methods=["GET"])
@require_auth
def get_memory(key):
    """Retrieve a previously saved memory by key."""
    value = friday.db.get_memory(key)
    if value is None:
        return jsonify({"error": f"Key '{key}' not found"}), 404
    return jsonify({"key": key, "value": value})


@app.route("/api/v1/memory", methods=["POST"])
@require_auth
def set_memory():
    """Save a key-value pair to memory.

    Body: { "key": "...", "value": "..." }
    """
    data = request.json or {}
    key = data.get("key", "")
    value = data.get("value", "")
    if not key:
        return jsonify({"error": "Key required"}), 400
    friday.db.save_memory(key, value)
    return jsonify({"message": "Memory saved", "key": key})


# ══════════════════════════════════════════════════════════════
# System
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/system/status", methods=["GET"])
@require_auth
def system_status():
    """Health check with current configuration state."""
    valid, msg = Config.validate()
    return jsonify({
        "status": "online" if valid else "degraded",
        "name": Config.APP_NAME,
        "model": Config.PRIMARY_MODEL,
        "model_vision": Config.VISION_MODEL,
        "agent": None,  # stateless — agent set per-request
        "config_valid": valid,
        "config_message": msg,
        "supabase_connected": friday.executive.supabase.enabled,
        "mcp_servers": [getattr(c, "name", str(c)) for c in getattr(friday.executive.mcp, "clients", [])],
    })


@app.route("/api/v1/system/tools", methods=["GET"])
@require_auth
def list_tools():
    """List all available tools (built-in + MCP)."""
    builtin = sorted(friday.executive.tool_map.keys())
    mcp = sorted(friday.executive.mcp.tool_map.keys())
    return jsonify({
        "tools": sorted(set(builtin + mcp)),
        "builtin": builtin,
        "mcp": mcp,
    })


@app.route("/api/v1/system/tools/execute", methods=["POST"])
@require_auth
def execute_tool():
    """Execute a specific tool by name.

    Body: { "tool": "name", "args": {...} }
    """
    data = request.json or {}
    tool = data.get("tool", "")
    args = data.get("args")
    if not tool:
        return jsonify({"error": "Tool name required"}), 400
    result = friday.executive.handle_tool_call(tool, args)
    return jsonify({"tool": tool, "result": str(result)})


# ══════════════════════════════════════════════════════════════
# SaaS Auth
# ══════════════════════════════════════════════════════════════


@app.route("/api/v1/auth/register", methods=["POST"])
def auth_register():
    """Register a new user account.

    Body (JSON): { "email": "...", "password": "...", "name": "..." }
    """
    data = request.json or {}
    email = data.get("email", "")
    password = data.get("password", "")
    name = data.get("name", "")

    success, msg, result = saas.auth.register(email, password, name)
    status = 201 if success else 400
    resp = {"message": msg}
    if result:
        resp["data"] = result
    return jsonify(resp), status


@app.route("/api/v1/auth/login", methods=["POST"])
def auth_login():
    """Authenticate with email + password, receive JWT.

    Body (JSON): { "email": "...", "password": "..." }
    """
    data = request.json or {}
    email = data.get("email", "")
    password = data.get("password", "")

    success, msg, result = saas.auth.login(email, password)
    if not success:
        return jsonify({"error": msg}), 401
    return jsonify({"message": msg, "data": result})


@app.route("/api/v1/auth/refresh", methods=["POST"])
def auth_refresh():
    """Exchange a refresh token for a new JWT.

    Body (JSON): { "refresh_token": "..." }
    """
    data = request.json or {}
    token = data.get("refresh_token", "")
    if not token:
        return jsonify({"error": "refresh_token required"}), 400

    new_token = saas.auth.refresh_token(token)
    if not new_token:
        return jsonify({"error": "Invalid or expired refresh token"}), 401
    return jsonify({"token": new_token})


@app.route("/api/v1/auth/verify-email", methods=["POST"])
def auth_verify_email():
    """Verify email address with a token.

    Body (JSON): { "token": "..." }
    """
    data = request.json or {}
    token = data.get("token", "")
    if not token:
        return jsonify({"error": "token required"}), 400

    success, msg = saas.auth.verify_email(token)
    status = 200 if success else 400
    return jsonify({"message": msg}), status


@app.route("/api/v1/auth/reset-password", methods=["POST"])
def auth_reset_password():
    """Request a password reset token (sent to email).

    Body (JSON): { "email": "..." }
    """
    data = request.json or {}
    email = data.get("email", "")
    if not email:
        return jsonify({"error": "email required"}), 400

    token = saas.auth.generate_reset_token(email)
    # In production, send via email. Return token for development.
    return jsonify({"message": "If email exists, reset token sent", "token": token})


@app.route("/api/v1/auth/reset-password/confirm", methods=["POST"])
def auth_reset_password_confirm():
    """Reset password using a reset token.

    Body (JSON): { "token": "...", "new_password": "..." }
    """
    data = request.json or {}
    token = data.get("token", "")
    new_password = data.get("new_password", "")
    if not token or not new_password:
        return jsonify({"error": "token and new_password required"}), 400

    success, msg = saas.auth.reset_password(token, new_password)
    status = 200 if success else 400
    return jsonify({"message": msg}), status


@app.route("/api/v1/auth/profile", methods=["GET"])
@saas.gateway.require_jwt
def auth_profile(user_id, plan_limits, role):
    """Get the authenticated user's profile + subscription info."""
    profile = saas.auth.get_profile(user_id)
    if not profile:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"profile": profile})


# ══════════════════════════════════════════════════════════════
# SaaS Plans & Subscriptions
# ══════════════════════════════════════════════════════════════


@app.route("/api/v1/plans", methods=["GET"])
def list_plans():
    """List all available subscription plans with pricing."""
    plans = saas.list_plans()
    return jsonify({"plans": plans, "count": len(plans)})


@app.route("/api/v1/plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    """Get details for a specific plan."""
    plan = saas.get_plan(plan_id)
    if not plan:
        return jsonify({"error": f"Plan '{plan_id}' not found"}), 404
    return jsonify({"plan": plan})


@app.route("/api/v1/subscription", methods=["GET"])
@saas.gateway.require_jwt
def get_subscription(user_id, plan_limits, role):
    """Get the current user's subscription details."""
    sub = saas.db.get_subscription(user_id)
    if not sub:
        return jsonify({"plan_id": "free", "status": "active"})
    return jsonify({"subscription": sub})


@app.route("/api/v1/subscription/subscribe", methods=["POST"])
@saas.gateway.require_jwt
def subscribe(user_id, plan_limits, role):
    """Subscribe (or upgrade) to a plan.

    Body (JSON):
      plan_id:        str (required)
      billing_period: str ("monthly" | "yearly", default "monthly")
    """
    data = request.json or {}
    plan_id = data.get("plan_id", "")
    billing_period = data.get("billing_period", "monthly")

    if not plan_id:
        return jsonify({"error": "plan_id required"}), 400

    success, msg, result = saas.subscriptions.subscribe(
        user_id, plan_id, billing_period=billing_period,
    )
    status = 200 if success else 400
    resp = {"message": msg}
    if result:
        resp["data"] = result
    return jsonify(resp), status


@app.route("/api/v1/subscription/cancel", methods=["POST"])
@saas.gateway.require_jwt
def cancel_subscription(user_id, plan_limits, role):
    """Cancel the current subscription.

    Body (JSON): { "immediately": bool (default false) }
    """
    data = request.json or {}
    immediately = data.get("immediately", False)

    success, msg, result = saas.subscriptions.cancel(user_id, immediately=immediately)
    status = 200 if success else 400
    return jsonify({"message": msg}), status


@app.route("/api/v1/subscription/change", methods=["POST"])
@saas.gateway.require_jwt
def change_plan(user_id, plan_limits, role):
    """Change to a different plan.

    Body (JSON): { "plan_id": "...", "billing_period": "monthly|yearly" }
    """
    data = request.json or {}
    plan_id = data.get("plan_id", "")
    billing_period = data.get("billing_period")

    if not plan_id:
        return jsonify({"error": "plan_id required"}), 400

    success, msg, result = saas.subscriptions.change_plan(
        user_id, plan_id, billing_period=billing_period,
    )
    status = 200 if success else 400
    resp = {"message": msg}
    if result:
        resp["data"] = result
    return jsonify(resp), status


# ══════════════════════════════════════════════════════════════
# SaaS API Keys
# ══════════════════════════════════════════════════════════════


@app.route("/api/v1/keys", methods=["GET"])
@saas.gateway.require_jwt
def list_api_keys(user_id, plan_limits, role):
    """List all API keys for the authenticated user."""
    keys = saas.keys.list_keys(user_id)
    return jsonify({"keys": keys, "count": len(keys)})


@app.route("/api/v1/keys", methods=["POST"])
@saas.gateway.require_jwt
def create_api_key(user_id, plan_limits, role):
    """Create a new API key.

    Body (JSON): { "label": "optional label" }

    Returns the full key **once**. It will not be shown again.
    """
    data = request.json or {}
    label = data.get("label", "Default")

    # Check plan limit for max keys
    max_keys = plan_limits.get("max_api_keys", 1)
    current_count = saas.keys.get_key_count(user_id)
    if current_count >= max_keys:
        return jsonify({
            "error": f"Plan limit reached ({current_count}/{max_keys} API keys)",
        }), 429

    full_key, display = saas.keys.generate_key(user_id, label=label)
    return jsonify({
        "message": "API key created — save it now, it won't be shown again",
        "key": full_key,
        "data": display,
    }), 201


@app.route("/api/v1/keys/<int:key_id>", methods=["DELETE"])
@saas.gateway.require_jwt
def revoke_api_key(user_id, plan_limits, role, key_id):
    """Revoke (delete) an API key."""
    success = saas.keys.revoke_key(key_id, user_id)
    if not success:
        return jsonify({"error": "Key not found or already revoked"}), 404
    return jsonify({"message": "API key revoked"})


@app.route("/api/v1/keys/regenerate", methods=["POST"])
@saas.gateway.require_jwt
def regenerate_api_key(user_id, plan_limits, role):
    """Revoke an old key and create a new one.

    Body (JSON): { "key_id": int, "label": "optional new label" }
    """
    data = request.json or {}
    key_id = data.get("key_id")
    label = data.get("label")

    if not key_id:
        return jsonify({"error": "key_id required"}), 400

    full_key, display = saas.keys.regenerate_key(user_id, key_id, label=label)
    return jsonify({
        "message": "Key regenerated — save it now, it won't be shown again",
        "key": full_key,
        "data": display,
    })


# ══════════════════════════════════════════════════════════════
# SaaS Usage
# ══════════════════════════════════════════════════════════════


@app.route("/api/v1/usage", methods=["GET"])
@saas.gateway.require_jwt
def get_usage(user_id, plan_limits, role):
    """Get usage report for the authenticated user."""
    report = saas.usage.get_usage_report(user_id)
    return jsonify({
        "usage": report,
        "plan_limits": plan_limits,
    })


# ══════════════════════════════════════════════════════════════
# SaaS Admin
# ══════════════════════════════════════════════════════════════


@app.route("/api/v1/admin/users", methods=["GET"])
@saas.gateway.require_admin
def admin_list_users(user_id, plan_limits, role):
    """List all users (admin only)."""
    users = saas.db.get_all_users()
    # Strip sensitive fields
    for u in users:
        u.pop("password_hash", None)
        u.pop("verification_token", None)
        u.pop("reset_token", None)
        u.pop("reset_token_expires", None)
    return jsonify({"users": users, "count": len(users)})


@app.route("/api/v1/admin/stats", methods=["GET"])
@saas.gateway.require_admin
def admin_stats(user_id, plan_limits, role):
    """Get aggregate platform statistics (admin only)."""
    stats = saas.usage.get_overall_stats()
    return jsonify({"stats": stats})


@app.route("/api/v1/admin/audit-logs", methods=["GET"])
@saas.gateway.require_admin
def admin_audit_logs(user_id, plan_limits, role):
    """Get audit trail (admin only).

    Query params:
      limit: int (default 50)
      user_id: str (optional filter)
    """
    limit = request.args.get("limit", 50, type=int)
    filter_user = request.args.get("user_id")
    logs = saas.db.get_audit_logs(limit=limit, user_id=filter_user)
    return jsonify({"audit_logs": logs, "count": len(logs)})


# ══════════════════════════════════════════════════════════════
# Public API (no auth — for website embedding)
# ══════════════════════════════════════════════════════════════


@app.route("/api/v1/public/chat", methods=["POST"])
def public_chat():
    """Public chat endpoint (no auth, rate-limited).

    Request body (JSON): same as /api/v1/chat.
    """
    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"error": "Rate limit exceeded. Try again later."}), 429

    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    conversation_id = data.get("conversation_id")

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    # Per-IP isolation for anonymous users
    user_id = f"anon_{ip.replace('.', '_')}"

    try:
        full_response = friday.process_message(message, image_path=image_path, user_id=user_id, conversation_id=conversation_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    cleaned = strip_markers(full_response)
    return jsonify({
        "response": cleaned,
        "model": Config.PRIMARY_MODEL,
        "conversation_id": conversation_id,
    })


@app.route("/api/v1/public/chat/stream", methods=["POST"])
def public_chat_stream():
    """Public streaming chat endpoint (no auth, rate-limited)."""
    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"error": "Rate limit exceeded"}), 429

    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    conversation_id = data.get("conversation_id")

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    # Per-IP isolation for anonymous users
    user_id = f"anon_{ip.replace('.', '_')}"

    def generate():
        try:
            for chunk in friday.process_message_stream(message, image_path=image_path, user_id=user_id, conversation_id=conversation_id):
                cleaned = strip_markers(chunk)
                if cleaned:
                    yield f"data: {json.dumps({'text': cleaned})}\n\n"
            yield f"data: {json.dumps({'done': True, 'conversation_id': conversation_id})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


# ══════════════════════════════════════════════════════════════
# Conversations (CRUD for ChatGPT-style conversation management)
# ══════════════════════════════════════════════════════════════


@app.route("/api/v1/conversations", methods=["GET"])
@require_auth
def list_conversations():
    """List all conversations for the authenticated user."""
    return jsonify({"conversations": [], "count": 0})


@app.route("/api/v1/conversations", methods=["POST"])
@require_auth
def create_conversation():
    """Create a new conversation."""
    data = request.json or {}
    title = data.get("title", "New conversation")
    conv_id = str(uuid.uuid4())
    return jsonify({"conversation_id": conv_id, "title": title}), 201


@app.route("/api/v1/conversations/<conversation_id>", methods=["DELETE"])
@require_auth
def delete_conversation(conversation_id):
    """Delete a conversation."""
    return jsonify({"message": f"Conversation {conversation_id} deleted"})


@app.route("/api/v1/conversations/<conversation_id>", methods=["PATCH"])
@require_auth
def rename_conversation(conversation_id):
    """Rename a conversation."""
    data = request.json or {}
    title = data.get("title")
    if not title:
        return jsonify({"error": "title required"}), 400
    return jsonify({"conversation_id": conversation_id, "title": title})


# ══════════════════════════════════════════════════════════════
# Frontend-compatible API routes (for Friday Web/PWA — /api/*)
# ══════════════════════════════════════════════════════════════


@app.route("/api/chat", methods=["POST"])
@require_auth
def api_chat():
    """Frontend chat endpoint — returns frontend-compatible response format (reply, timestamp, conversation_id)."""
    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    agent = data.get("agent")
    conversation_id = data.get("conversation_id")

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    user_id = _get_user_id()
    logger.info(f"[api/chat] user_id={user_id}, conversation_id={conversation_id}, message_len={len(message)}")

    try:
        full_response = friday.process_message(
            message, image_path=image_path, user_id=user_id, conversation_id=conversation_id, agent_name=agent
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    cleaned = strip_markers(full_response)
    logger.info(f"[api/chat] response_len={len(cleaned)}, conversation_id={conversation_id}")

    return jsonify({
        "reply": cleaned,
        "timestamp": datetime.utcnow().isoformat(),
        "conversation_id": conversation_id,
    })


@app.route("/api/conversations", methods=["GET"])
@require_auth
def api_list_conversations():
    """Frontend: list conversations with nested response format."""
    return jsonify({"conversations": [], "count": 0})


@app.route("/api/conversations", methods=["POST"])
@require_auth
def api_create_conversation():
    """Frontend: create conversation with nested conversation object."""
    data = request.json or {}
    title = data.get("title", "New Chat")
    conv_id = str(uuid.uuid4())
    conv = {
        "id": conv_id,
        "title": title,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    return jsonify({"conversation": conv}), 201


@app.route("/api/conversations/<conversation_id>/messages", methods=["GET"])
@require_auth
def api_get_conversation_messages(conversation_id):
    """Frontend: get messages for a conversation."""
    return jsonify({"messages": [], "count": 0})


@app.route("/api/conversations/<conversation_id>", methods=["DELETE"])
@require_auth
def api_delete_conversation(conversation_id):
    """Frontend: delete a conversation."""
    return jsonify({"message": f"Conversation {conversation_id} deleted"})


@app.route("/api/conversations/<conversation_id>", methods=["PATCH"])
@require_auth
def api_rename_conversation(conversation_id):
    """Frontend: rename a conversation."""
    data = request.json or {}
    title = data.get("title")
    if not title:
        return jsonify({"error": "title required"}), 400
    return jsonify({"conversation_id": conversation_id, "title": title})


# ══════════════════════════════════════════════════════════════
# Websites (multi-tenant chatbot engine)
# ══════════════════════════════════════════════════════════════


@app.route("/api/v1/websites", methods=["GET"])
@require_auth
def list_websites():
    """List all registered websites."""
    sites = friday.tenants.list_websites()
    return jsonify({"websites": sites, "count": len(sites)})


@app.route("/api/v1/websites", methods=["POST"])
@require_auth
def create_website():
    """Register a new website/tenant.

    Body (JSON):
      slug:         str (required, URL-safe identifier)
      name:         str (required, display name)
      domain:       str (optional)
      business_info: dict (optional, for persona building)
      style:        dict (optional, chatbot styling)
      welcome_msg:  str (optional)
    """
    data = request.json or {}
    slug = data.get("slug", "").strip()
    name = data.get("name", "").strip()
    if not slug or not name:
        return jsonify({"error": "slug and name are required"}), 400

    website_id = friday.tenants.add_website(
        slug=slug,
        name=name,
        domain=data.get("domain"),
        business_info=data.get("business_info"),
        style=data.get("style"),
        welcome_message=data.get("welcome_msg"),
    )
    return jsonify({"message": f"Website '{slug}' created", "id": website_id}), 201


@app.route("/api/v1/websites/<slug>", methods=["GET"])
@require_auth
def get_website(slug):
    """Get website/tenant details by slug."""
    site = friday.tenants.get(slug)
    if not site:
        return jsonify({"error": f"Website '{slug}' not found"}), 404
    return jsonify({"website": site})


@app.route("/api/v1/websites/<slug>", methods=["PUT"])
@require_auth
def update_website(slug):
    """Update website/tenant configuration.

    Body (JSON): any subset of { name, domain, business_info, style, welcome_msg }
    """
    data = request.json or {}
    fields = {}
    for key in ("name", "domain", "business_info", "style", "welcome_msg"):
        if key in data:
            fields[key] = data[key]
    if not fields:
        return jsonify({"error": "No fields to update"}), 400

    friday.tenants.update_website(slug, **fields)
    return jsonify({"message": f"Website '{slug}' updated"})


@app.route("/api/v1/websites/<slug>", methods=["DELETE"])
@require_auth
def delete_website(slug):
    """Delete a website/tenant."""
    site = friday.tenants.get(slug)
    if not site:
        return jsonify({"error": f"Website '{slug}' not found"}), 404
    friday.tenants.delete_website(slug)
    return jsonify({"message": f"Website '{slug}' deleted"})


# ── Website chat ──


@app.route("/api/v1/websites/<slug>/chat", methods=["POST"])
@require_auth
def website_chat(slug):
    """Non-streaming chat with a website's chatbot persona.

    Body (JSON):
      message:    str (required unless image_path set)
      image_path: str (optional)
      session_id: str (optional, auto-generated if omitted)
    """
    site = friday.tenants.get(slug)
    if not site:
        return jsonify({"error": f"Website '{slug}' not found"}), 404

    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    session_id = data.get("session_id", uuid.uuid4().hex[:12])

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    try:
        response = friday.process_website_message(slug, message, session_id, image_path=image_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    cleaned = strip_markers(response)
    return jsonify({
        "response": cleaned,
        "session_id": session_id,
        "website": slug,
    })


@app.route("/api/v1/websites/<slug>/chat/stream", methods=["POST"])
@require_auth
def website_chat_stream(slug):
    """Streaming chat with a website's chatbot persona.

    Body (JSON): same as non-streaming website chat.
    Returns SSE events.
    """
    site = friday.tenants.get(slug)
    if not site:
        return jsonify({"error": f"Website '{slug}' not found"}), 404

    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    session_id = data.get("session_id", uuid.uuid4().hex[:12])

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    def generate():
        try:
            for chunk in friday.process_website_message_stream(slug, message, session_id, image_path=image_path):
                cleaned = strip_markers(chunk)
                if cleaned:
                    yield f"data: {json.dumps({'text': cleaned, 'session_id': session_id})}\n\n"
            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


# ── Leads ──


@app.route("/api/v1/websites/<slug>/leads", methods=["GET"])
@require_auth
def list_leads(slug):
    """List leads captured for a website.

    Query params:
      status: str (optional, filter by status)
    """
    site = friday.tenants.get(slug)
    if not site:
        return jsonify({"error": f"Website '{slug}' not found"}), 404

    status_filter = request.args.get("status")
    rows = friday.db.get_leads(website_id=site["id"], status=status_filter)
    leads = [
        {
            "id": r[0],
            "website_id": r[1],
            "name": r[2],
            "email": r[3],
            "phone": r[4],
            "message": r[5],
            "status": r[6],
            "metadata": r[7],
            "created_at": r[8],
        }
        for r in rows
    ]
    return jsonify({"leads": leads, "count": len(leads)})


@app.route("/api/v1/leads/<int:lead_id>/status", methods=["PUT"])
@require_auth
def update_lead_status(lead_id):
    """Update a lead's status.

    Body (JSON): { "status": "new" | "contacted" | "qualified" | "closed" }
    """
    data = request.json or {}
    status = data.get("status", "").strip()
    if not status:
        return jsonify({"error": "status required"}), 400

    friday.db.update_lead_status(lead_id, status)
    return jsonify({"message": f"Lead {lead_id} status updated to '{status}'"})


# ── Website conversations ──


@app.route("/api/v1/websites/<slug>/conversations/<session_id>", methods=["GET"])
@require_auth
def get_website_conversation(slug, session_id):
    """Retrieve a website's conversation session."""
    site = friday.tenants.get(slug)
    if not site:
        return jsonify({"error": f"Website '{slug}' not found"}), 404

    rows = friday.db.get_website_conversation(site["id"], session_id)
    conversation = [
        {"role": r[0], "message": r[1], "timestamp": r[2]}
        for r in rows
    ]
    return jsonify({
        "website": slug,
        "session_id": session_id,
        "conversation": conversation,
        "count": len(conversation),
    })


# ══════════════════════════════════════════════════════════════
# Legacy / convenience
# ══════════════════════════════════════════════════════════════

@app.route("/ask", methods=["POST"])
def ask_legacy():
    """Legacy alias — redirects to /api/v1/chat."""
    return chat()


@app.route("/status", methods=["GET"])
def status_legacy():
    """Legacy health check."""
    return system_status()


@app.route("/", methods=["GET"])
def index():
    """API documentation root."""
    return jsonify({
        "name": "Friday API",
        "version": "2.0.0",
        "endpoints": {
            "Chat": {
                "POST /api/v1/chat": "Send message, get full response",
                "POST /api/v1/chat/stream": "Stream response via SSE",
            },
            "History": {
                "GET /api/v1/history": "Get conversation history",
                "DELETE /api/v1/history": "Clear history",
            },
            "Files": {
                "GET /api/v1/files": "List uploaded files",
                "POST /api/v1/files/upload": "Upload a file",
                "GET /api/v1/files/<name>": "Download a file",
                "DELETE /api/v1/files/<name>": "Delete a file",
            },
            "Agents": {
                "GET /api/v1/agents": "List agents + active",
                "POST /api/v1/agents/activate": "Activate an agent",
                "POST /api/v1/agents/deactivate": "Deactivate agent",
            },
            "Memory": {
                "GET /api/v1/memory/<key>": "Get a memory value",
                "POST /api/v1/memory": "Save a memory key-value",
            },
            "System": {
                "GET /api/v1/system/status": "Health & config status",
                "GET /api/v1/system/tools": "List all tools",
                "POST /api/v1/system/tools/execute": "Execute a tool",
            },
            "Websites": {
                "GET /api/v1/websites": "List all websites",
                "POST /api/v1/websites": "Create a website",
                "GET /api/v1/websites/<slug>": "Get website details",
                "PUT /api/v1/websites/<slug>": "Update website",
                "DELETE /api/v1/websites/<slug>": "Delete website",
                "POST /api/v1/websites/<slug>/chat": "Website chatbot (non-streaming)",
                "POST /api/v1/websites/<slug>/chat/stream": "Website chatbot (SSE stream)",
            },
            "Leads": {
                "GET /api/v1/websites/<slug>/leads": "List leads for a website",
                "PUT /api/v1/leads/<id>/status": "Update lead status",
            },
            "Website Conversations": {
                "GET /api/v1/websites/<slug>/conversations/<session_id>": "Get website conversation",
            },
            "Public (no auth)": {
                "POST /api/v1/public/chat": "Public chat (rate-limited)",
                "POST /api/v1/public/chat/stream": "Public streaming chat",
            },
            "v3 Universal API": {
                "GET /api/v3/actions": "List all 45 available actions across 9 categories",
                "POST /api/v3/command": "Universal command — single endpoint for all actions",
                "POST /api/v3/command/stream": "Universal SSE streaming (chat:stream, websites:chat/stream)",
            },
        },
            "SaaS Auth": {
                "POST /api/v1/auth/register": "Register a new user",
                "POST /api/v1/auth/login": "Login, receive JWT",
                "POST /api/v1/auth/refresh": "Refresh JWT with refresh token",
                "POST /api/v1/auth/verify-email": "Verify email with token",
                "POST /api/v1/auth/reset-password": "Request password reset",
                "POST /api/v1/auth/reset-password/confirm": "Confirm password reset",
                "GET /api/v1/auth/profile": "Get profile (JWT required)",
            },
            "SaaS Plans & Subscriptions": {
                "GET /api/v1/plans": "List all plans",
                "GET /api/v1/plans/<id>": "Get plan details",
                "GET /api/v1/subscription": "Get my subscription (JWT)",
                "POST /api/v1/subscription/subscribe": "Subscribe to a plan (JWT)",
                "POST /api/v1/subscription/cancel": "Cancel subscription (JWT)",
                "POST /api/v1/subscription/change": "Change plan (JWT)",
            },
            "SaaS API Keys": {
                "GET /api/v1/keys": "List my API keys (JWT)",
                "POST /api/v1/keys": "Create API key (JWT)",
                "DELETE /api/v1/keys/<id>": "Revoke API key (JWT)",
                "POST /api/v1/keys/regenerate": "Regenerate API key (JWT)",
            },
            "SaaS Usage": {
                "GET /api/v1/usage": "Get usage report (JWT)",
            },
            "SaaS Admin": {
                "GET /api/v1/admin/users": "List all users (admin)",
                "GET /api/v1/admin/stats": "Platform stats (admin)",
                "GET /api/v1/admin/audit-logs": "Audit trail (admin)",
            },
            "SaaS v2 Chat": {
                "POST /api/v2/chat": "Gateway chat (API key auth)",
                "POST /api/v2/chat/stream": "Gateway streaming chat (API key auth)",
            },
            "SaaS v2 Chat (Telegram)": {
                "POST /api/v2/chat/telegram": "Gateway chat via Telegram bot (API key auth)",
            },
        "auth": "Bearer token in Authorization header (if FRIDAY_API_KEY is set); SaaS uses frd_live_ keys or JWT",
    })


# ══════════════════════════════════════════════════════════════
# Entrypoint
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Friday REST API")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", default=5000, type=int, help="Port to bind")
    parser.add_argument("--debug", action="store_true", default=False, help="Enable debug mode")
    parser.add_argument("--cert", default=None, help="Path to SSL certificate file (enables HTTPS)")
    parser.add_argument("--key", default=None, help="Path to SSL private key file")
    args = parser.parse_args()

    ssl_context = None
    if args.cert:
        if not args.key:
            print("[!] --cert provided without --key, using it as a combined cert+key file")
        ssl_context = (args.cert, args.key) if args.key else args.cert
        protocol = "https"
    else:
        protocol = "http"

    print(f"[*] Friday API v2 starting on {protocol}://{args.host}:{args.port}")
    if API_KEY:
        print("[*] API key authentication is ENABLED")
    else:
        print("[*] API key authentication is DISABLED (set FRIDAY_API_KEY in .env to enable)")

    app.run(host=args.host, port=args.port, debug=args.debug, ssl_context=ssl_context)
