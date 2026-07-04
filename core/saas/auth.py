"""
Authentication service — JWT, password hashing, registration, login, email verification.
"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta

import jwt
from werkzeug.security import generate_password_hash, check_password_hash


class AuthService:
    """Handles user authentication and JWT management."""

    def __init__(self, db):
        self.db = db
        self.jwt_secret = os.getenv("FRIDAY_JWT_SECRET", secrets.token_hex(32))
        self.jwt_algorithm = "HS256"
        self.jwt_expiry_hours = int(os.getenv("FRIDAY_JWT_EXPIRY", "72"))

    # ── Password ──

    def hash_password(self, password):
        return generate_password_hash(password, method="pbkdf2:sha256:600000")

    def verify_password(self, password, password_hash):
        return check_password_hash(password_hash, password)

    # ── JWT ──

    def generate_token(self, user_id, role="user"):
        now = datetime.utcnow()
        payload = {
            "sub": user_id,
            "role": role,
            "iat": now,
            "exp": now + timedelta(hours=self.jwt_expiry_hours),
        }
        return jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)

    def generate_refresh_token(self, user_id):
        return secrets.token_urlsafe(48)

    def verify_token(self, token):
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def refresh_token(self, refresh_token):
        """Validate and issue a new JWT from a refresh token."""
        # Refresh tokens stored as email_tokens of type 'refresh'
        record = self.db.use_email_token(refresh_token, "refresh")
        if record:
            return self.generate_token(record["user_id"])
        return None

    # ── Registration ──

    def register(self, email, password, name=""):
        """Register a new user. Returns (success, message, data_or_error)."""
        email = email.lower().strip()

        # Validate email
        if not email or "@" not in email or "." not in email:
            return False, "Invalid email address", None

        # Validate password
        if len(password) < 8:
            return False, "Password must be at least 8 characters", None

        # Check existing
        existing = self.db.get_user_by_email(email)
        if existing:
            return False, "Email already registered", None

        # Create user
        pw_hash = self.hash_password(password)
        try:
            user_id = self.db.create_user(email, pw_hash, name)
            token = self.generate_token(user_id)
            return True, "Registration successful", {
                "user_id": user_id,
                "token": token,
                "email": email,
            }
        except Exception as e:
            return False, f"Registration failed: {str(e)}", None

    # ── Login ──

    def login(self, email, password):
        """Authenticate a user. Returns (success, message, data_or_error)."""
        email = email.lower().strip()
        user = self.db.get_user_by_email(email)
        if not user:
            return False, "Invalid email or password", None

        if not user.get("is_active"):
            return False, "Account is disabled", None

        if not self.verify_password(password, user["password_hash"]):
            return False, "Invalid email or password", None

        token = self.generate_token(user["id"], user.get("role", "user"))
        refresh = self.generate_refresh_token(user["id"])
        # Store refresh token
        self.db.create_email_token(
            user["id"], refresh, "refresh",
            (datetime.utcnow() + timedelta(days=30)).isoformat(),
        )

        return True, "Login successful", {
            "user_id": user["id"],
            "token": token,
            "refresh_token": refresh,
            "email": user["email"],
            "name": user.get("name", ""),
            "role": user.get("role", "user"),
        }

    # ── Email Verification ──

    def generate_verification_token(self, user_id):
        token = secrets.token_urlsafe(32)
        self.db.create_email_token(
            user_id, token, "email_verify",
            (datetime.utcnow() + timedelta(hours=48)).isoformat(),
        )
        self.db.update_user(user_id, verification_token=token)
        return token

    def verify_email(self, token):
        record = self.db.use_email_token(token, "email_verify")
        if record:
            self.db.update_user(record["user_id"], email_verified=1, verification_token=None)
            return True, "Email verified"
        return False, "Invalid or expired verification token"

    # ── Password Reset ──

    def generate_reset_token(self, email):
        user = self.db.get_user_by_email(email.lower().strip())
        if not user:
            return True  # Don't reveal whether email exists
        token = secrets.token_urlsafe(32)
        self.db.create_email_token(
            user["id"], token, "password_reset",
            (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        )
        self.db.update_user(
            user["id"],
            reset_token=token,
            reset_token_expires=(datetime.utcnow() + timedelta(hours=1)).isoformat(),
        )
        return token  # In production, send via email

    def reset_password(self, token, new_password):
        if len(new_password) < 8:
            return False, "Password must be at least 8 characters"
        record = self.db.use_email_token(token, "password_reset")
        if not record:
            return False, "Invalid or expired reset token"
        pw_hash = self.hash_password(new_password)
        self.db.update_user(record["user_id"], password_hash=pw_hash,
                             reset_token=None, reset_token_expires=None)
        return True, "Password reset successful"

    # ── Profile ──

    def get_profile(self, user_id):
        user = self.db.get_user_by_id(user_id)
        if not user:
            return None
        # Remove sensitive fields
        del user["password_hash"]
        del user["verification_token"]
        del user["reset_token"]
        del user["reset_token_expires"]

        # Attach subscription info
        sub = self.db.get_subscription(user_id)
        user["subscription"] = dict(sub) if sub else {"plan_id": "free", "status": "active"}

        return user

    # ── Middleware helper ──

    def authenticate_request(self, auth_header):
        """Extract and validate JWT from Authorization header.
        Returns (user_id, role) or (None, None)."""
        if not auth_header or not auth_header.startswith("Bearer "):
            return None, None
        token = auth_header.split(" ", 1)[1].strip()
        payload = self.verify_token(token)
        if not payload:
            return None, None
        user = self.db.get_user_by_id(payload["sub"])
        if not user or not user.get("is_active"):
            return None, None
        return user["id"], user.get("role", "user")
