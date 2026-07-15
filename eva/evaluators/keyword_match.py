"""Keyword match evaluator."""
import logging
from typing import Any, Dict, List

from eva.core.registry import plugin
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)


@plugin("evaluator", "keyword_match")
class KeywordMatchEvaluator(BaseEvaluator):
    """Evaluates presence of required keywords in output."""

    name = "keyword_match"

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        required: List[str] = test.get("required_keywords", test.get("keywords", []))
        forbidden: List[str] = test.get("forbidden_keywords", [])
        if not required and not forbidden:
            return {"keyword_score": 100.0, "overall": 100.0}

        output_lower = output.lower()
        found = sum(1 for kw in required if kw.lower() in output_lower)
        violations = sum(1 for kw in forbidden if kw.lower() in output_lower)

        required_score = (found / len(required) * 100) if required else 100.0
        forbidden_penalty = violations * 25.0  # -25 per forbidden keyword
        total = max(0, required_score - forbidden_penalty)

        logger.debug("KeywordMatch: %s = %.2f (found %d/%d, violated %d)",
                     test.get("id"), total, found, len(required), violations)
        return {"keyword_score": total, "overall": total}
