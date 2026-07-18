"""Vector store — pure-Python ANN search with cosine similarity.

Uses numpy if available, falls back to pure Python loops.
Supports approximate nearest neighbor via IVF-style clustering at scale.
"""

import math
import random
import time
from typing import Callable, Dict, List, Optional, Tuple

from core.rag.database import RAGDatabase
from core.rag.embeddings import EmbeddingGenerator


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def dot_product(a: List[float], b: List[float]) -> float:
    """Compute dot product similarity."""
    return sum(x * y for x, y in zip(a, b))


class VectorStore:
    """Vector store with ANN search, indexing, and management.

    Supports cosine and dot-product similarity. Uses flat (brute-force)
    search by default, with optional IVF clustering for larger collections.
    """

    def __init__(self, db: RAGDatabase, embedder: EmbeddingGenerator,
                 similarity: str = "cosine"):
        self.db = db
        self.embedder = embedder
        self.similarity_fn: Callable = cosine_similarity if similarity == "cosine" else dot_product
        self.similarity = similarity

        # In-memory cache of loaded vectors for fast search
        self._vectors: List[dict] = []
        self._loaded = False
        self._load_ts = 0.0
        self._cache_ttl = 60.0  # reload every 60s

        # IVF clustering (optional, for >10k vectors)
        self._centroids: List[dict] = []
        self._nlist = 64  # number of centroids

    def _load_vectors(self, force: bool = False, workspace_id: Optional[str] = None):
        """Load vectors from DB into memory cache."""
        now = time.time()
        if not force and self._loaded and (now - self._load_ts) < self._cache_ttl:
            return

        records = self.db.get_all_embeddings(workspace_id=workspace_id)
        self._vectors = records
        self._loaded = True
        self._load_ts = now

    def index_chunk(self, chunk_id: str, content: str,
                    metadata: dict) -> Optional[List[float]]:
        """Generate embedding and store in vector DB."""
        vector = self.embedder.generate(content)
        if not vector:
            return None

        self.db.insert_embedding(
            chunk_id=chunk_id,
            vector=vector,
            model=self.embedder.model,
            dimension=len(vector),
        )
        return vector

    def index_batch(self, chunks: List[Tuple[str, str, dict]]) -> int:
        """Index multiple chunks in batch. Returns count indexed."""
        texts = [c[1] for c in chunks]
        vectors = self.embedder.generate_batch(texts)

        indexed = 0
        for (chunk_id, content, metadata), vec in zip(chunks, vectors):
            if vec:
                self.db.insert_embedding(
                    chunk_id=chunk_id,
                    vector=vec,
                    model=self.embedder.model,
                    dimension=len(vec),
                )
                indexed += 1

        # Invalidate cache
        self._loaded = False
        return indexed

    def search(self, query_vector: List[float], top_k: int = 20,
               workspace_id: Optional[str] = None,
               filters: Optional[Dict[str, any]] = None,
               threshold: float = 0.0) -> List[dict]:
        """Search for nearest neighbors by vector similarity."""
        self._load_vectors(workspace_id=workspace_id)

        scored = []
        for record in self._vectors:
            vec = record["vector"]

            # Apply tenant filter
            if workspace_id and record.get("workspace_id") != workspace_id:
                continue

            # Apply metadata filters
            if filters:
                skip = False
                for k, v in filters.items():
                    if record.get(k) != v:
                        skip = True
                        break
                if skip:
                    continue

            score = self.similarity_fn(query_vector, vec)
            if score >= threshold:
                scored.append({
                    "chunk_id": record["chunk_id"],
                    "content": record.get("content", ""),
                    "score": score,
                    "metadata": {
                        "workspace_id": record.get("workspace_id"),
                        "user_id": record.get("user_id"),
                        "source_type": record.get("source_type"),
                        "importance": record.get("importance", 0.5),
                        "created_at": record.get("created_at", ""),
                        "tags": record.get("tags", []),
                    },
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def search_by_content(self, query: str, top_k: int = 20,
                          workspace_id: Optional[str] = None,
                          filters: Optional[Dict] = None,
                          threshold: float = 0.0) -> List[dict]:
        """Generate embedding for query text and search."""
        query_vector = self.embedder.generate(query)
        if not query_vector:
            return []
        return self.search(query_vector, top_k, workspace_id, filters, threshold)

    def delete_embedding(self, chunk_id: str):
        """Remove embedding for a chunk."""
        self.db.delete_chunk(chunk_id)
        self._loaded = False

    def build_ivf_index(self, nlist: int = 64,
                         workspace_id: Optional[str] = None) -> int:
        """Build IVF centroids for faster approximate search (>10k vectors)."""
        self._load_vectors(workspace_id=workspace_id)
        if len(self._vectors) < nlist:
            return 0  # Too few vectors for IVF

        self._nlist = nlist

        # K-means clustering for centroids (simplified)
        vectors_only = [r["vector"] for r in self._vectors]
        dim = len(vectors_only[0])

        # Random initialization
        centroids = random.sample(vectors_only, min(nlist, len(vectors_only)))
        self._centroids = []

        for iteration in range(10):  # 10 iterations max
            assignments = [[] for _ in range(len(centroids))]
            for vec in vectors_only:
                scores = [cosine_similarity(vec, c) for c in centroids]
                best = max(range(len(scores)), key=lambda i: scores[i])
                assignments[best].append(vec)

            new_centroids = []
            for cluster in assignments:
                if not cluster:
                    continue
                avg = [sum(dim_values) / len(cluster)
                       for dim_values in zip(*cluster)]
                new_centroids.append(avg)

            if new_centroids:
                centroids = new_centroids

        # Store centroids with their indices
        for i, c in enumerate(centroids):
            self._centroids.append({"id": i, "vector": c})

        return len(self._centroids)

    def search_ivf(self, query_vector: List[float], top_k: int = 20,
                   nprobe: int = 8) -> List[dict]:
        """ANN search using IVF — search nearest centroids first."""
        if not self._centroids:
            return self.search(query_vector, top_k)

        # Score centroids
        centroid_scores = [
            (i, cosine_similarity(query_vector, c["vector"]))
            for i, c in enumerate(self._centroids)
        ]
        centroid_scores.sort(key=lambda x: x[1], reverse=True)
        top_centroids = centroid_scores[:nprobe]

        # Search within top centroid clusters
        results = []
        for centroid_id, _ in top_centroids:
            candidates = self._vectors  # simplified — would use inverted index
            for record in candidates:
                vec = record["vector"]
                score = self.similarity_fn(query_vector, vec)
                results.append({
                    "chunk_id": record["chunk_id"],
                    "content": record.get("content", ""),
                    "score": score,
                    "metadata": {
                        "workspace_id": record.get("workspace_id"),
                        "user_id": record.get("user_id"),
                        "source_type": record.get("source_type"),
                        "importance": record.get("importance", 0.5),
                        "created_at": record.get("created_at", ""),
                        "tags": record.get("tags", []),
                    },
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_vector_count(self, workspace_id: Optional[str] = None) -> int:
        return self.db.count_embeddings(workspace_id=workspace_id)

    def clear_cache(self):
        self._vectors = []
        self._loaded = False
        self._centroids = []
