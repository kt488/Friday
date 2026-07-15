"""Regex validator evaluator."""
import logging
import re
from typing import Any, Dict

from eva.core.registry import plugin
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)


@plugin("evaluator", "regex_validator")
class RegexValidatorEvaluator(BaseEvaluator):
    """Evaluates output against expected regex patterns."""

    name = "regex_validator"

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        patterns: list = test.get("regex_patterns", test.get("patterns", []))
        if not patterns:
            return {"formatting": 100.0, "overall": 100.0}

        passed = 0
        errors = []
        for p in patterns:
            try:
                if re.search(p, output):
                    passed += 1
                else:
                    errors.append(p)
            except re.error as e:
                logger.warning("Invalid regex pattern '%s': %s", p, e)

        total = len(patterns)
        score = (passed / total * 100) if total else 100.0
        if errors:
            logger.debug("RegexValidator: %s matched %d/%d patterns",
                         test.get("id"), passed, total)
        return {"formatting": score, "overall": score}
