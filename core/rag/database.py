"""RAG database — vector store, chunks, knowledge sources, embeddings tables.

All tables use the existing friday.db with WAL mode. FTS5 for BM25 keyword search.
"""

import json
import os
import sqlite3
import struct
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "friday.db")


def _parse_iso(dt_str: Optional[str]) -> str:
    if dt_str:
        return dt_str
    return datetime.utcnow().isoformat()


class RAGDatabase:
    """Manages RAG-specific tables: chunks, embeddings, knowledge_sources, FTS."""

    def __init__(self, db_path: Optional[str] = None):
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

            # ── Chunks table ──────────────────────────────────────────
            c.execute("""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    workspace_id TEXT DEFAULT 'default',
                    organization_id TEXT,
                    team_id TEXT,
                    user_id TEXT,
                    project_id TEXT,
                    conversation_id TEXT,
                    session_id TEXT,
                    source_type TEXT NOT NULL DEFAULT 'document',
                    source_id TEXT DEFAULT '',
                    source_path TEXT,
                    source_url TEXT,
                    chunk_type TEXT DEFAULT 'text',
                    language TEXT,
                    mime_type TEXT,
                    filename TEXT,
                    heading TEXT,
                    section TEXT,
                    parent_id TEXT,
                    position INTEGER DEFAULT 0,
                    importance REAL DEFAULT 0.5,
                    access_level INTEGER DEFAULT 4,
                    version INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    tokens INTEGER DEFAULT 0,
                    hash TEXT,
                    is_sanitized INTEGER DEFAULT 0,
                    contains_pii INTEGER DEFAULT 0,
                    tags TEXT DEFAULT '[]',
                    custom_fields TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                )
            """)

            # ── Vector embeddings table ───────────────────────────────
            c.execute("""
                CREATE TABLE IF NOT EXISTS rag_embeddings (
                    chunk_id TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    model TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE
                )
            """)

            # ── Knowledge sources table ───────────────────────────────
            c.execute("""
                CREATE TABLE IF NOT EXISTS rag_knowledge_sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'document',
                    uri TEXT DEFAULT '',
                    config TEXT DEFAULT '{}',
                    is_active INTEGER DEFAULT 1,
                    last_indexed_at TEXT,
                    error TEXT,
                    workspace_id TEXT DEFAULT 'default',
                    user_id TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # ── Memory records table (RAG memory) ─────────────────────
            c.execute("""
                CREATE TABLE IF NOT EXISTS rag_memory (
                    id TEXT PRIMARY KEY,
                    chunk_id TEXT,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'short_term',
                    importance REAL DEFAULT 0.5,
                    access_count INTEGER DEFAULT 0,
                    last_accessed_at TEXT,
                    workspace_id TEXT DEFAULT 'default',
                    user_id TEXT,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
            """)

            # ─── Tenant isolation index ───────────────────────────────
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_chunks_tenant
                ON rag_chunks(workspace_id, user_id, source_type)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_chunks_source
                ON rag_chunks(source_id)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_embeddings_model
                ON rag_embeddings(model)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_memory_tenant
                ON rag_memory(workspace_id, user_id, memory_type)
            """)

            # ── FTS5 for BM25 keyword search ──────────────────────────
            try:
                c.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
                        content,
                        chunk_id UNINDEXED,
                        source_type UNINDEXED,
                        workspace_id UNINDEXED,
                        user_id UNINDEXED,
                        content='rag_chunks',
                        content_rowid='rowid'
                    )
                """)
            except sqlite3.OperationalError:
                pass  # FTS5 may not be available

            conn.commit()

    # ── Chunk CRUD ────────────────────────────────────────────────────────

    def insert_chunk(self, chunk_id: str, content: str, metadata: dict,
                     tokens: int = 0) -> bool:
        """Insert a chunk with its metadata."""
        now = datetime.utcnow().isoformat()
        tags = json.dumps(metadata.get("tags", []))
        custom = json.dumps(metadata.get("custom_fields", {}))
        with self._connect() as conn:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO rag_chunks (
                        id, content, workspace_id, organization_id, team_id,
                        user_id, project_id, conversation_id, session_id,
                        source_type, source_id, source_path, source_url,
                        chunk_type, language, mime_type, filename,
                        heading, section, parent_id, position,
                        importance, access_level, version, is_active,
                        tokens, hash, is_sanitized, contains_pii,
                        tags, custom_fields, created_at, updated_at, expires_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    chunk_id, content,
                    metadata.get("workspace_id", "default"),
                    metadata.get("organization_id"),
                    metadata.get("team_id"),
                    metadata.get("user_id"),
                    metadata.get("project_id"),
                    metadata.get("conversation_id"),
                    metadata.get("session_id"),
                    metadata.get("source_type", "document"),
                    metadata.get("source_id", ""),
                    metadata.get("source_path"),
                    metadata.get("source_url"),
                    metadata.get("chunk_type", "text"),
                    metadata.get("language"),
                    metadata.get("mime_type"),
                    metadata.get("filename"),
                    metadata.get("heading"),
                    metadata.get("section"),
                    metadata.get("parent_id"),
                    metadata.get("position", 0),
                    metadata.get("importance", 0.5),
                    metadata.get("access_level", 4),
                    metadata.get("version", 1),
                    1,
                    tokens,
                    metadata.get("hash", ""),
                    1 if metadata.get("is_sanitized") else 0,
                    1 if metadata.get("contains_pii") else 0,
                    tags, custom, now, now,
                    metadata.get("expires_at"),
                ))
                conn.commit()

                # Also insert into FTS
                try:
                    row = conn.execute(
                        "SELECT rowid FROM rag_chunks WHERE id = ?", (chunk_id,)
                    ).fetchone()
                    if row:
                        conn.execute(
                            "INSERT OR REPLACE INTO rag_chunks_fts (rowid, content, chunk_id, source_type, workspace_id, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                            (row["rowid"], content, chunk_id,
                             metadata.get("source_type", "document"),
                             metadata.get("workspace_id", "default"),
                             metadata.get("user_id", ""))
                        )
                except sqlite3.OperationalError:
                    pass
                return True
            except Exception as e:
                print(f"[RAG DB] insert_chunk error: {e}")
                return False

    def get_chunk(self, chunk_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM rag_chunks WHERE id = ?", (chunk_id,)
            ).fetchone()
            if row:
                d = dict(row)
                d["tags"] = json.loads(d.get("tags", "[]"))
                d["custom_fields"] = json.loads(d.get("custom_fields", "{}"))
                return d
            return None

    def delete_chunk(self, chunk_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM rag_chunks WHERE id = ?", (chunk_id,))
            conn.commit()
            return True

    def delete_chunks_by_source(self, source_id: str, workspace_id: str = "default"):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM rag_chunks WHERE source_id = ? AND workspace_id = ?",
                (source_id, workspace_id)
            )
            conn.commit()

    # ── Embedding CRUD ───────────────────────────────────────────────────

    def insert_embedding(self, chunk_id: str, vector: List[float],
                         model: str, dimension: int) -> bool:
        """Store a vector embedding as binary blob."""
        blob = struct.pack(f"{len(vector)}f", *vector)
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO rag_embeddings (chunk_id, vector, model, dimension, created_at) VALUES (?, ?, ?, ?, ?)",
                    (chunk_id, blob, model, dimension, now)
                )
                conn.commit()
                return True
            except Exception as e:
                print(f"[RAG DB] insert_embedding error: {e}")
                return False

    def get_embedding(self, chunk_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM rag_embeddings WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
            if row:
                d = dict(row)
                vec_bytes = d["vector"]
                dim = d["dimension"]
                d["vector"] = list(struct.unpack(f"{dim}f", vec_bytes))
                return d
            return None

    def get_all_embeddings(self, model: Optional[str] = None,
                           workspace_id: Optional[str] = None) -> List[dict]:
        """Load all embeddings for ANN search, with optional filtering."""
        query = """
            SELECT e.chunk_id, e.vector, e.dimension, e.model,
                   c.content, c.workspace_id, c.user_id, c.source_type,
                   c.importance, c.created_at, c.tags
            FROM rag_embeddings e
            JOIN rag_chunks c ON e.chunk_id = c.id
            WHERE c.is_active = 1
        """
        params = []
        if model:
            query += " AND e.model = ?"
            params.append(model)
        if workspace_id:
            query += " AND c.workspace_id = ?"
            params.append(workspace_id)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                vec_bytes = d["vector"]
                dim = d["dimension"]
                d["vector"] = list(struct.unpack(f"{dim}f", vec_bytes))
                d["tags"] = json.loads(d.get("tags", "[]"))
                results.append(d)
            return results

    def count_embeddings(self, workspace_id: Optional[str] = None) -> int:
        query = "SELECT COUNT(*) FROM rag_embeddings e JOIN rag_chunks c ON e.chunk_id = c.id WHERE c.is_active = 1"
        params = []
        if workspace_id:
            query += " AND c.workspace_id = ?"
            params.append(workspace_id)
        with self._connect() as conn:
            return conn.execute(query, params).fetchone()[0]

    # ── FTS / BM25 Search ────────────────────────────────────────────────

    def bm25_search(self, query: str, workspace_id: str = "default",
                    user_id: Optional[str] = None,
                    limit: int = 20) -> List[dict]:
        """Full-text search using FTS5 BM25 scoring."""
        try:
            with self._connect() as conn:
                q = " AND ".join(query.split()[:10])  # sanitize
                sql = """
                    SELECT c.*, rank
                    FROM rag_chunks_fts f
                    JOIN rag_chunks c ON f.chunk_id = c.id
                    WHERE rag_chunks_fts MATCH ?
                    AND c.workspace_id = ?
                    AND c.is_active = 1
                """
                params = [q, workspace_id]
                if user_id:
                    sql += " AND (c.user_id IS NULL OR c.user_id = ?)"
                    params.append(user_id)
                sql += " ORDER BY rank LIMIT ?"
                params.append(limit)

                rows = conn.execute(sql, params).fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    d["tags"] = json.loads(d.get("tags", "[]"))
                    d["bm25_score"] = -d.get("rank", 0)  # negate so higher=better
                    results.append(d)
                return results
        except sqlite3.OperationalError:
            # FTS5 not available, fall back to LIKE
            return self._like_search(query, workspace_id, user_id, limit)

    def _like_search(self, query: str, workspace_id: str = "default",
                     user_id: Optional[str] = None,
                     limit: int = 20) -> List[dict]:
        """Fallback keyword search using LIKE when FTS5 unavailable."""
        terms = query.split()
        conditions = " AND ".join(f"c.content LIKE ?" for _ in terms)
        params = [f"%{t}%" for t in terms]
        sql = f"""
            SELECT c.* FROM rag_chunks c
            WHERE {conditions}
            AND c.workspace_id = ?
            AND c.is_active = 1
        """
        params.append(workspace_id)
        if user_id:
            sql += " AND (c.user_id IS NULL OR c.user_id = ?)"
            params.append(user_id)
        sql += " LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["tags"] = json.loads(d.get("tags", "[]"))
                d["bm25_score"] = 0.0
                results.append(d)
            return results

    # ── Metadata-filtered search ─────────────────────────────────────────

    def search_by_metadata(self, filters: Dict[str, Any],
                           limit: int = 20) -> List[dict]:
        """Search chunks by metadata filters."""
        conditions = ["c.is_active = 1"]
        params = []
        for key, value in filters.items():
            col = f"c.{key}"
            if isinstance(value, list):
                placeholders = ",".join("?" for _ in value)
                conditions.append(f"{col} IN ({placeholders})")
                params.extend(value)
            else:
                conditions.append(f"{col} = ?")
                params.append(value)

        sql = f"SELECT c.* FROM rag_chunks c WHERE {' AND '.join(conditions)} LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["tags"] = json.loads(d.get("tags", "[]"))
                results.append(d)
            return results

    # ── Knowledge Sources CRUD ───────────────────────────────────────────

    def insert_source(self, source_id: str, name: str, source_type: str,
                      uri: str = "", config: Optional[dict] = None,
                      workspace_id: str = "default",
                      user_id: Optional[str] = None) -> bool:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            try:
                conn.execute("""
                    INSERT INTO rag_knowledge_sources
                    (id, name, source_type, uri, config, is_active, workspace_id, user_id, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                """, (source_id, name, source_type, uri,
                      json.dumps(config or {}), workspace_id, user_id, now))
                conn.commit()
                return True
            except Exception as e:
                print(f"[RAG DB] insert_source error: {e}")
                return False

    def update_source_indexed(self, source_id: str, error: Optional[str] = None):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE rag_knowledge_sources SET last_indexed_at = ?, error = ? WHERE id = ?",
                (now, error, source_id)
            )
            conn.commit()

    def list_sources(self, workspace_id: str = "default",
                     source_type: Optional[str] = None) -> List[dict]:
        sql = "SELECT * FROM rag_knowledge_sources WHERE workspace_id = ?"
        params = [workspace_id]
        if source_type:
            sql += " AND source_type = ?"
            params.append(source_type)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    # ── Memory CRUD ──────────────────────────────────────────────────────

    def insert_memory(self, mem_id: str, content: str, memory_type: str,
                      importance: float = 0.5, chunk_id: Optional[str] = None,
                      workspace_id: str = "default",
                      user_id: Optional[str] = None,
                      metadata: Optional[dict] = None) -> bool:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            try:
                conn.execute("""
                    INSERT INTO rag_memory
                    (id, chunk_id, content, memory_type, importance,
                     access_count, last_accessed_at, workspace_id, user_id,
                     metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """, (mem_id, chunk_id, content, memory_type, importance,
                      now, workspace_id, user_id,
                      json.dumps(metadata or {}), now))
                conn.commit()
                return True
            except Exception as e:
                print(f"[RAG DB] insert_memory error: {e}")
                return False

    def search_memory(self, query: str, workspace_id: str = "default",
                      user_id: Optional[str] = None,
                      memory_type: Optional[str] = None,
                      limit: int = 20) -> List[dict]:
        sql = """
            SELECT m.* FROM rag_memory m
            WHERE m.workspace_id = ?
        """
        params = [workspace_id]
        if user_id:
            sql += " AND m.user_id = ?"
            params.append(user_id)
        if memory_type:
            sql += " AND m.memory_type = ?"
            params.append(memory_type)
        sql += " ORDER BY m.importance DESC, m.last_accessed_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["metadata"] = json.loads(d.get("metadata", "{}"))
                results.append(d)
            return results

    def update_memory_access(self, mem_id: str):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE rag_memory SET access_count = access_count + 1, last_accessed_at = ? WHERE id = ?",
                (now, mem_id)
            )
            conn.commit()

    def delete_expired_memory(self):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM rag_memory WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
            conn.commit()

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self, workspace_id: str = "default") -> dict:
        with self._connect() as conn:
            total_chunks = conn.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE workspace_id = ? AND is_active = 1",
                (workspace_id,)
            ).fetchone()[0]
            total_embeddings = conn.execute(
                "SELECT COUNT(*) FROM rag_embeddings"
            ).fetchone()[0]
            total_sources = conn.execute(
                "SELECT COUNT(*) FROM rag_knowledge_sources WHERE workspace_id = ?",
                (workspace_id,)
            ).fetchone()[0]
            total_memories = conn.execute(
                "SELECT COUNT(*) FROM rag_memory WHERE workspace_id = ?",
                (workspace_id,)
            ).fetchone()[0]
            by_type = conn.execute("""
                SELECT source_type, COUNT(*) as cnt FROM rag_chunks
                WHERE workspace_id = ? AND is_active = 1
                GROUP BY source_type
            """, (workspace_id,)).fetchall()

            return {
                "total_chunks": total_chunks,
                "total_embeddings": total_embeddings,
                "total_sources": total_sources,
                "total_memories": total_memories,
                "chunks_by_type": {r["source_type"]: r["cnt"] for r in by_type},
            }
