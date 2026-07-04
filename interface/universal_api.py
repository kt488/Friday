"""
Friday Universal API v3
=======================
Single-command interface to control every aspect of Friday —
chat, history, files, agents, memory, system, websites, leads, SaaS, and admin.

All actions go through ``POST /api/v3/command`` with a structured payload::

    {
      "action": "<category:operation>",
      "params": { ... },
      "id": "optional-client-request-id"
    }

Auth: ``Authorization: Bearer <frd_live_xxx>`` (API key) **or** JWT.
"""

import json
import os
import time
import uuid
from functools import wraps

from flask import Blueprint, request, jsonify, send_from_directory, Response, stream_with_context
from werkzeug.utils import secure_filename

from core.friday import FridayCore
from core.config import Config
from core.saas import SaaSService

bp = Blueprint("universal_api", __name__, url_prefix="/api/v3")

TEMP_DIR = Config.TEMP_DIR

# ── Helpers ──


def _strip_markers(text):
    """Remove internal tool/file markers from response text."""
    import re
    pattern = re.compile(
        r'(?:\[TOOL:|\*\*TOOL:).*?(?:\]|\*\*)|'
        r'(?:\[SEND_FILE:|\*\*SEND_FILE:).*?(?:\]|\*\*)|'
        r'(?:\[SEND_FILE_NOW:|\*\*SEND_FILE_NOW:).*?(?:\]|\*\*)|'
        r'(?:\[Executed|\*\*\[?Executed).*?(?:\]|\*\*)',
        flags=re.DOTALL
    )
    return pattern.sub('', text).strip()


def ok(data=None, request_id=None):
    """Standard success response."""
    resp = {"success": True}
    if data is not None:
        resp["data"] = data
    if request_id:
        resp["id"] = request_id
    return jsonify(resp)


def fail(error, status=400, request_id=None):
    """Standard error response."""
    resp = {"success": False, "error": error}
    if request_id:
        resp["id"] = request_id
    return jsonify(resp), status


# ── Gateway auth wrapper ──

def _resolve_auth():
    """Try API key auth first, fall back to JWT.

    Returns (user_id, plan_limits, role) or None.
    """
    from core.saas import SaaSService
    saas = SaaSService()

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        # Try API key first
        if token.startswith("frd_live_"):
            key_record = saas.keys.validate_key(token)
            if key_record:
                user_id = key_record["user_id"]
                plan_limits = saas.subscriptions.get_user_limits(user_id)
                return user_id, plan_limits, "user"
        # Try JWT
        auth_result = saas.auth.authenticate_request(token)
        if auth_result:
            user_id, role = auth_result
            plan_limits = saas.subscriptions.get_user_limits(user_id)
            return user_id, plan_limits, role
    return None


def require_auth(f):
    """Decorator that injects user auth context or returns 401."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        ctx = _resolve_auth()
        if not ctx:
            return fail("Unauthorized — provide a valid API key or JWT", status=401)
        kwargs["_user_id"] = ctx[0]
        kwargs["_plan_limits"] = ctx[1]
        kwargs["_role"] = ctx[2]
        return f(*args, **kwargs)
    return wrapper


def _get_friday():
    """Lazy access to FridayCore (singleton-like via Flask app context)."""
    from flask import current_app
    if not hasattr(current_app, "_friday"):
        current_app._friday = FridayCore()
    return current_app._friday


def _get_saas():
    """Lazy access to SaaSService."""
    from flask import current_app
    if not hasattr(current_app, "_saas"):
        current_app._saas = SaaSService()
    return current_app._saas


# ══════════════════════════════════════════════════════════════
# Command dispatcher
# ══════════════════════════════════════════════════════════════


def _dispatch(action, params, user_id=None, plan_limits=None, role=None):
    """Route an action string to its handler.

    Returns (data_dict, status_code_or_None).
    """
    friday = _get_friday()
    saas = _get_saas()

    # ── Chat ──────────────────────────────────────────────

    if action == "chat:message":
        message = params.get("message", "")
        image_path = params.get("image_path")
        agent = params.get("agent")

        if not message and not image_path:
            return {"error": "message or image_path required"}, 400

        prev = friday._active_agent
        if agent:
            friday._active_agent = agent
        try:
            resp, metadata = friday.process_message(message, image_path=image_path)
        finally:
            if agent:
                friday._active_agent = prev

        return {
            "response": _strip_markers(resp),
            "model": Config.PRIMARY_MODEL,
            "metadata": metadata,
            "agent": friday._active_agent,
        }, None

    if action == "chat:stream":
        raise NotImplementedError("Use POST /api/v3/command/stream for streaming")

    if action == "chat:agent/set":
        name = params.get("name", "")
        if not name:
            return {"error": "agent name required"}, 400
        prompt = friday.brain.load_agent_prompt(name)
        if prompt is None:
            return {"error": f"Agent '{name}' not found"}, 404
        friday._active_agent = name
        return {"agent": name, "message": f"Agent '{name}' activated"}, None

    if action == "chat:agent/get":
        return {"agent": friday._active_agent}, None

    if action == "chat:agent/clear":
        friday._active_agent = None
        return {"agent": None, "message": "Agent deactivated"}, None

    # ── History ───────────────────────────────────────────

    if action == "history:list":
        limit = params.get("limit", 50)
        rows = friday.db.get_conversation_history(limit=limit)
        history = [
            {"role": r["role"], "message": r["message"], "timestamp": r["timestamp"]}
            for r in rows
        ]
        return {"history": history, "count": len(history)}, None

    if action == "history:clear":
        friday.clear_history()
        return {"message": "Conversation history cleared"}, None

    # ── Files ─────────────────────────────────────────────

    if action == "files:list":
        files = []
        for name in os.listdir(TEMP_DIR):
            fp = os.path.join(TEMP_DIR, name)
            if os.path.isfile(fp):
                stat = os.stat(fp)
                files.append({
                    "name": name,
                    "size": stat.st_size,
                    "modified": time.strftime(
                        "%Y-%m-%dT%H:%M:%S", time.gmtime(stat.st_mtime)
                    ),
                })
        return {"files": files, "count": len(files)}, None

    if action == "files:read":
        name = params.get("name", "")
        safe = secure_filename(name)
        fp = os.path.join(TEMP_DIR, safe)
        if not os.path.exists(fp):
            return {"error": f"File '{name}' not found"}, 404
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return {"name": name, "content": content, "size": len(content)}, None
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}, 500

    if action == "files:delete":
        name = params.get("name", "")
        safe = secure_filename(name)
        fp = os.path.join(TEMP_DIR, safe)
        if not os.path.exists(fp):
            return {"error": f"File '{name}' not found"}, 404
        os.remove(fp)
        return {"message": f"Deleted {name}"}, None

    # ── Agents ────────────────────────────────────────────

    if action == "agents:list":
        agents = friday.brain.list_agents()
        return {"agents": agents, "active": friday._active_agent}, None

    if action == "agents:activate":
        name = params.get("name", "")
        if not name:
            return {"error": "Agent name required"}, 400
        prompt = friday.brain.load_agent_prompt(name)
        if prompt is None:
            return {"error": f"Agent '{name}' not found"}, 404
        friday._active_agent = name
        return {"message": f"Agent '{name}' activated", "agent": name}, None

    if action == "agents:deactivate":
        friday._active_agent = None
        return {"message": "Agent deactivated"}, None

    # ── Memory ────────────────────────────────────────────

    if action == "memory:get":
        key = params.get("key", "")
        value = friday.db.get_memory(key)
        if value is None:
            return {"error": f"Key '{key}' not found"}, 404
        return {"key": key, "value": value}, None

    if action == "memory:set":
        key = params.get("key", "")
        value = params.get("value", "")
        if not key:
            return {"error": "Key required"}, 400
        friday.db.save_memory(key, value)
        return {"message": "Memory saved", "key": key}, None

    # ── System ────────────────────────────────────────────

    if action == "system:status":
        valid, msg = Config.validate()
        return {
            "status": "online" if valid else "degraded",
            "name": Config.APP_NAME,
            "model": Config.PRIMARY_MODEL,
            "model_vision": Config.VISION_MODEL,
            "agent": friday._active_agent,
            "config_valid": valid,
            "config_message": msg,
            "supabase_connected": friday.executive.supabase.enabled,
            "mcp_servers": [
                getattr(c, "name", str(c))
                for c in getattr(friday.executive.mcp, "clients", [])
            ],
        }, None

    if action == "system:tools":
        builtin = sorted(friday.executive.tool_map.keys())
        mcp = sorted(friday.executive.mcp.tool_map.keys())
        return {"tools": sorted(set(builtin + mcp)), "builtin": builtin, "mcp": mcp}, None

    if action == "system:tool/execute":
        tool = params.get("tool", "")
        args = params.get("args")
        if not tool:
            return {"error": "Tool name required"}, 400
        result = friday.executive.handle_tool_call(tool, args)
        return {"tool": tool, "result": str(result)}, None

    # ── Websites ──────────────────────────────────────────

    if action == "websites:list":
        sites = friday.tenants.list_all()
        return {"websites": sites, "count": len(sites)}, None

    if action == "websites:create":
        slug = params.get("slug", "").strip()
        name = params.get("name", "").strip()
        if not slug or not name:
            return {"error": "slug and name are required"}, 400
        wid = friday.tenants.register(
            slug=slug,
            name=name,
            domain=params.get("domain"),
            business_info=params.get("business_info"),
            style=params.get("style"),
            welcome_message=params.get("welcome_msg"),
        )
        if not wid:
            return {"error": f"Failed to create website '{slug}'"}, 400
        return {"message": f"Website '{slug}' created", "id": wid}, 201

    if action == "websites:get":
        slug = params.get("slug", "")
        site = friday.tenants.get(slug)
        if not site:
            return {"error": f"Website '{slug}' not found"}, 404
        return {"website": site}, None

    if action == "websites:update":
        slug = params.get("slug", "")
        site = friday.tenants.get(slug)
        if not site:
            return {"error": f"Website '{slug}' not found"}, 404
        fields = {}
        for key in ("name", "domain", "business_info", "style", "welcome_msg"):
            if key in params:
                fields[key] = params[key]
        if not fields:
            return {"error": "No fields to update"}, 400
        friday.tenants.update(slug, **fields)
        return {"message": f"Website '{slug}' updated"}, None

    if action == "websites:delete":
        slug = params.get("slug", "")
        if not friday.tenants.get(slug):
            return {"error": f"Website '{slug}' not found"}, 404
        friday.tenants.delete(slug)
        return {"message": f"Website '{slug}' deleted"}, None

    if action == "websites:chat":
        slug = params.get("slug", "")
        message = params.get("message", "")
        image_path = params.get("image_path")
        session_id = params.get("session_id", uuid.uuid4().hex[:12])

        site = friday.tenants.get(slug)
        if not site:
            return {"error": f"Website '{slug}' not found"}, 404
        if not message and not image_path:
            return {"error": "message or image_path required"}, 400

        try:
            response = friday.process_website_message(
                slug, message, session_id, image_path=image_path
            )
        except Exception as e:
            return {"error": str(e)}, 500

        return {
            "response": _strip_markers(response),
            "session_id": session_id,
            "website": slug,
        }, None

    if action == "websites:chat/stream":
        raise NotImplementedError("Use POST /api/v3/command/stream for streaming")

    # ── Leads ─────────────────────────────────────────────

    if action == "leads:list":
        slug = params.get("slug", "")
        site = friday.tenants.get(slug)
        if not site:
            return {"error": f"Website '{slug}' not found"}, 404
        status_filter = params.get("status")
        rows = friday.db.get_leads(website_id=site["id"], status=status_filter)
        leads = [
            {
                "id": r["id"],
                "website_id": r["website_id"],
                "name": r["name"],
                "email": r["email"],
                "phone": r["phone"],
                "message": r["message"],
                "status": r["status"],
                "metadata": r.get("metadata", {}),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return {"leads": leads, "count": len(leads)}, None

    if action == "leads:update_status":
        lead_id = params.get("lead_id")
        status = params.get("status", "").strip()
        if not lead_id or not status:
            return {"error": "lead_id and status required"}, 400
        success = friday.db.update_lead_status(int(lead_id), status)
        if not success:
            return {"error": "Lead not found"}, 404
        return {"message": f"Lead {lead_id} status updated to '{status}'"}, None

    # ── SaaS Auth ─────────────────────────────────────────

    if action == "saas:plans/list":
        plans = saas.list_plans()
        return {"plans": plans, "count": len(plans)}, None

    if action == "saas:plans/get":
        plan_id = params.get("plan_id", "")
        plan = saas.get_plan(plan_id)
        if not plan:
            return {"error": f"Plan '{plan_id}' not found"}, 404
        return {"plan": plan}, None

    if action == "saas:auth/register":
        email = params.get("email", "")
        password = params.get("password", "")
        name = params.get("name", "")
        success, msg, result = saas.auth.register(email, password, name)
        status = 201 if success else 400
        resp = {"message": msg}
        if result:
            resp["data"] = result
        return resp, status

    if action == "saas:auth/login":
        email = params.get("email", "")
        password = params.get("password", "")
        success, msg, result = saas.auth.login(email, password)
        if not success:
            return {"error": msg}, 401
        return {"message": msg, "data": result}, None

    if action == "saas:auth/profile":
        if not user_id:
            return {"error": "Authentication required"}, 401
        profile = saas.auth.get_profile(user_id)
        if not profile:
            return {"error": "User not found"}, 404
        return {"profile": profile}, None

    # ── SaaS Subscription ─────────────────────────────────

    if action == "saas:subscription/get":
        if not user_id:
            return {"error": "Authentication required"}, 401
        sub = saas.db.get_subscription(user_id)
        if not sub:
            return {"plan_id": "free", "status": "active"}, None
        return {"subscription": sub}, None

    if action == "saas:subscription/subscribe":
        if not user_id:
            return {"error": "Authentication required"}, 401
        plan_id = params.get("plan_id", "")
        billing_period = params.get("billing_period", "monthly")
        if not plan_id:
            return {"error": "plan_id required"}, 400
        success, msg, result = saas.subscriptions.subscribe(
            user_id, plan_id, billing_period=billing_period,
        )
        status = 200 if success else 400
        resp = {"message": msg}
        if result:
            resp["data"] = result
        return resp, status

    if action == "saas:subscription/cancel":
        if not user_id:
            return {"error": "Authentication required"}, 401
        immediately = params.get("immediately", False)
        success, msg, result = saas.subscriptions.cancel(user_id, immediately=immediately)
        status = 200 if success else 400
        return {"message": msg}, status

    if action == "saas:subscription/change":
        if not user_id:
            return {"error": "Authentication required"}, 401
        plan_id = params.get("plan_id", "")
        billing_period = params.get("billing_period")
        if not plan_id:
            return {"error": "plan_id required"}, 400
        success, msg, result = saas.subscriptions.change_plan(
            user_id, plan_id, billing_period=billing_period,
        )
        status = 200 if success else 400
        resp = {"message": msg}
        if result:
            resp["data"] = result
        return resp, status

    # ── SaaS API Keys ─────────────────────────────────────

    if action == "saas:keys/list":
        if not user_id:
            return {"error": "Authentication required"}, 401
        keys = saas.keys.list_keys(user_id)
        return {"keys": keys, "count": len(keys)}, None

    if action == "saas:keys/create":
        if not user_id:
            return {"error": "Authentication required"}, 401
        if role != "admin":
            return {"error": "Admin access required"}, 403
        label = params.get("label", "Default")
        max_keys = plan_limits.get("max_api_keys", 1) if plan_limits else 1
        current_count = saas.keys.get_key_count(user_id)
        if current_count >= max_keys:
            return {
                "error": f"Plan limit reached ({current_count}/{max_keys} API keys)",
            }, 429
        full_key, display = saas.keys.generate_key(user_id, label=label)
        return {
            "message": "API key created — save it now, it won't be shown again",
            "key": full_key,
            "data": display,
        }, 201

    if action == "saas:keys/revoke":
        if not user_id:
            return {"error": "Authentication required"}, 401
        key_id = params.get("key_id")
        if not key_id:
            return {"error": "key_id required"}, 400
        success = saas.keys.revoke_key(int(key_id), user_id)
        if not success:
            return {"error": "Key not found or already revoked"}, 404
        return {"message": "API key revoked"}, None

    if action == "saas:keys/regenerate":
        if not user_id:
            return {"error": "Authentication required"}, 401
        key_id = params.get("key_id")
        label = params.get("label")
        if not key_id:
            return {"error": "key_id required"}, 400
        full_key, display = saas.keys.regenerate_key(user_id, int(key_id), label=label)
        return {
            "message": "Key regenerated — save it now, it won't be shown again",
            "key": full_key,
            "data": display,
        }, None

    # ── SaaS Usage ────────────────────────────────────────

    if action == "saas:usage/get":
        if not user_id:
            return {"error": "Authentication required"}, 401
        report = saas.usage.get_usage_report(user_id)
        return {"usage": report, "plan_limits": plan_limits}, None

    # ── SaaS Connections ────────────────────────────────────

    if action == "saas:connections/providers":
        categories = saas.connections.get_categories()
        return {"categories": categories}, None

    if action == "saas:connections/list":
        if not user_id:
            return {"error": "Authentication required"}, 401
        service = params.get("service")
        connections = saas.connections.list_connections(user_id, service=service)
        return {"connections": connections, "count": len(connections)}, None

    if action == "saas:connections/connect":
        if not user_id:
            return {"error": "Authentication required"}, 401
        service = params.get("service", "")
        redirect_uri = params.get("redirect_uri", "")
        sub_services = params.get("sub_services")
        if not service or not redirect_uri:
            return {"error": "service and redirect_uri required"}, 400
        plan = (plan_limits or {}).get("plan_id", "free")
        under, current, limit = saas.connections.check_connection_limit(user_id, plan)
        if not under:
            return {"error": f"Connection limit reached ({current}/{limit})"}, 429
        try:
            auth_url, state = saas.connections.get_authorization_url(
                user_id, service, redirect_uri, sub_services=sub_services,
            )
            return {"authorization_url": auth_url, "state": state, "service": service}, None
        except ValueError as e:
            return {"error": str(e)}, 400

    if action == "saas:connections/callback":
        if not user_id:
            return {"error": "Authentication required"}, 401
        service = params.get("service", "")
        code = params.get("code", "")
        state = params.get("state", "")
        redirect_uri = params.get("redirect_uri", "")
        if not service or not code or not state:
            return {"error": "service, code, and state required"}, 400
        success, msg, data = saas.connections.exchange_code_with_state(
            user_id, service, code, state, redirect_uri,
        )
        if not success:
            return {"error": msg}, 400
        return {"message": msg, "data": data}, None

    if action == "saas:connections/disconnect":
        if not user_id:
            return {"error": "Authentication required"}, 401
        connection_id = params.get("connection_id")
        if not connection_id:
            return {"error": "connection_id required"}, 400
        success = saas.connections.delete_connection(int(connection_id), user_id)
        if not success:
            return {"error": "Connection not found"}, 404
        return {"message": "Connection deleted"}, None

    if action == "saas:connections/refresh":
        if not user_id:
            return {"error": "Authentication required"}, 401
        connection_id = params.get("connection_id")
        if not connection_id:
            return {"error": "connection_id required"}, 400
        success, msg = saas.connections.refresh_expired_token(int(connection_id), user_id)
        if not success:
            return {"error": msg}, 400
        return {"message": msg}, None

    # ── Admin ─────────────────────────────────────────────

    if action == "admin:users":
        if role != "admin":
            return {"error": "Admin access required"}, 403
        users = saas.db.get_all_users()
        for u in users:
            u.pop("password_hash", None)
            u.pop("verification_token", None)
            u.pop("reset_token", None)
            u.pop("reset_token_expires", None)
        return {"users": users, "count": len(users)}, None

    if action == "admin:stats":
        if role != "admin":
            return {"error": "Admin access required"}, 403
        stats = saas.usage.get_overall_stats()
        return {"stats": stats}, None

    if action == "admin:audit_logs":
        if role != "admin":
            return {"error": "Admin access required"}, 403
        limit = params.get("limit", 50)
        filter_user = params.get("user_id")
        logs = saas.db.get_audit_logs(limit=limit, user_id=filter_user)
        return {"audit_logs": logs, "count": len(logs)}, None

    # ── Unknown action ────────────────────────────────────

    return {"error": f"Unknown action '{action}'"}, 404


# ══════════════════════════════════════════════════════════════
# Public dispatch — no auth required
# ══════════════════════════════════════════════════════════════


def _dispatch_public(action, params):
    """Handle actions that don't require authentication (admin bootstrap/login)."""
    saas = _get_saas()

    if action == "admin:setup-password":
        password = params.get("password", "")
        if len(password) < 8:
            return {"error": "Password must be at least 8 characters"}, 400

        existing = saas.db.get_user_by_email("admin@friday.local")
        if existing and existing.get("password_hash"):
            return {"error": "Admin password already set"}, 400

        pw_hash = saas.auth.hash_password(password)
        if existing:
            saas.db.update_user(existing["id"], password_hash=pw_hash)
            return {"message": "Admin password updated"}, None
        else:
            user_id = saas.db.create_user("admin@friday.local", pw_hash, "Admin")
            saas.db.update_user(user_id, role="admin")
            return {"message": "Admin user created with password set", "user_id": user_id}, 201

    if action == "admin:login":
        password = params.get("password", "")
        email = params.get("email", "admin@friday.local")

        user = saas.db.get_user_by_email(email)
        if not user or user.get("role") != "admin":
            return {"error": "Invalid credentials"}, 401
        if not saas.auth.verify_password(password, user["password_hash"]):
            return {"error": "Invalid credentials"}, 401

        token = saas.auth.generate_token(user["id"], "admin")
        return {
            "message": "Admin login successful",
            "token": token,
            "user_id": user["id"],
            "role": "admin",
        }, None

    return {"error": f"Unknown public action '{action}'"}, 404


# ══════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════


@bp.route("/command", methods=["POST"])
@require_auth
def command(_user_id, _plan_limits, _role):
    """Universal command endpoint.

    Body (JSON)::

        {
          "action": "<category:operation>",
          "params": { ... },
          "id": "optional-request-id"
        }

    Returns::

        { "success": true, "data": { ... }, "id": "..." }
        { "success": false, "error": "...", "id": "..." }
    """
    data = request.json or {}
    action = data.get("action", "")
    params = data.get("params", {})
    req_id = data.get("id")

    if not action:
        return fail("action is required", status=400, request_id=req_id)

    try:
        result, status = _dispatch(
            action, params,
            user_id=_user_id, plan_limits=_plan_limits, role=_role,
        )
    except NotImplementedError:
        return fail(
            "This action requires POST /api/v3/command/stream for SSE",
            status=400,
            request_id=req_id,
        )
    except Exception as e:
        return fail(str(e), status=500, request_id=req_id)

    if status and status >= 400:
        return fail(result.get("error", "Unknown error"), status=status, request_id=req_id)

    return ok(data=result, request_id=req_id)


@bp.route("/public", methods=["POST"])
def public():
    """Public endpoint (no auth required) for admin bootstrap/login.

    Body (JSON)::

        {
          "action": "admin:setup-password",
          "params": { "password": "..." }
        }

    or::

        {
          "action": "admin:login",
          "params": { "password": "..." }
        }
    """
    data = request.json or {}
    action = data.get("action", "")
    params = data.get("params", {})
    req_id = data.get("id")

    if not action:
        return fail("action is required", status=400, request_id=req_id)

    try:
        result, status = _dispatch_public(action, params)
    except Exception as e:
        return fail(str(e), status=500, request_id=req_id)

    if status and status >= 400:
        return fail(result.get("error", "Unknown error"), status=status, request_id=req_id)

    return ok(data=result, request_id=req_id)


@bp.route("/command/stream", methods=["POST"])
@require_auth
def command_stream(_user_id, _plan_limits, _role):
    """Streaming variant of the universal command endpoint.

    Currently supports:
      - ``chat:message``  → SSE stream of response chunks
      - ``websites:chat`` → SSE stream of website chatbot chunks

    Body: same as ``POST /command``.
    Response: ``text/event-stream``.
    """
    data = request.json or {}
    action = data.get("action", "")
    params = data.get("params", {})
    req_id = data.get("id")

    if not action:
        return fail("action is required", status=400, request_id=req_id)

    friday = _get_friday()

    def generate():
        # Send start event
        yield f"data: {json.dumps({'event': 'start', 'action': action})}\n\n"

        try:
            if action == "chat:stream":
                message = params.get("message", "")
                image_path = params.get("image_path")
                agent = params.get("agent")

                if not message and not image_path:
                    yield f"data: {json.dumps({'event': 'error', 'error': 'message or image_path required'})}\n\n"
                    return

                prev = friday._active_agent
                if agent:
                    friday._active_agent = agent
                try:
                    for chunk in friday.process_message_stream(message, image_path=image_path):
                        cleaned = _strip_markers(chunk)
                        if cleaned:
                            yield f"data: {json.dumps({'event': 'chunk', 'text': cleaned})}\n\n"
                finally:
                    if agent:
                        friday._active_agent = prev

            elif action == "websites:chat/stream":
                slug = params.get("slug", "")
                message = params.get("message", "")
                image_path = params.get("image_path")
                session_id = params.get("session_id", uuid.uuid4().hex[:12])

                site = friday.tenants.get(slug)
                if not site:
                    yield f"data: {json.dumps({'event': 'error', 'error': f'Website {slug!r} not found'})}\n\n"
                    return
                if not message and not image_path:
                    yield f"data: {json.dumps({'event': 'error', 'error': 'message or image_path required'})}\n\n"
                    return

                for chunk in friday.process_website_message_stream(
                    slug, message, session_id, image_path=image_path,
                ):
                    cleaned = _strip_markers(chunk)
                    if cleaned:
                        yield f"data: {json.dumps({'event': 'chunk', 'text': cleaned, 'session_id': session_id})}\n\n"
            else:
                yield f"data: {json.dumps({'event': 'error', 'error': f'Action {action!r} does not support streaming'})}\n\n"
                return

        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'error': str(e)})}\n\n"
            return

        yield f"data: {json.dumps({'event': 'done'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@bp.route("/actions", methods=["GET"])
@require_auth
def list_actions(_user_id, _plan_limits, _role):
    """List all available actions with descriptions."""
    catalog = {
        "chat:message": "Send a message and get a full response",
        "chat:stream": "Stream a chat response via SSE",
        "chat:agent/set": "Set the active agent persona",
        "chat:agent/get": "Get the currently active agent",
        "chat:agent/clear": "Deactivate the current agent",
        "history:list": "Get conversation history",
        "history:clear": "Clear all conversation history",
        "files:list": "List uploaded files in temp directory",
        "files:read": "Read a file's content",
        "files:delete": "Delete a file",
        "agents:list": "List available agent profiles",
        "agents:activate": "Activate an agent persona",
        "agents:deactivate": "Deactivate the active agent",
        "memory:get": "Retrieve a saved memory value",
        "memory:set": "Save a key-value pair to memory",
        "system:status": "Get system health and configuration status",
        "system:tools": "List all available tools (built-in + MCP)",
        "system:tool/execute": "Execute a specific tool by name",
        "websites:list": "List all registered websites",
        "websites:create": "Register a new website/tenant",
        "websites:get": "Get website details by slug",
        "websites:update": "Update website configuration",
        "websites:delete": "Delete a website",
        "websites:chat": "Chat with a website's chatbot persona",
        "websites:chat/stream": "Streaming website chatbot chat",
        "leads:list": "List leads for a website",
        "leads:update_status": "Update a lead's status",
        "saas:plans/list": "List all subscription plans",
        "saas:plans/get": "Get a specific plan's details",
        "saas:auth/register": "Register a new user account",
        "saas:auth/login": "Authenticate and receive JWT",
        "saas:auth/profile": "Get the authenticated user's profile",
        "saas:subscription/get": "Get current subscription details",
        "saas:subscription/subscribe": "Subscribe to a plan",
        "saas:subscription/cancel": "Cancel subscription",
        "saas:subscription/change": "Change to a different plan",
        "saas:keys/list": "List API keys for the user",
        "saas:keys/create": "Create a new API key",
        "saas:keys/revoke": "Revoke an API key",
        "saas:keys/regenerate": "Regenerate an API key",
        "saas:usage/get": "Get usage report for the user",
        "saas:connections/providers": "List all available connection providers and categories",
        "saas:connections/list": "List the user's connected services",
        "saas:connections/connect": "Get an OAuth authorization URL for a service",
        "saas:connections/callback": "Handle OAuth callback and complete the connection",
        "saas:connections/disconnect": "Remove a service connection",
        "saas:connections/refresh": "Refresh an expired OAuth token",
        "admin:users": "List all users (admin only)",
        "admin:stats": "Get aggregate platform statistics (admin only)",
        "admin:audit_logs": "Get audit trail (admin only)",
        "admin:setup-password": "Set up initial admin password (no auth required)",
        "admin:login": "Authenticate as admin and receive JWT (no auth required)",
    }
    return ok(data={"actions": catalog, "count": len(catalog)})
