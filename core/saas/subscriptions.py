"""
Subscription service — plan definitions, lifecycle, and plan-based limits.
"""
from datetime import datetime, timedelta


# ── Plan catalogue ──

PLANS = {
    "free": {
        "id": "free",
        "name": "Free",
        "price_monthly": 0.0,
        "price_yearly": 0.0,
        "requests_per_day": 100,
        "requests_per_month": 3_000,
        "max_api_keys": 1,
        "tokens_per_month": 100_000,
        "max_tokens_per_request": 4_096,
        "rate_limit_per_minute": 10,
        "features": [
            "Basic AI chat",
            "100 requests/day",
            "1 API key",
            "Community support",
        ],
    },
    "starter": {
        "id": "starter",
        "name": "Starter",
        "price_monthly": 29.0,
        "price_yearly": 290.0,
        "requests_per_day": 10_000,
        "requests_per_month": 300_000,
        "max_api_keys": 5,
        "tokens_per_month": 500_000,
        "max_tokens_per_request": 8_192,
        "rate_limit_per_minute": 60,
        "features": [
            "Advanced AI chat",
            "10,000 requests/day",
            "5 API keys",
            "Email support",
            "Usage analytics",
        ],
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "price_monthly": 99.0,
        "price_yearly": 990.0,
        "requests_per_day": 100_000,
        "requests_per_month": 3_000_000,
        "max_api_keys": 20,
        "tokens_per_month": 5_000_000,
        "max_tokens_per_request": 16_384,
        "rate_limit_per_minute": 300,
        "features": [
            "Priority AI chat",
            "100,000 requests/day",
            "20 API keys",
            "Priority support",
            "Usage analytics",
            "Webhook integrations",
        ],
    },
    "enterprise": {
        "id": "enterprise",
        "name": "Enterprise",
        "price_monthly": None,   # custom pricing
        "price_yearly": None,
        "requests_per_day": 1_000_000,
        "requests_per_month": 30_000_000,
        "max_api_keys": 100,
        "tokens_per_month": 100_000_000,
        "max_tokens_per_request": 32_768,
        "rate_limit_per_minute": 1_000,
        "features": [
            "Unlimited AI chat",
            "1,000,000 requests/day",
            "100 API keys",
            "Dedicated support",
            "Custom model fine-tuning",
            "SLA guarantee",
            "On-premise option",
        ],
    },
}


class SubscriptionService:
    """Manages subscription plan definitions and lifecycle."""

    def __init__(self, db):
        self.db = db

    # ── Plan info ──

    @staticmethod
    def list_plans():
        """Return all plans with public-facing data."""
        return [
            {k: v for k, v in plan.items() if k != "rate_limit_per_minute"}
            for plan in PLANS.values()
        ]

    @staticmethod
    def get_plan(plan_id):
        """Return a single plan or None."""
        return PLANS.get(plan_id)

    @staticmethod
    def get_plan_limit(plan_id: str, limit_key: str):
        """Get a specific limit value from a plan.

        Example: get_plan_limit("starter", "max_api_keys") -> 5
        """
        plan = PLANS.get(plan_id)
        if not plan:
            return None
        return plan.get(limit_key)

    # ── Limits helper ──

    def get_user_limits(self, user_id):
        """Get the effective limits for a user based on their subscription plan."""
        sub = self.db.get_subscription(user_id)
        plan_id = sub["plan_id"] if sub else "free"
        status = sub["status"] if sub else "active"

        plan = PLANS.get(plan_id, PLANS["free"])

        # If subscription is expired/cancelled, fall back to free limits
        if status not in ("active", "trialing"):
            plan = PLANS["free"]

        return dict(plan)

    # ── Lifecycle ──

    def subscribe(self, user_id, plan_id, billing_period="monthly",
                  payment_provider=None, payment_provider_sub_id=None):
        """Upgrade a user's subscription to a new plan.

        Returns (success, message, data).
        """
        if plan_id not in PLANS:
            return False, f"Unknown plan '{plan_id}'", None

        plan = PLANS[plan_id]
        if billing_period == "monthly" and plan["price_monthly"] is None:
            return False, f"Plan '{plan_id}' requires custom pricing — contact sales", None

        # Cancel existing subscription first
        existing = self.db.get_subscription(user_id)
        if existing:
            self.db.update_subscription(
                existing["id"],
                status="cancelled",
                cancelled_at=datetime.utcnow().isoformat(),
            )

        # Create new subscription
        now = datetime.utcnow()
        trial_end = None
        # Give trials only when moving from free to paid
        if existing and existing["plan_id"] == "free" and plan_id != "free":
            trial_end = now + timedelta(days=7)

        period_days = 30 if billing_period == "monthly" else 365
        sub_id = self.db.create_subscription(
            user_id, plan_id, billing_period,
            trial_end=trial_end.isoformat() if trial_end else None,
            payment_provider=payment_provider,
            payment_provider_sub_id=payment_provider_sub_id,
        )

        self.db.log_audit(
            user_id, "subscription.upgraded", "subscription",
            f"Plan={plan_id} billing={billing_period}",
        )

        return True, f"Subscribed to {plan['name']}", {
            "subscription_id": sub_id,
            "plan_id": plan_id,
            "billing_period": billing_period,
            "current_period_end": (now + timedelta(days=period_days)).isoformat(),
            "trial_end": trial_end.isoformat() if trial_end else None,
        }

    def cancel(self, user_id, immediately=False):
        """Cancel a user's subscription.

        If immediately=True, set status to 'cancelled' right away.
        Otherwise, set status to 'cancelling' and mark renews_at=None.
        """
        sub = self.db.get_subscription(user_id)
        if not sub:
            return False, "No active subscription", None

        now = datetime.utcnow()
        if immediately:
            self.db.update_subscription(
                sub["id"],
                status="cancelled",
                cancelled_at=now.isoformat(),
                plan_id="free",
            )
            # Create a free-tier sub
            self.db.create_subscription(
                user_id, "free", "monthly",
            )
            msg = "Subscription cancelled immediately"
        else:
            self.db.update_subscription(
                sub["id"],
                status="cancelling",
                renews_at=None,
                cancelled_at=now.isoformat(),
            )
            msg = "Subscription will cancel at period end"

        self.db.log_audit(user_id, "subscription.cancelled", "subscription", msg)
        return True, msg, None

    def renew(self, user_id):
        """Renew a subscription for another period (called by cron/webhook)."""
        sub = self.db.get_subscription(user_id)
        if not sub:
            return False, "No subscription found", None

        now = datetime.utcnow()
        period_days = 30 if sub.get("billing_period") == "monthly" else 365
        new_end = (datetime.fromisoformat(sub["current_period_end"]) + timedelta(days=period_days)).isoformat()

        self.db.update_subscription(
            sub["id"],
            status="active",
            current_period_start=sub["current_period_end"],
            current_period_end=new_end,
        )

        self.db.log_audit(user_id, "subscription.renewed", "subscription",
                          f"Period extended to {new_end}")
        return True, "Subscription renewed", {"current_period_end": new_end}

    def change_plan(self, user_id, new_plan_id, billing_period=None):
        """Upgrade or downgrade a user's plan."""
        if new_plan_id not in PLANS:
            return False, f"Unknown plan '{new_plan_id}'", None

        sub = self.db.get_subscription(user_id)
        if not sub:
            return False, "No active subscription", None

        updates = {"plan_id": new_plan_id}
        if billing_period:
            updates["billing_period"] = billing_period

        self.db.update_subscription(sub["id"], **updates)
        self.db.log_audit(user_id, "subscription.changed", "subscription",
                          f"Plan changed to {new_plan_id}")

        plan = PLANS[new_plan_id]
        return True, f"Plan changed to {plan['name']}", {"plan_id": new_plan_id}

    def get_user_plan_id(self, user_id):
        """Get the current plan_id for a user (fast helper)."""
        sub = self.db.get_subscription(user_id)
        if sub and sub["status"] in ("active", "trialing"):
            return sub["plan_id"]
        return "free"
