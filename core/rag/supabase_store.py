"""Supabase pgvector store — REST API based vector storage & similarity search.

Replaces local SQLite VectorStore with Supabase's pgvector extension for:
- Scalable vector storage on PostgreSQL
- IVFFlat-indexed cosine similarity search
- Built-in multi-tenant isolation via workspace_id
- Cloud-native persistence (survives container restarts)

No ``supabase-py`` required — uses ``requests`` directly against the
Supabase PostgREST and pgvector RPC endpoints.
"""

import json
import os
from typing import Any, Dict, List, Optional

import requests

from core.config import Config


class SupabaseVectorStore:
    """Vector store backed by Supabase pgvector.

    Expects a ``rag_vectors`` table and ``match_vectors()`` RPC function
    to exist in the Supabase project (see schema SQL in this module's docstring
    or the project's migrations).

    Usage:
        store = SupabaseVectorStore()
        store.store_embedding("chunk_1", [0.1, 0.2, ...], "Hello world")
        results = store.search([0.1, 0.2, ...], top_k=5)
    """

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        self.url = (url or Config.SUPABASE_URL).rstrip("/")
        self.key = key or Config.SUPABASE_KEY
        self._headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Low-level HTTP helpers ─────────────────────────────────────────

    def _post(self, path: str, data: dict, params: Optional[dict] = None,
              extra_headers: Optional[dict] = None) -> requests.Response:
        headers = {**self._headers, **(extra_headers or {})}
        resp = requests.post(
            f"{self.url}/rest/v1/{path.lstrip('/')}",
            headers=headers,
            params=params,
            json=data,
            timeout=30,
        )
        resp.raise_for_status()
        return resp

    def _patch(self, path: str, data: dict) -> requests.Response:
        resp = requests.patch(
            f"{self.url}/rest/v1/{path.lstrip('/')}",
            headers=self._headers,
            json=data,
            timeout=30,
        )
        resp.raise_for_status()
        return resp

    def _delete(self, path: str, params: dict) -> requests.Response:
        resp = requests.delete(
            f"{self.url}/rest/v1/{path.lstrip('/')}",
            headers=self._headers,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return resp

    def _rpc(self, fn: str, params: dict) -> Any:
        """Call a Supabase RPC (stored procedure)."""
        resp = requests.post(
            f"{self.url}/rest/v1/rpc/{fn}",
            headers=self._headers,
            json=params,
            timeout=30,
        )
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {}

    # ── Embedding CRUD ─────────────────────────────────────────────────

    def store_embedding(self, chunk_id: str, vector: List[float],
                        content: str = "",
                        metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Insert or update a single embedding vector.

        Uses PostgREST upsert (``resolution=merge-duplicates``) so
        re-indexing the same chunk_id updates in place.
        """
        meta = metadata or {}
        try:
            row = {
                "chunk_id": chunk_id,
                "embedding": vector,           # pgvector accepts JSON arrays
                "content": content,
                "workspace_id": meta.get("workspace_id", "default"),
                "user_id": meta.get("user_id"),
                "source_type": meta.get("source_type", "document"),
                "source_id": meta.get("source_id", ""),
                "importance": meta.get("importance", 0.5),
                "tags": json.dumps(meta.get("tags", [])),
                "metadata": json.dumps(meta),
            }
            self._post(
                "rag_vectors",
                data=row,
                extra_headers={"Prefer": "resolution=merge-duplicates"},
            )
            return True
        except requests.RequestException as e:
            print(f"[SupabaseStore] store_embedding error: {e}")
            return False

    def store_batch(self, embeddings: List[tuple]) -> int:
        """Store multiple (chunk_id, vector, content, metadata) tuples.

        Returns count of successfully stored embeddings.
        """
        stored = 0
        for chunk_id, vector, content, metadata in embeddings:
            if self.store_embedding(chunk_id, vector, content, metadata):
                stored += 1
        return stored

    def delete_embedding(self, chunk_id: str) -> bool:
        """Delete an embedding by chunk_id."""
        try:
            self._delete("rag_vectors", {"chunk_id": f"eq.{chunk_id}"})
            return True
        except requests.RequestException:
            return False

    def delete_by_source(self, source_id: str,
                         workspace_id: str = "default") -> bool:
        """Delete all embeddings for a source."""
        try:
            self._delete("rag_vectors", {
                "source_id": f"eq.{source_id}",
                "workspace_id": f"eq.{workspace_id}",
            })
            return True
        except requests.RequestException:
            return False

    # ── Similarity search ──────────────────────────────────────────────

    def search(self, query_vector: List[float], top_k: int = 20,
               workspace_id: Optional[str] = None,
               filters: Optional[Dict[str, Any]] = None,
               threshold: float = 0.0) -> List[dict]:
        """Nearest-neighbor search via pgvector cosine similarity.

        Calls the ``match_vectors()`` RPC function, then applies any
        additional metadata filters client-side.
        """
        result = self._rpc("match_vectors", {
            "query_embedding": query_vector,
            "match_threshold": threshold,
            "match_count": top_k * 2,           # fetch extra for client-side filter
            "p_workspace_id": workspace_id or "default",
        })
        raw = result if isinstance(result, list) else []

        # Client-side metadata filters
        if filters:
            filtered = []
            for r in raw:
                meta = r.get("metadata", {})
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except (json.JSONDecodeError, TypeError):
                        meta = {}
                skip = False
                for k, v in filters.items():
                    if meta.get(k) != v:
                        skip = True
                        break
                if not skip:
                    filtered.append(r)
            raw = filtered

        # Normalise to match VectorStore output format
        results = []
        for i, r in enumerate(raw[:top_k]):
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            results.append({
                "chunk_id": r.get("chunk_id", ""),
                "content": r.get("content", ""),
                "score": r.get("similarity", 0.0),
                "metadata": {
                    "workspace_id": r.get("workspace_id"),
                    "user_id": r.get("user_id"),
                    "source_type": r.get("source_type"),
                    "source_id": r.get("source_id"),
                    "importance": r.get("importance", 0.5),
                    "created_at": r.get("created_at", ""),
                    "tags": r.get("tags", []),
                },
            })

        return results

    def search_by_content(self, query: str, top_k: int = 20,
                          workspace_id: Optional[str] = None,
                          filters: Optional[Dict] = None,
                          threshold: float = 0.0,
                          embedder=None) -> List[dict]:
        """Generate embedding for query text, then search."""
        if embedder is None:
            from core.rag.embeddings import EmbeddingGenerator
            embedder = EmbeddingGenerator()
        query_vector = embedder.generate(query)
        if not query_vector:
            return []
        return self.search(query_vector, top_k, workspace_id, filters, threshold)

    # ── Admin / stats ──────────────────────────────────────────────────

    def get_vector_count(self, workspace_id: Optional[str] = None) -> int:
        """Count vectors, optionally filtered by workspace."""
        try:
            params = {"select": "count"}
            if workspace_id:
                params["workspace_id"] = f"eq.{workspace_id}"
            resp = requests.get(
                f"{self.url}/rest/v1/rag_vectors",
                headers=self._headers,
                params=params,
                timeout=10,
            )
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0].get("count", 0)
            return 0
        except Exception:
            return 0

    def health_check(self) -> dict:
        """Check connectivity to Supabase and vector table."""
        try:
            count = self.get_vector_count()
            return {
                "status": "connected",
                "vector_count": count,
                "url": self.url,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }

    def clear_cache(self):
        """No-op: Supabase is always authoritative."""
        pass
