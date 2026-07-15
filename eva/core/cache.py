"""Caching system for evaluation results with LRU and SQLite persistence."""

import json
import logging
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CacheError(Exception):
    """Raised on cache operation errors."""


class MemoryCache:
    """Thread-safe LRU cache with TTL support.

    Args:
        capacity: Maximum number of items.
        ttl: Default time-to-live in seconds.
    """

    def __init__(self, capacity: int = 1000, ttl: int = 3600):
        self.capacity = capacity
        self.default_ttl = ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.

        Args:
            key: Cache key.

        Returns:
            Cached value or None if missing/expired.
        """
        with self._lock:
            if key not in self._cache:
                return None
            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Time-to-live in seconds (default: self.default_ttl).
        """
        with self._lock:
            expiry = time.time() + (ttl if ttl is not None else self.default_ttl)
            self._cache[key] = (value, expiry)
            self._cache.move_to_end(key)
            while len(self._cache) > self.capacity:
                self._cache.popitem(last=False)

    def delete(self, key: str) -> bool:
        """Delete a key from cache.

        Args:
            key: Cache key.

        Returns:
            True if key existed.
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cached items."""
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        """Current number of items in cache."""
        with self._lock:
            return len(self._cache)


class PersistentCache:
    """SQLite-backed persistent cache for evaluation results.

    Args:
        db_path: Path to SQLite database file.
        ttl: Default time-to-live in seconds.
    """

    def __init__(self, db_path: str = "eva/data/cache/eval_cache.db", ttl: int = 86400):
        self.db_path = db_path
        self.default_ttl = ttl
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite database and table."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                "  key TEXT PRIMARY KEY,"
                "  value TEXT NOT NULL,"
                "  expiry REAL NOT NULL,"
                "  created_at REAL NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_expiry ON cache(expiry)"
            )
            conn.commit()
            conn.close()

    def get(self, key: str) -> Optional[Any]:
        """Get value from persistent cache.

        Args:
            key: Cache key.

        Returns:
            Deserialized value or None.
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    "SELECT value, expiry FROM cache WHERE key = ?", (key,)
                )
                row = cursor.fetchone()
                conn.close()

                if row is None:
                    return None

                value_json, expiry = row
                if time.time() > expiry:
                    self.delete(key)
                    return None

                return json.loads(value_json)

            except Exception as e:
                logger.error("Cache read error for key '%s': %s", key, e)
                return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in persistent cache.

        Args:
            key: Cache key.
            value: Value to cache (must be JSON-serializable).
            ttl: Time-to-live in seconds.
        """
        with self._lock:
            try:
                expiry = time.time() + (ttl if ttl is not None else self.default_ttl)
                value_json = json.dumps(value, default=str)

                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "INSERT OR REPLACE INTO cache (key, value, expiry, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (key, value_json, expiry, time.time()),
                )
                conn.commit()
                conn.close()

            except Exception as e:
                logger.error("Cache write error for key '%s': %s", key, e)

    def delete(self, key: str) -> bool:
        """Delete a key from cache.

        Args:
            key: Cache key.

        Returns:
            True if key was deleted.
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                deleted = cursor.rowcount > 0
                conn.commit()
                conn.close()
                return deleted
            except Exception as e:
                logger.error("Cache delete error: %s", e)
                return False

    def clear(self) -> None:
        """Clear all cached items."""
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("DELETE FROM cache")
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("Cache clear error: %s", e)

    def cleanup(self) -> int:
        """Remove expired entries.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute("DELETE FROM cache WHERE expiry < ?", (time.time(),))
                removed = cursor.rowcount
                conn.commit()
                conn.close()
                return removed
            except Exception as e:
                logger.error("Cache cleanup error: %s", e)
                return 0
