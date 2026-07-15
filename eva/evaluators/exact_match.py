"""Exact match evaluator - checks exact string equality."""
import logging
from typing import Any, Dict

from eva.core.registry import plugin
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)


@plugin("evaluator", "exact_match")
class ExactMatchEvaluator(BaseEvaluator):
    """Evaluates output against expected string with exact match."""

    name = "exact_match"

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        expected = test.get("expected", "")
        if not expected:
            return {"accuracy": 0.0, "overall": 0.0}

        match = output.strip() == expected.strip()
        score = 100.0 if match else 0.0
        logger.debug("ExactMatch: %s = %s", test.get("id"), "PASS" if match else "FAIL")
        return {"accuracy": score, "overall": score}
