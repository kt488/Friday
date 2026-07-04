"""
API key service — generation, hashing, validation, and lifecycle.
"""
import hashlib
import secrets
import hmac


# ── Constants ──

KEY_PREFIX = "frd_live_"
KEY_BYTES = 32       # 256-bit random payload
HASH_ALGO = "sha256"


class APIKeyService:
    """Generates, hashes, and validates FRD-format API keys."""

    def __init__(self, db):
        self.db = db

    # ── Key generation ──

    def generate_key(self, user_id, label="Default"):
        """Create a new API key.

        Returns (full_key, display_data).

        The full key is returned exactly once — the caller is responsible
        for showing it to the user. Only the SHA-256 hash is stored.
        """
        # Count existing keys to check plan limits (enforced by gateway)
        existing_count = self.db.count_active_keys(user_id)

        # Generate random payload
        raw = secrets.token_urlsafe(KEY_BYTES)  # 43 base64 chars
        full_key = f"{KEY_PREFIX}{raw}"

        # Hash for storage
        key_hash = self._hash_key(full_key)
        prefix = full_key[: len(KEY_PREFIX) + 8] + "..."  # frd_live_ABCd1234...

        key_id = self.db.create_api_key(user_id, key_hash, prefix, label)

        return full_key, {
            "id": key_id,
            "key_prefix": prefix,
            "label": label,
        }

    def _hash_key(self, key: str) -> str:
        """SHA-256 hash of the API key."""
        return hashlib.sha256(key.encode()).hexdigest()

    # ── Validation ──

    def validate_key(self, key: str):
        """Validate a raw API key against stored hash.

        Returns the key record (dict) if valid and active, else None.
        """
        if not key or not key.startswith(KEY_PREFIX):
            return None

        key_hash = self._hash_key(key)
        record = self.db.get_api_key_by_hash(key_hash)
        if not record:
            return None
        if record.get("is_revoked") or not record.get("is_active"):
            return None

        # Touch last_used_at
        self.db.update_api_key_last_used(record["id"])
        return record

    def verify_key_hash(self, key: str, stored_hash: str) -> bool:
        """Constant-time comparison of a raw key against a stored hash."""
        computed = self._hash_key(key)
        return hmac.compare_digest(computed, stored_hash)

    # ── Key lifecycle ──

    def revoke_key(self, key_id, user_id):
        """Revoke an API key by ID (scoped to user)."""
        return self.db.revoke_api_key(key_id, user_id)

    def list_keys(self, user_id):
        """List all keys for a user (without exposing hashes)."""
        return self.db.get_api_keys_for_user(user_id)

    def get_key_count(self, user_id):
        """Count active (non-revoked) keys for a user."""
        return self.db.count_active_keys(user_id)

    def regenerate_key(self, user_id, old_key_id, label=None):
        """Revoke an old key and create a new one in one operation.

        Returns (full_key, display_data) like generate_key().
        """
        # Revoke old
        self.db.revoke_api_key(old_key_id, user_id)

        # Determine label
        old_keys = self.db.get_api_keys_for_user(user_id)
        old_label = "Regenerated"
        for k in old_keys:
            if k["id"] == old_key_id:
                old_label = k.get("label", "Regenerated")
                break

        return self.generate_key(user_id, label=label or f"{old_label} (replacement)")
