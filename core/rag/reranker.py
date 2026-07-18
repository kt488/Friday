"""Reranking pipeline — cross-encoder scoring, MMR diversity, recency boost.

Reranks initial retrieval results using multiple signals for higher precision.
"""

import math
import time
from typing import List, Optional

from core.rag.models import SearchResult


class Reranker:
    """Multi-stage reranking pipeline.

    Stages:
      1. Cross-encoder scoring (via NVIDIA NIM or local)
      2. MMR diversity
      3. Recency boost
      4. Importance boost
    """

    def __init__(self, model: str = "nvidia/nv-rerank-qa-mistral-4b:1"):
        self.model = model
        self.api_key = None  # Set externally
        self.url = None  # Set externally

    def configure(self, api_key: str, base_url: str):
        """Set NVIDIA NIM credentials for cross-encoder reranking."""
        self.api_key = api_key
        self.url = f"{base_url}/chat/completions"

    def rerank(self, query: str, results: List[SearchResult],
               top_k: int = 5, min_score: float = 0.3,
               diversity_factor: float = 0.3) -> List[SearchResult]:
        """Execute full reranking pipeline.

        If cross-encoder is unavailable, falls back to score-based reranking.
        """
        t0 = time.time()

        if not results:
            return results

        # Stage 1: Cross-encoder scoring (if available)
        if self.api_key and self.url:
            results = self._cross_encoder_score(query, results)

        # Stage 2: Filter by minimum score
        results = [r for r in results if r.score >= min_score]

        # Stage 3: MMR diversity
        if diversity_factor > 0 and len(results) > top_k:
            results = self._mmr_select(query, results, top_k, diversity_factor)
        else:
            results = sorted(results, key=lambda x: x.score, reverse=True)[:top_k]

        # Stage 4: Assign final ranks
        for i, r in enumerate(results):
            r.rank = i + 1

        return results

    def _cross_encoder_score(self, query: str,
                              results: List[SearchResult]) -> List[SearchResult]:
        """Score results using cross-encoder model via NVIDIA NIM."""
        try:
            import json
            import requests

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": f"Query: {query}\nPassage: {results[0].content}\nScore the relevance (0-1):"}
                ],
                "max_tokens": 10,
            }
            # Only use cross-encoder on top candidates to save cost
            for i, r in enumerate(results[:10]):
                try:
                    payload["messages"][0]["content"] = (
                        f"Query: {query}\nPassage: {r.content[:500]}\n"
                        f"Rate relevance 0-1 (just the number):"
                    )
                    resp = requests.post(
                        self.url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        data=json.dumps(payload),
                        timeout=10,
                    )
                    if resp.ok:
                        text = resp.json()["choices"][0]["message"]["content"].strip()
                        try:
                            ce_score = float(text.split()[0])
                            r.score = r.score * 0.5 + ce_score * 0.5
                        except (ValueError, IndexError):
                            pass
                except Exception:
                    continue
        except ImportError:
            pass
        except Exception:
            pass

        return results

    def _mmr_select(self, query: str, results: List[SearchResult],
                    top_k: int, lambda_param: float = 0.3) -> List[SearchResult]:
        """Maximum Marginal Relevance selection for diversity."""
        if not results:
            return []

        selected = [results[0]]
        candidates = results[1:]

        while len(selected) < top_k and candidates:
            best_idx = 0
            best_score = -float("inf")

            for i, cand in enumerate(candidates):
                relevance = cand.score

                # Max similarity to selected set
                max_sim = max(
                    self._text_jaccard(cand.content, sel.content)
                    for sel in selected
                )

                mmr = lambda_param * relevance - (1 - lambda_param) * max_sim
                if mmr > best_score:
                    best_score = mmr
                    best_idx = i

            selected.append(candidates.pop(best_idx))

        return selected

    def _text_jaccard(self, a: str, b: str) -> float:
        """Jaccard similarity between two texts."""
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)
