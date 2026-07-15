"""Weighted scoring evaluator - combines multiple evaluator scores with weights."""
import logging
from typing import Any, Dict, List, Optional

from eva.config import EVAConfig
from eva.core.registry import PluginRegistry
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)


@plugin("evaluator", "weighted_scoring")
class WeightedScoringEvaluator(BaseEvaluator):
    """Meta-evaluator that runs sub-evaluators and combines scores with weights.

    Reads weights from EVAConfig under evaluators.weights. Each dimension
    is scored by a corresponding registered evaluator, then aggregated.
    """

    name = "weighted_scoring"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._weights: Dict[str, float] = {}
        weights_config = config.get("weights") if config else None
        if weights_config:
            self._weights = weights_config
        else:
            self._weights = dict(EVAConfig.get("evaluators.weights", {}))
        self._pass_threshold = config.get("pass_threshold") if config else None
        if self._pass_threshold is None:
            self._pass_threshold = EVAConfig.get("scoring.pass_threshold", 70.0)

        # Map dimensions to sub-evaluators
        self._dim_evaluators: Dict[str, str] = {
            "accuracy": "exact_match",
            "completeness": "keyword_match",
            "safety": "ai_judge",
            "formatting": "regex_validator",
            "correctness": "semantic_similarity",
        }

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        if not self._weights:
            logger.warning("No weights configured for weighted_scoring")
            return {"overall": 0.0}

        scores: Dict[str, float] = {}
        errors: List[str] = []

        for dimension, weight in self._weights.items():
            if weight <= 0:
                continue

            eval_name = self._dim_evaluators.get(dimension) or test.get(
                f"{dimension}_evaluator", "exact_match"
            )
            try:
                instance = PluginRegistry.create("evaluator", eval_name)
                dim_test = dict(test)
                # Allow per-dimension expected values
                dim_expected = test.get(f"{dimension}_expected")
                if dim_expected is not None:
                    dim_test["expected"] = dim_expected

                dim_scores = await instance.evaluate(dim_test, output)
                # Pick the best matching score key
                dim_score = dim_scores.get(
                    dimension, dim_scores.get("overall", dim_scores.get("accuracy", 0.0))
                )
                scores[dimension] = dim_score
            except KeyError:
                logger.debug("Evaluator '%s' not registered for dimension '%s'", eval_name, dimension)
                errors.append(f"Evaluator '{eval_name}' not found for '{dimension}'")
            except Exception as e:
                logger.warning("Dimension '%s' evaluation error: %s", dimension, e)
                errors.append(str(e))

        if not scores:
            return {"overall": 0.0, "errors": len(errors)}

        # Weighted combination
        weighted_sum = 0.0
        total_weight = 0.0
        for dim, score in scores.items():
            w = self._weights.get(dim, 1.0)
            weighted_sum += score * w
            total_weight += w

        overall = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0
        result: Dict[str, float] = {**scores, "overall": overall}
        result["_errors"] = float(len(errors))

        return result
