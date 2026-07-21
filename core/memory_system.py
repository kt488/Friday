"""Friday Persistent Memory & Context System.

Wraps the harness memory manager with automatic extraction, project tracking,
relationship graphs, task tracking, adaptive recall, and a learning loop.

Memory Hierarchy (highest → lowest priority):
  1. System Instructions
  2. Safety Rules
  3. User Profile & Preferences
  4. Long-Term Memory (SQLite)
  5. Current Conversation
  6. Retrieved Knowledge (RAG)
  7. External Tools
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field


# ── Types ──────────────────────────────────────────────────────────────────────

class MemoryDomain(Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    PROFILE = "profile"
    PROJECT = "project"
    DECISION = "decision"
    ERROR = "error"
    WORKFLOW = "workflow"
    TASK = "task"
    CODE = "code"
    RELATIONSHIP = "relationship"
    CONTEXT = "context"


class TaskStatus(Enum):
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class MemoryItem:
    """A single memory with confidence scoring and relationships."""
    id: str
    domain: MemoryDomain
    key: str
    value: Any
    importance: float  # 0.0 - 1.0
    confidence: float  # 0.0 - 1.0, increases with confirmation
    source: str        # "user", "inference", "system", "correction"
    tags: List[str]
    related_ids: List[str]
    created_at: str
    updated_at: str
    ttl: Optional[int] = None  # seconds, None = permanent


@dataclass
class TaskItem:
    """Tracked task with status and relationships."""
    id: str
    description: str
    status: TaskStatus
    project: Optional[str] = None
    priority: int = 0  # 0-5
    created_at: str
    updated_at: str
    tags: List[str] = field(default_factory=list)


@dataclass
class RelationshipEdge:
    """A relationship between two entities."""
    source_id: str
    target_id: str
    relation_type: str  # e.g. "depends_on", "part_of", "connected_to"
    weight: float = 1.0


# ── Persistent Memory System ───────────────────────────────────────────────────

class PersistentMemory:
    """Central memory system with auto-extraction, relationships, and recall.

    Uses SQLite for durable storage with WAL mode for concurrent access.
    """

    def __init__(self, db_path: str = "data/persistent_memory.db"):
        self._db_path = db_path
        self._local = threading.local()
        self._cache: Dict[str, MemoryItem] = {}
        self._task_cache: Dict[str, TaskItem] = {}
        self._ensure_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _ensure_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    source TEXT NOT NULL DEFAULT 'inference',
                    tags TEXT NOT NULL DEFAULT '[]',
                    related_ids TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ttl INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_mem_key ON memories(key);
                CREATE INDEX IF NOT EXISTS idx_mem_domain ON memories(domain);
                CREATE INDEX IF NOT EXISTS idx_mem_importance ON memories(importance);
                CREATE INDEX IF NOT EXISTS idx_mem_confidence ON memories(confidence);

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    project TEXT,
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_task_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_task_project ON tasks(project);

                CREATE TABLE IF NOT EXISTS relationships (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, relation_type)
                );
                CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id);
                CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id);

                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    topics TEXT NOT NULL DEFAULT '[]',
                    decisions TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conv_id ON conversation_summaries(conversation_id);
            """)
            conn.commit()
        finally:
            conn.close()

    # ── Store / Recall ──────────────────────────────────────────────────────

    def store(
        self,
        key: str,
        value: Any,
        domain: MemoryDomain = MemoryDomain.FACT,
        importance: float = 0.5,
        confidence: float = 0.5,
        source: str = "inference",
        tags: Optional[List[str]] = None,
        related_ids: Optional[List[str]] = None,
        ttl: Optional[int] = None,
    ) -> MemoryItem:
        """Store a memory. If key exists, update with increased confidence."""
        now = datetime.utcnow().isoformat() + "Z"

        # Check for existing
        existing = self._find_existing(key, domain)
        if existing:
            existing.value = value
            existing.importance = max(existing.importance, importance)
            existing.confidence = min(1.0, existing.confidence + 0.1)
            existing.updated_at = now
            if tags:
                existing.tags = list(set(existing.tags + tags))
            if related_ids:
                existing.related_ids = list(set(existing.related_ids + related_ids))
            self._upsert_memory(existing)
            self._cache[existing.id] = existing
            return existing

        item = MemoryItem(
            id=uuid.uuid4().hex[:12],
            domain=domain,
            key=key,
            value=value,
            importance=importance,
            confidence=confidence,
            source=source,
            tags=tags or [],
            related_ids=related_ids or [],
            created_at=now,
            updated_at=now,
            ttl=ttl,
        )
        self._upsert_memory(item)
        self._cache[item.id] = item
        return item

    def recall(self, key: str, domain: Optional[MemoryDomain] = None) -> Optional[MemoryItem]:
        """Recall the most recent memory by key, optionally filtered by domain."""
        item = self._find_existing(key, domain)
        return item

    def search(
        self,
        query: Optional[str] = None,
        domain: Optional[MemoryDomain] = None,
        tags: Optional[List[str]] = None,
        min_importance: float = 0.0,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> List[MemoryItem]:
        """Search memories with filters. Returns sorted by importance desc."""
        conditions = ["1=1"]
        params: List[Any] = []

        if query:
            conditions.append("(key LIKE ? OR value LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        if domain:
            conditions.append("domain = ?")
            params.append(domain.value)

        if min_importance > 0:
            conditions.append("importance >= ?")
            params.append(min_importance)

        if min_confidence > 0:
            conditions.append("confidence >= ?")
            params.append(min_confidence)

        sql = f"SELECT * FROM memories WHERE {' AND '.join(conditions)} ORDER BY importance DESC, confidence DESC, updated_at DESC LIMIT ?"
        params.append(limit)

        results: List[MemoryItem] = []
        cursor = self._conn.execute(sql, params)
        for row in cursor.fetchall():
            item = self._row_to_item(row)
            if tags and not any(t in item.tags for t in tags):
                continue
            results.append(item)
        return results

    def delete(self, key: str, domain: Optional[MemoryDomain] = None) -> bool:
        """Delete memories matching key and optional domain."""
        conditions = ["key = ?"]
        params: List[Any] = [key]
        if domain:
            conditions.append("domain = ?")
            params.append(domain.value)
        self._conn.execute(f"DELETE FROM memories WHERE {' AND '.join(conditions)}", params)
        self._conn.commit()
        # Clean cache
        to_del = [k for k, v in self._cache.items() if v.key == key and (domain is None or v.domain == domain)]
        for k in to_del:
            del self._cache[k]
        return True

    # ── Relationship Graph ──────────────────────────────────────────────────

    def relate(
        self,
        source_key: str,
        target_key: str,
        relation_type: str = "related_to",
        weight: float = 1.0,
    ) -> None:
        """Create a relationship between two memory entries by key."""
        now = datetime.utcnow().isoformat() + "Z"
        self._conn.execute(
            """INSERT OR REPLACE INTO relationships (source_id, target_id, relation_type, weight, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (source_key, target_key, relation_type, weight, now),
        )
        self._conn.commit()

    def get_related(
        self,
        key: str,
        relation_type: Optional[str] = None,
        max_depth: int = 1,
    ) -> List[Tuple[str, str, float]]:
        """Get related entities for a key. Returns [(related_key, relation_type, weight)]."""
        if max_depth == 1:
            if relation_type:
                rows = self._conn.execute(
                    """SELECT target_id, relation_type, weight FROM relationships
                       WHERE source_id = ? AND relation_type = ?
                       UNION
                       SELECT source_id, relation_type, weight FROM relationships
                       WHERE target_id = ? AND relation_type = ?""",
                    (key, relation_type, key, relation_type),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT target_id, relation_type, weight FROM relationships
                       WHERE source_id = ?
                       UNION
                       SELECT source_id, relation_type, weight FROM relationships
                       WHERE target_id = ?""",
                    (key, key),
                ).fetchall()
            return [(r["target_id"], r["relation_type"], r["weight"]) for r in rows]
        # Multi-depth BFS
        visited: Set[str] = {key}
        results: List[Tuple[str, str, float]] = []
        frontier = [key]
        for _ in range(max_depth):
            next_frontier: List[str] = []
            for f in frontier:
                rows = self._conn.execute(
                    """SELECT target_id, relation_type, weight FROM relationships WHERE source_id = ?
                       UNION
                       SELECT source_id, relation_type, weight FROM relationships WHERE target_id = ?""",
                    (f, f),
                ).fetchall()
                for r in rows:
                    related_key = r["target_id"]
                    if related_key not in visited:
                        visited.add(related_key)
                        results.append((related_key, r["relation_type"], r["weight"]))
                        next_frontier.append(related_key)
            frontier = next_frontier
        return results

    # ── Project Memory ──────────────────────────────────────────────────────

    def track_project(
        self,
        name: str,
        description: str,
        tags: Optional[List[str]] = None,
    ) -> MemoryItem:
        """Create or update a project memory."""
        return self.store(
            key=f"project:{name}",
            value=json.dumps({
                "name": name,
                "description": description,
                "files": [],
                "apis": [],
                "features_completed": [],
                "features_pending": [],
                "bugs": [],
                "decisions": [],
            }),
            domain=MemoryDomain.PROJECT,
            importance=0.9,
            confidence=0.9,
            source="user",
            tags=["project"] + (tags or []),
        )

    def add_project_file(self, project: str, file_path: str) -> None:
        """Track a file under a project."""
        key = f"project:{project}"
        item = self.recall(key, MemoryDomain.PROJECT)
        if not item:
            return
        data = json.loads(item.value) if isinstance(item.value, str) else item.value
        if file_path not in data["files"]:
            data["files"].append(file_path)
        self.store(key, json.dumps(data), domain=MemoryDomain.PROJECT, importance=item.importance, confidence=item.confidence)
        self.relate(key, file_path, "has_file")

    def get_project_context(self, project: str) -> Optional[Dict[str, Any]]:
        """Get full project context as dict."""
        item = self.recall(f"project:{project}", MemoryDomain.PROJECT)
        if not item:
            return None
        data = json.loads(item.value) if isinstance(item.value, str) else item.value
        # Enrich with related memories
        related = self.get_related(f"project:{project}")
        for rel_key, rel_type, _ in related:
            if rel_type == "has_file":
                if rel_key not in data["files"]:
                    data["files"].append(rel_key)
        return data

    # ── Task Tracking ───────────────────────────────────────────────────────

    def create_task(
        self,
        description: str,
        project: Optional[str] = None,
        priority: int = 0,
        tags: Optional[List[str]] = None,
    ) -> TaskItem:
        """Create a tracked task."""
        now = datetime.utcnow().isoformat() + "Z"
        task = TaskItem(
            id=uuid.uuid4().hex[:12],
            description=description,
            status=TaskStatus.ACTIVE,
            project=project,
            priority=priority,
            created_at=now,
            updated_at=now,
            tags=tags or [],
        )
        self._conn.execute(
            """INSERT INTO tasks (id, description, status, project, priority, created_at, updated_at, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (task.id, task.description, task.status.value, task.project, task.priority,
             task.created_at, task.updated_at, json.dumps(task.tags)),
        )
        self._conn.commit()
        self._task_cache[task.id] = task
        # Also store as memory
        self.store(f"task:{task.id}", task.description, domain=MemoryDomain.TASK,
                   importance=0.7, tags=tags)
        return task

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        priority: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Update a task's status/priority/tags."""
        task = self._task_cache.get(task_id)
        if not task:
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return False
            task = self._row_to_task(row)
        now = datetime.utcnow().isoformat() + "Z"
        if status:
            task.status = status
        if priority is not None:
            task.priority = priority
        if tags:
            task.tags = list(set(task.tags + tags))
        task.updated_at = now
        self._conn.execute(
            "UPDATE tasks SET status=?, priority=?, updated_at=?, tags=? WHERE id=?",
            (task.status.value, task.priority, task.updated_at, json.dumps(task.tags), task.id),
        )
        self._conn.commit()
        self._task_cache[task_id] = task
        return True

    def list_tasks(self, status: Optional[TaskStatus] = None, project: Optional[str] = None) -> List[TaskItem]:
        """List tasks, optionally filtered."""
        conditions = ["1=1"]
        params: List[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        if project:
            conditions.append("project = ?")
            params.append(project)
        rows = self._conn.execute(
            f"SELECT * FROM tasks WHERE {' AND '.join(conditions)} ORDER BY priority DESC, created_at DESC",
            params,
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def summarize_tasks(self) -> str:
        """Get a human-readable summary of all active/waiting tasks."""
        active = self.list_tasks(TaskStatus.ACTIVE)
        waiting = self.list_tasks(TaskStatus.WAITING)
        lines = []
        if active:
            lines.append("Active tasks:")
            for t in active:
                proj = f" [{t.project}]" if t.project else ""
                lines.append(f"  {t.id} {proj}: {t.description} (p{t.priority})")
        if waiting:
            lines.append("Waiting tasks:")
            for t in waiting:
                proj = f" [{t.project}]" if t.project else ""
                lines.append(f"  {t.id} {proj}: {t.description}")
        if not lines:
            lines.append("No active or waiting tasks.")
        return "\n".join(lines)

    # ── Conversation Context ────────────────────────────────────────────────

    def summarize_conversation(
        self,
        conv_id: str,
        messages: List[Dict[str, Any]],
        decisions: Optional[List[str]] = None,
        topics: Optional[List[str]] = None,
    ) -> str:
        """Store a conversation summary for future recall."""
        now = datetime.utcnow().isoformat() + "Z"
        existing = self._conn.execute(
            "SELECT * FROM conversation_summaries WHERE conversation_id = ? ORDER BY updated_at DESC LIMIT 1",
            (conv_id,),
        ).fetchone()

        summary_text = self._condense_messages(messages)
        if decisions is None:
            decisions = []
        if topics is None:
            topics = self._extract_topics(summary_text)

        if existing:
            old_decisions = json.loads(existing["decisions"])
            old_topics = json.loads(existing["topics"])
            all_decisions = list(set(old_decisions + decisions))
            all_topics = list(set(old_topics + topics))
            self._conn.execute(
                """UPDATE conversation_summaries
                   SET summary=?, message_count=?, topics=?, decisions=?, updated_at=?
                   WHERE id=?""",
                (summary_text, len(messages), json.dumps(all_topics), json.dumps(all_decisions), now, existing["id"]),
            )
        else:
            conv_id_str = uuid.uuid4().hex[:12]
            self._conn.execute(
                """INSERT INTO conversation_summaries
                   (id, conversation_id, summary, message_count, topics, decisions, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (conv_id_str, conv_id, summary_text, len(messages),
                 json.dumps(topics), json.dumps(decisions), now, now),
            )
        self._conn.commit()
        return summary_text

    def get_conversation_context(self, conv_id: str) -> Optional[Dict[str, Any]]:
        """Get stored conversation summary for context injection."""
        row = self._conn.execute(
            "SELECT * FROM conversation_summaries WHERE conversation_id = ? ORDER BY updated_at DESC LIMIT 1",
            (conv_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "summary": row["summary"],
            "message_count": row["message_count"],
            "topics": json.loads(row["topics"]),
            "decisions": json.loads(row["decisions"]),
            "updated_at": row["updated_at"],
        }

    # ── Adaptive Recall ─────────────────────────────────────────────────────

    def get_relevant_context(self, query: str, max_items: int = 10) -> str:
        """Search all memory stores and return a compiled context string for prompt injection."""
        parts: List[str] = []

        # 1. Search memories
        memories = self.search(query=query, min_importance=0.3, limit=max_items)
        if memories:
            mem_lines = []
            for m in memories[:5]:
                val = m.value if isinstance(m.value, str) else json.dumps(m.value, indent=2)[:200]
                mem_lines.append(f"  [{m.domain.value}] {m.key}: {val}")
            parts.append("Relevant memories:\n" + "\n".join(mem_lines))

        # 2. Active tasks
        tasks = self.list_tasks(TaskStatus.ACTIVE)
        if tasks:
            parts.append("Active tasks:\n" + "\n".join(f"  {t.description}" for t in tasks[:3]))

        # 3. Relevant projects
        proj_memories = self.search(query=query, domain=MemoryDomain.PROJECT, limit=3)
        for pm in proj_memories:
            data = json.loads(pm.value) if isinstance(pm.value, str) else pm.value
            parts.append(f"Project '{data['name']}': {data['description']}")

        return "\n\n".join(parts) if parts else ""

    # ── Learning Loop ───────────────────────────────────────────────────────

    def learn_from_correction(self, old_key: str, new_value: Any, domain: Optional[MemoryDomain] = None) -> MemoryItem:
        """Update memory on user correction — increases confidence in new value."""
        self.delete(old_key, domain)
        return self.store(
            key=old_key,
            value=new_value,
            domain=domain or MemoryDomain.FACT,
            importance=0.8,
            confidence=0.9,
            source="correction",
            tags=["corrected"],
        )

    def confirm_memory(self, key: str, domain: Optional[MemoryDomain] = None) -> Optional[MemoryItem]:
        """Increase confidence when user confirms a memory."""
        item = self._find_existing(key, domain)
        if not item:
            return None
        item.confidence = min(1.0, item.confidence + 0.15)
        item.updated_at = datetime.utcnow().isoformat() + "Z"
        self._upsert_memory(item)
        self._cache[item.id] = item
        return item

    # ── Code Memory ─────────────────────────────────────────────────────────

    def track_code_context(
        self,
        folder: str,
        description: str,
        conventions: Optional[List[str]] = None,
        apis: Optional[List[str]] = None,
    ) -> MemoryItem:
        """Remember codebase context for a folder/module."""
        value = {
            "folder": folder,
            "description": description,
            "conventions": conventions or [],
            "apis": apis or [],
            "naming": [],
            "env_vars": [],
        }
        return self.store(
            key=f"code:{folder}",
            value=json.dumps(value),
            domain=MemoryDomain.CODE,
            importance=0.8,
            tags=["code", folder],
        )

    def get_code_context(self, folder: str) -> Optional[Dict[str, Any]]:
        """Get remembered context for a code folder."""
        item = self.recall(f"code:{folder}", MemoryDomain.CODE)
        if not item:
            return None
        return json.loads(item.value) if isinstance(item.value, str) else item.value

    # ── Stats & Maintenance ─────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get memory system statistics."""
        mem_count = self._conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
        task_count = self._conn.execute("SELECT COUNT(*) as c FROM tasks").fetchone()["c"]
        rel_count = self._conn.execute("SELECT COUNT(*) as c FROM relationships").fetchone()["c"]
        conv_count = self._conn.execute("SELECT COUNT(*) as c FROM conversation_summaries").fetchone()["c"]
        avg_imp = self._conn.execute("SELECT AVG(importance) as a FROM memories").fetchone()["a"] or 0.0
        return {
            "total_memories": mem_count,
            "total_tasks": task_count,
            "total_relationships": rel_count,
            "total_conversations": conv_count,
            "avg_importance": round(avg_imp, 3),
            "cache_size": len(self._cache),
        }

    def expire_old(self) -> int:
        """Remove expired TTL entries. Returns count removed."""
        now = datetime.utcnow()
        rows = self._conn.execute(
            "SELECT id, created_at, ttl FROM memories WHERE ttl IS NOT NULL"
        ).fetchall()
        removed = 0
        for row in rows:
            created = datetime.fromisoformat(row["created_at"].rstrip("Z"))
            if (now - created).total_seconds() > row["ttl"]:
                self._conn.execute("DELETE FROM memories WHERE id = ?", (row["id"],))
                self._cache.pop(row["id"], None)
                removed += 1
        if removed:
            self._conn.commit()
        return removed

    # ── Self-Check ──────────────────────────────────────────────────────────

    def self_check(self, query: str) -> Dict[str, Any]:
        """Check if relevant context was found before responding."""
        memories = self.search(query=query, min_importance=0.3, limit=5)
        tasks = self.list_tasks(TaskStatus.ACTIVE)
        project_mem = self.search(query=query, domain=MemoryDomain.PROJECT, limit=2)
        return {
            "memories_found": len(memories),
            "active_tasks": len(tasks),
            "projects_found": len(project_mem),
            "has_relevant_context": len(memories) > 0 or len(project_mem) > 0,
        }

    # ── Internal Helpers ────────────────────────────────────────────────────

    def _find_existing(self, key: str, domain: Optional[MemoryDomain] = None) -> Optional[MemoryItem]:
        """Find existing memory by key and optional domain."""
        if domain:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE key = ? AND domain = ? ORDER BY updated_at DESC LIMIT 1",
                (key, domain.value),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE key = ? ORDER BY updated_at DESC LIMIT 1",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_item(row)

    def _upsert_memory(self, item: MemoryItem) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO memories
               (id, domain, key, value, importance, confidence, source, tags, related_ids, created_at, updated_at, ttl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id, item.domain.value, item.key,
                item.value if isinstance(item.value, str) else json.dumps(item.value),
                item.importance, item.confidence, item.source,
                json.dumps(item.tags), json.dumps(item.related_ids),
                item.created_at, item.updated_at, item.ttl,
            ),
        )
        self._conn.commit()

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        tags = json.loads(row["tags"]) if isinstance(row["tags"], str) else (row["tags"] or [])
        related = json.loads(row["related_ids"]) if isinstance(row["related_ids"], str) else (row["related_ids"] or [])
        raw_value = row["value"]
        try:
            value = json.loads(raw_value) if raw_value.startswith(("{", "[")) else raw_value
        except (json.JSONDecodeError, ValueError):
            value = raw_value
        return MemoryItem(
            id=row["id"],
            domain=MemoryDomain(row["domain"]),
            key=row["key"],
            value=value,
            importance=row["importance"],
            confidence=row["confidence"],
            source=row["source"],
            tags=tags,
            related_ids=related,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            ttl=row["ttl"],
        )

    def _row_to_task(self, row: sqlite3.Row) -> TaskItem:
        return TaskItem(
            id=row["id"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            project=row["project"],
            priority=row["priority"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else (row["tags"] or []),
        )

    @staticmethod
    def _condense_messages(messages: List[Dict[str, Any]]) -> str:
        """Condense a list of messages into a brief summary string."""
        if not messages:
            return ""
        # Take last N messages and summarize
        recent = messages[-10:] if len(messages) > 10 else messages
        lines = []
        for m in recent:
            role = m.get("role", "unknown")
            content = m.get("message", m.get("content", ""))
            if isinstance(content, str):
                content = content[:200]
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    @staticmethod
    def _extract_topics(text: str) -> List[str]:
        """Extract likely topics from text (simple keyword extraction)."""
        common_words = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
                        "to", "for", "of", "with", "and", "or", "but", "not", "be", "this"}
        words = re.findall(r'\b[A-Za-z][A-Za-z0-9]{3,}\b', text.lower())
        freq: Dict[str, int] = {}
        for w in words:
            if w not in common_words:
                freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.items(), key=lambda x: -x[1])
        return [w for w, _ in sorted_words[:10]]
