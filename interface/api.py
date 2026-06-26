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
from functools import wraps
from datetime import datetime

# Ensure project root is on sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from core.friday import FridayCore
from core.config import Config

load_dotenv()

app = Flask(__name__)
friday = FridayCore()

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
      message:    str (required unless image_path set)
      image_path: str (optional, path to an image)
      agent:      str (optional, activate an agent before responding)

    Returns: { response, model, metadata, agent }
    """
    data = request.json or {}
    message = data.get("message", "")
    image_path = data.get("image_path")
    agent = data.get("agent")

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    # Temporarily activate agent if specified
    previous_agent = friday._active_agent
    if agent:
        friday._active_agent = agent

    try:
        full_response, metadata = friday.process_message(message, image_path=image_path)
    finally:
        if agent:
            friday._active_agent = previous_agent

    cleaned = strip_markers(full_response)

    return jsonify({
        "response": cleaned,
        "model": Config.PRIMARY_MODEL,
        "metadata": metadata,
        "agent": friday._active_agent
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

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    previous_agent = friday._active_agent
    if agent:
        friday._active_agent = agent

    def generate():
        try:
            for chunk in friday.process_message_stream(message, image_path=image_path):
                cleaned = strip_markers(chunk)
                if cleaned:
                    yield f"data: {json.dumps({'text': cleaned})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        finally:
            if agent:
                friday._active_agent = previous_agent

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
      limit: int (default 50)
    """
    limit = request.args.get("limit", 50, type=int)
    rows = friday.db.get_conversation_history(limit=limit)
    # Convert to list of dicts for easier consumption
    history = [
        {"role": r[0], "message": r[1], "timestamp": r[2]}
        for r in rows
    ]
    return jsonify({"history": history, "count": len(history)})


@app.route("/api/v1/history", methods=["DELETE"])
@require_auth
def clear_history():
    """Delete all conversation history."""
    friday.clear_history()
    return jsonify({"message": "Conversation history cleared"})


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
        "active": friday._active_agent,
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

    friday._active_agent = name
    return jsonify({"message": f"Agent '{name}' activated", "agent": name})


@app.route("/api/v1/agents/deactivate", methods=["POST"])
@require_auth
def deactivate_agent():
    """Deactivate (clear) the active agent persona."""
    friday._active_agent = None
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
        "agent": friday._active_agent,
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

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    try:
        full_response, metadata = friday.process_message(message, image_path=image_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    cleaned = strip_markers(full_response)
    return jsonify({
        "response": cleaned,
        "model": Config.PRIMARY_MODEL,
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

    if not message and not image_path:
        return jsonify({"error": "message or image_path required"}), 400

    def generate():
        try:
            for chunk in friday.process_message_stream(message, image_path=image_path):
                cleaned = strip_markers(chunk)
                if cleaned:
                    yield f"data: {json.dumps({'text': cleaned})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
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
            "Public (no auth)": {
                "POST /api/v1/public/chat": "Public chat (rate-limited)",
                "POST /api/v1/public/chat/stream": "Public streaming chat",
            },
        },
        "auth": "Bearer token in Authorization header (if FRIDAY_API_KEY is set)",
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
