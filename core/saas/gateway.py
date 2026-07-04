"""
API Gateway — middleware and decorators for the SaaS API.

The gateway sits in front of Friday AI requests and handles:
  1. API key validation (frd_live_xxx → SHA-256 lookup)
  2. Subscription status check
  3. Quota enforcement (daily + monthly)
  4. Rate limiting (sliding window)
  5. Usage logging
  6. Audit trail

Usage::

    from core.saas.gateway import saas_gateway

    @app.route("/api/v2/chat", methods=["POST"])
    @saas_gateway.require_key
    def chat_v2(user_id, plan_limits):
        ...
"""
import time
import functools
import logging

logger = logging.getLogger(__name__)


class APIGateway:
    """Flask middleware helpers for the SaaS API gateway flow."""

    def __init__(self, saas):
        self.saas = saas
        self.auth = saas.auth
        self.keys = saas.keys
        self.subscriptions = saas.subscriptions
        self.usage = saas.usage

    # ── Decorators ──

    def require_key(self, route_func):
        """Decorator that validates an frd_live_ API key on a Flask route.

        Injects ``user_id`` and ``plan_limits`` kwargs into the route.

        Expected header: Authorization: Bearer frd_live_xxxxxxxxx
        """
        @functools.wraps(route_func)
        def wrapper(*args, **kwargs):
            request = __import__("flask", fromlist=["flask"]).request
            jsonify = __import__("flask", fromlist=["flask"]).jsonify

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return jsonify({"error": "Missing or invalid Authorization header"}), 401

            api_key = auth_header.split(" ", 1)[1].strip()

            # Validate API key
            key_record = self.keys.validate_key(api_key)
            if not key_record:
                return jsonify({"error": "Invalid or revoked API key"}), 401

            user_id = key_record["user_id"]

            # Check subscription
            plan_limits = self.subscriptions.get_user_limits(user_id)
            if not plan_limits:
                return jsonify({"error": "No active subscription"}), 403

            # Check daily + monthly quota
            allowed, reason = self.usage.check_quota(user_id, plan_limits)
            if not allowed:
                return jsonify({"error": "Quota exceeded", "detail": reason}), 429

            # Check rate limit
            rl_allowed, retry_after, rl_reason = self.usage.check_rate_limit(user_id, plan_limits)
            if not rl_allowed:
                resp = jsonify({"error": rl_reason, "retry_after": retry_after})
                resp.headers["Retry-After"] = str(retry_after)
                return resp, 429

            # Log the request (will be updated by the route with status/tokens)
            request._saas_user_id = user_id
            request._saas_key_id = key_record["id"]
            request._saas_plan_limits = plan_limits
            request._saas_logged = False

            # Inject into route kwargs
            kwargs["user_id"] = user_id
            kwargs["plan_limits"] = plan_limits

            try:
                response = route_func(*args, **kwargs)
            except Exception as e:
                self._log_request(request, user_id, key_record["id"],
                                  status_code=500, plan_limits=plan_limits)
                raise

            # Log successful requests
            status = getattr(response, "status_code", 200) if hasattr(response, "status_code") else 200
            self._log_request(request, user_id, key_record["id"],
                              status_code=status, plan_limits=plan_limits)

            return response

        return wrapper

    def require_jwt(self, route_func):
        """Decorator that validates a JWT Bearer token on a Flask route.

        Injects ``user_id`` and ``plan_limits`` kwargs into the route.

        Use this for dashboard / admin routes where users authenticate
        via JWT (email+password login) rather than API keys.
        """
        @functools.wraps(route_func)
        def wrapper(*args, **kwargs):
            request = __import__("flask", fromlist=["flask"]).request
            jsonify = __import__("flask", fromlist=["flask"]).jsonify

            auth_header = request.headers.get("Authorization", "")
            user_id, role = self.auth.authenticate_request(auth_header)
            if not user_id:
                return jsonify({"error": "Invalid or expired token"}), 401

            plan_limits = self.subscriptions.get_user_limits(user_id)

            kwargs["user_id"] = user_id
            kwargs["plan_limits"] = plan_limits
            kwargs["role"] = role

            try:
                response = route_func(*args, **kwargs)
            except Exception as e:
                self._log_request(request, user_id, None,
                                  status_code=500, plan_limits=plan_limits)
                raise

            status = getattr(response, "status_code", 200) if hasattr(response, "status_code") else 200
            self._log_request(request, user_id, None,
                              status_code=status, plan_limits=plan_limits)

            return response

        return wrapper

    def require_admin(self, route_func):
        """Decorator for admin-only routes (requires JWT + admin role)."""
        @functools.wraps(route_func)
        def wrapper(*args, **kwargs):
            request = __import__("flask", fromlist=["flask"]).request
            jsonify = __import__("flask", fromlist=["flask"]).jsonify

            auth_header = request.headers.get("Authorization", "")
            user_id, role = self.auth.authenticate_request(auth_header)
            if not user_id:
                return jsonify({"error": "Invalid or expired token"}), 401
            if role != "admin":
                return jsonify({"error": "Admin access required"}), 403

            plan_limits = self.subscriptions.get_user_limits(user_id)

            kwargs["user_id"] = user_id
            kwargs["plan_limits"] = plan_limits
            kwargs["role"] = role

            return route_func(*args, **kwargs)

        return wrapper

    # ── Gateway helpers ──

    def authenticate_key(self, auth_header):
        """Direct API key validation (for non-decorator usage).

        Returns (user_id, plan_limits, key_record) or raises.
        """
        if not auth_header or not auth_header.startswith("Bearer "):
            return None, None, None

        api_key = auth_header.split(" ", 1)[1].strip()
        key_record = self.keys.validate_key(api_key)
        if not key_record:
            return None, None, None

        user_id = key_record["user_id"]
        plan_limits = self.subscriptions.get_user_limits(user_id)
        return user_id, plan_limits, key_record

    def _log_request(self, flask_request, user_id, key_id, status_code=200, plan_limits=None):
        """Log a request to the usage tracker."""
        if getattr(flask_request, "_saas_logged", False):
            return
        flask_request._saas_logged = True

        start_time = getattr(flask_request, "_saas_start_time", None)
        latency_ms = 0
        if start_time:
            latency_ms = int((time.time() - start_time) * 1000)

        # Estimate tokens (simplified — real apps would read from response)
        tokens_used = 0
        if plan_limits:
            tokens_used = min(
                getattr(flask_request, "_saas_tokens_used", 0),
                plan_limits.get("max_tokens_per_request", 4096),
            )

        self.usage.log_request(
            user_id=user_id,
            api_key_id=key_id,
            endpoint=str(flask_request.path),
            method=str(flask_request.method),
            status_code=status_code,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            ip_address=flask_request.remote_addr or "",
            user_agent=str(flask_request.user_agent or ""),
        )
