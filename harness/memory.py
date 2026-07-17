"""Friday AI Runtime Harness — Memory Management.

Structured memory with persistence, importance scoring, TTL-based
expiration, and recall. Uses SQLite for durable storage.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import MemoryEntry, MemoryType


class MemoryManager:
    """Persistent memory store with importance scoring, tagging, and TTL."""

    def __init__(self, db_path: str = "data/memory.db"):
        self._db_path = db_path
        self._local = threading.local()
        self._ensure_db()
        self._cache: Dict[str, MemoryEntry] = {}

    @property
    def _conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _ensure_db(self) -> None:
        """Ensure the database and tables exist."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'fact',
                    tags TEXT DEFAULT '[]',
                    importance REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ttl INTEGER
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)
            """)
            conn.commit()
        finally:
            conn.close()

    def store(
        self,
        key: str,
        value: Any,
        memory_type: MemoryType = MemoryType.FACT,
        tags: Optional[List[str]] = None,
        importance: float = 0.5,
        ttl: Optional[int] = None,
    ) -> MemoryEntry:
        """Store a memory entry."""
        now = datetime.utcnow()
        entry = MemoryEntry(
            id=uuid.uuid4().hex[:12],
            key=key,
            value=value,
            memory_type=memory_type,
            tags=tags or [],
            importance=importance,
            created_at=now,
            updated_at=now,
            ttl=ttl,
        )
        self._upsert(entry)
        self._cache[entry.id] = entry
        return entry

    def recall(self, key: str) -> Optional[MemoryEntry]:
        """Recall the most recent memory by key."""
        cursor = self._conn.execute(
            "SELECT * FROM memories WHERE key = ? ORDER BY updated_at DESC LIMIT 1",
            (key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def search(
        self,
        query: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        tags: Optional[List[str]] = None,
        min_importance: float = 0.0,
        limit: int = 20,
    ) -> List[MemoryEntry]:
        """Search memories with filters."""
        conditions = ["1=1"]
        params: List[Any] = []

        if query:
            conditions.append("(key LIKE ? OR value LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        if memory_type:
            conditions.append("memory_type = ?")
            params.append(memory_type.value)

        if min_importance > 0:
            conditions.append("importance >= ?")
            params.append(min_importance)

        sql = f"SELECT * FROM memories WHERE {' AND '.join(conditions)} ORDER BY importance DESC, updated_at DESC LIMIT ?"
        params.append(limit)

        results: List[MemoryEntry] = []
        cursor = self._conn.execute(sql, params)
        for row in cursor.fetchall():
            entry = self._row_to_entry(row)
            if tags:
                if not any(t in entry.tags for t in tags):
                    continue
            results.append(entry)
        return results

    def update(
        self,
        entry_id: str,
        value: Optional[Any] = None,
        importance: Optional[float] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Update an existing memory entry."""
        existing = self._cache.get(entry_id)
        if not existing:
            cursor = self._conn.execute(
                "SELECT * FROM memories WHERE id = ?", (entry_id,)
            )
            row = cursor.fetchone()
            if not row:
                return False
            existing = self._row_to_entry(row)

        if value is not None:
            existing.value = value
        if importance is not None:
            existing.importance = importance
        if tags is not None:
            existing.tags = tags
        existing.updated_at = datetime.utcnow()

        self._upsert(existing)
        self._cache[entry_id] = existing
        return True

    def delete(self, entry_id: str) -> bool:
        """Delete a memory entry."""
        self._conn.execute("DELETE FROM memories WHERE id = ?", (entry_id,))
        self._conn.commit()
        self._cache.pop(entry_id, None)
        return True

    def forget(self, key: str) -> bool:
        """Delete all memories with a given key."""
        self._conn.execute("DELETE FROM memories WHERE key = ?", (key,))
        self._conn.commit()
        # Clean cache
        to_delete = [k for k, v in self._cache.items() if v.key == key]
        for k in to_delete:
            del self._cache[k]
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get memory store statistics."""
        cursor = self._conn.execute("SELECT COUNT(*) as count FROM memories")
        total = cursor.fetchone()["count"]

        cursor = self._conn.execute(
            "SELECT memory_type, COUNT(*) as count FROM memories GROUP BY memory_type"
        )
        by_type = {row["memory_type"]: row["count"] for row in cursor.fetchall()}

        cursor = self._conn.execute("SELECT AVG(importance) as avg_imp FROM memories")
        avg_imp = cursor.fetchone()["avg_imp"] or 0.0

        return {
            "total_entries": total,
            "by_type": by_type,
            "avg_importance": round(avg_imp, 3),
            "cache_size": len(self._cache),
        }

    def expire_old(self) -> int:
        """Remove expired TTL entries. Returns count removed."""
        now = datetime.utcnow()
        cursor = self._conn.execute(
            "SELECT id, created_at, ttl FROM memories WHERE ttl IS NOT NULL"
        )
        removed = 0
        for row in cursor.fetchall():
            created = datetime.fromisoformat(row["created_at"])
            if (now - created).total_seconds() > row["ttl"]:
                self._conn.execute(
                    "DELETE FROM memories WHERE id = ?", (row["id"],)
                )
                self._cache.pop(row["id"], None)
                removed += 1
        if removed > 0:
            self._conn.commit()
        return removed

    # ── Internal ─────────────────────────────────────────────────────────────

    def _upsert(self, entry: MemoryEntry) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO memories
               (id, key, value, memory_type, tags, importance, created_at, updated_at, ttl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.key,
                json.dumps(entry.value) if not isinstance(entry.value, str) else entry.value,
                entry.memory_type.value,
                json.dumps(entry.tags),
                entry.importance,
                entry.created_at.isoformat(),
                entry.updated_at.isoformat(),
                entry.ttl,
            ),
        )
        self._conn.commit()

    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        tags = json.loads(row["tags"]) if isinstance(row["tags"], str) else (row["tags"] or [])
        raw_value = row["value"]
        try:
            value = json.loads(raw_value) if raw_value.startswith(("{", "[")) else raw_value
        except (json.JSONDecodeError, ValueError):
            value = raw_value

        return MemoryEntry(
            id=row["id"],
            key=row["key"],
            value=value,
            memory_type=MemoryType(row["memory_type"]),
            tags=tags,
            importance=row["importance"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            ttl=row["ttl"],
        )
