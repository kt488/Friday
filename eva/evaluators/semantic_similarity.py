"""Semantic similarity evaluator using text comparison."""
import logging
import re
from typing import Any, Dict, Set

from eva.core.registry import plugin
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)


@plugin("evaluator", "semantic_similarity")
class SemanticSimilarityEvaluator(BaseEvaluator):
    """Evaluates semantic similarity using token overlap and TF-style scoring."""

    name = "semantic_similarity"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self._threshold = self.config.get("threshold", 0.5)

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        expected = test.get("expected", "")
        if not expected:
            return {"similarity": 0.0, "overall": 0.0}

        score = self._compute_similarity(expected.strip(), output.strip())
        logger.debug("SemanticSimilarity: %s = %.2f", test.get("id"), score)
        return {"similarity": score, "overall": score}

    def _compute_similarity(self, expected: str, output: str) -> float:
        """Compute similarity using token overlap + n-gram scoring."""
        exp_tokens = self._tokenize(expected)
        out_tokens = self._tokenize(output)

        if not exp_tokens:
            return 100.0
        if not out_tokens:
            return 0.0

        # Jaccard similarity on sets
        exp_set: Set[str] = set(exp_tokens)
        out_set: Set[str] = set(out_tokens)
        intersection = exp_set & out_set
        union = exp_set | out_set
        jaccard = len(intersection) / len(union) if union else 0.0

        # Bigram overlap
        exp_bigrams = self._bigrams(exp_tokens)
        out_bigrams = self._bigrams(out_tokens)
        bi_intersection = exp_bigrams & out_bigrams
        bi_union = exp_bigrams | out_bigrams
        bigram = len(bi_intersection) / len(bi_union) if bi_union else 0.0

        # Combined score (0-100)
        combined = (jaccard * 0.4 + bigram * 0.6)
        return round(combined * 100, 2)

    @staticmethod
    def _tokenize(text: str) -> list:
        return re.findall(r"\w+", text.lower())

    @staticmethod
    def _bigrams(tokens: list) -> Set[str]:
        return {" ".join(tokens[i:i+2]) for i in range(len(tokens)-1)}
