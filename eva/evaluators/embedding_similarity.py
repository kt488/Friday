"""Embedding similarity evaluator using vector comparison."""
import logging
from typing import Any, Dict, List, Optional

from eva.core.registry import plugin
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:
    np = None


@plugin("evaluator", "embedding_similarity")
class EmbeddingSimilarityEvaluator(BaseEvaluator):
    """Evaluates similarity using embedding vectors.

    Supports direct embedding vectors in test definitions or
    computes token-level approximate embeddings when no model is available.
    """

    name = "embedding_similarity"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._model = config.get("embedding_model") if config else None

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        expected = test.get("expected", "")

        # Use pre-computed embeddings if provided
        exp_embedding: Optional[List[float]] = test.get("embedding")
        out_embedding: Optional[List[float]] = test.get("output_embedding")

        if exp_embedding and out_embedding:
            score = self._cosine_similarity(exp_embedding, out_embedding)
            return {"embedding_similarity": score, "overall": score}

        if not expected:
            return {"embedding_similarity": 0.0, "overall": 0.0}

        # Fallback: character n-gram cosine similarity
        score = self._ngram_similarity(expected, output)
        return {"embedding_similarity": score, "overall": score}

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        if np is None:
            return self._pure_cosine(a, b)
        a_arr = np.array(a)
        b_arr = np.array(b)
        denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
        if denom == 0:
            return 0.0
        return round(float(np.dot(a_arr, b_arr) / denom) * 100, 2)

    @staticmethod
    def _pure_cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        if na * nb == 0:
            return 0.0
        return round((dot / (na * nb)) * 100, 2)

    def _ngram_similarity(self, expected: str, output: str) -> float:
        """Character n-gram cosine similarity fallback."""
        exp_ngrams = self._char_ngrams(expected.lower(), 3)
        out_ngrams = self._char_ngrams(output.lower(), 3)

        all_grams = set(exp_ngrams.keys()) | set(out_ngrams.keys())
        if not all_grams:
            return 0.0

        exp_vec = [exp_ngrams.get(g, 0) for g in all_grams]
        out_vec = [out_ngrams.get(g, 0) for g in all_grams]

        return self._pure_cosine(exp_vec, out_vec)

    @staticmethod
    def _char_ngrams(text: str, n: int) -> Dict[str, int]:
        ngrams: Dict[str, int] = {}
        for i in range(len(text) - n + 1):
            gram = text[i:i+n]
            ngrams[gram] = ngrams.get(gram, 0) + 1
        return ngrams
