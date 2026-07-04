"""
SaaS database models — all CRUD operations for SaaS tables.
"""
import sqlite3
import os
import json
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "friday.db")


class SaaSDatabase:
    """Manages all SaaS-related database tables and operations."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _initialize(self):
        with self._connect() as conn:
            c = conn.cursor()

            # ── Users ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    email_verified INTEGER DEFAULT 0,
                    verification_token TEXT,
                    reset_token TEXT,
                    reset_token_expires DATETIME,
                    role TEXT DEFAULT 'user',
                    is_active INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Subscriptions ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plan_id TEXT NOT NULL DEFAULT 'free',
                    status TEXT NOT NULL DEFAULT 'active',
                    billing_period TEXT DEFAULT 'monthly',
                    current_period_start DATETIME,
                    current_period_end DATETIME,
                    trial_end DATETIME,
                    cancelled_at DATETIME,
                    renews_at DATETIME,
                    payment_provider TEXT,
                    payment_provider_sub_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES saas_users(id)
                )
            """)

            # ── API Keys ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    key_prefix TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    label TEXT DEFAULT 'Default',
                    is_active INTEGER DEFAULT 1,
                    is_revoked INTEGER DEFAULT 0,
                    last_used_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES saas_users(id)
                )
            """)

            # ── Usage Logs ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    api_key_id INTEGER,
                    endpoint TEXT,
                    method TEXT,
                    status_code INTEGER,
                    tokens_used INTEGER DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0,
                    ip_address TEXT,
                    user_agent TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES saas_users(id)
                )
            """)

            # ── Daily Usage Aggregates ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_daily_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    request_count INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    total_latency_ms INTEGER DEFAULT 0,
                    UNIQUE(user_id, date),
                    FOREIGN KEY (user_id) REFERENCES saas_users(id)
                )
            """)

            # ── Monthly Usage Aggregates ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_monthly_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    month TEXT NOT NULL,
                    request_count INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    total_latency_ms INTEGER DEFAULT 0,
                    UNIQUE(user_id, month),
                    FOREIGN KEY (user_id) REFERENCES saas_users(id)
                )
            """)

            # ── Payments ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    subscription_id INTEGER,
                    amount REAL NOT NULL,
                    currency TEXT DEFAULT 'USD',
                    status TEXT DEFAULT 'pending',
                    payment_method TEXT,
                    payment_provider TEXT,
                    payment_provider_pay_id TEXT,
                    plan_id TEXT,
                    billing_period TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES saas_users(id),
                    FOREIGN KEY (subscription_id) REFERENCES saas_subscriptions(id)
                )
            """)

            # ── Invoices ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    payment_id INTEGER,
                    invoice_number TEXT UNIQUE,
                    amount REAL NOT NULL,
                    currency TEXT DEFAULT 'USD',
                    status TEXT DEFAULT 'pending',
                    description TEXT,
                    pdf_url TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES saas_users(id),
                    FOREIGN KEY (payment_id) REFERENCES saas_payments(id)
                )
            """)

            # ── Rate Limit Buckets (sliding window) ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_rate_buckets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    window_start REAL NOT NULL,
                    request_count INTEGER DEFAULT 1,
                    UNIQUE(user_id, window_start)
                )
            """)

            # ── Audit Logs ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    resource TEXT,
                    details TEXT,
                    ip_address TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Email Verification Tokens ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_email_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    type TEXT NOT NULL,
                    expires_at DATETIME NOT NULL,
                    used INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES saas_users(id)
                )
            """)

            # ── Webhook Events ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_webhook_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    event_type TEXT,
                    payload TEXT,
                    status TEXT DEFAULT 'received',
                    processed_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Service Connections ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    service TEXT NOT NULL,
                    service_type TEXT NOT NULL,
                    label TEXT,
                    credentials_encrypted TEXT NOT NULL,
                    scopes TEXT,
                    status TEXT DEFAULT 'active',
                    expires_at DATETIME,
                    last_verified_at DATETIME,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, service, label),
                    FOREIGN KEY (user_id) REFERENCES saas_users(id)
                )
            """)
            # Migration: add metadata column for existing databases
            try:
                conn.execute("ALTER TABLE saas_connections ADD COLUMN metadata TEXT")
            except sqlite3.OperationalError:
                pass  # Already exists

            # ── OAuth States ──
            c.execute("""
                CREATE TABLE IF NOT EXISTS saas_oauth_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    service TEXT NOT NULL,
                    state TEXT NOT NULL UNIQUE,
                    code_verifier TEXT NOT NULL,
                    scopes TEXT,
                    redirect_uri TEXT,
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES saas_users(id)
                )
            """)

            conn.commit()

    # ══════════════════════════════════════════
    # Users
    # ══════════════════════════════════════════

    def create_user(self, email, password_hash, name=""):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO saas_users (email, password_hash, name) VALUES (?, ?, ?)",
                (email, password_hash, name),
            )
            user_id = c.lastrowid
            # Auto-create free subscription
            now = datetime.utcnow()
            c.execute(
                "INSERT INTO saas_subscriptions (user_id, plan_id, status, billing_period, current_period_start, current_period_end) VALUES (?, 'free', 'active', 'monthly', ?, ?)",
                (user_id, now, now + timedelta(days=30)),
            )
            self._audit(user_id, "user.created", "user", f"User {email} registered", conn=conn)
            return user_id

    def get_user_by_id(self, user_id):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM saas_users WHERE id = ?", (user_id,))
            row = c.fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM saas_users WHERE email = ?", (email,))
            row = c.fetchone()
            return dict(row) if row else None

    def update_user(self, user_id, **kwargs):
        allowed = {"name", "password_hash", "email_verified", "verification_token",
                    "reset_token", "reset_token_expires", "is_active", "role"}
        cols = {k: v for k, v in kwargs.items() if k in allowed}
        if not cols:
            return False
        cols["updated_at"] = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k} = ?" for k in cols)
        vals = list(cols.values()) + [user_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE saas_users SET {sets} WHERE id = ?", vals)
            conn.commit()
        return True

    def list_users(self, offset=0, limit=50):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM saas_users ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
            return [dict(r) for r in c.fetchall()]

    def count_users(self):
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM saas_users").fetchone()[0]

    # ══════════════════════════════════════════
    # Subscriptions
    # ══════════════════════════════════════════

    def get_subscription(self, user_id):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_subscriptions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            )
            row = c.fetchone()
            return dict(row) if row else None

    def get_subscription_by_id(self, sub_id):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM saas_subscriptions WHERE id = ?", (sub_id,))
            row = c.fetchone()
            return dict(row) if row else None

    def create_subscription(self, user_id, plan_id, billing_period="monthly",
                             trial_end=None, payment_provider=None, payment_provider_sub_id=None):
        now = datetime.utcnow()
        period_days = 30 if billing_period == "monthly" else 365
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                """INSERT INTO saas_subscriptions
                   (user_id, plan_id, status, billing_period, current_period_start, current_period_end, trial_end, payment_provider, payment_provider_sub_id)
                   VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?)""",
                (user_id, plan_id, billing_period, now, now + timedelta(days=period_days),
                 trial_end, payment_provider, payment_provider_sub_id),
            )
            sub_id = c.lastrowid
            self._audit(user_id, "subscription.created", "subscription",
                        f"Plan={plan_id} billing={billing_period}")
            return sub_id

    def update_subscription(self, sub_id, **kwargs):
        allowed = {"plan_id", "status", "billing_period", "current_period_start",
                    "current_period_end", "cancelled_at", "renews_at", "trial_end",
                    "payment_provider", "payment_provider_sub_id"}
        cols = {k: v for k, v in kwargs.items() if k in allowed}
        if not cols:
            return False
        cols["updated_at"] = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k} = ?" for k in cols)
        vals = list(cols.values()) + [sub_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE saas_subscriptions SET {sets} WHERE id = ?", vals)
            conn.commit()
        return True

    def list_subscriptions(self, offset=0, limit=50):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT s.*, u.email, u.name
                FROM saas_subscriptions s
                JOIN saas_users u ON s.user_id = u.id
                ORDER BY s.created_at DESC LIMIT ? OFFSET ?
            """, (limit, offset))
            return [dict(r) for r in c.fetchall()]

    def count_active_subscriptions(self):
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM saas_subscriptions WHERE status = 'active'"
            ).fetchone()[0]

    def count_subscriptions_by_plan(self):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT plan_id, COUNT(*) as cnt FROM saas_subscriptions WHERE status='active' GROUP BY plan_id"
            )
            return {r["plan_id"]: r["cnt"] for r in c.fetchall()}

    # ══════════════════════════════════════════
    # API Keys
    # ══════════════════════════════════════════

    def create_api_key(self, user_id, key_hash, key_prefix, label="Default"):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO saas_api_keys (user_id, key_hash, key_prefix, label) VALUES (?, ?, ?, ?)",
                (user_id, key_hash, key_prefix, label),
            )
            key_id = c.lastrowid
            self._audit(user_id, "apikey.created", "api_key", f"Label={label}", conn=conn)
            return key_id

    def get_api_key_by_hash(self, key_hash):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM saas_api_keys WHERE key_hash = ?", (key_hash,))
            row = c.fetchone()
            return dict(row) if row else None

    def get_api_keys_for_user(self, user_id):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, user_id, key_prefix, label, is_active, is_revoked, last_used_at, created_at FROM saas_api_keys WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            )
            return [dict(r) for r in c.fetchall()]

    def revoke_api_key(self, key_id, user_id):
        with self._connect() as conn:
            conn.execute(
                "UPDATE saas_api_keys SET is_revoked = 1, is_active = 0 WHERE id = ? AND user_id = ?",
                (key_id, user_id),
            )
            conn.commit()
            self._audit(user_id, "apikey.revoked", "api_key", f"KeyID={key_id}")
        return True

    def update_api_key_last_used(self, key_id):
        with self._connect() as conn:
            conn.execute(
                "UPDATE saas_api_keys SET last_used_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), key_id),
            )
            conn.commit()

    def count_active_keys(self, user_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM saas_api_keys WHERE user_id = ? AND is_revoked = 0 AND is_active = 1",
                (user_id,),
            ).fetchone()[0]

    # ══════════════════════════════════════════
    # Usage Logging
    # ══════════════════════════════════════════

    def log_usage(self, user_id, api_key_id=None, endpoint=None, method=None,
                   status_code=None, tokens_used=0, latency_ms=0, ip_address=None,
                   user_agent=None):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO saas_usage_logs
                   (user_id, api_key_id, endpoint, method, status_code, tokens_used, latency_ms, ip_address, user_agent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, api_key_id, endpoint, method, status_code, tokens_used,
                 latency_ms, ip_address, user_agent),
            )
            conn.commit()

    def increment_daily_usage(self, user_id, tokens_used=0, latency_ms=0, is_error=False):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id FROM saas_daily_usage WHERE user_id = ? AND date = ?",
                (user_id, today),
            )
            row = c.fetchone()
            if row:
                conn.execute(
                    "UPDATE saas_daily_usage SET request_count = request_count + 1, tokens_used = tokens_used + ?, total_latency_ms = total_latency_ms + ?, error_count = error_count + ? WHERE id = ?",
                    (tokens_used, latency_ms, 1 if is_error else 0, row["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO saas_daily_usage (user_id, date, request_count, tokens_used, error_count, total_latency_ms) VALUES (?, ?, 1, ?, ?, ?)",
                    (user_id, today, tokens_used, 1 if is_error else 0, latency_ms),
                )
            conn.commit()

    def increment_monthly_usage(self, user_id, tokens_used=0, latency_ms=0, is_error=False):
        month = datetime.utcnow().strftime("%Y-%m")
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id FROM saas_monthly_usage WHERE user_id = ? AND month = ?",
                (user_id, month),
            )
            row = c.fetchone()
            if row:
                conn.execute(
                    "UPDATE saas_monthly_usage SET request_count = request_count + 1, tokens_used = tokens_used + ?, total_latency_ms = total_latency_ms + ?, error_count = error_count + ? WHERE id = ?",
                    (tokens_used, latency_ms, 1 if is_error else 0, row["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO saas_monthly_usage (user_id, month, request_count, tokens_used, error_count, total_latency_ms) VALUES (?, ?, 1, ?, ?, ?)",
                    (user_id, month, tokens_used, 1 if is_error else 0, latency_ms),
                )
            conn.commit()

    # ══════════════════════════════════════════
    # Usage Queries
    # ══════════════════════════════════════════

    def get_daily_usage(self, user_id, days=30):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_daily_usage WHERE user_id = ? ORDER BY date DESC LIMIT ?",
                (user_id, days),
            )
            return [dict(r) for r in c.fetchall()]

    def get_monthly_usage(self, user_id, months=12):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_monthly_usage WHERE user_id = ? ORDER BY month DESC LIMIT ?",
                (user_id, months),
            )
            return [dict(r) for r in c.fetchall()]

    def get_current_month_usage(self, user_id):
        month = datetime.utcnow().strftime("%Y-%m")
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_monthly_usage WHERE user_id = ? AND month = ?",
                (user_id, month),
            )
            row = c.fetchone()
            if row:
                return dict(row)
            return {"request_count": 0, "tokens_used": 0, "error_count": 0, "total_latency_ms": 0}

    def get_usage_logs(self, user_id, limit=50, offset=0):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_usage_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            )
            return [dict(r) for r in c.fetchall()]

    def get_overall_usage_stats(self):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) as total_requests, COALESCE(SUM(tokens_used),0) as total_tokens FROM saas_usage_logs")
            total = dict(c.fetchone())
            c.execute("SELECT COUNT(*) as total_errors FROM saas_usage_logs WHERE status_code >= 400")
            errors = c.fetchone()[0]
            c.execute("SELECT AVG(latency_ms) as avg_latency FROM saas_usage_logs")
            avg_lat = c.fetchone()[0] or 0
            total["total_errors"] = errors
            total["avg_latency_ms"] = round(avg_lat, 2)
            return total

    # ══════════════════════════════════════════
    # Payments & Invoices
    # ══════════════════════════════════════════

    def create_payment(self, user_id, amount, subscription_id=None, status="pending",
                        payment_method=None, payment_provider=None,
                        payment_provider_pay_id=None, plan_id=None, billing_period=None):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                """INSERT INTO saas_payments
                   (user_id, subscription_id, amount, status, payment_method, payment_provider, payment_provider_pay_id, plan_id, billing_period)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, subscription_id, amount, status, payment_method,
                 payment_provider, payment_provider_pay_id, plan_id, billing_period),
            )
            return c.lastrowid

    def update_payment(self, payment_id, **kwargs):
        allowed = {"status", "payment_provider_pay_id", "payment_method"}
        cols = {k: v for k, v in kwargs.items() if k in allowed}
        if not cols:
            return False
        sets = ", ".join(f"{k} = ?" for k in cols)
        vals = list(cols.values()) + [payment_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE saas_payments SET {sets} WHERE id = ?", vals)
            conn.commit()
        return True

    def get_payments(self, user_id, limit=50):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_payments WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
            return [dict(r) for r in c.fetchall()]

    def get_all_payments(self, offset=0, limit=50):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT p.*, u.email FROM saas_payments p JOIN saas_users u ON p.user_id = u.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            return [dict(r) for r in c.fetchall()]

    def create_invoice(self, user_id, payment_id, amount, description="",
                        invoice_number=None, status="pending"):
        if not invoice_number:
            invoice_number = f"INV-{datetime.utcnow().strftime('%Y%m%d')}-{user_id}-{int(datetime.utcnow().timestamp())}"
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO saas_invoices (user_id, payment_id, amount, description, invoice_number, status) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, payment_id, amount, description, invoice_number, status),
            )
            return c.lastrowid

    def get_invoices(self, user_id, limit=50):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_invoices WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
            return [dict(r) for r in c.fetchall()]

    # ══════════════════════════════════════════
    # Rate Limiting
    # ══════════════════════════════════════════

    def get_rate_bucket(self, user_id, window_start):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_rate_buckets WHERE user_id = ? AND window_start = ?",
                (user_id, window_start),
            )
            row = c.fetchone()
            return dict(row) if row else None

    def upsert_rate_bucket(self, user_id, window_start):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO saas_rate_buckets (user_id, window_start, request_count) VALUES (?, ?, 1) ON CONFLICT(user_id, window_start) DO UPDATE SET request_count = request_count + 1",
                (user_id, window_start),
            )
            conn.commit()

    def cleanup_rate_buckets(self, before_window):
        with self._connect() as conn:
            conn.execute("DELETE FROM saas_rate_buckets WHERE window_start < ?", (before_window,))
            conn.commit()

    # ══════════════════════════════════════════
    # Email Tokens
    # ══════════════════════════════════════════

    def create_email_token(self, user_id, token, token_type, expires_at):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO saas_email_tokens (user_id, token, type, expires_at) VALUES (?, ?, ?, ?)",
                (user_id, token, token_type, expires_at),
            )
            conn.commit()

    def use_email_token(self, token, token_type):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_email_tokens WHERE token = ? AND type = ? AND used = 0 AND expires_at > ?",
                (token, token_type, datetime.utcnow().isoformat()),
            )
            row = c.fetchone()
            if row:
                conn.execute("UPDATE saas_email_tokens SET used = 1 WHERE id = ?", (row["id"],))
                conn.commit()
                return dict(row)
            return None

    # ══════════════════════════════════════════
    # Audit
    # ══════════════════════════════════════════

    def _audit(self, user_id, action, resource=None, details=None, ip_address=None, conn=None):
        if conn:
            conn.execute(
                "INSERT INTO saas_audit_logs (user_id, action, resource, details, ip_address) VALUES (?, ?, ?, ?, ?)",
                (user_id, action, resource, details, ip_address),
            )
        else:
            with self._connect() as c:
                c.execute(
                    "INSERT INTO saas_audit_logs (user_id, action, resource, details, ip_address) VALUES (?, ?, ?, ?, ?)",
                    (user_id, action, resource, details, ip_address),
                )
                c.commit()

    def log_audit(self, user_id, action, resource=None, details=None, ip_address=None):
        self._audit(user_id, action, resource, details, ip_address)

    def get_audit_logs(self, limit=100, offset=0, user_id=None):
        with self._connect() as conn:
            c = conn.cursor()
            if user_id:
                c.execute(
                    "SELECT * FROM saas_audit_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (user_id, limit, offset),
                )
            else:
                c.execute(
                    "SELECT * FROM saas_audit_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            return [dict(r) for r in c.fetchall()]

    # ══════════════════════════════════════════
    # Webhook Events
    # ══════════════════════════════════════════

    def log_webhook_event(self, provider, event_type, payload):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO saas_webhook_events (provider, event_type, payload) VALUES (?, ?, ?)",
                (provider, event_type, json.dumps(payload)),
            )
            conn.commit()
            return c.lastrowid

    def mark_webhook_processed(self, event_id):
        with self._connect() as conn:
            conn.execute(
                "UPDATE saas_webhook_events SET status = 'processed', processed_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), event_id),
            )
            conn.commit()

    # ══════════════════════════════════════════
    # Service Connections
    # ══════════════════════════════════════════

    def create_connection(self, user_id, service, service_type, credentials_encrypted, label=None, scopes=None):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO saas_connections (user_id, service, service_type, credentials_encrypted, label, scopes) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, service, service_type, credentials_encrypted, label, scopes),
            )
            conn_id = c.lastrowid
            self._audit(user_id, "connection.created", "connection",
                        f"Service={service} service_type={service_type} label={label}")
            return conn_id

    def get_connection(self, connection_id, user_id):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_connections WHERE id = ? AND user_id = ?",
                (connection_id, user_id),
            )
            row = c.fetchone()
            return dict(row) if row else None

    def get_connections_for_user(self, user_id, service=None):
        with self._connect() as conn:
            c = conn.cursor()
            if service:
                c.execute(
                    "SELECT * FROM saas_connections WHERE user_id = ? AND service = ? ORDER BY created_at DESC",
                    (user_id, service),
                )
            else:
                c.execute(
                    "SELECT * FROM saas_connections WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                )
            return [dict(r) for r in c.fetchall()]

    def update_connection(self, connection_id, user_id, **kwargs):
        allowed = {"credentials_encrypted", "label", "scopes", "status", "expires_at", "last_verified_at"}
        cols = {k: v for k, v in kwargs.items() if k in allowed}
        if not cols:
            return False
        cols["updated_at"] = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k} = ?" for k in cols)
        vals = list(cols.values()) + [connection_id, user_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE saas_connections SET {sets} WHERE id = ? AND user_id = ?", vals)
            conn.commit()
        return True

    def delete_connection(self, connection_id, user_id):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT service FROM saas_connections WHERE id = ? AND user_id = ?",
                (connection_id, user_id),
            )
            row = c.fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM saas_connections WHERE id = ? AND user_id = ?",
                         (connection_id, user_id))
            conn.commit()
            self._audit(user_id, "connection.deleted", "connection",
                        f"connection_id={connection_id} service={row['service']}")
            return True

    def count_connections(self, user_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM saas_connections WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()[0]

    # ══════════════════════════════════════════
    # OAuth States
    # ══════════════════════════════════════════

    def create_oauth_state(self, user_id, service, state, code_verifier, scopes=None, redirect_uri=None, expires_at=None):
        if expires_at is None:
            expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO saas_oauth_states (user_id, service, state, code_verifier, scopes, redirect_uri, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, service, state, code_verifier, scopes, redirect_uri, expires_at),
            )
            return c.lastrowid

    def get_oauth_state(self, state):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM saas_oauth_states WHERE state = ? AND expires_at > ?",
                (state, datetime.utcnow().isoformat()),
            )
            row = c.fetchone()
            return dict(row) if row else None

    def consume_oauth_state(self, state):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM saas_oauth_states WHERE state = ?", (state,))
            row = c.fetchone()
            if row:
                conn.execute("DELETE FROM saas_oauth_states WHERE state = ?", (state,))
                conn.commit()
                return dict(row)
            return None
