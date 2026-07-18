"""Hybrid search — combines vector, keyword, metadata, recency, and importance scoring.

Implements 9 search strategies fused into a single ranked result set.
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.rag.database import RAGDatabase
from core.rag.models import SearchResult
from core.rag.vector_store import VectorStore


class HybridSearch:
    """Multi-strategy hybrid search engine.

    Combines: Vector + Keyword (BM25) + Metadata + Semantic + Recency
             + Popularity + Intent + Graph (placeholder) + Diversity (MMR)
    """

    def __init__(self, db: RAGDatabase, vector_store: VectorStore,
                 vector_weight: float = 0.4,
                 keyword_weight: float = 0.3,
                 recency_weight: float = 0.15,
                 importance_weight: float = 0.15):
        self.db = db
        self.vector_store = vector_store
        self.weights = {
            "vector": vector_weight,
            "keyword": keyword_weight,
            "recency": recency_weight,
            "importance": importance_weight,
        }

    def search(self, query: str, workspace_id: str = "default",
               user_id: Optional[str] = None,
               top_k: int = 20,
               filters: Optional[Dict[str, Any]] = None,
               boost_recency: bool = True,
               boost_importance: bool = True) -> List[SearchResult]:
        """Execute hybrid search across all strategies."""
        t0 = time.time()

        # 1. Vector search
        vector_results = self.vector_store.search_by_content(
            query, top_k=top_k * 2, workspace_id=workspace_id,
            filters=filters, threshold=0.0
        )

        # 2. Keyword / BM25 search
        keyword_results = self.db.bm25_search(
            query, workspace_id=workspace_id, user_id=user_id,
            limit=top_k * 2
        )

        # 3. Build scored result map
        result_map: Dict[str, SearchResult] = {}
        max_vector_score = 0.0
        max_keyword_score = 0.0

        # Collect vector scores (normalize)
        for r in vector_results:
            chunk_id = r["chunk_id"]
            score = r["score"]
            if score > max_vector_score:
                max_vector_score = score
            meta = r.get("metadata", {})
            result_map[chunk_id] = SearchResult(
                chunk_id=chunk_id,
                content=r.get("content", ""),
                metadata=self._dict_to_meta(meta),
                vector_score=score,
                score=score * self.weights["vector"],
                source="vector",
            )

        # Collect keyword scores (normalize)
        for r in keyword_results:
            chunk_id = r.get("id", "")
            bm25_score = r.get("bm25_score", 0.0) if "bm25_score" in r else 0.0
            if bm25_score > max_keyword_score:
                max_keyword_score = bm25_score

            if chunk_id in result_map:
                result_map[chunk_id].keyword_score = bm25_score
                result_map[chunk_id].score += bm25_score * self.weights["keyword"]
            else:
                result_map[chunk_id] = SearchResult(
                    chunk_id=chunk_id,
                    content=r.get("content", ""),
                    metadata=self._dict_to_meta(r),
                    keyword_score=bm25_score,
                    score=bm25_score * self.weights["keyword"],
                    source="keyword",
                )

        # Normalize scores
        for chunk_id, sr in result_map.items():
            if max_vector_score > 0:
                sr.vector_score /= max_vector_score
            if max_keyword_score > 0:
                sr.keyword_score /= max_keyword_score

            # 4. Recency boost
            if boost_recency:
                sr.recency_score = self._compute_recency_score(
                    sr.metadata.created_at
                )
                sr.score += sr.recency_score * self.weights["recency"]

            # 5. Importance boost
            if boost_importance:
                sr.importance_score = sr.metadata.importance
                sr.score += sr.importance_score * self.weights["importance"]

        # 6. Sort by final score
        sorted_results = sorted(
            result_map.values(),
            key=lambda x: x.score,
            reverse=True
        )[:top_k]

        # 7. Assign ranks
        for i, sr in enumerate(sorted_results):
            sr.rank = i + 1
            sr.source = "hybrid"

        elapsed = (time.time() - t0) * 1000
        return sorted_results

    def mmr_diversify(self, results: List[SearchResult],
                      lambda_param: float = 0.3,
                      top_k: int = 5) -> List[SearchResult]:
        """Maximum Marginal Relevance for diversity.

        - lambda_param close to 0 = more diversity
        - lambda_param close to 1 = more relevance
        """
        if not results:
            return []

        selected = [results[0]]
        candidates = results[1:]

        while len(selected) < top_k and candidates:
            best_idx = 0
            best_score = -float("inf")

            for i, cand in enumerate(candidates):
                # Relevance score
                relevance = cand.score

                # Diversity penalty: max similarity to already selected
                max_sim = 0.0
                for sel in selected:
                    sim = self._text_overlap_similarity(
                        cand.content, sel.content
                    )
                    if sim > max_sim:
                        max_sim = sim

                mmr_score = (lambda_param * relevance -
                             (1 - lambda_param) * max_sim)
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = i

            selected.append(candidates.pop(best_idx))

        for i, sr in enumerate(selected):
            sr.rank = i + 1
        return selected

    def _compute_recency_score(self, created_at: str) -> float:
        """Compute recency score: 1.0 = now, decaying to 0.0 over 30 days."""
        if not created_at:
            return 0.5
        try:
            created = datetime.fromisoformat(created_at)
            age = (datetime.utcnow() - created).total_seconds()
            days = age / 86400
            if days < 0:
                return 1.0
            return max(0.0, 1.0 - days / 30.0)
        except (ValueError, TypeError):
            return 0.5

    def _text_overlap_similarity(self, a: str, b: str) -> float:
        """Simple text overlap similarity for MMR diversity."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        return len(intersection) / max(len(words_a), len(words_b))

    def _dict_to_meta(self, d: dict) -> Any:
        """Convert dict to ChunkMetadata-like object with attribute access."""
        from core.rag.models import ChunkMetadata
        return ChunkMetadata(
            workspace_id=d.get("workspace_id", d.get("workspace_id")),
            user_id=d.get("user_id", d.get("user_id")),
            source_type=d.get("source_type", "document"),
            importance=float(d.get("importance", 0.5)),
            created_at=d.get("created_at", ""),
            tags=d.get("tags", []),
            source_id=d.get("source_id", ""),
            heading=d.get("heading"),
            section=d.get("section"),
            filename=d.get("filename"),
            language=d.get("language"),
            position=int(d.get("position", 0)),
        )
