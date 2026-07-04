"""
Usage tracking, quota enforcement, and rate limiting.
"""
import time
from datetime import datetime


class UsageTracker:
    """Tracks API usage, checks quotas, and enforces rate limits."""

    def __init__(self, db):
        self.db = db
        # In-memory cache for rate limit decisions (optional optimisation)
        self._rate_cache: dict[str, tuple[float, int]] = {}

    # ── Logging ──

    def log_request(self, user_id, api_key_id=None, endpoint=None, method=None,
                    status_code=200, tokens_used=0, latency_ms=0,
                    ip_address=None, user_agent=None):
        """Log a single API request and update aggregate counters."""
        self.db.log_usage(
            user_id=user_id,
            api_key_id=api_key_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.increment_daily_usage(
            user_id,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            is_error=status_code >= 400,
        )
        self.db.increment_monthly_usage(
            user_id,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            is_error=status_code >= 400,
        )

    # ── Quota checks ──

    def check_daily_quota(self, user_id, plan_limits: dict):
        """Check if the user has exceeded their daily request quota.

        Returns (allowed, reason).
        """
        daily_limit = plan_limits.get("requests_per_day", 100)
        usage = self.db.get_daily_usage(user_id, days=1)
        today_count = usage[0]["request_count"] if usage else 0

        if today_count >= daily_limit:
            return False, f"Daily quota exceeded ({today_count}/{daily_limit})"
        return True, ""

    def check_monthly_quota(self, user_id, plan_limits: dict):
        """Check if the user has exceeded their monthly request/token quota.

        Returns (allowed, reason).
        """
        monthly = self.db.get_current_month_usage(user_id)

        req_limit = plan_limits.get("requests_per_month", 3_000)
        token_limit = plan_limits.get("tokens_per_month", 100_000)

        if monthly["request_count"] >= req_limit:
            return False, f"Monthly request quota exceeded ({monthly['request_count']}/{req_limit})"
        if monthly["tokens_used"] >= token_limit:
            return False, f"Monthly token quota exceeded ({monthly['tokens_used']}/{token_limit})"
        return True, ""

    def check_quota(self, user_id, plan_limits: dict):
        """Combined daily + monthly quota check.

        Returns (allowed, reason).
        """
        allowed, reason = self.check_daily_quota(user_id, plan_limits)
        if not allowed:
            return False, reason
        return self.check_monthly_quota(user_id, plan_limits)

    # ── Rate limiting (sliding window) ──

    def check_rate_limit(self, user_id, plan_limits: dict):
        """Sliding-window rate limiter using database-backed buckets.

        Returns (allowed, retry_after_seconds, reason).
        """
        max_per_minute = plan_limits.get("rate_limit_per_minute", 10)
        window_seconds = 60

        now = time.time()
        window_start = int(now / window_seconds) * window_seconds

        # Upsert the current bucket (increments counter)
        self.db.upsert_rate_bucket(user_id, window_start)

        # Get count for this window
        bucket = self.db.get_rate_bucket(user_id, window_start)
        count = bucket["request_count"] if bucket else 0

        if count > max_per_minute:
            retry_after = int(window_start + window_seconds - now) + 1
            return False, retry_after, f"Rate limit exceeded ({count}/{max_per_minute} per minute)"

        # Clean up old buckets periodically (roughly every 100th request)
        if bucket and bucket.get("id", 0) % 100 == 0:
            self.db.cleanup_rate_buckets(now - 2 * window_seconds)

        return True, 0, ""

    # ── Usage reports ──

    def get_usage_report(self, user_id):
        """Get a comprehensive usage summary for a user."""
        daily = self.db.get_daily_usage(user_id, days=30)
        monthly = self.db.get_monthly_usage(user_id, months=12)
        logs = self.db.get_usage_logs(user_id, limit=20)

        return {
            "daily": daily,
            "monthly": monthly,
            "recent_logs": logs,
            "current_month": self.db.get_current_month_usage(user_id),
        }

    def get_overall_stats(self):
        """Get aggregate usage stats across all users (admin)."""
        return self.db.get_overall_usage_stats()
